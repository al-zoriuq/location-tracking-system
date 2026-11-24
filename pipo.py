"""Pipo: asistente de voz para el conductor (P3-S5).

La app GPSLink escucha la palabra «Pipo», convierte la pregunta a texto y la
manda aquí:

    POST /api/pipo
    {
      "device_id": "<uuid del celular>",
      "pregunta": "¿cumplí el último pare?",
      "contexto": {                      # lo que el celular sabe en este momento
        "velocidad_kmh": 38.0,           # o null
        "limite_kmh": 30,                # último límite visto (15 min) o null
        "lat": 10.99, "lon": -74.80,     # o null
        "raspberry": "Conectada"         # texto libre, opcional
      }
    }

    -> 200 {"respuesta": "Sí, frenaste hasta 2 kilómetros por hora en el pare de las 3:14."}

El servidor junta lo que hay en la base de datos de ESE vehículo (señales de
hoy, resumen de los últimos 7 días y si paró en cada PARE, calculado con la
ruta) y se lo pasa a Groq con la personalidad de Pipo. La API key de Groq vive
solo aquí, en el .env (GROQ_API_KEY), nunca dentro del APK.

Variables del .env:
    GROQ_API_KEY   obligatoria
    GROQ_MODEL     opcional (por defecto openai/gpt-oss-120b)
"""

import math
import os
import re
from datetime import timedelta

import psycopg2
import psycopg2.errors
import requests
from flask import jsonify, request

URL_GROQ = "https://api.groq.com/openai/v1/chat/completions"
MODELO_POR_DEFECTO = "openai/gpt-oss-120b"

MAX_PREGUNTA = 500
PATRON_DEVICE = re.compile(r"^[\w-]{1,64}$")

# Regla del PARE: cumple si en los 12 s siguientes a la detección el carro
# bajó de 5 km/h (velocidad calculada entre puntos consecutivos de la ruta).
PARE_VENTANA_S = 12
PARE_VEL_MAX_KMH = 5.0
PARE_MAX_EVALUADOS = 10

PERSONALIDAD = """Eres Pipo, el copiloto de voz de un sistema que detecta señales de tránsito \
desde el carro (cámara + Raspberry Pi) en Barranquilla, Colombia. Eres hombre, amable, \
tranquilo y un poco gracioso, y hablas español colombiano.

Cómo respondes:
- Tu respuesta se va a LEER EN VOZ ALTA a alguien que va manejando: máximo 2 o 3 frases \
cortas, sin listas, sin viñetas, sin emojis, sin markdown, sin símbolos raros.
- Di las velocidades como "kilómetros por hora" y las horas como "las 3 y 14".
- Usa SOLO los datos de abajo para hablar de lo que pasó en el recorrido (señales vistas, \
velocidades, si cumplió). Si un dato no está, dilo con sinceridad; nunca inventes \
detecciones ni velocidades.
- Puedes explicar qué significa una señal de tránsito o una norma básica de Colombia con tu \
propio conocimiento.
- "Cumplió" un límite si iba a máximo el límite + 3 km/h (EXCEDE = no cumplió). "Cumplió" un \
PARE si el carro se detuvo (bajó de 5 km/h) poco después de verlo.
- Si el conductor está excediendo el límite ahora mismo, recuérdaselo con amabilidad.
- Nunca animes a manejar rápido ni a usar el celular mientras maneja.
- Si te preguntan algo que no tiene que ver con manejar, responde muy breve y con buena \
onda."""


WEB = """Quien pregunta NO va manejando: está mirando la página web del sistema. \
"Ahora mismo" es lo último que reportó el carro; habla del carro en tercera persona y \
no des avisos de manejo. Aquí puedes responder de lo que sea: el carro elegido, sus \
recorridos de los últimos días, los otros carros, las señales, o cualquier otro tema con \
tu propio conocimiento. Puedes usar hasta 5 frases. Si te preguntan por un dato del \
sistema que no está abajo (por ejemplo, de hace más de 7 días), dilo con sinceridad."""


