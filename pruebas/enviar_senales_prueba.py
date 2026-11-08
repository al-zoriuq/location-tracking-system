"""Envia por UDP un recorrido ficticio del ESP32 con detecciones de señales de transito.

Pareja de tests/sniffer_udpforesp32.py: ese sniffer, arrancado con --guardar en la
carpeta de PRUEBAS, recibe estos paquetes y los guarda en la base de datos de test
(ubicaciones + detecciones_senal).

Uso (en la EC2, carpeta location-tracking-system-test, con su venv):
    # terminal 1: receptor (solo acepta bases *_test)
    python tests/sniffer_udpforesp32.py --guardar --no-hex

    # terminal 2: emisor
    python pruebas/enviar_senales_prueba.py --dry-run          # solo muestra, no envia
    python pruebas/enviar_senales_prueba.py                    # envia a 127.0.0.1:5005

Recorrido: Uninorte -> Centro (Barranquilla), AYER desde las 09:00 (hora de Bogota),
un punto cada 5 s con el formato del ESP32. Las fechas son siempre de ayer, asi que
nunca son "futuras" y repetir el envio el mismo dia no duplica nada.

Detecciones que se envian y lo que debe quedar en detecciones_senal:
    LIMITE 30  vel 25 (GPS)            cumplimiento SI
    PARE       Vel GPS NA, MPU 28      cumplimiento NA
    LIMITE 30  vel 41 (GPS)            cumplimiento EXCEDE   (+ el mismo paquete repetido:
                                                              debe guardarse UNA sola vez)
    CEDA       vel 12 (GPS)            cumplimiento NA
    LIMITE 50  Vel GPS NA, MPU 47      cumplimiento SI
    LIMITE 30  vel 36 (GPS), pos-45s   cumplimiento EXCEDE   (posicion de 45 s antes:
                                                              timestamp_evento = gps + 45 s)
Cada deteccion va justo despues del punto normal con la MISMA hora GPS, como hace el
ESP32: la ubicacion ya existe y la deteccion igual debe guardarse.
Total esperado: 97 ubicaciones y 6 detecciones.

Para borrar los datos de prueba (en psql, base de test):
    DELETE FROM detecciones_senal WHERE device_id = 'esp32-prueba-001';
    DELETE FROM ubicaciones       WHERE device_id = 'esp32-prueba-001';
"""
import argparse
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "tests"))
from enviar_rutas_prueba import TRAZADOS  # noqa: E402
from sniffer_udpforesp32 import parsear  # noqa: E402  (misma validacion que el receptor)

IP_SERVIDOR = "127.0.0.1"
PUERTO = 5005  # puerto de tests/sniffer_udpforesp32.py
DEVICE_POR_DEFECTO = "esp32-prueba-001"
CADA_SEGUNDOS = 5
BOGOTA = timezone(timedelta(hours=-5))

# (fraccion del recorrido, senal, conf, vel_gps, vel_mpu, usa, cumplimiento, edad_posicion_s)
DETECCIONES = [
    (0.15, "LIMITE 30", 0.97, "25", "24", "GPS", "SI", None),
    (0.30, "PARE", 1.00, "NA", "28", "MPU", "NA", None),
    (0.45, "LIMITE 30", 0.92, "41", "39", "GPS", "EXCEDE", None),
    (0.60, "CEDA", 0.88, "12", "14", "GPS", "NA", None),
    (0.75, "LIMITE 50", 0.99, "NA", "47", "MPU", "SI", None),
    (0.85, "LIMITE 30", 0.95, "36", "35", "GPS", "EXCEDE", 45),
]
INDICE_REPETIDA = 2  # esta deteccion se envia dos veces


def inicio_recorrido():
    ayer = datetime.now(BOGOTA).date() - timedelta(days=1)
    return datetime(ayer.year, ayer.month, ayer.day, 9, 0, 0, tzinfo=BOGOTA)


def marca(fecha):
    # Igual que el ESP32: "2026-11-03 07:50:28.000000 -0500"
    return fecha.strftime("%Y-%m-%d %H:%M:%S.%f %z")


def msg_ubicacion(device, fecha, lat, lon):
    return f"Device: {device}, Lat: {lat:.6f}, Lon: {lon:.6f}, Timestamp GPS: {marca(fecha)}"


