from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import math
import requests
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Load environment variables from .env (RDS credentials, etc.)
load_dotenv()

app = Flask(__name__)
CORS(app)  # allow the React frontend to call this API from the browser

# RDS connection settings, pulled from the .env file
password = os.getenv("rdspass")
host = os.getenv("rdshost")
database = os.getenv("rdsdbname")
user = os.getenv("rdsuser")

# GPS timestamps are stored as Barranquilla wall-clock time without timezone
# (the sniffer drops the -05:00 offset the phone sends), so "now" for date
# validation has to be computed in that same zone, not in UTC.
ZONA_DATOS = ZoneInfo("America/Bogota")

# Folder where the built React app (Vite output) lives, served as static files
BUILD_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "disenop2web",
    "dist"
)

# Serve the React app's index.html at the root URL
@app.route("/")
def inicio():

    return send_from_directory(BUILD_FOLDER, "index.html")

# Serve any other built asset (JS, CSS, images) requested by the React app
@app.route("/<path:path>")
def archivos_react(path):
    return send_from_directory(BUILD_FOLDER, path)

# API - GEOCODING (place name / address -> coordinates + search area)

# Uses Nominatim (OpenStreetMap's free geocoder, same map tiles the app
# already uses) to turn a place name or address into a location. Cities and
# towns come back with a bounding box (their real extent); specific
# addresses come back as a single point, to which we apply a small radius.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
RADIO_DIRECCION_KM = 0.3  # used only when Nominatim returns a point, not a box

@app.route("/api/buscar-lugar")
def buscar_lugar():
    consulta = request.args.get("q", default="", type=str).strip()

    if not consulta:
        return jsonify({"error": "Falta el parametro q"}), 400

    try:
        respuesta = requests.get(
            NOMINATIM_URL,
            params={
                "q": consulta,
                "format": "json",
                "limit": 5,
                "addressdetails": 1,
            },
            headers={
                # Nominatim's usage policy requires a descriptive User-Agent
                "User-Agent": "GPSLink-location-tracking-system/1.0"
            },
            timeout=5,
        )
        respuesta.raise_for_status()
        resultados = respuesta.json()
    except requests.RequestException as e:
        return jsonify({"error": f"Error consultando el geocodificador: {e}"}), 502

    lugares = []
    for r in resultados:
        lat = float(r["lat"])
        lon = float(r["lon"])
        bbox = r.get("boundingbox")  # [lat_min, lat_max, lon_min, lon_max] as strings

        if bbox:
            lat_min, lat_max, lon_min, lon_max = map(float, bbox)
        else:
            # Point-only result: build a small box around it instead
            delta = RADIO_DIRECCION_KM / 111.0  # ~km per degree of latitude
            lat_min, lat_max = lat - delta, lat + delta
            lon_min, lon_max = lon - delta, lon + delta

        lugares.append({
            "nombre": r.get("display_name", consulta),
            "lat": lat,
            "lon": lon,
            "lat_min": lat_min,
            "lat_max": lat_max,
            "lon_min": lon_min,
            "lon_max": lon_max,
        })

    return jsonify(lugares)


# CONNECTION TO POSTGRESQL

# Opens a new connection to the RDS database.
# Called fresh for each request instead of keeping one long-lived connection.
def obtener_conexion():

    return psycopg2.connect(
        host=host,
        port=5432,
        database=database,
        user=user,
        password=password,
        sslmode='verify-full',
        sslrootcert='./global-bundle.pem'
    )


# Opens a connection + dict cursor for one query and always closes both,
# even if the query fails half-way.
@contextmanager
def cursor_bd():

    conexion = obtener_conexion()

    try:
        cursor = conexion.cursor(cursor_factory=RealDictCursor)

        try:
            yield cursor
        finally:
            cursor.close()

    finally:
        conexion.close()


# Database failures answer JSON (the frontend shows the "error" text) instead
# of Flask's HTML traceback page. Details go to the server log, not the client.
@app.errorhandler(psycopg2.OperationalError)
def error_bd_no_disponible(e):
    app.logger.exception("No se pudo conectar con la base de datos")
    return jsonify({
        "error": "No se pudo conectar con la base de datos. Intenta de nuevo en unos segundos."
    }), 503


@app.errorhandler(psycopg2.Error)
def error_bd(e):
    app.logger.exception("Error consultando la base de datos")
    return jsonify({"error": "Error consultando la base de datos"}), 500


# API - LATEST LOCATION