def registrar(app, cursor_bd, alias_de_numero, numero_de_alias):
    """Agrega /api/pipo a la app Flask. Se pasan las funciones de
    servidorweb.py para no importar ese módulo desde aquí (import circular).

    El celular manda su device_id; la página web manda el alias del carro
    ("vehiculo": "A01") porque nunca ve los device_id."""

    @app.route("/api/pipo", methods=["POST"])
    def pipo():
        datos = request.get_json(silent=True) or {}

        pregunta = str(datos.get("pregunta") or "").strip()
        if not pregunta:
            return jsonify({"error": "Falta la pregunta"}), 400
        pregunta = pregunta[:MAX_PREGUNTA]

        device_id = str(datos.get("device_id") or "").strip()
        numero = None
        if not device_id and datos.get("vehiculo"):
            numero = numero_de_alias(str(datos.get("vehiculo")))
            if numero is None:
                return jsonify({"error": "El vehículo no es válido"}), 400
        elif not PATRON_DEVICE.match(device_id):
            return jsonify({"error": "El device_id no es válido"}), 400
        desde_web = datos.get("origen") == "web"

        contexto = datos.get("contexto")
        if not isinstance(contexto, dict):
            contexto = {}

        clave = os.getenv("GROQ_API_KEY")
        if not clave:
            app.logger.error("Falta GROQ_API_KEY en el .env: Pipo no puede responder")
            return jsonify({
                "error": "Pipo no está configurado en el servidor",
                "respuesta": "Uy, todavía no me han configurado en el servidor.",
            }), 503

        try:
            if numero is not None:
                device_id = device_del_alias(cursor_bd, numero)
                if device_id is None:
                    return jsonify({
                        "error": "No existe ese vehículo",
                        "respuesta": "No encuentro ese carro en la base de datos.",
                    }), 404
            resumen = resumen_vehiculo(cursor_bd, alias_de_numero, device_id)
            if desde_web:
                resumen += "\n\n" + resumen_web(cursor_bd, alias_de_numero, device_id)
        except psycopg2.Error:
            if not device_id:  # the alias could not even be looked up
                app.logger.exception("Pipo: no se pudo leer la base de datos")
                return jsonify({
                    "error": "No se pudo leer la base de datos",
                    "respuesta": "Perdón, no pude revisar los datos del carro. Inténtalo otra vez.",
                }), 503
            app.logger.exception("Pipo: no se pudo leer la base de datos")
            resumen = "(No se pudo leer la base de datos en este momento.)"

        mensajes = [
            {"role": "system", "content": PERSONALIDAD + ("\n\n" + WEB if desde_web else "")},
            {"role": "system", "content": "DATOS DEL VEHÍCULO\n" + resumen
                + "\n\nAHORA MISMO (" + ("último dato del carro" if desde_web else "según el celular")
                + ")\n" + texto_contexto(contexto)},
            {"role": "user", "content": pregunta},
        ]

        try:
            respuesta = preguntar_a_groq(clave, mensajes)
        except Exception:
            app.logger.exception("Pipo: falló la llamada a Groq")
            return jsonify({
                "error": "No se pudo consultar a Groq",
                "respuesta": "Perdón, no pude pensar la respuesta. Inténtalo otra vez.",
            }), 502

        return jsonify({"respuesta": limpiar_para_voz(respuesta)})


# --- Datos de la base ---

