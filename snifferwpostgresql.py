"""Servidor UDP: recibe ubicaciones (y señales de tránsito del ESP32) y las guarda en RDS.

Formatos aceptados:

  Solo ubicación (celular Android y firmware anterior del ESP32):
    Device: X, Lat: 11.03, Lon: -74.85, Timestamp GPS: 2026-11-03 07:50:28.000000 -0500

  Ubicación + señal de tránsito detectada (ESP32-S3 + SIM7670G):
    Device: X, Lat: 11.03, Lon: -74.85, Timestamp GPS: 2026-11-03 07:50:28.000000 -0500,
    Senal: LIMITE 30, Conf: 0.99, Vel GPS: 2, Vel MPU: 22, Usa: GPS, SI[, pos-45s]

    Vel GPS / Vel MPU pueden ser NA. El cumplimiento es SI, EXCEDE o NA.
    El campo opcional final "pos-<n>s" indica que la posición tenía n segundos.

La ubicación va a "ubicaciones" y la señal, si la hay, a "detecciones_senal",
en la misma transacción. Un paquete mal formado se descarta sin detener el
servidor, y si se cae la conexión con la base de datos se reconecta solo.

Si la base no tiene la tabla detecciones_senal (p. ej. una base de pruebas nueva),
el sniffer guarda solo las ubicaciones y avisa; cuando la tabla aparece, empieza
a guardar las señales sin tener que reiniciarlo.

Uso:
    python snifferwpostgresql.py               # puerto 5000
    python snifferwpostgresql.py --puerto 5006 # otro puerto (p. ej. para probar en la EC2)
"""
import argparse
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
import psycopg2.errors  # UndefinedTable
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

HOST = "0.0.0.0"
PORT = 5005 #change when sent to production

LOG_FILE = "ubicaciones_recibidas.log"

# Cada cuánto se vuelve a buscar la tabla detecciones_senal si no existía
REVISAR_TABLA_CADA_S = 60


# LECTURA DE LOS MENSAJES (no toca la base de datos)
# Mismo patrón y mismos campos que tests/sniffer_udpforesp32.py, para que el
# sniffer real y el de pruebas guarden exactamente lo mismo.

NUM = r"[-+]?\d+(?:\.\d+)?"

PATRON = re.compile(
    rf"Device:\s*(?P<device>[\w-]+),\s*"
    rf"Lat:\s*(?P<lat>{NUM}),\s*"
    rf"Lon:\s*(?P<lon>{NUM}),\s*"
    rf"Timestamp GPS:\s*(?P<ts>[^,]+?)"
    rf"(?:,\s*Senal:\s*(?P<senal>[^,]+?)"
    rf",\s*Conf:\s*(?P<conf>{NUM})"
    rf",\s*Vel GPS:\s*(?P<vel_gps>{NUM}|NA)"
    rf",\s*Vel MPU:\s*(?P<vel_mpu>{NUM}|NA)"
    rf",\s*Usa:\s*(?P<usa>\w+)"
    rf",\s*(?P<flag>\w+)"
    rf"(?:,\s*(?P<extra>[^\r\n]*?))?)?"
    rf"\s*$"
)

FORMATO_TS = "%Y-%m-%d %H:%M:%S.%f %z"
PATRON_EDAD = re.compile(r"\bpos-(\d+)s\b", re.IGNORECASE)

# Valores de "Senal" que significan "no se detecto nada"
SIN_SENAL = {"", "NA", "NINGUNA", "NONE"}


@dataclass
class Ubicacion:
    device_id: str
    latitud: float
    longitud: float
    timestamp_gps: datetime  # hora de Bogota, sin tzinfo (ver README)


@dataclass
class Deteccion:
    senal_texto: str
    senal_tipo: str
    senal_valor: Optional[int]
    confianza: float
    vel_gps: Optional[float]
    vel_mpu: Optional[float]
    vel_fuente: str
    cumplimiento: str
    edad_posicion_s: Optional[int]
    timestamp_evento: datetime
    extra: Optional[str]


