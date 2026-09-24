from datetime import datetime

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import os
from dotenv import load_dotenv

from repositorio import crear_repositorio, modo_demo_activo
from tiempo_bogota import formatear

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


# API - LATEST LOCATION

# Returns only the single most recent GPS point (used for the map marker
# and the "last position" panel in the frontend).
@app.route("/api/ultima-ubicacion")
def ultima_ubicacion():

    ubicacion = repositorio.ultima_ubicacion()

    if ubicacion is None:

        return jsonify({
            "error": "No hay ubicaciones registradas"
        }), 404

    return jsonify(serializar(ubicacion))


# API - LOCATION HISTORY (used to draw the route line and list every point)

# Returns all points within the last N hours (defaults to 24), ordered oldest
# to newest, so the frontend can draw a route line and a point-by-point list.
# Includes ip_origen so the sidebar list can show it per point, same as the
# floating "last position" panel does.
@app.route("/api/historial-ubicaciones")
def historial_ubicaciones():

    # Optional query param, e.g. /api/historial-ubicaciones?horas=48
    horas = request.args.get("horas", default=24, type=int)

    ubicaciones = repositorio.historial(horas)

    return jsonify([serializar(u) for u in ubicaciones])


# START SERVER (only used for local development; production runs via Gunicorn)

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=True
    )