def resumen_vehiculo(cursor_bd, alias_de_numero, device_id):
    """Texto con lo que Pipo necesita saber de ese vehículo."""
    lineas = []
    with cursor_bd() as cursor:
        alias = alias_del_device(cursor, alias_de_numero, device_id)
        if alias:
            lineas.append(f"Vehículo: {alias}")

        try:
            hoy = detecciones_de_hoy(cursor, device_id)
            semana = resumen_semana(cursor, device_id)
        except psycopg2.errors.UndefinedTable:
            cursor.connection.rollback()
            return "\n".join(lineas + ["(Esta base de datos todavía no guarda señales.)"])

        pares = [d for d in hoy if d["senal_tipo"] == "PARE"][:PARE_MAX_EVALUADOS]
        paradas = {d["id"]: evaluar_pare(cursor, device_id, d["timestamp_gps"]) for d in pares}

    if hoy:
        lineas.append(f"Señales detectadas HOY ({len(hoy)}, la más reciente primero):")
        for d in hoy:
            lineas.append("- " + linea_deteccion(d, paradas.get(d["id"])))
    else:
        lineas.append("Hoy no se ha detectado ninguna señal.")

    if semana:
        partes = []
        for s in semana:
            texto = f"{s['senal_tipo']}: {s['total']}"
            if s["excesos"]:
                texto += f" ({s['excesos']} con exceso de velocidad"
                if s["vel_max"] is not None:
                    texto += f", máximo {s['vel_max']:.0f} km/h"
                texto += ")"
            partes.append(texto)
        lineas.append("Últimos 7 días: " + "; ".join(partes) + ".")

    return "\n".join(lineas)


# --- Más datos para la página web (ahí se puede preguntar de lo que sea) ---

DIAS_WEB = 7

# Recorrido por día: horas, kilómetros (puntos seguidos con menos de 5 min entre
# ellos) y velocidad máxima entre puntos (2 a 60 s de separación, descartando
# saltos del GPS de más de 200 km/h). timestamp_gps ya está en hora de Bogotá.
SQL_DIAS = """
    WITH p AS (
        SELECT
            timestamp_gps AS t, latitud AS la, longitud AS lo,
            LAG(timestamp_gps) OVER w AS t0, LAG(latitud) OVER w AS la0,
            LAG(longitud) OVER w AS lo0
        FROM ubicaciones
        WHERE device_id = %s
          AND timestamp_gps >= (NOW() AT TIME ZONE 'America/Bogota') - INTERVAL '7 days'
        WINDOW w AS (ORDER BY timestamp_gps)
    ), s AS (
        SELECT
            t,
            EXTRACT(EPOCH FROM t - t0) AS dt,
            2 * 6371 * ASIN(SQRT(
                POWER(SIN(RADIANS(la - la0) / 2), 2)
                + COS(RADIANS(la0)) * COS(RADIANS(la)) * POWER(SIN(RADIANS(lo - lo0) / 2), 2)
            )) AS km
        FROM p
    )
    SELECT
        t::date AS dia,
        MIN(t) AS desde,
        MAX(t) AS hasta,
        COALESCE(SUM(km) FILTER (WHERE dt > 0 AND dt <= 300), 0) AS km,
        MAX(km / dt * 3600) FILTER (WHERE dt BETWEEN 2 AND 60 AND km / dt * 3600 < 200) AS vel_max
    FROM s
    GROUP BY 1
    ORDER BY 1 DESC
"""

SQL_SENALES_DIAS = """
    SELECT
        timestamp_gps::date AS dia,
        senal_tipo,
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE cumplimiento = 'EXCEDE') AS excesos
    FROM detecciones_senal
    WHERE device_id = %s
      AND timestamp_gps >= (NOW() AT TIME ZONE 'America/Bogota') - INTERVAL '7 days'
    GROUP BY 1, 2
    ORDER BY 1 DESC, 3 DESC
"""

SQL_FLOTA = """
    SELECT
        a.numero,
        (SELECT u.timestamp_gps FROM ubicaciones u
         WHERE u.device_id = a.device_id
         ORDER BY u.timestamp_gps DESC LIMIT 1) AS ultimo
    FROM alias_dispositivos a
    ORDER BY a.numero
    LIMIT 20
"""


