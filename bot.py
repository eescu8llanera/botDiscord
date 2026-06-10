import json
import os
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
RUTA_DATOS = "datos_quiniela.json"
PUNTOS_ACIERTO = 1
SIGNOS_VALIDOS = {"1", "X", "2"}


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ============================
#   ESTRUCTURA BASE DE DATOS
# ============================

DATOS_BASE = {
    "jornada_activa": None,
    "jornadas": {},
    "clasificacion": {},
    "penalizaciones": {},
    "pleno15": {},
    "pronosticos": {},
    "resultados": {},
}

# ============================
#   UTILIDADES GENERALES/FUNCIONES INTERNAS
# ============================

def ahora_iso():
    """Devuelve la fecha actual en UTC para guardar cuándo se crea una jornada."""
    return datetime.now(timezone.utc).isoformat()


def normalizar_signo(signo):
    """Limpia y valida un signo de quiniela."""
    signo = str(signo).strip().upper()
    if signo not in SIGNOS_VALIDOS:
        raise ValueError("El signo debe ser 1, X o 2.")
    return signo

async def nombre_usuario(usuario_id):
    """Obtiene el nombre visible de Discord a partir de su ID."""
    try:
        usuario = await bot.fetch_user(int(usuario_id))
        return usuario.display_name
    except discord.DiscordException:
        return f"Usuario {usuario_id}"


def es_admin(ctx):
    """Comprueba si el usuario puede gestionar el servidor."""
    return ctx.author.guild_permissions.manage_guild


def cargar_datos():
    """Lee el JSON de datos y completa claves antiguas si faltan."""
    if not os.path.exists(RUTA_DATOS):
        guardar_datos(DATOS_BASE.copy())
        return DATOS_BASE.copy()

    with open(RUTA_DATOS, "r", encoding="utf-8") as archivo:
        datos = json.load(archivo)

    # Asegurar estructura mínima
    if datos.get("jornadas") is None:
        datos["jornadas"] = {}

    if datos.get("clasificacion") is None:
        datos["clasificacion"] = {}

    if datos.get("penalizaciones") is None:
        datos["penalizaciones"] = {}

    if datos.get("pleno15") is None:
        datos["pleno15"] = {}

    for jornada in datos["jornadas"].values():
        jornada.setdefault("partidos", {})
        jornada.setdefault("pronosticos", {})
        jornada.setdefault("pleno15", {})
        jornada.setdefault("resultados", {})
        jornada.setdefault("abierta", True)

    jornada_id = datos.get("jornada_activa")
    jornada = datos["jornadas"].get(str(jornada_id)) if jornada_id else None
    if jornada:
        # Compatibilidad con datos guardados por versiones anteriores del bot.
        if datos.get("pronosticos") and not jornada["pronosticos"]:
            jornada["pronosticos"] = datos["pronosticos"]
        if datos.get("pleno15") and not jornada["pleno15"]:
            jornada["pleno15"] = datos["pleno15"]

    return datos


def guardar_datos(datos):
    """Guarda todos los datos de la quiniela en disco."""
    with open(RUTA_DATOS, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, indent=4, ensure_ascii=False)


def datos_vacios():
    """Devuelve una estructura limpia para reiniciar la quiniela."""
    return deepcopy(DATOS_BASE)


def jornada_actual(datos):
    """Devuelve el ID y los datos de la jornada activa."""
    jornada_id = datos.get("jornada_activa")
    if not jornada_id:
        return None, None
    return jornada_id, datos["jornadas"].get(str(jornada_id))


def clave_partido(item):
    """Ordena partidos numéricos antes que claves de texto."""
    numero = item[0]
    return (0, int(numero)) if str(numero).isdigit() else (1, str(numero))


def descripcion_partido(jornada, partido):
    """Construye una etiqueta legible con número y equipos del partido."""
    descripcion = jornada.get("partidos", {}).get(str(partido))
    if descripcion:
        return f"Partido {partido} - {descripcion}"
    return f"Partido {partido}"


def validar_pleno(pleno):
    """Valida el formato de marcador del Pleno al 15."""
    try:
        goles_local, goles_visitante = pleno.split("-")
        int(goles_local)
        int(goles_visitante)
    except ValueError as error:
        raise ValueError("El pleno debe tener formato número-número. Ejemplo: 2-1") from error

    return pleno


