import socket
from datetime import datetime
import mysql.connector
import re

HOST = "0.0.0.0"
PORT = 5000

LOG_FILE = "ubicaciones_recibidas.log"

# CONEXIÓN A MYSQL

conexion = mysql.connector.connect(
    host="localhost",
    port=3306,
    user="root",
    password="example",
    database="p1dbdiseno"
)

cursor = conexion.cursor()

print("✓ Conectado a MySQL")


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


            cursor.execute(
                sql,
                valores
            )

            conexion.commit()


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

    cursor.close()

    conexion.close()

    print("Conexión terminada.")