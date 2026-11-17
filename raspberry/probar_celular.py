# probar_celular.py
# Hace de "celular": manda posiciones y comandos a la Raspberry por UDP.
# Uso:  python probar_celular.py 127.0.0.1            (posiciones cada 1 s, Ctrl+C para parar)
#       python probar_celular.py 127.0.0.1 ESTADO     (o PAUSA, REANUDA, APAGAR)
# Puerto 5000: el mismo que usa la app GPSLink (detector con --celular 5000).
import socket
import sys
import time
from datetime import datetime, timezone, timedelta

ip = sys.argv[1]
destino = (ip, 5000)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2)

if len(sys.argv) > 2:
    s.sendto(f"CMD,{sys.argv[2].upper()}".encode(), destino)
    try:
        print("Respuesta:", s.recvfrom(200)[0].decode())
    except socket.timeout:
        print("Sin respuesta (revisa la IP y que el detector este corriendo con --celular)")
    sys.exit()

lat, lon = 11.030190, -74.859845
col = timezone(timedelta(hours=-5))
while True:
    lat += 0.00008                                   # ~9 m por segundo = ~32 km/h
    hora = datetime.now(col).strftime("%Y-%m-%d %H:%M:%S.000000 %z")
    msg = f"Device: CELULAR-PRUEBA, Lat: {lat:.6f}, Lon: {lon:.6f}, Timestamp GPS: {hora}"
    s.sendto(msg.encode(), destino)
    print(msg)
    time.sleep(1)
