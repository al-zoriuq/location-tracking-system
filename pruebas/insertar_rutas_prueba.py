"""Insert the sample routes DIRECTLY into the TEST database.

Alternative to enviar_rutas_prueba.py (UDP) for when the sniffer on port 5000 is
the production one: no sniffer is involved here. The rows are inserted with the
same SQL statement snifferwpostgresql.py uses, into the database named in the
.env of the folder this script is run from.

LOCK: it refuses to run unless the database name ends in "_test" (for example
"locationtracker_test"). It never touches "p2database".

Usage (on the server, inside the test project folder and with its venv):
    python pruebas/insertar_rutas_prueba.py --dry-run     # only prints, does not touch the DB
    python pruebas/insertar_rutas_prueba.py               # inserts the routes
    python pruebas/insertar_rutas_prueba.py --borrar      # deletes the sample routes

The routes are the same as in enviar_rutas_prueba.py (see its description).
Running the insert again is safe: (device_id, timestamp_gps) is unique and
duplicates are ignored.
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

# Same statement as snifferwpostgresql.py
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
    """Abort unless the database is a test one."""
    if not nombre_bd().endswith("_test"):
        sys.exit(
            f"ABORTED: the database is '{nombre_bd() or '(not set)'}', and this script only "
            "works with databases whose name ends in '_test'. Nothing was changed."
        )


def conectar():
    # Same parameters as servidorweb.py and snifferwpostgresql.py
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
    ap = argparse.ArgumentParser(description="Insert sample routes into the test database")
    ap.add_argument("--device", default=DEVICE_POR_DEFECTO, help=f"device_id (default {DEVICE_POR_DEFECTO})")
    ap.add_argument("--dry-run", action="store_true", help="print what would be done, without connecting to the DB")
    ap.add_argument("--borrar", action="store_true", help="delete the rows of that device_id instead of inserting")
    ap.add_argument("--si", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()

    load_dotenv(os.path.join(RAIZ, ".env"))
    verificar_candado()

    lecturas, resumen = construir_lecturas()
    accion = "DELETE" if args.borrar else "INSERT"
    print(f"Database: {nombre_bd()} @ {os.getenv('rdshost')}")
    print(f"Device:   {args.device}")
    print(f"Action:   {accion}   ({len(lecturas)} readings in {len(resumen)} routes)\n")
    for nombre, inicio, n in resumen:
        print(f"  {inicio:%Y-%m-%d %H:%M}  {n:3d} points  {nombre}")

    if args.dry_run:
        print("\n--dry-run: did not connect to the database, nothing was changed.")
        return

    if not args.si and input(f"\nType 'y' to {accion.lower()}: ").strip().lower() not in ("y", "yes", "s", "si"):
        print("Cancelled.")
        sys.exit(1)

    conexion = conectar()
    try:
        cursor = conexion.cursor()
        if args.borrar:
            cursor.execute(SQL_BORRAR, (args.device,))
            print(f"\nRows deleted: {cursor.rowcount}")
        else:
            insertadas = 0
            for fecha, lat, lon in lecturas:
                # Bogota wall-clock time without a zone: how the sniffer stores it
                marca = fecha.replace(tzinfo=None)
                cursor.execute(SQL_INSERTAR, (args.device, IP_ORIGEN, lat, lon, marca, marca))
                insertadas += cursor.rowcount
            print(f"\nRows inserted: {insertadas} of {len(lecturas)} "
                  f"({len(lecturas) - insertadas} already existed)")
        conexion.commit()
        cursor.close()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


if __name__ == "__main__":
    main()
