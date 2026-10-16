"""Recrea en la base de datos de PRUEBAS el caso del "mapa pegado en un punto lejano".

Inserta, para un device_id de prueba:
  1. dos puntos en las Azores (39.3910, -31.2546) hace 20 minutos, 10 s entre ellos
  2. una ruta en Cartagena, un punto cada 10 s, desde hace 19 minutos hasta ahora

Es lo que paso en produccion el 16/10/2026: el primer punto de la ventana estaba a
~5.000 km de los reales, y la pagina descartaba todos los puntos reales como
"saltos imposibles" (> 180 km/h), asi que el mapa se quedaba en las Azores.

Que debe verse en la pagina de pruebas (modo en vivo, sin filtros):
  - con el codigo VIEJO: "Ruta 1 de 1", marcador en las Azores
  - con la CORRECCION:   "Ruta 2 de 2", marcador en Cartagena; la ruta 1 son
                         los dos puntos de las Azores

Igual que insertar_rutas_prueba.py, inserta DIRECTO en la base del .env de la carpeta
del proyecto, y se niega a correr si esa base no termina en "_test".

Uso (en el servidor, dentro de la carpeta del proyecto de test y con su venv):
    python pruebas/insertar_salto_prueba.py --dry-run   # solo muestra, no toca la BD
    python pruebas/insertar_salto_prueba.py             # inserta
    python pruebas/insertar_salto_prueba.py --borrar    # borra las filas de ese device

Las fechas dependen de la hora actual: cada ejecucion crea puntos nuevos.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from insertar_rutas_prueba import (  # noqa: E402
    IP_ORIGEN, RAIZ, SQL_BORRAR, SQL_INSERTAR, conectar, nombre_bd, verificar_candado,
)

DEVICE_POR_DEFECTO = "device-prueba-salto"
BOGOTA = timezone(timedelta(hours=-5))
AZORES = (39.3910, -31.2546)  # the far-away point seen in production
CARTAGENA = (10.4242, -75.5476)
CADA_SEGUNDOS = 10  # same cadence as the Android app


def construir_lecturas():
    """(fecha_bogota_sin_zona, lat, lon) in chronological order, the last one now."""
    ahora = datetime.now(BOGOTA).replace(tzinfo=None, microsecond=0)
    inicio = ahora - timedelta(minutes=20)
    lecturas = [
        (inicio, *AZORES),
        (inicio + timedelta(seconds=CADA_SEGUNDOS), *AZORES),
    ]
    # Cartagena: a slow walk north-east (~1.6 m every 10 s), so it draws as a short route
    t = inicio + timedelta(minutes=1)
    i = 0
    while t <= ahora:
        lecturas.append((t, round(CARTAGENA[0] + i * 0.00001, 6), round(CARTAGENA[1] + i * 0.00001, 6)))
        t += timedelta(seconds=CADA_SEGUNDOS)
        i += 1
    return lecturas


def main():
    ap = argparse.ArgumentParser(description="Recrea el caso del punto lejano en la BD de pruebas")
    ap.add_argument("--device", default=DEVICE_POR_DEFECTO, help=f"device_id (por defecto {DEVICE_POR_DEFECTO})")
    ap.add_argument("--dry-run", action="store_true", help="muestra lo que haria, sin conectarse a la BD")
    ap.add_argument("--borrar", action="store_true", help="borra las filas de ese device_id en vez de insertar")
    ap.add_argument("--si", action="store_true", help="no pedir confirmacion")
    args = ap.parse_args()

    load_dotenv(os.path.join(RAIZ, ".env"))
    verificar_candado()

    lecturas = construir_lecturas()
    accion = "BORRAR" if args.borrar else "INSERTAR"
    print(f"Base de datos: {nombre_bd()} @ {os.getenv('rdshost')}")
    print(f"Dispositivo:   {args.device}")
    print(f"Accion:        {accion}")
    if not args.borrar:
        print(f"  2 puntos en las Azores    {lecturas[0][0]:%H:%M:%S} y {lecturas[1][0]:%H:%M:%S}")
        print(f"  {len(lecturas) - 2} puntos en Cartagena  {lecturas[2][0]:%H:%M:%S} a {lecturas[-1][0]:%H:%M:%S}")

    if args.dry_run:
        print("\n--dry-run: no se conecto a la base de datos ni se cambio nada.")
        return

    if not args.si and input(f"\nEscribe 's' para {accion.lower()}: ").strip().lower() != "s":
        print("Cancelado.")
        sys.exit(1)

    conexion = conectar()
    try:
        cursor = conexion.cursor()
        if args.borrar:
            cursor.execute(SQL_BORRAR, (args.device,))
            print(f"\nFilas borradas: {cursor.rowcount}")
        else:
            insertadas = 0
            for fecha, lat, lon in lecturas:
                cursor.execute(SQL_INSERTAR, (args.device, IP_ORIGEN, lat, lon, fecha, fecha))
                insertadas += cursor.rowcount
            print(f"\nFilas insertadas: {insertadas} de {len(lecturas)}")
            print("Abre la pagina de pruebas en modo en vivo: el marcador debe quedar en Cartagena.")
        conexion.commit()
        cursor.close()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


if __name__ == "__main__":
    main()