def resumen_web(cursor_bd, alias_de_numero, device_id):
    """Recorridos y señales por día de este carro, y los demás carros."""
    lineas = []
    with cursor_bd() as cursor:
        try:
            cursor.execute(SQL_DIAS, (device_id,))
            dias = cursor.fetchall()
        except psycopg2.Error:
            cursor.connection.rollback()
            dias = []
        try:
            cursor.execute(SQL_SENALES_DIAS, (device_id,))
            senales = cursor.fetchall()
        except psycopg2.Error:
            cursor.connection.rollback()
            senales = []
        try:
            cursor.execute(SQL_FLOTA)
            flota = cursor.fetchall()
        except psycopg2.Error:
            cursor.connection.rollback()
            flota = []

    por_dia = {}
    for s in senales:
        texto = f"{s['senal_tipo']} {s['total']}"
        if s["excesos"]:
            texto += f" ({s['excesos']} con exceso)"
        por_dia.setdefault(s["dia"], []).append(texto)

    if dias:
        lineas.append(f"Recorridos de los últimos {DIAS_WEB} días (el más reciente primero):")
        for d in dias:
            texto = (f"- {d['dia']:%d/%m}: de {d['desde']:%H:%M} a {d['hasta']:%H:%M}, "
                     f"{float(d['km']):.1f} km")
            if d["vel_max"] is not None:
                texto += f", velocidad máxima unos {float(d['vel_max']):.0f} km/h"
            if d["dia"] in por_dia:
                texto += ". Señales: " + ", ".join(por_dia[d["dia"]])
            lineas.append(texto)
    else:
        lineas.append(f"No hay recorridos de este carro en los últimos {DIAS_WEB} días.")

    if flota:
        partes = []
        for f in flota:
            cuando = f"{f['ultimo']:%d/%m %H:%M}" if f["ultimo"] else "nunca"
            partes.append(f"{alias_de_numero(f['numero'])} (último dato {cuando})")
        lineas.append("Carros del sistema: " + "; ".join(partes) + ".")

    return "\n".join(lineas)


def device_del_alias(cursor_bd, numero):
    with cursor_bd() as cursor:
        cursor.execute("SELECT device_id FROM alias_dispositivos WHERE numero = %s", (numero,))
        fila = cursor.fetchone()
    return fila["device_id"] if fila else None


def alias_del_device(cursor, alias_de_numero, device_id):
    try:
        cursor.execute(
            "SELECT numero FROM alias_dispositivos WHERE device_id = %s", (device_id,)
        )
    except psycopg2.errors.UndefinedTable:
        cursor.connection.rollback()
        return None
    fila = cursor.fetchone()
    return alias_de_numero(fila["numero"]) if fila else None


SQL_HOY = """
    SELECT
        id,
        timestamp_gps,
        senal_texto,
        senal_tipo,
        senal_valor,
        vel_fuente,
        CASE vel_fuente
            WHEN 'GPS' THEN vel_gps
            WHEN 'MPU' THEN vel_mpu
        END AS velocidad,
        cumplimiento
    FROM detecciones_senal
    WHERE device_id = %s
      AND timestamp_gps >= date_trunc('day', NOW() AT TIME ZONE 'America/Bogota')
    ORDER BY timestamp_gps DESC
    LIMIT 40
"""

SQL_SEMANA = """
    SELECT
        senal_tipo,
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE cumplimiento = 'EXCEDE') AS excesos,
        MAX(CASE vel_fuente WHEN 'GPS' THEN vel_gps WHEN 'MPU' THEN vel_mpu END)
            FILTER (WHERE cumplimiento = 'EXCEDE') AS vel_max
    FROM detecciones_senal
    WHERE device_id = %s
      AND timestamp_gps >= (NOW() AT TIME ZONE 'America/Bogota') - INTERVAL '7 days'
    GROUP BY senal_tipo
    ORDER BY total DESC
"""

SQL_RUTA_PARE = """
    SELECT latitud, longitud, timestamp_gps
    FROM ubicaciones
    WHERE device_id = %s
      AND timestamp_gps BETWEEN %s AND %s
    ORDER BY timestamp_gps
"""


