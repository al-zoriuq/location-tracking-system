from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import psycopg2
import psycopg2.errors  # UndefinedTable, see /api/detecciones-senal
from psycopg2.extras import RealDictCursor
import os
import math
import re
import threading
import time
import requests
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta
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

# Longest widening a client may ask for with margen_horas (7 days)
MARGEN_MAX_HORAS = 168

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


# API - REVERSE GEOCODING (coordinates -> approximate address)

# Used by the "last position" card. Same free geocoder as /api/buscar-lugar.
# Nominatim's usage policy asks for at most 1 request per second and for
# caching results, so:
#   - coordinates are rounded to 4 decimals (~11 m) and each rounded point is
#     asked only once per server process (small LRU cache);
#   - requests to Nominatim are spaced at least 1 s apart.
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
DECIMALES_DIRECCION = 4
MAX_CACHE_DIRECCIONES = 2000
_cache_direcciones = OrderedDict()
_candado_nominatim = threading.Lock()
_ultima_consulta_nominatim = 0.0


# Builds a short address from Nominatim's address parts, e.g.
# "Carrera 51B #82-10, El Prado, Barranquilla". Falls back to the first parts
# of display_name when the place has no street.
def armar_direccion(resultado):
    partes = resultado.get("address") or {}

    calle = partes.get("road") or partes.get("pedestrian") or partes.get("footway")
    if calle and partes.get("house_number"):
        calle = f"{calle} #{partes['house_number']}"

    sector = (
        partes.get("neighbourhood")
        or partes.get("suburb")
        or partes.get("quarter")
        or partes.get("city_district")
    )
    ciudad = (
        partes.get("city")
        or partes.get("town")
        or partes.get("village")
        or partes.get("municipality")
        or partes.get("county")
    )

    elegidas = []
    for parte in (calle, sector, ciudad):
        if parte and parte not in elegidas:
            elegidas.append(parte)

    if elegidas:
        return ", ".join(elegidas)

    nombre = resultado.get("display_name") or ""
    return ", ".join(p.strip() for p in nombre.split(",")[:3]) or None


def consultar_nominatim_inverso(lat, lon):
    global _ultima_consulta_nominatim

    with _candado_nominatim:
        espera = 1.0 - (time.monotonic() - _ultima_consulta_nominatim)
        if espera > 0:
            time.sleep(espera)
        try:
            respuesta = requests.get(
                NOMINATIM_REVERSE_URL,
                params={
                    "lat": lat,
                    "lon": lon,
                    "format": "jsonv2",
                    "zoom": 18,
                    "addressdetails": 1,
                    "accept-language": "es",
                },
                headers={"User-Agent": "GPSLink-location-tracking-system/1.0"},
                timeout=5,
            )
        finally:
            _ultima_consulta_nominatim = time.monotonic()

    respuesta.raise_for_status()
    return respuesta.json()


@app.route("/api/direccion")
def direccion():
    try:
        lat = float(request.args.get("lat", ""))
        lon = float(request.args.get("lon", ""))
    except ValueError:
        return jsonify({"error": "Los parámetros lat y lon deben ser números"}), 400

    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return jsonify({"error": "Coordenadas fuera de rango"}), 400

    clave = (round(lat, DECIMALES_DIRECCION), round(lon, DECIMALES_DIRECCION))
    if clave in _cache_direcciones:
        _cache_direcciones.move_to_end(clave)
        return jsonify(_cache_direcciones[clave])

    try:
        resultado = consultar_nominatim_inverso(*clave)
    except (requests.RequestException, ValueError) as e:
        app.logger.warning("Error consultando la dirección: %s", e)
        return jsonify({"error": "No se pudo obtener la dirección"}), 502

    # Points in the sea or with no data come back as {"error": "Unable to geocode"}
    datos = {
        "direccion": None if "error" in resultado else armar_direccion(resultado),
        "completa": resultado.get("display_name"),
    }

    _cache_direcciones[clave] = datos
    if len(_cache_direcciones) > MAX_CACHE_DIRECCIONES:
        _cache_direcciones.popitem(last=False)

    return jsonify(datos)


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


