import json
import os
from collections import Counter
from datetime import datetime, timezone

import discord
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
#   FUNCIONES INTERNAS
# ============================

def ahora_iso():
    return datetime.now(timezone.utc).isoformat()


def normalizar_signo(signo):
    signo = str(signo).strip().upper()
    if signo not in SIGNOS_VALIDOS:
        raise ValueError("El signo debe ser 1, X o 2.")
    return signo


def cargar_datos():
    if not os.path.exists(RUTA_DATOS):
        guardar_datos(DATOS_BASE.copy())

    with open(RUTA_DATOS, "r", encoding="utf-8") as archivo:
        try:
            datos = json.load(archivo)
        except json.JSONDecodeError:
            datos = DATOS_BASE.copy()

    for clave, valor in DATOS_BASE.items():
        datos.setdefault(clave, valor.copy() if isinstance(valor, dict) else valor)

def guardar_datos(datos):
    with open(RUTA_DATOS, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, indent=4, ensure_ascii=False)


def jornada_actual(datos):
    jornada_id = datos.get("jornada_activa")
    if not jornada_id:
        return None, None
    return jornada_id, datos["jornadas"].get(str(jornada_id))


def clave_partido(item):
    numero = item[0]
    return (0, int(numero)) if str(numero).isdigit() else (1, str(numero))


def descripcion_partido(jornada, partido):
    descripcion = jornada.get("partidos", {}).get(str(partido))
    if descripcion:
        return f"Partido {partido} - {descripcion}"
    return f"Partido {partido}"


def recalcular_clasificacion(datos):
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


async def nombre_usuario(usuario_id):
    try:
        usuario = await bot.fetch_user(int(usuario_id))
        return usuario.display_name
    except discord.DiscordException:
        return f"Usuario {usuario_id}"


def es_admin(ctx):
    return ctx.author.guild_permissions.manage_guild

# ============================
#   CÁLCULO PLENO AL 15
# ============================

def calcular_pleno_media_jornada(jornada):
    plenos = jornada.get("pleno15", {})
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

# ============================
#   CÁLCULO ELIGE8
# ============================

def calcular_elige8(pronosticos):
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
#   CLASIFICACIÓN GENERAL
# ============================

def recalcular_clasificacion(datos):
    clasificacion = {}

    for jornada in datos["jornadas"].values():
        resultados = jornada.get("resultados", {})

        for usuario_id, pronos in jornada.get("pronosticos", {}).items():
            puntos = 0
            aciertos = 0
            jugados = 0

            for partido, signo in pronos.items():
                if partido in resultados:
                    jugados += 1
                    if signo == resultados[partido]:
                        aciertos += 1
                        puntos += PUNTOS_ACIERTO

            fila = clasificacion.setdefault(usuario_id, {"puntos": 0, "aciertos": 0, "jugados": 0})
            fila["puntos"] += puntos
            fila["aciertos"] += aciertos
            fila["jugados"] += jugados

    datos["clasificacion"] = clasificacion

# ============================
#   EVENTOS Y COMANDOS
# ============================

# Evento automatico: se ejecuta cuando el bot se conecta correctamente.
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")


# Comando: !ping
# Formato correcto: !ping
# Sirve para comprobar que el bot responde.
@bot.command(name="ping")
async def ping(ctx):
    await ctx.send("Pong.")


# Comando: !ayudaquiniela
# Formato correcto: !ayudaquiniela
# Muestra la lista de comandos disponibles y su formato basico.
@bot.command(name="ayudaquiniela")
async def ayuda_quiniela(ctx):
    await ctx.send(
        "**Comandos de la quiniela**\n"
        "`!crearjornada <numero>` - crea y activa una jornada. Admin.\n"
        "`!partido <numero> <local> vs <visitante>` - añade un partido. Admin.\n"
        "`!cerrarjornada` / `!abrirjornada` - bloquea o reabre apuestas. Admin.\n"
        "`!apostar <partido> <1|X|2>` - guarda tu pronóstico.\n"
        "`!mispronosticos` - muestra tus pronósticos.\n"
        "`!verpronosticos` - muestra todos los pronósticos.\n"
        "`!partidos` / `!listarpartidos` - muestra la lista de partidos.\n"
        "`!resultado / `!apostar 1X12X212X112X1 2-0` - guarda resultado oficial. Admin.\n"
        "`!calcular` - recalcula puntos. Admin.\n"
        "`!clasificacion` - muestra la tabla general.\n"
        "`!penalizar @usuario <puntos>` - resta puntos. Admin."
    )