def texto_ayuda_quiniela():
    """Devuelve el texto de ayuda compartido por comandos ! y /."""
    return (
        "**Ayuda de la quiniela**\n\n"
        "**Para jugar**\n"
        "`!partidos` o `/partidos` - muestra los partidos de la jornada activa.\n"
        "`!apostar <14 signos> <pleno>` o `/apostar pronos pleno` - guarda tus 14 pronósticos y el Pleno al 15.\n"
        "Ejemplo: `!apostar 1X12X212X112X1 2-0`\n"
        "Los 14 signos van seguidos, sin espacios. Cada signo debe ser `1`, `X` o `2`.\n"
        "`1` gana el equipo local, `X` empate, `2` gana el visitante.\n"
        "El pleno se escribe como marcador: `goles-local-goles-visitante`.\n"
        "`!mispronosticos` o `/mispronosticos` - muestra tus apuestas con el nombre de cada partido.\n"
        "`!verpronosticos` o `/verpronosticos` - muestra todas las apuestas con el nombre de cada partido.\n"
        "`!pleno <marcador>` o `/pleno resultado` - cambia solo tu Pleno al 15.\n"
        "`!clasificacion` o `/clasificacion` - muestra la clasificación general.\n\n"
        "**Administración**\n"
        "`!crearjornada <numero>` o `/crearjornada numero` - crea y activa una jornada.\n"
        "`!partido <numero> <local> vs <visitante>` o `/partido numero descripcion` - añade o cambia un partido.\n"
        "Ejemplo: `!partido 1 España vs Cabo Verde`\n"
        "Para el Pleno al 15 puedes usar `!partido 15 Italia vs Rumania`.\n"
        "`!cerrarjornada` / `!abrirjornada` o `/cerrarjornada` / `/abrirjornada` - cierra o reabre las apuestas.\n"
        "`!resultado <numero> <1|X|2>` o `/resultado partido signo` - guarda el resultado oficial.\n"
        "`!calcular` o `/calcular` - recalcula la clasificación.\n"
        "`!calcularautomatico` o `/calcularautomatico` - calcula resultados por consenso y pleno medio.\n"
        "`!elige8` o `/elige8` - muestra los 8 partidos con mayor consenso.\n"
        "`!penalizar @usuario <puntos>` o `/penalizar usuario puntos` - resta puntos a un usuario.\n"
        "`!limpiardatos CONFIRMAR` o `/limpiardatos confirmacion:CONFIRMAR` - borra todos los datos guardados. Admin."
    )

# ==============================
# CÁLCULO: CLASIFICACIÓN GENERAL
# ==============================

def recalcular_clasificacion(datos):
    """Recalcula la clasificación general con todas las jornadas y penalizaciones."""
    clasificacion = {}

    for jornada in datos["jornadas"].values():
        resultados = jornada.get("resultados", {})
        for usuario_id, pronosticos in jornada.get("pronosticos", {}).items():
            puntos = 0
            aciertos = 0
            jugados = 0

            for partido, signo in pronosticos.items():
                if partido in resultados:
                    jugados += 1
                    if signo == resultados[partido]:
                        aciertos += 1
                        puntos += PUNTOS_ACIERTO

            fila = clasificacion.setdefault(
                usuario_id,
                {"puntos": 0, "aciertos": 0, "jugados": 0},
            )
            fila["puntos"] += puntos
            fila["aciertos"] += aciertos
            fila["jugados"] += jugados

    for usuario_id, penalizacion in datos.get("penalizaciones", {}).items():
        fila = clasificacion.setdefault(
            usuario_id,
            {"puntos": 0, "aciertos": 0, "jugados": 0},
        )
        fila["puntos"] -= int(penalizacion)

    datos["clasificacion"] = clasificacion

# ============================
#   CÁLCULO PLENO AL 15
# ============================

def calcular_pleno_media_jornada(jornada):
    """Calcula la media redondeada de los pronósticos del Pleno al 15."""

    plenos = jornada.get("pleno15", {})
    if not plenos:
        return None

    goles = [tuple(map(int, p.split("-"))) for p in plenos.values()]
    media1 = round(sum(g1 for g1, _ in goles) / len(goles))
    media2 = round(sum(g2 for _, g2 in goles) / len(goles))

    return f"{media1}-{media2}"

# ============================
#   EVENTOS Y COMANDOS
# ============================

# Evento automatico: se ejecuta cuando el bot se conecta correctamente.
@bot.event
async def on_ready():
    """Avisa por consola cuando el bot se conecta correctamente."""
    await bot.tree.sync()
    print(f"Bot conectado como {bot.user}")


# Comando: !ping
# Formato correcto: !ping
# Sirve para comprobar que el bot responde.
@bot.command(name="ping")
async def ping(ctx):
    """Responde con Pong para comprobar que el bot está vivo."""
    await ctx.send("Pong.")


# Comando: !ayudaquiniela
# Formato correcto: !ayudaquiniela
# Muestra la lista de comandos disponibles y su formato basico.
@bot.command(name="ayudaquiniela")
async def ayuda_quiniela(ctx):
    """Muestra una guía de comandos y formatos de la quiniela."""
    await ctx.send(texto_ayuda_quiniela())


# Comando: !crearjornada
# Formato correcto: !crearjornada <numero>
# Ejemplo: !crearjornada 1
# Permisos: solo administradores con permiso "Gestionar servidor".
# Crea una jornada si no existe y la marca como jornada activa.
@bot.command(name="crearjornada")
@commands.check(es_admin)
async def crear_jornada(ctx, numero):
    """Crea una jornada si no existe y la marca como activa."""
    datos = cargar_datos()
    jornada_id = str(numero)
    datos["jornadas"].setdefault(
        jornada_id,
        {
            "abierta": True,
            "partidos": {},
            "pronosticos": {},
            "pleno15": {},
            "resultados": {},
            "creada_en": ahora_iso(),
        },
    )
    datos["jornada_activa"] = jornada_id
    guardar_datos(datos)
    await ctx.send(f"Jornada {jornada_id} creada y activada.")