# Returns only the single most recent GPS point (used for the map marker
# and the "last position" panel in the frontend).
@app.route("/api/ultima-ubicacion")
def ultima_ubicacion():

    with cursor_bd() as cursor:

        cursor.execute("""
            SELECT
                device_id,
                ip_origen,
                latitud,
                longitud,
                timestamp_gps,
                timestamp_recepcion
            FROM ubicaciones
            ORDER BY id DESC
            LIMIT 1
        """)

        ubicacion = cursor.fetchone()


    if ubicacion is None:

        return jsonify({
            "error": "No hay ubicaciones registradas"
        }), 404


    # Convert datetime objects to plain strings so they can be JSON-serialized
    ubicacion["timestamp_gps"] = str(
        ubicacion["timestamp_gps"]
    )

    ubicacion["timestamp_recepcion"] = str(
        ubicacion["timestamp_recepcion"]
    )


    return jsonify(ubicacion)


# DATE FILTER PARSING

FORMATOS_CON_SEGUNDOS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")
FORMATOS_SIN_SEGUNDOS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M")

# Current time in the same zone the data is stored in, without tzinfo so it
# can be compared directly against the parsed filter dates.
def ahora_local():
    return datetime.now(ZONA_DATOS).replace(tzinfo=None)


# Parses a "desde"/"hasta" query param. Returns None if the format is invalid.
# A range end without seconds means "until the end of that minute", which
# keeps the old behaviour where the frontend appended :59 to "hasta".
def parsear_fecha_filtro(texto, es_fin):
    for formato in FORMATOS_CON_SEGUNDOS:
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            pass

    for formato in FORMATOS_SIN_SEGUNDOS:
        try:
            fecha = datetime.strptime(texto, formato)
        except ValueError:
            continue
        if es_fin:
            fecha = fecha.replace(second=59, microsecond=999999)
        return fecha

    return None


# Validates the explicit range. Returns (desde, hasta, None) when valid, or
# (None, None, mensaje) with the text to send back in a 400 response.
def validar_rango(desde_texto, hasta_texto):
    if not desde_texto or not hasta_texto:
        return None, None, "Debes enviar 'desde' y 'hasta' juntos"

    desde = parsear_fecha_filtro(desde_texto, es_fin=False)
    if desde is None:
        return None, None, "Formato de fecha inválido en 'desde' (usa AAAA-MM-DD HH:MM)"

    hasta = parsear_fecha_filtro(hasta_texto, es_fin=True)
    if hasta is None:
        return None, None, "Formato de fecha inválido en 'hasta' (usa AAAA-MM-DD HH:MM)"

    if hasta < desde:
        return None, None, "La fecha final no puede ser anterior a la inicial"

    # Compared at minute precision: the frontend picks whole minutes, and a
    # "hasta" of the current minute becomes HH:MM:59, which is a few seconds
    # ahead of now but is not a future date from the user's point of view.
    ahora_minuto = ahora_local().replace(second=0, microsecond=0)
    if (desde.replace(second=0, microsecond=0) > ahora_minuto
            or hasta.replace(second=0, microsecond=0) > ahora_minuto):
        return None, None, "No se pueden consultar fechas futuras"

    return desde, hasta, None


# API - LOCATION HISTORY (used to draw the route line and list every point)