def msg_senal(device, fecha, lat, lon, senal, conf, vel_gps, vel_mpu, usa, cumple, edad):
    texto = (f"{msg_ubicacion(device, fecha, lat, lon)}, Senal: {senal}, Conf: {conf:.2f}, "
             f"Vel GPS: {vel_gps}, Vel MPU: {vel_mpu}, Usa: {usa}, {cumple}")
    if edad:
        texto += f", pos-{edad}s"
    return texto


def construir_paquetes(device):
    """Lista ordenada de (descripcion, mensaje)."""
    puntos = TRAZADOS["uninorte_centro"]
    inicio = inicio_recorrido()
    fechas = [inicio + timedelta(seconds=i * CADA_SEGUNDOS) for i in range(len(puntos))]

    # indice del punto en el que "se ve" cada senal
    por_indice = {}
    for n, det in enumerate(DETECCIONES):
        por_indice[round(det[0] * (len(puntos) - 1))] = (n, det)

    paquetes = []
    for i, ((lat, lon), fecha) in enumerate(zip(puntos, fechas)):
        paquetes.append(("ubicacion", msg_ubicacion(device, fecha, lat, lon)))

        if i not in por_indice:
            continue
        n, (_, senal, conf, vg, vm, usa, cumple, edad) = por_indice[i]

        # Con pos-<edad>s el ESP manda la ultima posicion valida, de hace <edad> s
        j = max(0, i - (edad or 0) // CADA_SEGUNDOS)
        (lat_p, lon_p), fecha_p = puntos[j], fechas[j]
        mensaje = msg_senal(device, fecha_p, lat_p, lon_p, senal, conf, vg, vm, usa, cumple, edad)

        paquetes.append((f"senal {senal} ({cumple})", mensaje))
        if n == INDICE_REPETIDA:
            paquetes.append((f"senal {senal} REPETIDA", mensaje))

    return paquetes


def main():
    ap = argparse.ArgumentParser(description="Envia un recorrido ficticio del ESP32 con senales de transito")
    ap.add_argument("--host", default=IP_SERVIDOR, help=f"IP/dominio del sniffer (por defecto {IP_SERVIDOR})")
    ap.add_argument("--puerto", type=int, default=PUERTO, help=f"puerto UDP (por defecto {PUERTO})")
    ap.add_argument("--device", default=DEVICE_POR_DEFECTO, help=f"device_id (por defecto {DEVICE_POR_DEFECTO})")
    ap.add_argument("--dry-run", action="store_true", help="muestra lo que enviaria, sin enviar nada")
    ap.add_argument("--si", action="store_true", help="no pedir confirmacion")
    args = ap.parse_args()

    paquetes = construir_paquetes(args.device)

    # Ningun paquete sale si el receptor no lo aceptaria
    for _, mensaje in paquetes:
        try:
            parsear(mensaje)
        except ValueError as e:
            sys.exit(f"Paquete invalido, no se envio nada: {e}\n  {mensaje}")

    n_ubic = sum(1 for d, _ in paquetes if d == "ubicacion")
    print(f"Dispositivo: {args.device}   Destino: {args.host}:{args.puerto}")
    print(f"Paquetes: {len(paquetes)} ({n_ubic} de ubicacion, {len(paquetes) - n_ubic} con senal)")
    print(f"Recorrido: {inicio_recorrido():%Y-%m-%d %H:%M} (hora de Bogota), cada {CADA_SEGUNDOS} s\n")
    for descripcion, mensaje in paquetes:
        if descripcion != "ubicacion":
            print(f"  {descripcion:<28} {mensaje}")
    print(f"\nEsperado en la BD: {n_ubic} ubicaciones y {len(DETECCIONES)} detecciones.")

    if args.dry_run:
        print("\n--dry-run: no se envio nada.")
        return

    if not args.si:
        print("\nLos datos iran a la base de datos que use el sniffer de ese destino.")
        if input("Escribe 's' para enviar: ").strip().lower() != "s":
            print("Cancelado.")
            sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, mensaje in paquetes:
            sock.sendto(mensaje.encode("utf-8"), (args.host, args.puerto))
            time.sleep(0.05)  # el receptor inserta y hace commit uno por uno
    finally:
        sock.close()
    print(f"\nListo: {len(paquetes)} paquetes enviados.")


if __name__ == "__main__":
    main()