# VEHICLE ALIASES
#
# The page never sees a device_id: each device gets an alias from the
# alias_dispositivos table (created by hand in the database), whose identity
# column numbers devices in order of appearance and never reuses a number.
#   numero 1 -> "A01" ... 99 -> "A99", 100 -> "B01" ... 2574 -> "Z99", 2575 -> "AA01"
# The API identifies cars by that alias ("vehiculo") and the page shows it as
# "Vehículo A01". device_id is still accepted as a query param (test scripts),
# but no response includes it.

ALIAS_POR_LETRA = 99
PATRON_ALIAS = re.compile(r"^([A-Z]+)(\d{2})$")


class TablaAliasFaltante(Exception):
    """The alias_dispositivos table does not exist in this database."""


@app.errorhandler(TablaAliasFaltante)
def error_tabla_alias(e):
    # Never fall back to showing device_id: the page gets a clear error instead
    app.logger.error("La tabla alias_dispositivos no existe en esta base de datos")
    return jsonify({
        "error": "Falta configurar los alias de los vehículos en la base de datos."
    }), 503


def _letras(indice):
    # 0 -> A ... 25 -> Z, 26 -> AA, 27 -> AB ...
    texto = ""
    n = indice + 1
    while n:
        n, resto = divmod(n - 1, 26)
        texto = chr(ord("A") + resto) + texto
    return texto


def alias_de_numero(numero):
    indice_letra, resto = divmod(numero - 1, ALIAS_POR_LETRA)
    return f"{_letras(indice_letra)}{resto + 1:02d}"


def numero_de_alias(alias):
    """"A01" -> 1, "B01" -> 100. None when the text is not a valid alias."""
    m = PATRON_ALIAS.match((alias or "").strip().upper())
    if not m or m.group(2) == "00":
        return None
    indice = 0
    for letra in m.group(1):
        indice = indice * 26 + (ord(letra) - ord("A") + 1)
    return (indice - 1) * ALIAS_POR_LETRA + int(m.group(2))


def nombre_vehiculo(alias):
    return f"Vehículo {alias}"


# Gives an alias to the listed devices that still have none, in order of first
# appearance. Rows that already have one are skipped BEFORE drawing a number,
# so no number of the sequence is wasted on them. The sniffer does the same for
# each new device as it arrives; this is the safety net for devices that
# reported before the table existed or while an older sniffer was running.
SQL_ASIGNAR_ALIAS_FALTANTES = """
    INSERT INTO alias_dispositivos (device_id)
    SELECT u.device_id
    FROM ubicaciones u
    WHERE u.device_id = ANY(%s)
      AND NOT EXISTS (
          SELECT 1 FROM alias_dispositivos a WHERE a.device_id = u.device_id
      )
    GROUP BY u.device_id
    ORDER BY MIN(u.id)
    ON CONFLICT (device_id) DO NOTHING
"""

# alias -> device_id, filled on demand. An alias never changes owner, so a
# resolved one can be kept for the life of the process.
_cache_alias = {}
_candado_alias = threading.Lock()


def asignar_alias_faltantes(cursor, device_ids):
    if not device_ids:
        return
    try:
        cursor.execute(SQL_ASIGNAR_ALIAS_FALTANTES, (list(device_ids),))
        cursor.connection.commit()
    except psycopg2.errors.UndefinedTable as e:
        raise TablaAliasFaltante() from e


def device_de_alias(alias):
    """device_id of an alias, or None if no device has it."""
    numero = numero_de_alias(alias)
    if numero is None:
        return None
    with _candado_alias:
        if numero in _cache_alias:
            return _cache_alias[numero]
    with cursor_bd() as cursor:
        try:
            cursor.execute(
                "SELECT device_id FROM alias_dispositivos WHERE numero = %s", (numero,)
            )
        except psycopg2.errors.UndefinedTable as e:
            raise TablaAliasFaltante() from e
        fila = cursor.fetchone()
    if fila is None:
        return None
    with _candado_alias:
        _cache_alias[numero] = fila["device_id"]
    return fila["device_id"]


