import discord
from discord.ext import commands
import json
import os
from collections import Counter

TOKEN = "MTUxMzgzNjA5NTYwMTc3MDYwNw.GkRR4j.EfWgAHMd7mI6HYQJs8ARQbiYgWuOM3VqCWCIVE"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------------
#   SISTEMA DE ARCHIVO JSON
# ------------------------------

RUTA = "datos_quiniela.json"

def cargar_datos():
    if not os.path.exists(RUTA):
        with open(RUTA, "w") as f:
            json.dump({
                "pronosticos": {},
                "pleno15": {},
                "resultados": {},
                "clasificacion": {},
                "penalizaciones": {}
            }, f, indent=4)

    with open(RUTA, "r") as f:
        return json.load(f)

def guardar_datos(datos):
    with open(RUTA, "w") as f:
        json.dump(datos, f, indent=4)

# ------------------------------
#   EVENTO DE INICIO
# ------------------------------

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

# ------------------------------
#   COMANDO: !ping
# ------------------------------

@bot.command()
async def ping(ctx):
    await ctx.send("Pong 💞")

# ------------------------------
#   COMANDO: !pronostico
# ------------------------------

@bot.command()
async def pronostico(ctx, partido: str, signo: str):
    datos = cargar_datos()
    usuario = str(ctx.author.id)

    if usuario not in datos["pronosticos"]:
        datos["pronosticos"][usuario] = {}

    datos["pronosticos"][usuario][partido] = signo.upper()

    guardar_datos(datos)

    await ctx.send(f"Pronóstico guardado para {ctx.author.display_name}: Partido {partido} → {signo.upper()}")

# ------------------------------
#   COMANDO: !mispronosticos
# ------------------------------

@bot.command()
async def mispronosticos(ctx):
    datos = cargar_datos()
    usuario = str(ctx.author.id)

    if usuario not in datos["pronosticos"]:
        await ctx.send("No tienes pronósticos registrados todavía.")
        return

    mensaje = f"📋 **Tus pronósticos, {ctx.author.display_name}:**\n\n"

    for partido, signo in datos["pronosticos"][usuario].items():
        mensaje += f"• Partido {partido}: {signo}\n"

    await ctx.send(mensaje)

# ------------------------------
#   COMANDO: !verpronosticos
# ------------------------------

@bot.command()
async def verpronosticos(ctx):
    datos = cargar_datos()
    pronos = datos["pronosticos"]

    if not pronos:
        await ctx.send("Aún no hay pronósticos registrados.")
        return

    mensaje = "📋 **Pronósticos de la jornada**\n\n"

    for usuario_id, partidos in pronos.items():
        usuario = await bot.fetch_user(int(usuario_id))
        mensaje += f"**{usuario.display_name}:**\n"

        for partido, signo in partidos.items():
            mensaje += f"• Partido {partido}: {signo}\n"

        mensaje += "\n"

    await ctx.send(mensaje)

# ------------------------------
#   COMANDO: !pleno
# ------------------------------

@bot.command()
async def pleno(ctx, resultado: str):
    datos = cargar_datos()
    usuario = str(ctx.author.id)

    datos["pleno15"][usuario] = resultado

    guardar_datos(datos)

    await ctx.send(f"Pleno al 15 guardado para {ctx.author.display_name}: {resultado}")

# ------------------------------
#   CALCULAR PLENO AL 15 (MEDIA)
# ------------------------------

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

# ------------------------------
#   CALCULAR 8 PARTIDOS POR MAYORÍA
# ------------------------------

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

# ------------------------------
#   COMANDO: !calcular
# ------------------------------

@bot.command()
async def calcular(ctx):
    datos = cargar_datos()

    # 1) Pleno al 15 por media
    pleno = calcular_pleno_media(datos["pleno15"])
    datos["resultados"]["pleno15"] = pleno

    # 2) 8 partidos por mayoría
    mayorias = calcular_mayorias(datos["pronosticos"])
    for partido, signo in mayorias.items():
        datos["resultados"][partido] = signo

    guardar_datos(datos)

    await ctx.send("Resultados oficiales calculados automáticamente ✔")

# ------------------------------
#   CALCULAR PUNTOS
# ------------------------------

def calcular_puntos(datos):
    puntos = {}

    for usuario, pronos in datos["pronosticos"].items():
        puntos[usuario] = 0

        # Partidos normales
        for partido, pronostico in pronos.items():
            if partido == "pleno15":
                continue

            if partido in datos["resultados"]:
                if datos["resultados"][partido] == pronostico:
                    puntos[usuario] += 1

        # Pleno al 15
        if usuario in datos["pleno15"]:
            pron = datos["pleno15"][usuario]
            real = datos["resultados"]["pleno15"]

            if pron == real:
                puntos[usuario] += 2
            else:
                g1_p, g2_p = map(int, pron.split("-"))
                g1_r, g2_r = map(int, real.split("-"))

                signo_p = "1" if g1_p > g2_p else "2" if g1_p < g2_p else "X"
                signo_r = "1" if g1_r > g2_r else "2" if g1_r < g2_r else "X"

                if signo_p == signo_r:
                    puntos[usuario] += 1

    return puntos

# ------------------------------
#   COMANDO: !clasificacion
# ------------------------------

@bot.command()
async def clasificacion(ctx):
    datos = cargar_datos()
    puntos = calcular_puntos(datos)

    datos["clasificacion"] = puntos
    guardar_datos(datos)

    texto = "🏆 **Clasificación actual**\n\n"
    orden = sorted(puntos.items(), key=lambda x: x[1], reverse=True)

    for i, (usuario, pts) in enumerate(orden, start=1):
        nombre = await bot.fetch_user(int(usuario))
        texto += f"{i}. **{nombre.display_name}** — {pts} puntos\n"

    await ctx.send(texto)

# ------------------------------
#   COMANDO: !penalizacion
# ------------------------------

@bot.command()
async def penalizacion(ctx, coste: float = 4.0):
    datos = cargar_datos()
    puntos = calcular_puntos(datos)

    orden = sorted(puntos.items(), key=lambda x: x[1])
    ultimo = orden[0][0]
    primero = orden[-1][0]
    cantidad = coste / 4

    datos["penalizaciones"] = {
        "ultimo": ultimo,
        "primero": primero,
        "cantidad": cantidad
    }

    guardar_datos(datos)

    u1 = await bot.fetch_user(int(ultimo))
    u2 = await bot.fetch_user(int(primero))

    await ctx.send(f"💸 Penalización: **{u1.display_name}** paga **{cantidad}€** a **{u2.display_name}**")

# ------------------------------
#   INICIAR BOT
# ------------------------------

bot.run(TOKEN)
