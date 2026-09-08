from flask import Flask, jsonify, render_template
import mysql.connector

app = Flask(__name__)



# CONEXIÓN A MYSQL

def obtener_conexion():

    return mysql.connector.connect(
        host="localhost",
        port=3306,
        user="root",
        password="example",
        database="p1dbdiseno"
    )


# PÁGINA PRINCIPAL

@app.route("/")
def inicio():

    return render_template("index.html")


# API - ÚLTIMA UBICACIÓN

@app.route("/api/ultima-ubicacion")
def ultima_ubicacion():

    conexion = obtener_conexion()

    cursor = conexion.cursor(dictionary=True)

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


# INICIAR SERVIDOR

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=80,
        debug=True
    )