class MensajeInvalido(ValueError):
    """El mensaje no trae una ubicacion valida: no se guarda nada."""


def _velocidad(texto):
    return None if texto == "NA" else float(texto)


def parsear(mensaje):
    """Devuelve (ubicacion, deteccion, aviso).

    - deteccion es None si el mensaje no trae senal.
    - Si la ubicacion es valida pero la parte de la senal no (p. ej. Conf fuera
      de [0, 1]), deteccion es None y aviso explica por que: la ubicacion se
      guarda igual, no se pierde un punto del recorrido por un dato de la camara.
    - Lanza MensajeInvalido si no hay una ubicacion valida.
    """
    r = PATRON.search(mensaje.strip())
    if not r:
        raise MensajeInvalido("formato de mensaje no reconocido")
    g = r.groupdict()

    try:
        ts = datetime.strptime(g["ts"].strip(), FORMATO_TS)
    except ValueError as e:
        raise MensajeInvalido(f"timestamp invalido: {e}") from None

    latitud, longitud = float(g["lat"]), float(g["lon"])
    if not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
        raise MensajeInvalido(f"coordenadas fuera de rango: {latitud}, {longitud}")

    # Se guarda la hora local y se descarta el offset (ver README)
    ubicacion = Ubicacion(
        device_id=g["device"],
        latitud=latitud,
        longitud=longitud,
        timestamp_gps=ts.replace(tzinfo=None),
    )

    senal = (g["senal"] or "").strip().upper()
    if senal in SIN_SENAL:
        return ubicacion, None, None

    confianza = float(g["conf"])
    if not 0.0 <= confianza <= 1.0:
        return ubicacion, None, f"senal descartada: Conf fuera de [0, 1] ({confianza})"

    # "LIMITE 30" -> ("LIMITE", 30); "PARE" -> ("PARE", None)
    m = re.match(r"^(.*?)\s*(\d+)?$", senal)
    tipo = (m.group(1) or senal).strip()
    valor = int(m.group(2)) if m.group(2) else None
    if valor is not None and valor > 32767:  # columna SMALLINT
        return ubicacion, None, f"senal descartada: valor fuera de rango ({valor})"

    # Largos maximos de las columnas de detecciones_senal: un texto mas largo
    # haria fallar el INSERT y, con el, la ubicacion de la misma transaccion
    for campo, texto, maximo in (("Senal", senal, 50), ("tipo", tipo, 20),
                                 ("Usa", g["usa"], 5), ("cumplimiento", g["flag"], 10)):
        if len(texto) > maximo:
            return ubicacion, None, f"senal descartada: {campo} demasiado largo ({texto[:20]}...)"

    extra = (g["extra"] or "").strip()
    edad = None
    e = PATRON_EDAD.search(extra)
    if e:
        edad = int(e.group(1))
        extra = (extra[:e.start()] + extra[e.end():]).strip(" ,")

    deteccion = Deteccion(
        senal_texto=senal,
        senal_tipo=tipo,
        senal_valor=valor,
        confianza=confianza,
        vel_gps=_velocidad(g["vel_gps"]),
        vel_mpu=_velocidad(g["vel_mpu"]),
        vel_fuente=g["usa"].upper(),
        cumplimiento=g["flag"].upper(),
        edad_posicion_s=edad,
        timestamp_evento=ubicacion.timestamp_gps + timedelta(seconds=edad or 0),
        extra=extra or None,
    )
    return ubicacion, deteccion, None


# CONEXION A RDS
password = os.getenv("rdspass")
host = os.getenv("rdshost")
database = os.getenv("rdsdbname")
user = os.getenv("rdsuser")


def conectar():
    return psycopg2.connect(
        host=host,
        port=5432,
        database=database,
        user=user,
        password=password,
        sslmode='verify-full',
        sslrootcert='./global-bundle.pem'
    )


# Ignora duplicados del mismo dispositivo+timestamp
SQL_UBICACION = """
    INSERT INTO ubicaciones
    (device_id, ip_origen, latitud, longitud, timestamp_gps, timestamp_recepcion)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (device_id, timestamp_gps) DO NOTHING
"""

