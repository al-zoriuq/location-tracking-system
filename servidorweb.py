from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)


password = os.getenv("rdspass")
host = os.getenv("rdshost")
database = os.getenv("rdsdbname")
user = os.getenv("rdsuser")

BUILD_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "disenop2web",
    "dist"
)

@app.route("/")
def inicio():

    return send_from_directory(BUILD_FOLDER, "index.html")

@app.route("/<path:path>")
def archivos_react(path):
    return send_from_directory(BUILD_FOLDER, path)

# CONEXIÓN A POSTGRESQL

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



# API - ÚLTIMA UBICACIÓN

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


    # Convertir fechas a texto
    ubicacion["timestamp_gps"] = str(
        ubicacion["timestamp_gps"]
    )

    ubicacion["timestamp_recepcion"] = str(
        ubicacion["timestamp_recepcion"]
    )


    return jsonify(ubicacion)


# API - HISTORIAL DE UBICACIONES (para dibujar la ruta)

@app.route("/api/historial-ubicaciones")
def historial_ubicaciones():

    horas = request.args.get("horas", default=24, type=int)

    conexion = obtener_conexion()

    cursor = conexion.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT
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

    for u in ubicaciones:
        u["timestamp_gps"] = str(u["timestamp_gps"])

    return jsonify(ubicaciones)


# INICIAR SERVIDOR

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=True
    )