# Returns all points within the last N hours (defaults to 24), ordered oldest
# to newest, so the frontend can draw a route line and a point-by-point list.
# Includes ip_origen so the sidebar list can show it per point, same as the
# floating "last position" panel does.
@app.route("/api/historial-ubicaciones")
def historial_ubicaciones():

    # Optional query params:
    #   ?horas=48                        -> last N hours (default)
    #   ?desde=...&hasta=...             -> explicit range (ISO format)
    #   ?device_id=xyz                   -> filter by device
    horas = request.args.get("horas", default=24, type=int)
    device_id = request.args.get("device_id", default=None, type=str)
    desde = request.args.get("desde", default=None, type=str)
    hasta = request.args.get("hasta", default=None, type=str)

    # Validate before touching the database: a bad range answers 400 with JSON
    rango_explicito = bool(desde or hasta)
    if rango_explicito:
        desde, hasta, mensaje_error = validar_rango(desde, hasta)
        if mensaje_error:
            return jsonify({"error": mensaje_error}), 400

    with cursor_bd() as cursor:

        # Explicit date range takes priority over the "last N hours" default
        if rango_explicito:
            if device_id:
                cursor.execute("""
                    SELECT
                        ip_origen,
                        latitud,
                        longitud,
                        timestamp_gps
                    FROM ubicaciones
                    WHERE timestamp_gps BETWEEN %s AND %s
                      AND device_id = %s
                    ORDER BY timestamp_gps ASC
                """, (desde, hasta, device_id))
            else:
                cursor.execute("""
                    SELECT
                        ip_origen,
                        latitud,
                        longitud,
                        timestamp_gps
                    FROM ubicaciones
                    WHERE timestamp_gps BETWEEN %s AND %s
                      AND device_id = (
                          SELECT device_id FROM ubicaciones ORDER BY id DESC LIMIT 1
                      )
                    ORDER BY timestamp_gps ASC
                """, (desde, hasta))

        elif device_id:
            cursor.execute("""
                SELECT
                    ip_origen,
                    latitud,
                    longitud,
                    timestamp_gps
                FROM ubicaciones
                WHERE timestamp_gps >= NOW() - (%s || ' hours')::interval
                  AND device_id = %s
                ORDER BY timestamp_gps ASC
            """, (horas, device_id))

        else:
            cursor.execute("""
                SELECT
                    ip_origen,
                    latitud,
                    longitud,
                    timestamp_gps
                FROM ubicaciones
                WHERE timestamp_gps >= NOW() - (%s || ' hours')::interval
                  AND device_id = (
                      SELECT device_id FROM ubicaciones ORDER BY id DESC LIMIT 1
                  )
                ORDER BY timestamp_gps ASC
            """, (horas,))

        ubicaciones = cursor.fetchall()

    # Convert each row's datetime to a plain string for JSON
    for u in ubicaciones:
        u["timestamp_gps"] = str(u["timestamp_gps"])

    return jsonify(ubicaciones)


# API - VISITED PLACE CHECK

# Says whether the device has EVER been inside a bounding box, over the whole
# history (not limited by the date filter), so the frontend can tell "never
# visited" apart from "not visited in the selected dates".
#   ?lat_min=&lat_max=&lon_min=&lon_max=   -> the box (same as /api/buscar-lugar)
#   ?device_id=xyz                         -> defaults to the device of the
#                                             latest point, like the history
@app.route("/api/lugar-visitado")
def lugar_visitado():

    caja = {}

    for nombre in ("lat_min", "lat_max", "lon_min", "lon_max"):
        texto = request.args.get(nombre, default="", type=str).strip()

        if not texto:
            return jsonify({"error": f"Falta el parámetro {nombre}"}), 400

        try:
            valor = float(texto)
        except ValueError:
            valor = math.nan

        # float() also accepts "nan" and "inf", which are not coordinates
        if not math.isfinite(valor):
            return jsonify({"error": f"El parámetro {nombre} debe ser un número"}), 400

        caja[nombre] = valor

    if not (-90 <= caja["lat_min"] <= 90 and -90 <= caja["lat_max"] <= 90):
        return jsonify({"error": "La latitud debe estar entre -90 y 90"}), 400

    if not (-180 <= caja["lon_min"] <= 180 and -180 <= caja["lon_max"] <= 180):
        return jsonify({"error": "La longitud debe estar entre -180 y 180"}), 400

    if caja["lat_min"] > caja["lat_max"] or caja["lon_min"] > caja["lon_max"]:
        return jsonify({"error": "Los valores mínimos no pueden ser mayores que los máximos"}), 400

    device_id = request.args.get("device_id", default=None, type=str)

    with cursor_bd() as cursor:

        # EXISTS stops at the first matching row instead of counting them all
        if device_id:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM ubicaciones
                    WHERE latitud BETWEEN %s AND %s
                      AND longitud BETWEEN %s AND %s
                      AND device_id = %s
                    LIMIT 1
                ) AS visitado
            """, (caja["lat_min"], caja["lat_max"], caja["lon_min"], caja["lon_max"], device_id))
        else:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM ubicaciones
                    WHERE latitud BETWEEN %s AND %s
                      AND longitud BETWEEN %s AND %s
                      AND device_id = (
                          SELECT device_id FROM ubicaciones ORDER BY id DESC LIMIT 1
                      )
                    LIMIT 1
                ) AS visitado
            """, (caja["lat_min"], caja["lat_max"], caja["lon_min"], caja["lon_max"]))

        fila = cursor.fetchone()

    return jsonify({"visitado": bool(fila["visitado"])})


# START SERVER (only used for local development; production runs via Gunicorn)

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=True
    )
