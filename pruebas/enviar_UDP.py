import socket
import sys

IP_SERVIDOR = "127.0.0.1"
PUERTO = 5000

device_id = sys.argv[1] if len(sys.argv) > 1 else "device-prueba-001"

mensaje = f"Device: {device_id}, Lat: 10.987654, Lon: -74.123456, Timestamp GPS: 2026-08-30 17:23:04.000 -05:00"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

sock.sendto(
    mensaje.encode("utf-8"),
    (IP_SERVIDOR, PUERTO)
)

print(f"Mensaje UDP enviado: {mensaje}")

sock.close()