def dispositivo_pedido():
    """Device asked for in the query string, as (device_id, None), or
    (None, error response). ?vehiculo=A01 is what the page sends; ?device_id=
    is kept for the test scripts. Neither -> (None, None): the endpoint uses
    its usual default (the device of the latest point)."""
    vehiculo = request.args.get("vehiculo", default=None, type=str)
    if vehiculo is not None:
        if numero_de_alias(vehiculo) is None:
            return None, (jsonify({"error": "El parámetro 'vehiculo' no es válido (ej.: A01)"}), 400)
        device_id = device_de_alias(vehiculo)
        if device_id is None:
            return None, (jsonify({"error": f"No existe el vehículo {vehiculo.strip().upper()}"}), 404)
        return device_id, None
    return request.args.get("device_id", default=None, type=str), None


# A location row as the API returns it: the alias instead of the device_id
def fila_con_alias(fila):
    numero = fila.pop("numero", None)
    fila.pop("device_id", None)
    alias = alias_de_numero(numero)
    return {"vehiculo": alias, "nombre": nombre_vehiculo(alias), **fila}


# API - LATEST LOCATION

# Returns only the single most recent GPS point, with the vehicle's alias.
#   ?vehiculo=A01   -> the most recent point of that vehicle
#   ?device_id=xyz  -> same, by device_id (test scripts)
SQL_ULTIMA_UBICACION = """
    SELECT
        u.device_id,
        a.numero,
        u.ip_origen,
        u.latitud,
        u.longitud,
        u.timestamp_gps,
        u.timestamp_recepcion
    FROM ubicaciones u
    LEFT JOIN alias_dispositivos a ON a.device_id = u.device_id
    {filtro}
    ORDER BY u.id DESC
    LIMIT 1
"""


@app.route("/api/ultima-ubicacion")
def ultima_ubicacion():

    device_id, error = dispositivo_pedido()
    if error:
        return error

    filtro = "WHERE u.device_id = %s" if device_id else ""
    params = (device_id,) if device_id else ()

    with cursor_bd() as cursor:
        try:
            cursor.execute(SQL_ULTIMA_UBICACION.format(filtro=filtro), params)
            ubicacion = cursor.fetchone()

            # A device without an alias yet gets one now
            if ubicacion is not None and ubicacion["numero"] is None:
                asignar_alias_faltantes(cursor, [ubicacion["device_id"]])
                cursor.execute(SQL_ULTIMA_UBICACION.format(filtro=filtro), params)
                ubicacion = cursor.fetchone()
        except psycopg2.errors.UndefinedTable as e:
            raise TablaAliasFaltante() from e


    if ubicacion is None:

        return jsonify({
            "error": "No hay ubicaciones registradas"
        }), 404

    if ubicacion["numero"] is None:
        # Never answer with the bare device_id
        raise TablaAliasFaltante()

    # Convert datetime objects to plain strings so they can be JSON-serialized
    ubicacion["timestamp_gps"] = str(ubicacion["timestamp_gps"])
    ubicacion["timestamp_recepcion"] = str(ubicacion["timestamp_recepcion"])

    return jsonify(fila_con_alias(ubicacion))


# API - DEVICES

# Every device that has ever reported, each with its most recent GPS point
# (newest by GPS time) and its alias. The frontend uses it for the device
# cards and the current-position markers, so one request covers all the cars.
# Devices without an alias get one here (see SQL_ASIGNAR_ALIAS_FALTANTES).
SQL_DISPOSITIVOS = """
    SELECT DISTINCT ON (u.device_id)
        u.device_id,
        a.numero,
        u.ip_origen,
        u.latitud,
        u.longitud,
        u.timestamp_gps,
        u.timestamp_recepcion
    FROM ubicaciones u
    LEFT JOIN alias_dispositivos a ON a.device_id = u.device_id
    ORDER BY u.device_id, u.timestamp_gps DESC, u.id DESC
"""