# Comando: !partido
# Formato correcto: !partido <numero> <descripcion>
# Ejemplo: !partido 1 Real Madrid vs Barcelona
# Permisos: solo administradores con permiso "Gestionar servidor".
# Añade o sustituye un partido dentro de la jornada activa.
@bot.command(name="partido")
@commands.check(es_admin)
async def agregar_partido(ctx, numero, *, descripcion):
    """Añade o actualiza la descripción de un partido de la jornada activa."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await ctx.send("Primero crea una jornada con `!crearjornada <numero>`.")
        return

    jornada["partidos"][str(numero)] = descripcion.strip()
    guardar_datos(datos)
    await ctx.send(f"{descripcion_partido(jornada, numero)} añadido a la jornada {jornada_id}.")


# Comando: !partidos
# Formato correcto: !partidos
# Muestra los partidos configurados en la jornada activa.
@bot.command(name="partidos", aliases=["listarpartidos"])
async def ver_partidos(ctx):
    """Muestra todos los partidos configurados en la jornada activa."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await ctx.send("No hay jornada activa.")
        return
    if not jornada["partidos"]:
        await ctx.send(f"La jornada {jornada_id} todavía no tiene partidos.")
        return

    lineas = [f"**Jornada {jornada_id}**"]
    estado = "abierta" if jornada.get("abierta") else "cerrada"
    lineas.append(f"Estado: {estado}")
    for numero, descripcion in sorted(jornada["partidos"].items(), key=clave_partido):
        etiqueta_pleno = " (Pleno al 15)" if str(numero) == "15" else ""
        lineas.append(f"`{numero}` - {descripcion}{etiqueta_pleno}")
    if "15" not in jornada["partidos"]:
        lineas.append("`15` - Pleno al 15")
    await ctx.send("\n".join(lineas))

# ============================
#   APOSTAR
# ============================

# Comando: !apostar
# Formato correcto: !apostar <14_signos> <pleno>
# Signos validos: 1, X o 2. Pleno con formato goles-local-goles-visitante.
# Ejemplo: !apostar 1X12X212X112X1 2-0
# Guarda o actualiza todos tus pronosticos de la jornada activa.
@bot.command(name="apostar")
async def apostar(ctx, pronos: str, pleno: str):
    """Guarda los 14 signos y el Pleno al 15 del usuario en la jornada activa."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    usuario = str(ctx.author.id)

    if not jornada:
        await ctx.send("No hay jornada activa. Pide a un admin que use `!crearjornada <numero>`.")
        return
    if not jornada.get("abierta"):
        await ctx.send("La jornada está cerrada y no acepta apuestas.")
        return

    # Validación de longitud: una quiniela normal tiene 14 signos más el Pleno al 15.
    if len(pronos) != 14:
        await ctx.send("Debes enviar exactamente 14 signos (1, X o 2). Ejemplo: `1X12X212X112X1`")
        return

    # Validación de signos
    for s in pronos:
        if s.upper() not in SIGNOS_VALIDOS:
            await ctx.send("Solo se permiten signos `1`, `X` o `2`.")
            return

    # Validación del pleno al 15
    try:
        pleno = validar_pleno(pleno)
    except ValueError as error:
        await ctx.send(str(error))
        return

    jornada["pronosticos"].setdefault(usuario, {})

    for i, signo in enumerate(pronos, start=1):
        jornada["pronosticos"][usuario][str(i)] = signo.upper()

    jornada["pleno15"][usuario] = pleno

    guardar_datos(datos)

    resumen = [f"{descripcion_partido(jornada, partido)}: **{signo}**" for partido, signo in sorted(
        jornada["pronosticos"][usuario].items(),
        key=clave_partido,
    )]

    await ctx.send(
        f"Jornada {jornada_id} registrada para **{ctx.author.display_name}**\n"
        + "\n".join(resumen)
        + f"\n`15` Pleno al 15: **{pleno}**"
    )

# ============================
#   MIS PRONÓSTICOS
# ============================

# Comando: !mispronosticos
# Formato correcto: !mispronosticos
# Muestra los pronosticos guardados por quien ejecuta el comando.
@bot.command(name="mispronosticos")
async def mis_pronosticos(ctx):
    """Muestra los pronósticos del usuario que ejecuta el comando."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await ctx.send("No hay jornada activa.")
        return

    pronosticos = jornada["pronosticos"].get(str(ctx.author.id), {})
    if not pronosticos:
        await ctx.send("Aún no tienes pronósticos en la jornada activa.")
        return

    lineas = [f"**Tus pronósticos - Jornada {jornada_id}**"]
    for partido, signo in sorted(pronosticos.items(), key=clave_partido):
        lineas.append(f"{descripcion_partido(jornada, partido)}: **{signo}**")

    pleno = jornada["pleno15"].get(str(ctx.author.id))
    if pleno:
        lineas.append(f"`15` Pleno al 15: **{pleno}**")

    await ctx.send("\n".join(lineas))

# ============================
#   VER PRONÓSTICOS
# ============================

# Comando: !verpronosticos
# Formato correcto: !verpronosticos
# Muestra todos los pronosticos registrados en la jornada activa.
@bot.command(name="verpronosticos")
async def ver_pronosticos(ctx):
    """Muestra los pronósticos de todos los usuarios en la jornada activa."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)

    if not jornada:
        await ctx.send("No hay jornada activa.")
        return

    usuarios = set(jornada["pronosticos"].keys()) | set(jornada["pleno15"].keys())

    if not usuarios:
        await ctx.send("No hay pronósticos.")
        return

    lineas = [f"**Pronósticos Jornada {jornada_id}**"]

    for usuario_id in usuarios:
        nombre = await nombre_usuario(usuario_id)
        lineas.append(f"\n**{nombre}**")

        pronos = jornada["pronosticos"].get(usuario_id, {})
        for partido, signo in sorted(pronos.items(), key=clave_partido):
            lineas.append(f"{descripcion_partido(jornada, partido)}: **{signo}**")

        pleno = jornada["pleno15"].get(usuario_id)
        if pleno:
            lineas.append(f"`15` Pleno al 15: **{pleno}**")

    await ctx.send("\n".join(lineas))

# ============================
#   CERRAR JORNADA
# ============================

# Comando: !cerrarjornada
# Formato correcto: !cerrarjornada
# Permisos: solo administradores con permiso "Gestionar servidor".
# Cierra la jornada activa para que no se puedan cambiar apuestas.
@bot.command(name="cerrarjornada")
@commands.check(es_admin)
async def cerrar_jornada(ctx):
    """Cierra la jornada activa para impedir nuevas apuestas."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await ctx.send("No hay jornada activa.")
        return
    jornada["abierta"] = False
    guardar_datos(datos)
    await ctx.send(f"Jornada {jornada_id} cerrada.")

