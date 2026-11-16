"""Inserta datos de DOS carros en la base de datos de PRUEBAS, para probar la
pagina con dos dispositivos (selector "Ambos", tarjetas, colores, filtros).

Usa el mismo candado, la misma conexion y la misma sentencia SQL que
insertar_rutas_prueba.py: se niega a correr si el nombre de la base de datos no
termina en "_test". Nunca toca la base de produccion.

Uso (en el servidor, dentro de la carpeta del proyecto de test y con su venv):
    python pruebas/insertar_dos_carros_prueba.py --dry-run      # solo muestra, no toca la BD
    python pruebas/insertar_dos_carros_prueba.py                # inserta los datos
    python pruebas/insertar_dos_carros_prueba.py --vivo 10      # inserta y luego mueve los dos
                                                                #   carros "en vivo" 10 minutos
    python pruebas/insertar_dos_carros_prueba.py --borrar       # borra los dos carros de prueba

Repetir el insertado es seguro: (device_id, timestamp_gps) es unico y los
duplicados se ignoran. Las rutas de "hoy" se calculan respecto a la hora en que
se ejecuta, asi que conviene volver a correrlo antes de cada prueba.

Que se inserta (dias antes de hoy, hora de Bogota) y que debe verse:

  carro-prueba-1 (azul o naranja segun el orden alfabetico de los device_id)
    - las 10 rutas de enviar_rutas_prueba.py (hace 3 dias, hace 2 dias y ayer):
      Barranquilla, Santa Marta y Cartagena
    - hoy: Estadio -> Malecon, terminando 1 minuto antes de ejecutar  -> "en linea"

  carro-prueba-2
    - hace 2 dias 09:00  Centro -> Estadio (Barranquilla)
    - hace 2 dias 14:00  Barranquilla -> Santa Marta (1 parada)
    - ayer 10:00         Centro -> Buenavista (Barranquilla)
    - ayer 15:00         Uninorte -> Puerto Colombia
    - hoy: Uninorte -> Centro, terminando 20 minutos antes de ejecutar -> "hace 20 min"

Casos para probar con el filtro de LUGAR (en "Ambos"):
    Barranquilla     -> rutas de los dos carros
    Santa Marta      -> rutas de los dos (carro 1 hace 3 dias, carro 2 hace 2 dias)
    Cartagena        -> solo el carro 1
    Puerto Colombia  -> solo el carro 2
Con el filtro de FECHA "desde hace 3 dias" se ven las rutas de los dos carros.

Con --vivo N, despues de insertar, los dos carros siguen moviendose N minutos:
se inserta un punto de cada uno cada 30 s con la hora actual (Ctrl+C para parar).
El carro 1 vuelve del Malecon al Estadio y el carro 2 vuelve del Centro a
Uninorte, asi que sus rutas de hoy continuan sin cortarse.
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv  # noqa: E402
from enviar_rutas_prueba import (  # noqa: E402
    BOGOTA,
    CADA_SEGUNDOS,
    TRAZADOS,
    construir_lecturas,
    muestrear,
)
from insertar_rutas_prueba import (  # noqa: E402
    IP_ORIGEN,
    RAIZ,
    SQL_BORRAR,
    SQL_INSERTAR,
    conectar,
    nombre_bd,
    verificar_candado,
)

CARRO_1 = "carro-prueba-1"
CARRO_2 = "carro-prueba-2"

# Uninorte -> Puerto Colombia por la Via al Mar (trazado aproximado, solo para
# tener un lugar por donde paso unicamente el carro 2)
UNINORTE_PUERTO_COLOMBIA = [
    (11.01918, -74.85098), (11.0215, -74.8600), (11.0190, -74.8720), (11.0140, -74.8860),
    (11.0080, -74.9000), (11.0025, -74.9150), (10.9975, -74.9300), (10.9925, -74.9430),
    (10.9890, -74.9520), (10.9878, -74.9545),
]


def ahora_bogota():
    return datetime.now(BOGOTA).replace(microsecond=0)


def construir_carro_1():
    lecturas, resumen = construir_lecturas()
    puntos = muestrear(TRAZADOS["estadio_malecon"], 16, 31)
    inicio = ahora_bogota() - timedelta(minutes=1) - timedelta(seconds=CADA_SEGUNDOS * (len(puntos) - 1))
    lecturas = lecturas + [(inicio + timedelta(seconds=CADA_SEGUNDOS * i), la, lo) for i, (la, lo) in enumerate(puntos)]
    resumen = resumen + [("11. HOY: Estadio -> Malecon (termina hace 1 min)", inicio, len(puntos))]
    return lecturas, resumen


def construir_carro_2():
    hoy = datetime.now(BOGOTA).replace(hour=0, minute=0, second=0, microsecond=0)

    def a_las(dias_antes, hora, minuto):
        return hoy - timedelta(days=dias_antes) + timedelta(hours=hora, minutes=minuto)

    lecturas, resumen = [], []

    def agregar(nombre, inicio, puntos):
        for i, (lat, lon) in enumerate(puntos):
            lecturas.append((inicio + timedelta(seconds=CADA_SEGUNDOS * i), lat, lon))
        resumen.append((nombre, inicio, len(puntos)))

    agregar("1. Centro -> Estadio (Barranquilla)", a_las(2, 9, 0),
            muestrear(TRAZADOS["centro_estadio"], 13, 41))
    agregar("2. Barranquilla -> Santa Marta (1 parada)", a_las(2, 14, 0),
            muestrear(TRAZADOS["bq_santamarta"], 105, 42, [(0.4, 10)]))
    agregar("3. Centro -> Buenavista (Barranquilla)", a_las(1, 10, 0),
            muestrear(TRAZADOS["centro_buenavista"], 9, 43))
    agregar("4. Uninorte -> Puerto Colombia", a_las(1, 15, 0),
            muestrear(UNINORTE_PUERTO_COLOMBIA, 25, 44))

    puntos = muestrear(TRAZADOS["uninorte_centro"], 17, 45)
    inicio = ahora_bogota() - timedelta(minutes=20) - timedelta(seconds=CADA_SEGUNDOS * (len(puntos) - 1))
    agregar("5. HOY: Uninorte -> Centro (termina hace 20 min)", inicio, puntos)

    lecturas.sort(key=lambda x: x[0])
    return lecturas, resumen


def insertar(cursor, device, lecturas):
    insertadas = 0
    for fecha, lat, lon in lecturas:
        # Hora de Bogota sin zona: asi la guarda el sniffer
        marca = fecha.replace(tzinfo=None)
        cursor.execute(SQL_INSERTAR, (device, IP_ORIGEN, lat, lon, marca, marca))
        insertadas += cursor.rowcount
    return insertadas


def mover_en_vivo(conexion, carro1, carro2, minutos):
    """Un punto de cada carro cada CADA_SEGUNDOS, con la hora actual."""
    camino1 = muestrear(list(reversed(TRAZADOS["estadio_malecon"])), minutos, 51)
    camino2 = muestrear(list(reversed(TRAZADOS["uninorte_centro"])), minutos, 52)
    print(f"\nEn vivo durante {minutos} min ({len(camino1)} puntos por carro). Ctrl+C para parar.")
    cursor = conexion.cursor()
    try:
        for i, (p1, p2) in enumerate(zip(camino1, camino2)):
            marca = ahora_bogota().replace(tzinfo=None)
            cursor.execute(SQL_INSERTAR, (carro1, IP_ORIGEN, p1[0], p1[1], marca, marca))
            cursor.execute(SQL_INSERTAR, (carro2, IP_ORIGEN, p2[0], p2[1], marca, marca))
            conexion.commit()
            print(f"  {marca:%H:%M:%S}  punto {i + 1}/{len(camino1)}")
            if i < len(camino1) - 1:
                time.sleep(CADA_SEGUNDOS)
    except KeyboardInterrupt:
        print("\nDetenido.")
    finally:
        cursor.close()


def main():
    ap = argparse.ArgumentParser(description="Inserta datos de dos carros en la base de datos de pruebas")
    ap.add_argument("--carro1", default=CARRO_1, help=f"device_id del primer carro (por defecto {CARRO_1})")
    ap.add_argument("--carro2", default=CARRO_2, help=f"device_id del segundo carro (por defecto {CARRO_2})")
    ap.add_argument("--vivo", type=int, default=0, metavar="MIN",
                    help="despues de insertar, mover los dos carros en vivo durante MIN minutos")
    ap.add_argument("--dry-run", action="store_true", help="muestra lo que haria, sin conectarse a la BD")
    ap.add_argument("--borrar", action="store_true", help="borra las filas de los dos carros en vez de insertar")
    ap.add_argument("--si", action="store_true", help="no pedir confirmacion")
    args = ap.parse_args()

    if args.carro1 == args.carro2:
        sys.exit("Los dos carros deben tener device_id distintos.")

    load_dotenv(os.path.join(RAIZ, ".env"))
    verificar_candado()

    datos = {args.carro1: construir_carro_1(), args.carro2: construir_carro_2()}
    accion = "BORRAR" if args.borrar else "INSERTAR"
    print(f"Base de datos: {nombre_bd()} @ {os.getenv('rdshost')}")
    print(f"Accion:        {accion}\n")
    for device, (lecturas, resumen) in datos.items():
        print(f"{device}: {len(lecturas)} lecturas en {len(resumen)} rutas")
        for nombre, inicio, n in resumen:
            print(f"  {inicio:%Y-%m-%d %H:%M}  {n:3d} puntos  {nombre}")
        print()
    if args.vivo and not args.borrar:
        print(f"Luego: {args.vivo} min en vivo para los dos carros.\n")

    if args.dry_run:
        print("--dry-run: no se conecto a la base de datos ni se cambio nada.")
        return

    if not args.si and input(f"Escribe 's' para {accion.lower()}: ").strip().lower() != "s":
        print("Cancelado.")
        sys.exit(1)

    conexion = conectar()
    try:
        cursor = conexion.cursor()
        for device, (lecturas, _) in datos.items():
            if args.borrar:
                cursor.execute(SQL_BORRAR, (device,))
                print(f"{device}: filas borradas: {cursor.rowcount}")
            else:
                n = insertar(cursor, device, lecturas)
                print(f"{device}: filas insertadas: {n} de {len(lecturas)} ({len(lecturas) - n} ya existian)")
        conexion.commit()
        cursor.close()
        if args.vivo and not args.borrar:
            mover_en_vivo(conexion, args.carro1, args.carro2, args.vivo)
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


if __name__ == "__main__":
    main()