@app.route("/api/dispositivos")
def dispositivos():

    with cursor_bd() as cursor:
        try:
            cursor.execute(SQL_DISPOSITIVOS)
            filas = cursor.fetchall()

            # Rows with an empty device_id (old data) can never get an alias:
            # skipping them avoids a pointless write on every request
            sin_alias = [
                f["device_id"] for f in filas
                if f["numero"] is None and f["device_id"] is not None
            ]
            if sin_alias:
                asignar_alias_faltantes(cursor, sin_alias)
                cursor.execute(SQL_DISPOSITIVOS)
                filas = cursor.fetchall()
        except psycopg2.errors.UndefinedTable as e:
            raise TablaAliasFaltante() from e

    resultado = []
    for fila in filas:
        # A device still without an alias is left out rather than shown by its device_id
        if fila["numero"] is None:
            continue
        fila["timestamp_gps"] = str(fila["timestamp_gps"])
        fila["timestamp_recepcion"] = str(fila["timestamp_recepcion"])
        resultado.append(fila_con_alias(fila))

    # Ordered by alias ("A01" < "A99" < "B01" for the same number of letters)
    resultado.sort(key=lambda f: numero_de_alias(f["vehiculo"]))
    return jsonify(resultado)


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


# Limits of the intervalo_s sampling param of /api/historial-ubicaciones
INTERVALO_MIN_S = 1
INTERVALO_MAX_S = 300


# Start of the intervalo_s block that contains a (naive) timestamp. Same
# alignment as muestrear_sql: PostgreSQL's EXTRACT(EPOCH FROM timestamp) reads
# a timestamp without zone as if it were UTC, so this does the same.
def inicio_bloque(fecha, intervalo_s):
    segundos = (fecha - datetime(1970, 1, 1)).total_seconds()
    return datetime(1970, 1, 1) + timedelta(seconds=math.floor(segundos / intervalo_s) * intervalo_s)


