#!/usr/bin/env python3
"""
Sniffer UDP de prueba para el ESP32-S3 + SIM7670G.

Escucha en el puerto 5005 e imprime cada paquete que llega: hora, IP:puerto
de origen, tamaño, mensaje y volcado hexadecimal. Además lo pasa por la misma
regex y el mismo strptime del servidor real, para saber de antemano si el
servidor lo aceptaría.

Solo usa la librería estándar de Python.

Uso:
    python3 sniffer_udp.py              # puerto 5005
    python3 sniffer_udp.py --port 5000  # otro puerto
    python3 sniffer_udp.py --no-hex     # sin volcado hexadecimal

En EC2:
  - Security Group -> Inbound rules -> Custom UDP, puerto 5005, origen 0.0.0.0/0
  - Usa la IP pública (o Elastic IP) de la instancia en UDP_SERVER_IP del sketch.
"""

import argparse
import re
import socket
from datetime import datetime

# Mismo patrón y formato de fecha que el servidor real
PATRON = re.compile(
    r"Device:\s*([\w-]+),\s*"
    r"Lat:\s*([-+]?\d+(?:\.\d+)?),\s*"
    r"Lon:\s*([-+]?\d+(?:\.\d+)?),\s*"
    r"Timestamp GPS:\s*(.+)"
)
FORMATO_TS = "%Y-%m-%d %H:%M:%S.%f %z"


def volcado_hex(datos: bytes) -> str:
    """Volcado tipo hexdump: offset | bytes en hex | ASCII."""
    lineas = []
    for i in range(0, len(datos), 16):
        bloque = datos[i:i + 16]
        hexa = " ".join(f"{b:02X}" for b in bloque)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in bloque)
        lineas.append(f"   {i:04X}  {hexa:<47}  |{ascii_}|")
    return "\n".join(lineas)


def validar(mensaje: str) -> str:
    """Devuelve un resumen de si el servidor real aceptaría el mensaje."""
    r = PATRON.search(mensaje)
    if not r:
        return "NO -> formato no reconocido por la regex del servidor"
    device, lat, lon, ts = r.group(1), float(r.group(2)), float(r.group(3)), r.group(4).strip()
    try:
        ts_dt = datetime.strptime(ts, FORMATO_TS)
    except ValueError as e:
        return f"NO -> timestamp inválido ({e})"
    return (f"SI -> device={device}  lat={lat}  lon={lon}  ts={ts_dt.isoformat()}\n"
            f"   Mapa: https://maps.google.com/?q={lat},{lon}")


def main():
    ap = argparse.ArgumentParser(description="Sniffer UDP de prueba")
    ap.add_argument("--host", default="0.0.0.0", help="IP local (0.0.0.0 = todas)")
    ap.add_argument("--port", type=int, default=5005, help="Puerto UDP (por defecto 5005)")
    ap.add_argument("--no-hex", action="store_true", help="No mostrar volcado hexadecimal")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    print(f"Sniffer UDP escuchando en {args.host}:{args.port}  (Ctrl+C para salir)")

    total = 0
    try:
        while True:
            datos, (ip, puerto) = sock.recvfrom(2048)
            total += 1
            mensaje = datos.decode("utf-8", errors="replace").strip()

            print("\n" + "=" * 70)
            print(f"#{total}  {datetime.now():%Y-%m-%d %H:%M:%S}  desde {ip}:{puerto}  ({len(datos)} bytes)")
            print("-" * 70)
            print(f"Mensaje : {mensaje}")
            if not args.no_hex:
                print("Hex     :")
                print(volcado_hex(datos))
            print(f"Servidor lo aceptaría: {validar(mensaje)}")
    except KeyboardInterrupt:
        print(f"\nSniffer detenido. Paquetes recibidos: {total}")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
