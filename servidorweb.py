from flask import Flask, jsonify, render_template
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# CONEXIÓN A POSTGRESQL (RDS)
def obtener_conexion():
    return psycopg2.connect(
        host=os.getenv("rdshost"),
        port=5432,
        database=os.getenv("rdsdbname"),
        user=os.getenv("rdsuser"),
        password=os.getenv("rdspass"),
        sslmode='verify-full',
        sslrootcert='./global-bundle.pem'
    )


# PÁGINA PRINCIPAL
@app.route("/")
def inicio():
    return render_template("index.html")


# API - ÚLTIMA UBICACIÓN
@app.route("/api/ultima-ubicacion")
def ultima_ubicacion():
    conexion = obtener_conexion()
    cursor = conexion.cursor()

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

    fila = cursor.fetchone()
    cursor.close()
    conexion.close()

    if fila is None:
        return jsonify({
            "error": "No hay ubicaciones registradas"
        }), 404

    ubicacion = {
        "ip_origen": fila[0],
        "latitud": fila[1],
        "longitud": fila[2],
        "timestamp_gps": str(fila[3]),
        "timestamp_recepcion": str(fila[4])
    }

    return jsonify(ubicacion)