# Ignora el mismo paquete repetido (dispositivo + momento + señal)
SQL_DETECCION = """
    INSERT INTO detecciones_senal
    (device_id, ip_origen, latitud, longitud, timestamp_gps, edad_posicion_s,
     timestamp_evento, timestamp_recepcion, senal_texto, senal_tipo, senal_valor,
     confianza, vel_gps, vel_mpu, vel_fuente, cumplimiento, extra)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT ON CONSTRAINT detecciones_senal_unica DO NOTHING
"""

SQL_EXISTE_TABLA = "SELECT to_regclass('public.detecciones_senal') IS NOT NULL"


class Almacen:
    """Conexión a la base de datos y escritura de cada mensaje."""

    def __init__(self, conectar_bd=None):
        # conectar_bd: only for tests; by default the RDS connection above
        self._conectar = conectar_bd or conectar
        self.conn = self._conectar()
        self.tabla_senales = False
        self._revisada_en = 0.0
        self.revisar_tabla(forzar=True)

    def revisar_tabla(self, forzar=False):
        """¿Existe detecciones_senal? Se consulta al inicio y luego cada
        REVISAR_TABLA_CADA_S mientras no exista."""
        if self.tabla_senales or (not forzar and time.monotonic() - self._revisada_en < REVISAR_TABLA_CADA_S):
            return
        self._revisada_en = time.monotonic()
        with self.conn.cursor() as cur:
            cur.execute(SQL_EXISTE_TABLA)
            self.tabla_senales = bool(cur.fetchone()[0])
        self.conn.commit()
        if self.tabla_senales:
            print("Tabla detecciones_senal encontrada: se guardarán las señales de tránsito.")
        elif forzar:
            print("AVISO: la tabla detecciones_senal no existe en esta base de datos. "
                  "Se guardarán solo las ubicaciones hasta que se cree la tabla "
                  "(SQL en el README, «Esquema de detecciones_senal»; no hace falta reiniciar).")

    def _insertar(self, ubicacion, deteccion, ip_origen, hora_recepcion):
        self.revisar_tabla()
        resultado = []

        with self.conn.cursor() as cur:
            cur.execute(SQL_UBICACION, (
                ubicacion.device_id,
                ip_origen,
                ubicacion.latitud,
                ubicacion.longitud,
                ubicacion.timestamp_gps,
                hora_recepcion,
            ))
            resultado.append("ubicación nueva" if cur.rowcount else "ubicación ya existía")

            if deteccion is not None and self.tabla_senales:
                cur.execute(SQL_DETECCION, (
                    ubicacion.device_id,
                    ip_origen,
                    ubicacion.latitud,
                    ubicacion.longitud,
                    ubicacion.timestamp_gps,
                    deteccion.edad_posicion_s,
                    deteccion.timestamp_evento,
                    hora_recepcion,
                    deteccion.senal_texto,
                    deteccion.senal_tipo,
                    deteccion.senal_valor,
                    deteccion.confianza,
                    deteccion.vel_gps,
                    deteccion.vel_mpu,
                    deteccion.vel_fuente,
                    deteccion.cumplimiento,
                    deteccion.extra,
                ))
                resultado.append("señal nueva" if cur.rowcount else "señal repetida (ignorada)")
            elif deteccion is not None:
                resultado.append("señal NO guardada (falta la tabla detecciones_senal)")

        self.conn.commit()
        return ", ".join(resultado)

    def guardar(self, ubicacion, deteccion, ip_origen, hora_recepcion):
        """Guarda un mensaje ya leído. Devuelve un resumen; nunca lanza."""
        try:
            return self._insertar(ubicacion, deteccion, ip_origen, hora_recepcion)

        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            # Se cayó la conexión con la RDS: reconectar y reintentar una vez
            print(f"Conexión perdida ({str(e).strip()}). Reconectando...")
            try:
                self.conn.close()
            except psycopg2.Error:
                pass
            try:
                self.conn = self._conectar()
                return self._insertar(ubicacion, deteccion, ip_origen, hora_recepcion) + " (tras reconectar)"
            except psycopg2.Error as e2:
                return f"NO guardado, sin conexión con la base de datos: {str(e2).strip()}"

        except psycopg2.errors.UndefinedTable:
            # La tabla se borró con el sniffer corriendo: seguir sin señales
            self.conn.rollback()
            self.tabla_senales = False
            self._revisada_en = time.monotonic()
            return self.guardar(ubicacion, None, ip_origen, hora_recepcion) + \
                ", señal NO guardada (falta la tabla detecciones_senal)"

        except psycopg2.Error as e:
            # Error de datos: deshacer para que la conexión siga usable
            try:
                self.conn.rollback()
            except psycopg2.Error:
                pass
            return f"NO guardado: {str(e).strip()}"

    def cerrar(self):
        try:
            self.conn.close()
        except psycopg2.Error:
            pass


