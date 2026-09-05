import socket

IP_SERVIDOR = "186.117.186.79"
PUERTO = 5000

mensaje = "Lat: 10.987654, Lon: -74.123456, Timestamp GPS: 2026-08-30 17:23:04.000 -05:00"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

sock.sendto(
    mensaje.encode("utf-8"),
    (IP_SERVIDOR, PUERTO)
)

print("Mensaje UDP enviado.")

sock.close()