def detecciones_de_hoy(cursor, device_id):
    cursor.execute(SQL_HOY, (device_id,))
    return cursor.fetchall()


def resumen_semana(cursor, device_id):
    cursor.execute(SQL_SEMANA, (device_id,))
    return cursor.fetchall()


def evaluar_pare(cursor, device_id, momento):
    """Velocidad mínima (km/h) en los segundos después de un PARE, o None si la
    ruta no tiene suficientes puntos para saberlo."""
    cursor.execute(SQL_RUTA_PARE, (
        device_id,
        momento - timedelta(seconds=1),
        momento + timedelta(seconds=PARE_VENTANA_S),
    ))
    puntos = cursor.fetchall()
    velocidades = []
    for a, b in zip(puntos, puntos[1:]):
        dt = (b["timestamp_gps"] - a["timestamp_gps"]).total_seconds()
        if dt <= 0:
            continue
        metros = distancia_m(a["latitud"], a["longitud"], b["latitud"], b["longitud"])
        velocidades.append(metros / dt * 3.6)
    return min(velocidades) if len(velocidades) >= 2 else None


def distancia_m(lat1, lon1, lat2, lon2):
    r = 6_371_000
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def linea_deteccion(d, vel_min_pare=None):
    hora = d["timestamp_gps"].strftime("%H:%M:%S")
    texto = f"{hora} {d['senal_texto']}"
    if d["velocidad"] is not None:
        texto += f", iba a {d['velocidad']:.0f} km/h"
    if d["senal_tipo"] == "PARE":
        if vel_min_pare is None:
            texto += ", no hay suficientes puntos de ruta para saber si paró"
        elif vel_min_pare <= PARE_VEL_MAX_KMH:
            texto += f", SÍ paró (bajó a {vel_min_pare:.0f} km/h)"
        else:
            texto += f", NO paró (lo mínimo fue {vel_min_pare:.0f} km/h)"
    elif d["cumplimiento"] == "EXCEDE":
        texto += ", EXCEDIÓ el límite"
    elif d["cumplimiento"] == "SI":
        texto += ", cumplió el límite"
    return texto


def texto_contexto(c):
    partes = []
    v = numero(c.get("velocidad_kmh"))
    limite = numero(c.get("limite_kmh"))
    partes.append(f"Velocidad: {v:.0f} km/h" if v is not None else "Velocidad: sin dato de GPS")
    if limite is not None:
        partes.append(f"Último límite visto: {limite:.0f} km/h")
        if v is not None and v > limite + 3:
            partes.append(f"ESTÁ EXCEDIENDO el límite por {v - limite:.0f} km/h")
    else:
        partes.append("No ha visto un límite de velocidad en los últimos 15 minutos")
    pi = str(c.get("raspberry") or "").strip()[:40]
    if pi:
        partes.append(f"Raspberry: {pi}")
    return ". ".join(partes) + "."


def numero(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# --- Groq ---

def preguntar_a_groq(clave, mensajes):
    modelo = os.getenv("GROQ_MODEL") or MODELO_POR_DEFECTO
    cuerpo = {
        "model": modelo,
        "messages": mensajes,
        "temperature": 0.5,
        "max_completion_tokens": 700,
    }
    # Los gpt-oss "piensan" antes de responder; poco basta para esto y es más rápido.
    if modelo.startswith("openai/gpt-oss"):
        cuerpo["reasoning_effort"] = "low"
    r = requests.post(
        URL_GROQ,
        headers={"Authorization": f"Bearer {clave}"},
        json=cuerpo,
        timeout=20,
    )
    r.raise_for_status()
    texto = r.json()["choices"][0]["message"].get("content") or ""
    if not texto.strip():
        raise ValueError("Groq devolvió una respuesta vacía")
    return texto


def limpiar_para_voz(texto):
    """Quita lo que suena raro leído en voz alta (markdown, viñetas)."""
    texto = re.sub(r"[*_#`>]", "", texto)
    texto = re.sub(r"^\s*[-•]\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()