# ============================
#   ABRIR JORNADA
# ============================

# Comando: !abrirjornada
# Formato correcto: !abrirjornada
# Permisos: solo administradores con permiso "Gestionar servidor".
# Reabre la jornada activa para permitir apuestas o cambios.
@bot.command(name="abrirjornada")
@commands.check(es_admin)
async def abrir_jornada(ctx):
    """Reabre la jornada activa para permitir apuestas y cambios."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await ctx.send("No hay jornada activa.")
        return
    jornada["abierta"] = True
    guardar_datos(datos)
    await ctx.send(f"Jornada {jornada_id} abierta.")

# ============================
#   RESULTADO
# ============================

# Comando: !resultado
# Formato correcto: !resultado <numero_partido> <signo>
# Signos validos: 1, X o 2
# Ejemplo: !resultado 1 2
# Permisos: solo administradores con permiso "Gestionar servidor".
# Guarda el resultado oficial y recalcula la clasificacion.
@bot.command(name="resultado")
@commands.check(es_admin)
async def resultado(ctx, partido, signo):
    """Guarda el resultado oficial de un partido y recalcula la clasificación."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await ctx.send("No hay jornada activa.")
        return
    if str(partido) not in jornada["partidos"]:
        await ctx.send("Ese partido no existe en la jornada activa.")
        return

    try:
        signo = normalizar_signo(signo)
    except ValueError as error:
        await ctx.send(str(error))
        return

    jornada["resultados"][str(partido)] = signo
    recalcular_clasificacion(datos)
    guardar_datos(datos)
    await ctx.send(f"Resultado guardado: {descripcion_partido(jornada, partido)} -> **{signo}**.")

# ============================
#   CALCULAR 
# ============================

# Comando: !calcular
# Formato correcto: !calcular
# Permisos: solo administradores con permiso "Gestionar servidor".
# Recalcula la clasificacion usando los resultados oficiales guardados.
@bot.command(name="calcular")
@commands.check(es_admin)
async def calcular(ctx):
    """Recalcula la clasificación con los resultados oficiales guardados."""
    datos = cargar_datos()
    recalcular_clasificacion(datos)
    guardar_datos(datos)
    await ctx.send("Clasificación recalculada.")

# ============================
#   CLASIFICACION
# ============================

# Comando: !clasificacion
# Formato correcto: !clasificacion
# Muestra la tabla general con puntos, aciertos y partidos jugados.
@bot.command(name="clasificacion")
async def clasificacion(ctx):
    """Muestra la clasificación general ordenada por puntos y aciertos."""
    datos = cargar_datos()
    recalcular_clasificacion(datos)
    guardar_datos(datos)

    tabla = datos["clasificacion"]
    if not tabla:
        await ctx.send("Todavía no hay puntos calculados.")
        return

    ordenada = sorted(
        tabla.items(),
        key=lambda item: (item[1]["puntos"], item[1]["aciertos"]),
        reverse=True,
    )
    lineas = ["**Clasificación general**"]
    for posicion, (usuario_id, fila) in enumerate(ordenada, start=1):
        nombre = await nombre_usuario(usuario_id)
        lineas.append(
            f"{posicion}. **{nombre}** - {fila['puntos']} pts "
            f"({fila['aciertos']}/{fila['jugados']} aciertos)"
        )
    await ctx.send("\n".join(lineas))

# ============================
#   PENALIZAR
# ============================

# Comando: !penalizar
# Formato correcto: !penalizar @usuario <puntos>
# Ejemplo: !penalizar @Pepe 2
# Permisos: solo administradores con permiso "Gestionar servidor".
# Resta puntos al usuario indicado. El numero debe ser positivo.
@bot.command(name="penalizar")
@commands.check(es_admin)
async def penalizar(ctx, miembro: discord.Member, puntos: int):
    """Aplica una penalización de puntos a un usuario."""
    datos = cargar_datos()
    usuario_id = str(miembro.id)
    datos["penalizaciones"][usuario_id] = datos["penalizaciones"].get(usuario_id, 0) + puntos
    recalcular_clasificacion(datos)
    guardar_datos(datos)
    await ctx.send(f"Penalización aplicada a {miembro.display_name}: -{puntos} puntos.")

# ============================
#   LIMPIAR DATOS
# ============================

