"""Inserta las rutas de prueba DIRECTO en la base de datos de PRUEBAS.

Alternativa a enviar_rutas_prueba.py (UDP) para cuando el sniffer del puerto 5000
es el de produccion: aqui no se pasa por ningun sniffer, se inserta con la misma
sentencia SQL que usa snifferwpostgresql.py, en la base que indique el .env de la
carpeta desde donde se ejecute.

CANDADO: se niega a correr si el nombre de la base de datos no termina en "_test"
(por ejemplo "locationtracker_test"). Nunca toca "p2database".

Uso (en el servidor, dentro de la carpeta del proyecto de test y con su venv):
    python pruebas/insertar_rutas_prueba.py --dry-run     # solo muestra, no toca la BD
    python pruebas/insertar_rutas_prueba.py               # inserta las rutas
    python pruebas/insertar_rutas_prueba.py --borrar      # borra las rutas de prueba

Las rutas son las mismas de enviar_rutas_prueba.py (ver su descripcion). Repetir el
insertado es seguro: (device_id, timestamp_gps) es unico y los duplicados se ignoran.
"""
import argparse
import os
import sys

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enviar_rutas_prueba import DEVICE_POR_DEFECTO, construir_lecturas  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IP_ORIGEN = "127.0.0.1"

# Misma sentencia que snifferwpostgresql.py
SQL_INSERTAR = """
    INSERT INTO ubicaciones
    (device_id, ip_origen, latitud, longitud, timestamp_gps, timestamp_recepcion)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (device_id, timestamp_gps) DO NOTHING
"""
SQL_BORRAR = "DELETE FROM ubicaciones WHERE device_id = %s"


def nombre_bd():
    return os.getenv("rdsdbname") or ""


def verificar_candado():
    """Aborta si la base de datos no es de pruebas."""
    if not nombre_bd().endswith("_test"):
        sys.exit(
            f"ABORTADO: la base de datos es '{nombre_bd() or '(sin definir)'}', y este script "
            "solo trabaja con bases cuyo nombre termina en '_test'. No se toco nada."
        )


def conectar():
    # Mismos parametros que servidorweb.py y snifferwpostgresql.py
    return psycopg2.connect(
        host=os.getenv("rdshost"),
        port=5432,
        database=os.getenv("rdsdbname"),
        user=os.getenv("rdsuser"),
        password=os.getenv("rdspass"),
        sslmode="verify-full",
        sslrootcert=os.path.join(RAIZ, "global-bundle.pem"),
    )


def main():
    ap = argparse.ArgumentParser(description="Inserta rutas de prueba en la base de datos de pruebas")
    ap.add_argument("--device", default=DEVICE_POR_DEFECTO, help=f"device_id (por defecto {DEVICE_POR_DEFECTO})")
    ap.add_argument("--dry-run", action="store_true", help="muestra lo que haria, sin conectarse a la BD")
    ap.add_argument("--borrar", action="store_true", help="borra las filas de ese device_id en vez de insertar")
    ap.add_argument("--si", action="store_true", help="no pedir confirmacion")
    args = ap.parse_args()

    load_dotenv(os.path.join(RAIZ, ".env"))
    verificar_candado()

    lecturas, resumen = construir_lecturas()
    accion = "BORRAR" if args.borrar else "INSERTAR"
    print(f"Base de datos: {nombre_bd()} @ {os.getenv('rdshost')}")
    print(f"Dispositivo:   {args.device}")
    print(f"Accion:        {accion}   ({len(lecturas)} lecturas en {len(resumen)} rutas)\n")
    for nombre, inicio, n in resumen:
        print(f"  {inicio:%Y-%m-%d %H:%M}  {n:3d} puntos  {nombre}")

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
                # Hora de Bogota sin zona: asi la guarda el sniffer
                marca = fecha.replace(tzinfo=None)
                cursor.execute(SQL_INSERTAR, (args.device, IP_ORIGEN, lat, lon, marca, marca))
                insertadas += cursor.rowcount
            print(f"\nFilas insertadas: {insertadas} de {len(lecturas)} "
                  f"({len(lecturas) - insertadas} ya existian)")
        conexion.commit()
        cursor.close()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


if __name__ == "__main__":
    main()
