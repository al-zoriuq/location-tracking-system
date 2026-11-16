"""Inserta DOS rutas con senales de transito para CADA uno de los dos carros de
prueba, directo en la base de datos de PRUEBAS (ubicaciones + detecciones_senal).

Sirve para probar en la pagina, con dos carros: el panel de senales, los
marcadores de senal en el mapa, los excesos de velocidad y el cambio de carro.
Las rutas y las senales de cada carro son distintas.

Usa el mismo candado, la misma conexion y la misma sentencia de ubicaciones que
insertar_rutas_prueba.py (solo bases cuyo nombre termina en "_test"), y la misma
sentencia de senales que snifferwpostgresql.py. La tabla detecciones_senal debe
existir (ver "Esquema de detecciones_senal" en el README).

Uso (en el servidor, dentro de la carpeta del proyecto de test y con su venv):
    python pruebas/insertar_senales_dos_carros_prueba.py --dry-run    # solo muestra
    python pruebas/insertar_senales_dos_carros_prueba.py              # inserta
    python pruebas/insertar_senales_dos_carros_prueba.py --borrar     # borra SOLO lo que
                                                                      # inserta este script
Opciones: --carro1 / --carro2 (device_id; por defecto los mismos de
insertar_dos_carros_prueba.py) y --dias N (cuantos dias antes de hoy; por defecto 1 = ayer).
Repetir el insertado es seguro: los duplicados se ignoran.

Que se inserta (por defecto AYER, hora de Bogota):
  carro-prueba-1
    08:30  Uninorte -> Centro    LIMITE 30 SI (25), PARE, LIMITE 30 EXCEDE (41), CEDA
    17:30  Estadio -> Malecon    LIMITE 50 SI (44, MPU), LIMITE 30 EXCEDE (37), PARE
  carro-prueba-2
    09:30  Centro -> Estadio     LIMITE 40 SI (33), CEDA, LIMITE 40 EXCEDE (52)
    18:15  Centro -> Buenavista  LIMITE 60 SI (58, MPU), PARE, LIMITE 30 EXCEDE (45)
Total: 4 rutas y 13 senales (4 excesos).

Como verlas en la pagina: sin filtros solo se ve el ultimo punto de cada carro.
Usa "Filtrar por fecha" con el dia insertado (o la flecha / lista de rutas del
carro activo) y abre "Senales" en la barra de herramientas. Cambia de carro
tocando su tarjeta para ver sus senales.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv  # noqa: E402
from enviar_rutas_prueba import BOGOTA, CADA_SEGUNDOS, TRAZADOS, muestrear  # noqa: E402
from insertar_rutas_prueba import (  # noqa: E402
    IP_ORIGEN,
    RAIZ,
    SQL_INSERTAR,
    conectar,
    nombre_bd,
    verificar_candado,
)

CARRO_1 = "carro-prueba-1"
CARRO_2 = "carro-prueba-2"

# Misma sentencia que snifferwpostgresql.py
SQL_DETECCION = """
    INSERT INTO detecciones_senal
    (device_id, ip_origen, latitud, longitud, timestamp_gps,
     senal_texto, senal_tipo, senal_valor,
     confianza, vel_gps, vel_mpu, vel_fuente, cumplimiento, extra)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT ON CONSTRAINT detecciones_senal_unica DO NOTHING