# Comando: !limpiardatos
# Formato correcto: !limpiardatos CONFIRMAR
# Permisos: solo administradores con permiso "Gestionar servidor".
# Borra todas las jornadas, pronosticos, resultados, clasificacion y penalizaciones.
@bot.command(name="limpiardatos")
@commands.check(es_admin)
async def limpiar_datos(ctx, confirmacion: str = ""):
    """Reinicia todos los datos guardados de la quiniela tras confirmación explícita."""
    if confirmacion != "CONFIRMAR":
        await ctx.send(
            "Este comando borra jornadas, partidos, pronósticos, resultados y clasificación. "
            "Para confirmar usa `!limpiardatos CONFIRMAR`."
        )
        return

    guardar_datos(datos_vacios())
    await ctx.send("Todos los datos de la quiniela se han borrado.")

# ============================
#   PLENO
# ============================

# Comando: !pleno
# Formato correcto: !pleno <goles-local>-<goles-visitante>
# Ejemplo: !pleno 2-1
# Guarda el pronostico del Pleno al 15 del usuario.
@bot.command(name="pleno")
async def pleno(ctx, resultado: str):
    """Guarda solo el pronóstico del Pleno al 15 para la jornada activa."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    usuario = str(ctx.author.id)

    if not jornada:
        await ctx.send("No hay jornada activa.")
        return
    if not jornada.get("abierta"):
        await ctx.send("La jornada está cerrada y no acepta cambios.")
        return

    try:
        resultado = validar_pleno(resultado)
    except ValueError as error:
        await ctx.send(str(error))
        return

    jornada["pleno15"][usuario] = resultado

    guardar_datos(datos)

    await ctx.send(f"Pleno al 15 guardado para {ctx.author.display_name} en la jornada {jornada_id}: {resultado}")

# ============================
#   CÁLCULO ELIGE8
# ============================
# Formato correcto: !elige8
# Muestra los 8 partidos de la jornada activa con mayor consenso entre usuarios.

@bot.command(name="elige8")
async def elige8(ctx):
    """Muestra los 8 partidos con mayor consenso de la jornada activa."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)

    if not jornada:
        await ctx.send("No hay jornada activa.")
        return
    if not jornada["pronosticos"]:
        await ctx.send("Todavía no hay pronósticos registrados.")
        return

    resultados = calcular_elige8(jornada["pronosticos"])

    lineas = [f"**Informe ELIGE8 - Jornada {jornada_id}**"]
    for partido, signo in resultados.items():
        lineas.append(f"{descripcion_partido(jornada, partido)}: **{signo}**")

    await ctx.send("\n".join(lineas))


###############################################################


def calcular_pleno_media(plenos):
    """Calcula el Pleno al 15 por media redondeada desde un diccionario de marcadores."""
    if not plenos:
        return None

    goles1 = []
    goles2 = []

    for res in plenos.values():
        g1, g2 = map(int, res.split("-"))
        goles1.append(g1)
        goles2.append(g2)

    media1 = round(sum(goles1) / len(goles1))
    media2 = round(sum(goles2) / len(goles2))

    return f"{media1}-{media2}"


def calcular_mayorias(pronosticos):
    """Devuelve el signo más votado para cada partido."""
    conteo = {}

    for usuario, partidos in pronosticos.items():
        for partido, signo in partidos.items():
            if partido not in conteo:
                conteo[partido] = []
            conteo[partido].append(signo)

    resultados = {}

    for partido, lista_signos in conteo.items():
        signo_mas_votado = Counter(lista_signos).most_common(1)[0][0]
        resultados[partido] = signo_mas_votado

    return resultados

