import socket
from datetime import datetime
import re
import psycopg2

import os
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

HOST = "0.0.0.0"
PORT = 5000

LOG_FILE = "ubicaciones_recibidas.log"


# CONEXION A RDS
password = os.getenv("rdspass")

conn = None
try:
    conn = psycopg2.connect(
        host='dbdisenop2.censc0mwgvn8.us-east-1.rds.amazonaws.com',
        port=5432,
        database='p2database',
        user='postgres',
        password=password,
        sslmode='verify-full',
    sslrootcert='./global-bundle.pem'
    )
    cur = conn.cursor()
    cur.execute('SELECT version();')
    print(cur.fetchone()[0])
    cur.close()
except Exception as e:
    print(f"Database error: {e}")
    raise
finally:
    if conn:
        conn.close()


# SERVIDOR UDP

servidor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

servidor.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

servidor.bind((HOST, PORT))

print(f"Escuchando UDP en el puerto {PORT}...")


try:

    while True:

        # Recibir paquete UDP
        datos, direccion = servidor.recvfrom(1024)

        mensaje = datos.decode(
            "utf-8",
            errors="replace"
        ).strip()

        # IP del dispositivo que envió el mensaje
        ip_origen = direccion[0]

        # Hora en que Python recibió el mensaje
        hora_recepcion = datetime.now()

        print()
        print("--------------------------------------")
        print(f"IP: {ip_origen}")
        print(f"Mensaje: {mensaje}")
        print("--------------------------------------")


        # EXTRAER LATITUD, LONGITUD Y TIMESTAMP

        patron = (
            r"Lat:\s*([-+]?\d+(?:\.\d+)?),\s*"
            r"Lon:\s*([-+]?\d+(?:\.\d+)?),\s*"
            r"Timestamp GPS:\s*(.+)"
        )

        resultado = re.search(
            patron,
            mensaje
        )


        if resultado:

            latitud = float(resultado.group(1))

            longitud = float(resultado.group(2))

            timestamp_gps = resultado.group(3).strip()


            # Convertir timestamp
            timestamp_gps = datetime.strptime(timestamp_gps, "%Y-%m-%d %H:%M:%S.%f %z")
            timestamp_gps = timestamp_gps.replace(tzinfo=None) 



            print(f"Latitud: {latitud}")
            print(f"Longitud: {longitud}")
            print(f"GPS: {timestamp_gps}")


            # INSERTAR EN MYSQL

            sql = """
                INSERT INTO ubicaciones
                (
                    ip_origen,
                    latitud,
                    longitud,
                    timestamp_gps,
                    timestamp_recepcion
                )
                VALUES (%s, %s, %s, %s, %s)
            """


            valores = (
                ip_origen,
                latitud,
                longitud,
                timestamp_gps,
                hora_recepcion
            )


            cur.execute(
                sql,
                valores
            )

            conn.commit()


            print("Ubicación guardada en base de datos")


        else:

            print("Formato de mensaje no reconocido")


        # GUARDAR LOG

        linea = (
            f"[{hora_recepcion}] "
            f"Desde {ip_origen}: {mensaje}"
        )

        with open(
            LOG_FILE,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(linea + "\n")


except KeyboardInterrupt:

    print("\nServidor detenido.")


finally:

    servidor.close()

    cur.close()

    conn.close()

    print("Conexión terminada.")