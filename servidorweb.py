from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
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



# API - LATEST LOCATION

# Returns only the single most recent GPS point (used for the map marker
# and the "last position" panel in the frontend).
@app.route("/api/ultima-ubicacion")
def ultima_ubicacion():

    conexion = obtener_conexion()

    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT
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

    cursor.close()
    conexion.close()


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


# API - LOCATION HISTORY (used to draw the route line and list every point)

# Returns all points within the last N hours (defaults to 24), ordered oldest
# to newest, so the frontend can draw a route line and a point-by-point list.
# Includes ip_origen so the sidebar list can show it per point, same as the
# floating "last position" panel does.
@app.route("/api/historial-ubicaciones")
def historial_ubicaciones():

    # Optional query param, e.g. /api/historial-ubicaciones?horas=48
    horas = request.args.get("horas", default=24, type=int)

    conexion = obtener_conexion()

    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT
            ip_origen,
            latitud,
            longitud,
            timestamp_gps
        FROM ubicaciones
        WHERE timestamp_gps >= NOW() - (%s || ' hours')::interval
        ORDER BY timestamp_gps ASC
    """, (horas,))

    ubicaciones = cursor.fetchall()

    cursor.close()
    conexion.close()

    # Convert each row's datetime to a plain string for JSON
    for u in ubicaciones:
        u["timestamp_gps"] = str(u["timestamp_gps"])

    return jsonify(ubicaciones)


# START SERVER (only used for local development; production runs via Gunicorn)

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=True
    )