# Wraps a history query (one device, ordered by timestamp_gps) so it returns
# only the FIRST point of each fixed block of intervalo_s seconds. Blocks are
# aligned to the clock (epoch // N), so the same block always yields the same
# point: repeated or overlapping requests (despues_de) never produce two
# different points for one complete block, and the client's merge by
# timestamp_gps drops the repeats. Without intervalo_s the query is unchanged.
# intervalo_s is an int already validated against the limits above.
def muestrear_sql(sql, intervalo_s):
    if not intervalo_s:
        return sql
    n = int(intervalo_s)
    return f"""
        SELECT ip_origen, latitud, longitud, timestamp_gps
        FROM (
            SELECT DISTINCT ON (FLOOR(EXTRACT(EPOCH FROM t.timestamp_gps) / {n}))
                t.ip_origen, t.latitud, t.longitud, t.timestamp_gps
            FROM ({sql}) AS t
            ORDER BY FLOOR(EXTRACT(EPOCH FROM t.timestamp_gps) / {n}), t.timestamp_gps ASC
        ) AS muestreo
        ORDER BY timestamp_gps ASC
    """


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
    #   ?vehiculo=A01                    -> filter by vehicle alias
    #   ?device_id=xyz                   -> filter by device (test scripts)
    horas = request.args.get("horas", default=24, type=int)
    desde = request.args.get("desde", default=None, type=str)
    hasta = request.args.get("hasta", default=None, type=str)
    despues_de = request.args.get("despues_de", default=None, type=str)
    margen_horas = request.args.get("margen_horas", default=0, type=int)

    # Optional sampling: one point per block of N seconds (see muestrear_sql).
    # Devices may report every second; the web map only needs one point every
    # few seconds, and the full detail stays in the database.
    intervalo_texto = request.args.get("intervalo_s", default=None, type=str)
    intervalo_s = None
    if intervalo_texto is not None:
        try:
            intervalo_s = int(intervalo_texto)
        except ValueError:
            intervalo_s = None
        if intervalo_s is None or not (INTERVALO_MIN_S <= intervalo_s <= INTERVALO_MAX_S):
            return jsonify({
                "error": f"'intervalo_s' debe ser un entero entre {INTERVALO_MIN_S} y {INTERVALO_MAX_S}"
            }), 400

    # Validate before touching the database: a bad range answers 400 with JSON
    rango_explicito = bool(desde or hasta)
    if rango_explicito:
        desde, hasta, mensaje_error = validar_rango(desde, hasta)
        if mensaje_error:
            return jsonify({"error": mensaje_error}), 400

    # Incremental polling: only the points newer than a timestamp the client
    # already holds. It has no upper bound, so it never depends on the client's
    # clock and it is not subject to the "no future dates" rule.
    despues_de_fecha = None
    if despues_de:
        despues_de_fecha = parsear_fecha_filtro(despues_de, es_fin=False)
        if despues_de_fecha is None:
            return jsonify({
                "error": "Formato de fecha inválido en 'despues_de' (usa AAAA-MM-DD HH:MM:SS)"
            }), 400

    # With sampling, move the incremental lower bound back to the start of its
    # block: a bound in the middle of a block would pick a different "first
    # point" for it than the full load did, adding an extra point each poll.
    if despues_de_fecha is not None and intervalo_s:
        despues_de_fecha = inicio_bloque(despues_de_fecha, intervalo_s) - timedelta(microseconds=1)

    # Widen a validated range on both sides so the client can complete routes
    # that cross its edges. The far end is clamped to the server's own "now":
    # a widened range is never a future date.
    if rango_explicito and margen_horas > 0:
        margen = timedelta(hours=min(margen_horas, MARGEN_MAX_HORAS))
        desde = desde - margen
        hasta = min(hasta + margen, ahora_local())

    # Resolved after validating the other params: a bad request never opens the database
    device_id, error = dispositivo_pedido()
    if error:
        return error

    with cursor_bd() as cursor:

        # Every query below goes through here, so sampling applies to all of them
        def ejecutar(sql, params):
            cursor.execute(muestrear_sql(sql, intervalo_s), params)

        # Incremental polling takes priority over the rest
        if despues_de_fecha is not None:
            if device_id:
                ejecutar("""
                    SELECT
                        ip_origen,
                        latitud,
                        longitud,
                        timestamp_gps
                    FROM ubicaciones
                    WHERE timestamp_gps > %s
                      AND device_id = %s
                    ORDER BY timestamp_gps ASC
                """, (despues_de_fecha, device_id))
            else:
                ejecutar("""
                    SELECT
                        ip_origen,
                        latitud,
                        longitud,
                        timestamp_gps
                    FROM ubicaciones
                    WHERE timestamp_gps > %s
                      AND device_id = (
                          SELECT device_id FROM ubicaciones ORDER BY id DESC LIMIT 1
                      )
                    ORDER BY timestamp_gps ASC
                """, (despues_de_fecha,))

        # Explicit date range takes priority over the "last N hours" default
        elif rango_explicito:
            if device_id:
                ejecutar("""
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
                ejecutar("""
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
            ejecutar("""
                SELECT
                    ip_origen,
                    latitud,
                    longitud,
                    timestamp_gps
                FROM ubicaciones
                WHERE timestamp_gps >= (NOW() AT TIME ZONE 'America/Bogota') - (%s || ' hours')::interval
                  AND device_id = %s
                ORDER BY timestamp_gps ASC
            """, (horas, device_id))

        else:
            ejecutar("""
                SELECT
                    ip_origen,
                    latitud,
                    longitud,
                    timestamp_gps
                FROM ubicaciones
                WHERE timestamp_gps >= (NOW() AT TIME ZONE 'America/Bogota') - (%s || ' hours')::interval
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


# API - TRAFFIC SIGN DETECTIONS (sparse events sent by the ESP32 camera)

# Same window filters as /api/historial-ubicaciones, so the frontend asks for
# the detections of exactly the period it is drawing and then assigns each one
# to its route by time:
#   ?horas=72 (default 24)              -> last N hours
#   ?desde=...&hasta=...[&margen_horas=N] -> explicit range, optionally widened
#   ?vehiculo=A01 (or ?device_id=xyz)   -> defaults to the device of the latest point
# Filtered by timestamp_gps, the time of the location sent with the sign.
@app.route("/api/detecciones-senal")
def detecciones_senal():

    horas = request.args.get("horas", default=24, type=int)
    desde = request.args.get("desde", default=None, type=str)
    hasta = request.args.get("hasta", default=None, type=str)
    margen_horas = request.args.get("margen_horas", default=0, type=int)

    if desde or hasta:
        desde, hasta, mensaje_error = validar_rango(desde, hasta)
        if mensaje_error:
            return jsonify({"error": mensaje_error}), 400
        if margen_horas > 0:
            margen = timedelta(hours=min(margen_horas, MARGEN_MAX_HORAS))
            desde = desde - margen
            hasta = min(hasta + margen, ahora_local())
        filtro_fecha = "timestamp_gps BETWEEN %s AND %s"
        params = [desde, hasta]
    else:
        filtro_fecha = (
            "timestamp_gps >= (NOW() AT TIME ZONE 'America/Bogota')"
            " - (%s || ' hours')::interval"
        )
        params = [horas]

    # Resolved after validating the other params: a bad request never opens the database
    device_id, error = dispositivo_pedido()
    if error:
        return error

    if device_id:
        filtro_device = "device_id = %s"
        params.append(device_id)
    else:
        filtro_device = (
            "device_id = (SELECT device_id FROM ubicaciones ORDER BY id DESC LIMIT 1)"
        )

    try:
        detecciones = consultar_detecciones(filtro_fecha, filtro_device, params)
    except psycopg2.errors.UndefinedTable:
        # Database without the table (e.g. a new test database; SQL in the README):
        # no detections to show, instead of an error toast every 10 s.
        app.logger.warning("La tabla detecciones_senal no existe en esta base de datos")
        return jsonify([])

    for d in detecciones:
        d["timestamp_gps"] = str(d["timestamp_gps"])

    return jsonify(detecciones)


def consultar_detecciones(filtro_fecha, filtro_device, params):
    with cursor_bd() as cursor:
        # Only the fixed SQL fragments above are concatenated; every value
        # goes as a query parameter.
        cursor.execute(f"""
            SELECT
                id,
                latitud,
                longitud,
                timestamp_gps,
                senal_texto,
                senal_tipo,
                senal_valor,
                confianza,
                vel_gps,
                vel_mpu,
                vel_fuente,
                CASE vel_fuente
                    WHEN 'GPS' THEN vel_gps
                    WHEN 'MPU' THEN vel_mpu
                END AS velocidad,
                cumplimiento
            FROM detecciones_senal
            WHERE {filtro_fecha}
              AND {filtro_device}
            ORDER BY timestamp_gps ASC
        """, tuple(params))

        return cursor.fetchall()


# API - VISITED PLACE CHECK

# Says whether the device has EVER been inside a bounding box, over the whole
# history (not limited by the date filter), so the frontend can tell "never
# visited" apart from "not visited in the selected dates".
#   ?lat_min=&lat_max=&lon_min=&lon_max=   -> the box (same as /api/buscar-lugar)
#   ?vehiculo=A01 (or ?device_id=xyz)      -> defaults to the device of the
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


    # Resolved after validating the other params: a bad request never opens the database
    device_id, error = dispositivo_pedido()
    if error:
        return error

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