# ============================
#   CÁLCULO AUTOMATICO
# ============================
# # # Comando: !calcularautomatico
# Formato correcto: !calcularautomatico
# Permisos: solo administradores con permiso "Gestionar servidor".
# Calcula automaticamente el Pleno al 15 por media y los partidos por mayoria.
@bot.command(name="calcularautomatico")
@commands.check(es_admin)
async def calcular_automatico(ctx):
    """Calcula resultados automáticos por consenso y Pleno al 15 por media."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)

    if not jornada:
        await ctx.send("No hay jornada activa.")
        return

    pleno = calcular_pleno_media_jornada(jornada)
    if pleno:
        jornada["resultados"]["pleno15"] = pleno

    elige8 = calcular_elige8(jornada["pronosticos"])
    for partido, signo in elige8.items():
        jornada["resultados"][partido] = signo

    guardar_datos(datos)

    lineas = [f"Resultados calculados para la jornada {jornada_id}."]
    for partido, signo in elige8.items():
        lineas.append(f"{descripcion_partido(jornada, partido)}: **{signo}**")
    lineas.append(f"`15` Pleno al 15: **{pleno or 'sin pronósticos'}**")

    await ctx.send("\n".join(lineas))

# ============================
#   CÁLCULO ELIGE8
# ============================

def calcular_elige8(pronosticos):
    """Devuelve los 8 partidos con mayor consenso y su signo más votado."""
    conteo = {}

    for usuario, partidos in pronosticos.items():
        for partido, signo in partidos.items():
            conteo.setdefault(partido, []).append(signo)

    porcentajes = {}

    for partido, lista in conteo.items():
        total = len(lista)
        mas_comun = Counter(lista).most_common(1)[0][1]
        porcentajes[partido] = mas_comun / total

    partidos_ordenados = sorted(porcentajes.items(), key=lambda x: x[1], reverse=True)
    elige8 = partidos_ordenados[:8]

    resultados = {}

    for partido, _ in elige8:
        signo = Counter(conteo[partido]).most_common(1)[0][0]
        resultados[partido] = signo

    return resultados

# ============================
#   COMANDOS SLASH (/)
# ============================

async def enviar_interaccion(interaction, mensaje, ephemeral=False):
    """Envía una respuesta slash, usando followup si ya hubo respuesta inicial."""
    if interaction.response.is_done():
        await interaction.followup.send(mensaje, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(mensaje, ephemeral=ephemeral)


def usuario_es_admin(interaction):
    """Comprueba permisos de admin en un comando slash."""
    return bool(interaction.user.guild_permissions.manage_guild)


async def rechazar_si_no_admin(interaction):
    """Responde y bloquea el comando slash si el usuario no es admin."""
    if usuario_es_admin(interaction):
        return False

    await enviar_interaccion(interaction, "No tienes permisos para usar ese comando.", ephemeral=True)
    return True


@bot.tree.command(name="ayudaquiniela", description="Muestra la ayuda de comandos de la quiniela.")
async def slash_ayudaquiniela(interaction: discord.Interaction):
    """Comando slash: muestra la ayuda de la quiniela."""
    await enviar_interaccion(interaction, texto_ayuda_quiniela())


@bot.tree.command(name="ping", description="Comprueba que el bot responde.")
async def slash_ping(interaction: discord.Interaction):
    """Comando slash: responde Pong."""
    await enviar_interaccion(interaction, "Pong.")


@bot.tree.command(name="crearjornada", description="Crea y activa una jornada. Admin.")
@app_commands.describe(numero="Número o identificador de la jornada.")
@app_commands.default_permissions(manage_guild=True)
async def slash_crearjornada(interaction: discord.Interaction, numero: str):
    """Comando slash: crea una jornada y la marca como activa."""
    if await rechazar_si_no_admin(interaction):
        return

    datos = cargar_datos()
    jornada_id = str(numero)
    datos["jornadas"].setdefault(
        jornada_id,
        {
            "abierta": True,
            "partidos": {},
            "pronosticos": {},
            "pleno15": {},
            "resultados": {},
            "creada_en": ahora_iso(),
        },
    )
    datos["jornada_activa"] = jornada_id
    guardar_datos(datos)
    await enviar_interaccion(interaction, f"Jornada {jornada_id} creada y activada.")


@bot.tree.command(name="partido", description="Añade o cambia un partido de la jornada activa. Admin.")
@app_commands.describe(numero="Número del partido.", descripcion="Equipos del partido. Ejemplo: España vs Cabo Verde")
@app_commands.default_permissions(manage_guild=True)
async def slash_partido(interaction: discord.Interaction, numero: str, descripcion: str):
    """Comando slash: añade o actualiza un partido."""
    if await rechazar_si_no_admin(interaction):
        return

    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "Primero crea una jornada con `/crearjornada numero`.")
        return

    jornada["partidos"][str(numero)] = descripcion.strip()
    guardar_datos(datos)
    await enviar_interaccion(interaction, f"{descripcion_partido(jornada, numero)} añadido a la jornada {jornada_id}.")


@bot.tree.command(name="partidos", description="Muestra los partidos de la jornada activa.")
async def slash_partidos(interaction: discord.Interaction):
    """Comando slash: muestra los partidos de la jornada activa."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return
    if not jornada["partidos"]:
        await enviar_interaccion(interaction, f"La jornada {jornada_id} todavía no tiene partidos.")
        return

    lineas = [f"**Jornada {jornada_id}**"]
    estado = "abierta" if jornada.get("abierta") else "cerrada"
    lineas.append(f"Estado: {estado}")
    for numero, descripcion in sorted(jornada["partidos"].items(), key=clave_partido):
        etiqueta_pleno = " (Pleno al 15)" if str(numero) == "15" else ""
        lineas.append(f"`{numero}` - {descripcion}{etiqueta_pleno}")
    if "15" not in jornada["partidos"]:
        lineas.append("`15` - Pleno al 15")
    await enviar_interaccion(interaction, "\n".join(lineas))


@bot.tree.command(name="apostar", description="Guarda tus 14 pronósticos y el Pleno al 15.")
@app_commands.describe(pronos="14 signos seguidos. Ejemplo: 1X12X212X112X1", pleno="Marcador del pleno. Ejemplo: 2-0")
async def slash_apostar(interaction: discord.Interaction, pronos: str, pleno: str):
    """Comando slash: guarda los pronósticos del usuario."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    usuario = str(interaction.user.id)

    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa. Pide a un admin que use `/crearjornada`.")
        return
    if not jornada.get("abierta"):
        await enviar_interaccion(interaction, "La jornada está cerrada y no acepta apuestas.")
        return
    if len(pronos) != 14:
        await enviar_interaccion(interaction, "Debes enviar exactamente 14 signos (1, X o 2). Ejemplo: `1X12X212X112X1`")
        return

    for signo in pronos:
        if signo.upper() not in SIGNOS_VALIDOS:
            await enviar_interaccion(interaction, "Solo se permiten signos `1`, `X` o `2`.")
            return

    try:
        pleno = validar_pleno(pleno)
    except ValueError as error:
        await enviar_interaccion(interaction, str(error))
        return

    jornada["pronosticos"].setdefault(usuario, {})
    for partido, signo in enumerate(pronos, start=1):
        jornada["pronosticos"][usuario][str(partido)] = signo.upper()
    jornada["pleno15"][usuario] = pleno

    guardar_datos(datos)

    resumen = [f"{descripcion_partido(jornada, partido)}: **{signo}**" for partido, signo in sorted(
        jornada["pronosticos"][usuario].items(),
        key=clave_partido,
    )]
    await enviar_interaccion(
        interaction,
        f"Jornada {jornada_id} registrada para **{interaction.user.display_name}**\n"
        + "\n".join(resumen)
        + f"\n`15` Pleno al 15: **{pleno}**",
    )


@bot.tree.command(name="mispronosticos", description="Muestra tus pronósticos de la jornada activa.")
async def slash_mispronosticos(interaction: discord.Interaction):
    """Comando slash: muestra los pronósticos del usuario."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return

    pronosticos = jornada["pronosticos"].get(str(interaction.user.id), {})
    if not pronosticos:
        await enviar_interaccion(interaction, "Aún no tienes pronósticos en la jornada activa.")
        return

    lineas = [f"**Tus pronósticos - Jornada {jornada_id}**"]
    for partido, signo in sorted(pronosticos.items(), key=clave_partido):
        lineas.append(f"{descripcion_partido(jornada, partido)}: **{signo}**")

    pleno = jornada["pleno15"].get(str(interaction.user.id))
    if pleno:
        lineas.append(f"`15` Pleno al 15: **{pleno}**")
    await enviar_interaccion(interaction, "\n".join(lineas))