"""
SQL_EXISTE_TABLA = "SELECT to_regclass('public.detecciones_senal') IS NOT NULL"
SQL_BORRAR_UBICACIONES = (
    "DELETE FROM ubicaciones WHERE device_id = %s AND timestamp_gps BETWEEN %s AND %s"
)
SQL_BORRAR_DETECCIONES = (
    "DELETE FROM detecciones_senal WHERE device_id = %s AND timestamp_gps BETWEEN %s AND %s"
)

# Cada senal: (fraccion del recorrido, texto, confianza, vel_gps, vel_mpu, fuente)
# vel None = el sensor no dio dato ("NA"). El cumplimiento se calcula abajo.
RUTAS = {
    "carro1": [
        ("Uninorte -> Centro", (8, 30), "uninorte_centro", 17, 61, [
            (0.15, "LIMITE 30", 0.97, 25, 24, "GPS"),
            (0.35, "PARE", 1.00, None, 6, "MPU"),
            (0.60, "LIMITE 30", 0.93, 41, 39, "GPS"),
            (0.85, "CEDA", 0.89, 14, 15, "GPS"),
        ]),
        ("Estadio -> Malecon", (17, 30), "estadio_malecon", 16, 62, [
            (0.20, "LIMITE 50", 0.99, None, 44, "MPU"),
            (0.55, "LIMITE 30", 0.95, 37, 36, "GPS"),
            (0.80, "PARE", 0.98, 4, 5, "GPS"),
        ]),
    ],
    "carro2": [
        ("Centro -> Estadio", (9, 30), "centro_estadio", 13, 63, [
            (0.20, "LIMITE 40", 0.96, 33, 31, "GPS"),
            (0.50, "CEDA", 0.90, 11, 12, "GPS"),
            (0.80, "LIMITE 40", 0.94, 52, 50, "GPS"),
        ]),
        ("Centro -> Buenavista", (18, 15), "centro_buenavista", 9, 64, [
            (0.25, "LIMITE 60", 0.99, None, 58, "MPU"),
            (0.55, "PARE", 1.00, 3, 4, "GPS"),
            (0.85, "LIMITE 30", 0.92, 45, 44, "GPS"),
        ]),
    ],
}


def tipo_y_valor(texto):
    partes = texto.split()
    if partes[0] == "LIMITE":
        return "LIMITE", int(partes[1])
    return partes[0], None


def cumplimiento(tipo, valor, vel):
    if tipo != "LIMITE" or vel is None:
        return "NA"
    return "SI" if vel <= valor else "EXCEDE"


def construir(clave, dias):
    """Lista de rutas: (nombre, inicio, [(fecha, lat, lon)], [deteccion...])."""
    dia = datetime.now(BOGOTA).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=dias)
    rutas = []
    for nombre, (hora, minuto), trazado, minutos, semilla, senales in RUTAS[clave]:
        inicio = dia + timedelta(hours=hora, minutes=minuto)
        puntos = muestrear(TRAZADOS[trazado], minutos, semilla)
        lecturas = [(inicio + timedelta(seconds=CADA_SEGUNDOS * i), la, lo) for i, (la, lo) in enumerate(puntos)]
        detecciones = []
        for fraccion, texto, conf, vel_gps, vel_mpu, fuente in senales:
            # La senal llega con la posicion y la hora GPS de un punto de la ruta, como en el ESP32
            fecha, lat, lon = lecturas[int(fraccion * (len(lecturas) - 1))]
            tipo, valor = tipo_y_valor(texto)
            vel = vel_gps if fuente == "GPS" else vel_mpu
            detecciones.append((fecha, lat, lon, texto, tipo, valor, conf, vel_gps, vel_mpu,
                                fuente, cumplimiento(tipo, valor, vel)))
        rutas.append((nombre, inicio, lecturas, detecciones))
    return rutas


def sin_zona(fecha):
    # Hora de Bogota sin zona: asi la guarda el sniffer
    return fecha.replace(tzinfo=None)


def main():
    ap = argparse.ArgumentParser(description="Inserta 2 rutas con senales para cada uno de los dos carros de prueba")
    ap.add_argument("--carro1", default=CARRO_1, help=f"device_id del primer carro (por defecto {CARRO_1})")
    ap.add_argument("--carro2", default=CARRO_2, help=f"device_id del segundo carro (por defecto {CARRO_2})")
    ap.add_argument("--dias", type=int, default=1, help="dias antes de hoy (por defecto 1 = ayer)")
    ap.add_argument("--dry-run", action="store_true", help="muestra lo que haria, sin conectarse a la BD")
    ap.add_argument("--borrar", action="store_true", help="borra solo las rutas y senales de este script")
    ap.add_argument("--si", action="store_true", help="no pedir confirmacion")
    args = ap.parse_args()

    if args.carro1 == args.carro2:
        sys.exit("Los dos carros deben tener device_id distintos.")
    if args.dias < 1:
        sys.exit("--dias debe ser 1 o mas (las fechas no pueden ser de hoy ni futuras).")

    load_dotenv(os.path.join(RAIZ, ".env"))
    verificar_candado()

    datos = {args.carro1: construir("carro1", args.dias), args.carro2: construir("carro2", args.dias)}
    accion = "BORRAR" if args.borrar else "INSERTAR"
    print(f"Base de datos: {nombre_bd()} @ {os.getenv('rdshost')}")
    print(f"Accion:        {accion}\n")
    for device, rutas in datos.items():
        print(device)
        for nombre, inicio, lecturas, detecciones in rutas:
            print(f"  {inicio:%Y-%m-%d %H:%M}  {len(lecturas):3d} puntos  {nombre}")
            for fecha, _, _, texto, _, _, _, vel_gps, vel_mpu, fuente, cumple in detecciones:
                vel = vel_gps if fuente == "GPS" else vel_mpu
                print(f"      {fecha:%H:%M:%S}  {texto:<10} vel {vel if vel is not None else 'NA':>3} ({fuente})  {cumple}")
        print()

    if args.dry_run:
        print("--dry-run: no se conecto a la base de datos ni se cambio nada.")
        return

    if not args.si and input(f"Escribe 's' para {accion.lower()}: ").strip().lower() != "s":
        print("Cancelado.")
        sys.exit(1)

    conexion = conectar()
    try:
        cursor = conexion.cursor()
        cursor.execute(SQL_EXISTE_TABLA)
        if not cursor.fetchone()[0]:
            sys.exit("ABORTADO: la base de datos no tiene la tabla detecciones_senal "
                     "(ver 'Esquema de detecciones_senal' en el README). No se toco nada.")
        for device, rutas in datos.items():
            n_ubi = n_det = 0
            for _, _, lecturas, detecciones in rutas:
                desde, hasta = sin_zona(lecturas[0][0]), sin_zona(lecturas[-1][0])
                if args.borrar:
                    cursor.execute(SQL_BORRAR_DETECCIONES, (device, desde, hasta))
                    n_det += cursor.rowcount
                    cursor.execute(SQL_BORRAR_UBICACIONES, (device, desde, hasta))
                    n_ubi += cursor.rowcount
                    continue
                for fecha, lat, lon in lecturas:
                    m = sin_zona(fecha)
                    cursor.execute(SQL_INSERTAR, (device, IP_ORIGEN, lat, lon, m, m))
                    n_ubi += cursor.rowcount
                for (fecha, lat, lon, texto, tipo, valor, conf, vel_gps, vel_mpu,
                     fuente, cumple) in detecciones:
                    cursor.execute(SQL_DETECCION, (device, IP_ORIGEN, lat, lon, sin_zona(fecha),
                                                   texto, tipo, valor, conf, vel_gps, vel_mpu,
                                                   fuente, cumple, None))
                    n_det += cursor.rowcount
            verbo = "borradas" if args.borrar else "insertadas"
            print(f"{device}: ubicaciones {verbo}: {n_ubi}, senales {verbo}: {n_det}")
        conexion.commit()
        cursor.close()
    except BaseException:
        conexion.rollback()
        raise
    finally:
        conexion.close()


if __name__ == "__main__":
    main()