def procesar(mensaje, ip_origen, almacen, hora_recepcion):
    """Lee un mensaje y lo guarda. Devuelve las líneas a imprimir."""
    try:
        ubicacion, deteccion, aviso = parsear(mensaje)
    except MensajeInvalido as e:
        return [f"Mensaje descartado: {e}"]

    lineas = [
        f"Device: {ubicacion.device_id}",
        f"Latitud: {ubicacion.latitud}",
        f"Longitud: {ubicacion.longitud}",
        f"GPS: {ubicacion.timestamp_gps}",
    ]
    if deteccion:
        lineas.append(
            f"Señal: {deteccion.senal_texto} (conf {deteccion.confianza:.2f}) | "
            f"Vel GPS {deteccion.vel_gps} / MPU {deteccion.vel_mpu}, usa {deteccion.vel_fuente} | "
            f"cumple: {deteccion.cumplimiento}"
            + (f" | posición de hace {deteccion.edad_posicion_s} s" if deteccion.edad_posicion_s else "")
        )
    if aviso:
        lineas.append(f"AVISO: {aviso}")

    lineas.append(f"BD: {almacen.guardar(ubicacion, deteccion, ip_origen, hora_recepcion)}")
    return lineas


def main():
    ap = argparse.ArgumentParser(description="Servidor UDP de ubicaciones y señales de tránsito")
    ap.add_argument("--puerto", type=int, default=PORT, help=f"puerto UDP (por defecto {PORT})")
    args = ap.parse_args()

    # CONEXION A RDS
    try:
        almacen = Almacen()
        with almacen.conn.cursor() as cur:
            cur.execute('SELECT version();')
            print(cur.fetchone()[0])
        almacen.conn.commit()
    except Exception as e:
        print(f"Database error: {e}")
        raise

    # SERVIDOR UDP
    servidor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((HOST, args.puerto))

    print(f"Escuchando UDP en el puerto {args.puerto} (base de datos: {database})...")

    try:

        while True:

            # Recibir paquete UDP (2048: el mensaje con señal es más largo)
            datos, direccion = servidor.recvfrom(2048)

            mensaje = datos.decode("utf-8", errors="replace").strip()

            # IP del dispositivo que envió el mensaje
            ip_origen = direccion[0]

            # Hora en que Python recibió el mensaje (UTC, igual que la RDS; ver README)
            hora_recepcion = datetime.now(timezone.utc).replace(tzinfo=None)

            print()
            print("--------------------------------------")
            print(f"IP: {ip_origen}")
            print(f"Mensaje: {mensaje}")
            print("--------------------------------------")

            # GUARDAR LOG (antes de procesar, para no perder nada si algo falla)
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{hora_recepcion}] Desde {ip_origen}: {mensaje}\n")

            for linea in procesar(mensaje, ip_origen, almacen, hora_recepcion):
                print(linea)

    except KeyboardInterrupt:

        print("\nServidor detenido.")

    finally:

        servidor.close()

        almacen.cerrar()

        print("Conexión terminada.")


if __name__ == "__main__":
    main()