@bot.tree.command(name="verpronosticos", description="Muestra todos los pronósticos de la jornada activa.")
async def slash_verpronosticos(interaction: discord.Interaction):
    """Comando slash: muestra todos los pronósticos."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return

    usuarios = set(jornada["pronosticos"].keys()) | set(jornada["pleno15"].keys())
    if not usuarios:
        await enviar_interaccion(interaction, "No hay pronósticos.")
        return

    lineas = [f"**Pronósticos Jornada {jornada_id}**"]
    for usuario_id in usuarios:
        nombre = await nombre_usuario(usuario_id)
        lineas.append(f"\n**{nombre}**")

        pronos = jornada["pronosticos"].get(usuario_id, {})
        for partido, signo in sorted(pronos.items(), key=clave_partido):
            lineas.append(f"{descripcion_partido(jornada, partido)}: **{signo}**")

        pleno = jornada["pleno15"].get(usuario_id)
        if pleno:
            lineas.append(f"`15` Pleno al 15: **{pleno}**")

    await enviar_interaccion(interaction, "\n".join(lineas))


@bot.tree.command(name="cerrarjornada", description="Cierra la jornada activa. Admin.")
@app_commands.default_permissions(manage_guild=True)
async def slash_cerrarjornada(interaction: discord.Interaction):
    """Comando slash: cierra la jornada activa."""
    if await rechazar_si_no_admin(interaction):
        return

    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return
    jornada["abierta"] = False
    guardar_datos(datos)
    await enviar_interaccion(interaction, f"Jornada {jornada_id} cerrada.")


@bot.tree.command(name="abrirjornada", description="Reabre la jornada activa. Admin.")
@app_commands.default_permissions(manage_guild=True)
async def slash_abrirjornada(interaction: discord.Interaction):
    """Comando slash: abre la jornada activa."""
    if await rechazar_si_no_admin(interaction):
        return

    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return
    jornada["abierta"] = True
    guardar_datos(datos)
    await enviar_interaccion(interaction, f"Jornada {jornada_id} abierta.")


@bot.tree.command(name="resultado", description="Guarda el resultado oficial de un partido. Admin.")
@app_commands.describe(partido="Número del partido.", signo="Resultado: 1, X o 2.")
@app_commands.choices(signo=[
    app_commands.Choice(name="1 - gana local", value="1"),
    app_commands.Choice(name="X - empate", value="X"),
    app_commands.Choice(name="2 - gana visitante", value="2"),
])
@app_commands.default_permissions(manage_guild=True)
async def slash_resultado(interaction: discord.Interaction, partido: str, signo: app_commands.Choice[str]):
    """Comando slash: guarda un resultado oficial."""
    if await rechazar_si_no_admin(interaction):
        return

    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return
    if str(partido) not in jornada["partidos"]:
        await enviar_interaccion(interaction, "Ese partido no existe en la jornada activa.")
        return

    jornada["resultados"][str(partido)] = signo.value
    recalcular_clasificacion(datos)
    guardar_datos(datos)
    await enviar_interaccion(interaction, f"Resultado guardado: {descripcion_partido(jornada, partido)} -> **{signo.value}**.")


@bot.tree.command(name="calcular", description="Recalcula la clasificación. Admin.")
@app_commands.default_permissions(manage_guild=True)
async def slash_calcular(interaction: discord.Interaction):
    """Comando slash: recalcula la clasificación."""
    if await rechazar_si_no_admin(interaction):
        return

    datos = cargar_datos()
    recalcular_clasificacion(datos)
    guardar_datos(datos)
    await enviar_interaccion(interaction, "Clasificación recalculada.")


@bot.tree.command(name="clasificacion", description="Muestra la clasificación general.")
async def slash_clasificacion(interaction: discord.Interaction):
    """Comando slash: muestra la clasificación."""
    datos = cargar_datos()
    recalcular_clasificacion(datos)
    guardar_datos(datos)

    tabla = datos["clasificacion"]
    if not tabla:
        await enviar_interaccion(interaction, "Todavía no hay puntos calculados.")
        return

    ordenada = sorted(
        tabla.items(),
        key=lambda item: (item[1]["puntos"], item[1]["aciertos"]),
        reverse=True,
    )
    lineas = ["**Clasificación general**"]
    for posicion, (usuario_id, fila) in enumerate(ordenada, start=1):
        nombre = await nombre_usuario(usuario_id)
        lineas.append(
            f"{posicion}. **{nombre}** - {fila['puntos']} pts "
            f"({fila['aciertos']}/{fila['jugados']} aciertos)"
        )
    await enviar_interaccion(interaction, "\n".join(lineas))


@bot.tree.command(name="penalizar", description="Resta puntos a un usuario. Admin.")
@app_commands.describe(usuario="Usuario al que penalizar.", puntos="Puntos a restar.")
@app_commands.default_permissions(manage_guild=True)
async def slash_penalizar(interaction: discord.Interaction, usuario: discord.Member, puntos: int):
    """Comando slash: aplica una penalización."""
    if await rechazar_si_no_admin(interaction):
        return

    datos = cargar_datos()
    usuario_id = str(usuario.id)
    datos["penalizaciones"][usuario_id] = datos["penalizaciones"].get(usuario_id, 0) + puntos
    recalcular_clasificacion(datos)
    guardar_datos(datos)
    await enviar_interaccion(interaction, f"Penalización aplicada a {usuario.display_name}: -{puntos} puntos.")


@bot.tree.command(name="limpiardatos", description="Borra todos los datos guardados. Admin.")
@app_commands.describe(confirmacion="Escribe CONFIRMAR para borrar todo.")
@app_commands.default_permissions(manage_guild=True)
async def slash_limpiardatos(interaction: discord.Interaction, confirmacion: str):
    """Comando slash: reinicia todos los datos guardados."""
    if await rechazar_si_no_admin(interaction):
        return
    if confirmacion != "CONFIRMAR":
        await enviar_interaccion(
            interaction,
            "Este comando borra jornadas, partidos, pronósticos, resultados y clasificación. "
            "Para confirmar usa `/limpiardatos confirmacion:CONFIRMAR`.",
            ephemeral=True,
        )
        return

    guardar_datos(datos_vacios())
    await enviar_interaccion(interaction, "Todos los datos de la quiniela se han borrado.")


@bot.tree.command(name="pleno", description="Cambia solo tu Pleno al 15.")
@app_commands.describe(resultado="Marcador del pleno. Ejemplo: 2-1")
async def slash_pleno(interaction: discord.Interaction, resultado: str):
    """Comando slash: guarda el pleno del usuario."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    usuario = str(interaction.user.id)

    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return
    if not jornada.get("abierta"):
        await enviar_interaccion(interaction, "La jornada está cerrada y no acepta cambios.")
        return

    try:
        resultado = validar_pleno(resultado)
    except ValueError as error:
        await enviar_interaccion(interaction, str(error))
        return

    jornada["pleno15"][usuario] = resultado
    guardar_datos(datos)
    await enviar_interaccion(interaction, f"Pleno al 15 guardado para {interaction.user.display_name} en la jornada {jornada_id}: {resultado}")


