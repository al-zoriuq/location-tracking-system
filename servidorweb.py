from datetime import datetime, timedelta

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import os
from dotenv import load_dotenv

from analisis_lugar import analizar_pasos, caja_circulo
from geocodificacion import ErrorGeocodificacion, buscar_lugares
from repositorio import ErrorBaseDatos, crear_repositorio, modo_demo_activo
from tiempo_bogota import ahora_bogota, formatear
from validacion import (
    ErrorValidacion,
    leer_busqueda,
    leer_device_id,
    leer_horas,
    leer_lugar,
    leer_rango,
)

# Default period for Entrega 2 when no date range is given
DIAS_POR_DEFECTO_LUGAR = 30

# Load environment variables from .env (RDS credentials, MODO_DEMO, etc.)
load_dotenv()

app = Flask(__name__)
CORS(app)  # allow the React frontend to call this API from the browser

# Data source: real RDS, or in-memory simulated data when MODO_DEMO=1.
# Module-level so tests can swap it for another implementation.
repositorio = crear_repositorio()

if modo_demo_activo():
    print("MODO_DEMO=1: usando datos simulados, sin conexión a la RDS")

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


# Convert datetime values to "YYYY-MM-DD HH:MM:SS" strings so rows can be
# JSON-serialized. Builds a new dict so cached demo rows are never mutated.
def serializar(fila):
    return {
        clave: formatear(valor) if isinstance(valor, datetime) else valor
        for clave, valor in fila.items()
    }


# ERROR HANDLING: always answer JSON with a Spanish message, never an HTML page

# Invalid query parameters -> 400 with the validation message
@app.errorhandler(ErrorValidacion)
def error_validacion(error):
    return jsonify({"error": str(error)}), 400


# Database unreachable or query failed -> 503 (details only in the server log)
@app.errorhandler(ErrorBaseDatos)
def error_base_datos(error):
    app.logger.error("Error de base de datos: %s", error)
    return jsonify({"error": "No se pudo consultar la base de datos."}), 503


# Place search services unreachable -> 502 (bad gateway: an upstream failed)
@app.errorhandler(ErrorGeocodificacion)
def error_geocodificacion(error):
    app.logger.error("Error de geocodificación: %s", error)
    return jsonify({
        "error": "No se pudo buscar la dirección en este momento. "
                 "Intenta de nuevo o marca el lugar en el mapa."
    }), 502


# The device to query: the one requested, or else the one that sent the most
# recent GPS point. Returns None when the table is empty.
def resolver_device_id(args):
    return leer_device_id(args) or repositorio.ultimo_device_id()


# API - LATEST LOCATION

# Returns only the single most recent GPS point (used for the map marker
# and the "last position" panel in the frontend).
# Optional: ?device_id=... (defaults to the device with the latest point)
@app.route("/api/ultima-ubicacion")
def ultima_ubicacion():

    device_id = resolver_device_id(request.args)
    ubicacion = repositorio.ultima_ubicacion(device_id) if device_id else None

    if ubicacion is None:

        return jsonify({
            "error": "No hay ubicaciones registradas"
        }), 404

    return jsonify(serializar(ubicacion))


# API - LOCATION HISTORY (used to draw the route line and list every point)

# Returns one device's points ordered oldest to newest, so the frontend can
# split them into trips, draw the route line and list every point.
# Query params (all optional):
#   desde, hasta  "YYYY-MM-DD HH:MM:SS" in Bogota time, both or none (Entrega 1)
#   horas         window size when there is no range (default 24, 1..720)
#   device_id     defaults to the device with the latest point
@app.route("/api/historial-ubicaciones")
def historial_ubicaciones():

    desde, hasta = leer_rango(request.args)
    horas = leer_horas(request.args)
    device_id = resolver_device_id(request.args)

    if device_id is None:
        return jsonify([])

    ubicaciones = repositorio.historial(device_id, desde, hasta, horas)

    return jsonify([serializar(u) for u in ubicaciones])


# API - PASSES THROUGH A PLACE (Entrega 2)

# "When did the vehicle pass through this place?"
# Query params:
#   lat, lon      center of the place (required)
#   radio         meters, 20..2000 (default 100)
#   desde, hasta  same rules as the history; default: last 30 days (Bogota)
#   device_id     same logic as the history
# Answers {lugar, rango, total, pasos[]} with passes in chronological order.
@app.route("/api/pasos-por-lugar")
def pasos_por_lugar():

    lat, lon, radio = leer_lugar(request.args)
    desde, hasta = leer_rango(request.args)
    device_id = resolver_device_id(request.args)

    if desde is None:
        hasta = ahora_bogota()
        desde = hasta - timedelta(days=DIAS_POR_DEFECTO_LUGAR)

    pasos = []
    if device_id is not None:
        # SQL narrows the data to segments near the circle; the exact geometry
        # (segment-circle intersection, grouping) happens in analisis_lugar.py
        filas = repositorio.segmentos_cerca(device_id, desde, hasta, caja_circulo(lat, lon, radio))
        pasos = analizar_pasos(filas, lat, lon, radio)

    return jsonify({
        "lugar": {"lat": lat, "lon": lon, "radio": radio},
        "rango": {"desde": formatear(desde), "hasta": formatear(hasta)},
        "device_id": device_id,
        "total": len(pasos),
        "pasos": [serializar(p) for p in pasos],
    })


# API - PLACE SEARCH (location filter)

# Free text ("frisby calle 64", "universidad del norte") -> candidate places
# in Barranquilla, via OpenStreetMap geocoders (see geocodificacion.py).
# Query param: q (3 to 100 characters).
@app.route("/api/buscar-lugar")
def buscar_lugar():

    texto = leer_busqueda(request.args)

    return jsonify({
        "consulta": texto,
        "resultados": buscar_lugares(texto),
    })


# START SERVER (only used for local development; production runs via Gunicorn)

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=True
    )