# Comando: !crearjornada
# Formato correcto: !crearjornada <numero>
# Ejemplo: !crearjornada 1
# Permisos: solo administradores con permiso "Gestionar servidor".
# Crea una jornada si no existe y la marca como jornada activa.
@bot.command(name="crearjornada")
@commands.check(es_admin)
async def crear_jornada(ctx, numero):
    datos = cargar_datos()
    jornada_id = str(numero)
    datos["jornadas"].setdefault(
        jornada_id,
        {
            "abierta": True,
            "partidos": {},
            "pronosticos": {},
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
# AÃ±ade o sustituye un partido dentro de la jornada activa.
@bot.command(name="partido")
@commands.check(es_admin)
async def agregar_partido(ctx, numero, *, descripcion):
    datos = cargar_datos()
    jornada_id, jornada = jornada_actual(datos)
    if not jornada:
        await ctx.send("Primero crea una jornada con `!crearjornada <numero>`.")
        return

    jornada["partidos"][str(numero)] = descripcion.strip()
    guardar_datos(datos)
    await ctx.send(f"Partido {numero} aÃ±adido a la jornada {jornada_id}: {descripcion}")


# Comando: !partidos
# Formato correcto: !partidos
# Muestra los partidos configurados en la jornada activa.
@bot.command(name="partidos", aliases=["listarpartidos"])
async def ver_partidos(ctx):
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
        lineas.append(f"`{numero}` - {descripcion}")
    lineas.append("`15` - Pleno al 15")
    await ctx.send("\n".join(lineas))

# ============================
#   APOSTAR
# ============================

# Comando: !apostar
# Formato correcto: !apostar <numero_partido> <signo>
# Signos validos: 1, X o 2
# Ejemplo: !apostar 1X12X212X112X1 2-0
# Guarda o actualiza tu pronostico para un partido de la jornada activa.
@bot.command(name="apostar")
async def jornada(ctx, pronos: str, pleno: str):
    datos = cargar_datos()
    usuario = str(ctx.author.id)

    # Validación de longitud (14 partidos)
    if len(pronos) != 14:
        await ctx.send("❌ Debes enviar exactamente 8 signos (1, X o 2). Ejemplo: 1X2X12X1")
        return

    # Validación de signos
    for s in pronos:
        if s.upper() not in ["1", "X", "2"]:
            await ctx.send("❌ Solo se permiten signos 1, X o 2.")
            return

    # Validación del pleno al 15
    try:
        g1, g2 = pleno.split("-")
        g1 = int(g1)
        g2 = int(g2)
    except:
        await ctx.send("❌ El pleno debe tener formato número-número. Ejemplo: 2-1")
        return

    # Guardar pronósticos
    if usuario not in datos["pronosticos"]:
        datos["pronosticos"][usuario] = {}

    for i, signo in enumerate(pronos, start=1):
        datos["pronosticos"][usuario][str(i)] = signo.upper()

    # Guardar pleno al 15
    datos["pleno15"][usuario] = pleno

    guardar_datos(datos)

    await ctx.send(
        f"📝 Jornada registrada para **{ctx.author.display_name}**\n"
        f"• Partidos: {pronos}\n"
        f"• Pleno al 15: {pleno}"
    )


    return datos

# ============================
#   MIS PRONÓSTICOS
# ============================

# Comando: !mispronosticos
# Formato correcto: !mispronosticos
# Muestra los pronosticos guardados por quien ejecuta el comando.
@bot.command(name="mispronosticos")
async def mis_pronosticos(ctx):
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
        descripcion = jornada["partidos"].get(partido, "Partido sin descripciÃ³n")
        lineas.append(f"`{partido}` {descripcion}: **{signo}**")
    await ctx.send("\n".join(lineas))

# ============================
#   VER PRONÓSTICOS
# ============================

# Comando: !verpronosticos
# Formato correcto: !verpronosticos
# Muestra todos los pronosticos registrados en la jornada activa.
@bot.command(name="verpronosticos")
async def ver_pronosticos(ctx):
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
        for partido, signo in sorted(pronos.items(), key=lambda x: int(x[0])):
            desc = jornada["partidos"].get(partido, "Partido")
            lineas.append(f"`{partido}` {desc}: **{signo}**")

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
    await ctx.send(f"Resultado guardado: partido {partido} -> {signo}.")

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
    datos = cargar_datos()
    usuario_id = str(miembro.id)
    datos["penalizaciones"][usuario_id] = datos["penalizaciones"].get(usuario_id, 0) + puntos
    recalcular_clasificacion(datos)
    guardar_datos(datos)
    await ctx.send(f"Penalización aplicada a {miembro.display_name}: -{puntos} puntos.")

# ============================
#   PLENO
# ============================

# Comando: !pleno
# Formato correcto: !pleno <goles-local>-<goles-visitante>
# Ejemplo: !pleno 2-1
# Guarda el pronostico del Pleno al 15 del usuario.
@bot.command(name="pleno")
async def pleno(ctx, resultado: str):
    datos = cargar_datos()
    usuario = str(ctx.author.id)

    datos["pleno15"][usuario] = resultado

    guardar_datos(datos)

    await ctx.send(f"Pleno al 15 guardado para {ctx.author.display_name}: {resultado}")

# ============================
#   CÁLCULO ELIGE8
# ============================
# Formato correcto: !informe8 <goles-local>-<goles-visitante>
# Ejemplo: !informe 8
# Guarda el pronostico del Pleno al 15 del usuario.

@bot.command()
async def informe8(ctx):
    datos = cargar_datos()
    pronosticos = datos["pronosticos"]

    if not pronosticos:
        await ctx.send("❌ No hay pronósticos registrados todavía.")
        return

    conteo = {}  # { partido: [lista de signos] }

    # Reunir todos los signos por partido
    for usuario, partidos in pronosticos.items():
        for partido, signo in partidos.items():
            if partido not in conteo:
                conteo[partido] = []
            conteo[partido].append(signo)

    porcentajes = {}  # { partido: porcentaje_mayor }

    # Calcular porcentaje mayoritario por partido
    for partido, lista_signos in conteo.items():
        total = len(lista_signos)
        mas_comun = Counter(lista_signos).most_common(1)[0][1]
        porcentaje = mas_comun / total
        porcentajes[partido] = porcentaje

    # Ordenar partidos por consenso
    partidos_ordenados = sorted(porcentajes.items(), key=lambda x: x[1], reverse=True)

    # Seleccionar los 8 partidos con mayor consenso
    elige8 = partidos_ordenados[:8]

    # Construir informe visual
    mensaje = "📊 **ELIGE8 – Partidos con mayor consenso**\n\n"
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣"]

    for i, (partido, porcentaje) in enumerate(elige8):
        signo_mas_votado = Counter(conteo[partido]).most_common(1)[0][0]
        porcentaje_txt = round(porcentaje * 100)

        mensaje += (
            f"{emojis[i]} Partido {partido} — {porcentaje_txt}% → Resultado: {signo_mas_votado}\n"
        )

    mensaje += "\n🧠 *Elige8 calculado según el consenso de los jugadores.*"

    await ctx.send(mensaje)


# Metodo interno.
# Formato de entrada: {"usuario_id": "2-1", "otro_usuario_id": "1-1"}
# Devuelve el Pleno al 15 calculado por media redondeada.
def calcular_pleno_media(plenos):
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


# Metodo interno.
# Formato de entrada: {"usuario_id": {"1": "X", "2": "1"}}
# Devuelve el signo mas votado por cada partido.
def calcular_mayorias(pronosticos):
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

def calcular_elige8(pronosticos):
    conteo = {}  # { partido: [lista de signos] }

    # Reunir todos los signos por partido
    for usuario, partidos in pronosticos.items():
        for partido, signo in partidos.items():
            conteo.setdefault(partido, []).append(signo)

    porcentajes = {}  # { partido: porcentaje_mayor }

    # Calcular porcentaje mayoritario por partido
    for partido, lista in conteo.items():
        total = len(lista)
        mas_comun = Counter(lista).most_common(1)[0][1]
        porcentajes[partido] = mas_comun / total

    # Ordenar partidos por consenso (de mayor a menor)
    partidos_ordenados = sorted(porcentajes.items(), key=lambda x: x[1], reverse=True)
    elige8 = partidos_ordenados[:8]

    resultados = {}

    for partido, _ in elige8:
        signo_mas_votado = Counter(conteo[partido]).most_common(1)[0][0]
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

    await ctx.send(f"Resultados calculados.\nPleno oficial: {pleno}")

# ============================
#   CÁLCULO ELIGE8
# ============================

def calcular_elige8(pronosticos):
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
#   ERRORES
# ============================
# Evento automatico: gestiona errores de comandos y envia mensajes claros al canal.
@bot.event
async def on_command_error(ctx, error):
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