@bot.tree.command(name="elige8", description="Muestra los 8 partidos con mayor consenso.")
async def slash_elige8(interaction: discord.Interaction):
    """Comando slash: muestra el informe Elige8."""
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return
    if not jornada["pronosticos"]:
        await enviar_interaccion(interaction, "Todavía no hay pronósticos registrados.")
        return

    resultados = calcular_elige8(jornada["pronosticos"])
    lineas = [f"**Informe ELIGE8 - Jornada {jornada_id}**"]
    for partido, signo in resultados.items():
        lineas.append(f"{descripcion_partido(jornada, partido)}: **{signo}**")
    await enviar_interaccion(interaction, "\n".join(lineas))


@bot.tree.command(name="calcularautomatico", description="Calcula resultados por consenso y pleno medio. Admin.")
@app_commands.default_permissions(manage_guild=True)
async def slash_calcularautomatico(interaction: discord.Interaction):
    """Comando slash: calcula resultados automáticos."""
    if await rechazar_si_no_admin(interaction):
        return

    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await enviar_interaccion(interaction, "No hay jornada activa.")
        return

    pleno = calcular_pleno_media_jornada(jornada)
    if pleno:
        jornada["resultados"]["pleno15"] = pleno

    elige8 = calcular_elige8(jornada["pronosticos"])
    for partido, signo in elige8.items():
        jornada["resultados"][partido] = signo

    guardar_datos(datos)

    lineas = [f"Resultados calculados para la jornada {jornada_id}."]
    for partido, signo in elige8.items():
        lineas.append(f"{descripcion_partido(jornada, partido)}: **{signo}**")
    lineas.append(f"`15` Pleno al 15: **{pleno or 'sin pronósticos'}**")
    await enviar_interaccion(interaction, "\n".join(lineas))

# ============================
#   ERRORES
# ============================
# Evento automatico: gestiona errores de comandos y envia mensajes claros al canal.
@bot.event
async def on_command_error(ctx, error):
    """Convierte errores habituales de comandos en mensajes claros para Discord."""
    if isinstance(error, commands.CheckFailure):
        await ctx.send("No tienes permisos para usar ese comando.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Faltan datos. Usa `!ayudaquiniela` para ver ejemplos.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Algun dato no tiene el formato correcto. Usa `!ayudaquiniela`.")
    elif isinstance(error, commands.CommandNotFound):
        return
    else:
        await ctx.send("Ha ocurrido un error al ejecutar el comando.")
        raise error

# ============================
#   INICIAR BOT
# ============================

if __name__ == "__main__":
    if TOKEN != '':
        bot.run(TOKEN)
