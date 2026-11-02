#!/usr/bin/env python3
"""
Sniffer UDP de prueba para el ESP32-S3 + SIM7670G.

Escucha en el puerto 5005 e imprime cada paquete que llega: hora, IP:puerto
de origen, tamaño, mensaje, campos decodificados y volcado hexadecimal.
Además valida el mensaje con la misma regex y el mismo strptime que debe
usar el servidor real, para saber de antemano si lo aceptaría.

Formato esperado (nuevo):
    Device: ESP32S3-SIM7670G, Lat: 11.019607, Lon: -74.823385,
    Timestamp GPS: 2026-10-31 19:27:04.000000 -0500, Senal: LIMITE 50,
    Conf: 1.00, Vel GPS: 52, Vel MPU: 49, Usa: GPS, SI

    Vel GPS / Vel MPU pueden ser NA (sin dato). El campo de cumplimiento es
    SI, EXCEDE o NA (PARE/CEDA o sin velocidad). Puede venir un campo extra al
    final, "pos-<s>s", si la posición tenía más de 30 s.

También acepta el formato antiguo (solo Device/Lat/Lon/Timestamp) y lo
marca como tal, por si quedan dispositivos con el firmware anterior.

Solo usa la librería estándar de Python.

Uso:
    python3 sniffer_udp.py              # puerto 5005
    python3 sniffer_udp.py --port 5000  # otro puerto
    python3 sniffer_udp.py --no-hex     # sin volcado hexadecimal
    python3 sniffer_udp.py --estricto   # rechaza el formato antiguo

En EC2:
  - Security Group -> Inbound rules -> Custom UDP, puerto 5005, origen 0.0.0.0/0
  - Usa la IP pública (o Elastic IP) de la instancia en UDP_SERVER_IP del sketch.
"""

import argparse
import re
import socket
from datetime import datetime

NUM = r"[-+]?\d+(?:\.\d+)?"

# Patrón compartido con el servidor real. La parte extendida (Senal ... SI)
# es opcional para seguir aceptando el formato antiguo.
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


def volcado_hex(datos: bytes) -> str:
    """Volcado tipo hexdump: offset | bytes en hex | ASCII."""
    lineas = []
    for i in range(0, len(datos), 16):
        bloque = datos[i:i + 16]
        hexa = " ".join(f"{b:02X}" for b in bloque)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in bloque)
        lineas.append(f"   {i:04X}  {hexa:<47}  |{ascii_}|")
    return "\n".join(lineas)


def parsear(mensaje: str) -> dict:
    """Devuelve un dict con los campos del mensaje o lanza ValueError."""
    r = PATRON.search(mensaje)
    if not r:
        raise ValueError("formato no reconocido por la regex del servidor")

    g = r.groupdict()
    try:
        ts_dt = datetime.strptime(g["ts"].strip(), FORMATO_TS)
    except ValueError as e:
        raise ValueError(f"timestamp inválido ({e})")

    datos = {
        "formato": "nuevo" if g["senal"] is not None else "antiguo",
        "device": g["device"],
        "lat": float(g["lat"]),
        "lon": float(g["lon"]),
        "ts": ts_dt,
    }

    if datos["formato"] == "nuevo":
        senal = g["senal"].strip()
        # "LIMITE 50" -> tipo "LIMITE", valor 50 (si trae número al final)
        m = re.match(rf"^(.*?)\s*({NUM})?$", senal)
        datos.update({
            "senal": senal,
            "senal_tipo": m.group(1) or senal,
            "senal_valor": float(m.group(2)) if m.group(2) else None,
            "conf": float(g["conf"]),
            "vel_gps": None if g["vel_gps"] == "NA" else float(g["vel_gps"]),   # NA = sin dato
            "vel_mpu": None if g["vel_mpu"] == "NA" else float(g["vel_mpu"]),
            "extra": g["extra"],   # p. ej. "pos-45s" (posición vieja) o None
            "usa": g["usa"].upper(),
            "flag": g["flag"].upper(),
        })
    return datos


def validar(mensaje: str, estricto: bool = False) -> str:
    """Devuelve un resumen de si el servidor real aceptaría el mensaje."""
    try:
        d = parsear(mensaje)
    except ValueError as e:
        return f"NO -> {e}"

    if estricto and d["formato"] == "antiguo":
        return "NO -> formato antiguo (faltan Senal/Conf/Vel/Usa)"

    lineas = [
        f"SI ({d['formato']})",
        f"   device   = {d['device']}",
        f"   lat/lon  = {d['lat']}, {d['lon']}",
        f"   ts       = {d['ts'].isoformat()}",
    ]
    if d["formato"] == "nuevo":
        valor = "" if d["senal_valor"] is None else f"  (tipo={d['senal_tipo']}, valor={d['senal_valor']:g})"
        lineas += [
            f"   senal    = {d['senal']}{valor}",
            f"   conf     = {d['conf']:.2f}",
            f"   vel GPS  = {d['vel_gps']}   vel MPU = {d['vel_mpu']}"
            + (f"   (dif = {d['vel_gps'] - d['vel_mpu']:+g})" if None not in (d['vel_gps'], d['vel_mpu']) else ""),
            f"   usa      = {d['usa']}",
            f"   flag     = {d['flag']}",
        ]
        if d["extra"]:
            lineas.append(f"   extra    = {d['extra']}")
        if d["usa"] not in ("GPS", "MPU", "NA"):
            lineas.append(f"   AVISO: 'Usa' tiene un valor inesperado ({d['usa']})")
        if d["flag"] not in ("SI", "EXCEDE", "NA"):
            lineas.append(f"   AVISO: el campo de cumplimiento no es SI/EXCEDE/NA ({d['flag']})")
        if not 0.0 <= d["conf"] <= 1.0:
            lineas.append(f"   AVISO: Conf fuera de [0, 1] ({d['conf']})")
    lineas.append(f"   Mapa: https://maps.google.com/?q={d['lat']},{d['lon']}")
    return "\n".join(lineas)


def main():
    ap = argparse.ArgumentParser(description="Sniffer UDP de prueba")
    ap.add_argument("--host", default="0.0.0.0", help="IP local (0.0.0.0 = todas)")
    ap.add_argument("--port", type=int, default=5005, help="Puerto UDP (por defecto 5005)")
    ap.add_argument("--no-hex", action="store_true", help="No mostrar volcado hexadecimal")
    ap.add_argument("--estricto", action="store_true",
                    help="Rechazar mensajes con el formato antiguo")
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
            print(f"Servidor lo aceptaría: {validar(mensaje, args.estricto)}")
    except KeyboardInterrupt:
        print(f"\nSniffer detenido. Paquetes recibidos: {total}")
    finally:
        sock.close()


if __name__ == "__main__":
    main()