"""Inserta una ruta a 1 punto por segundo en la base de datos de PRUEBAS y
verifica que /api/historial-ubicaciones?intervalo_s=10 la entregue con un solo
punto por bloque de 10 s, sin perder bloques, sin duplicados y en orden.

Sirve para probar el muestreo del servidor (FEATURE 2) con datos como los que
manda el celular cuando reporta cada segundo. Inserta con la misma sentencia
SQL que snifferwpostgresql.py, en la base que indique el .env de la carpeta
desde donde se ejecute.

CANDADO: se niega a correr si el nombre de la base de datos no termina en
"_test" (por ejemplo "locationtracker_test"). Nunca toca "p2database".

Uso (en el servidor, dentro de la carpeta del proyecto de test y con su venv):
    python pruebas/insertar_ruta_1s_prueba.py --dry-run     # solo muestra, no toca la BD
    python pruebas/insertar_ruta_1s_prueba.py               # inserta la ruta (termina "ahora")
    python pruebas/insertar_ruta_1s_prueba.py --verificar   # comprueba el muestreo (solo lee)
    python pruebas/insertar_ruta_1s_prueba.py --borrar      # borra las filas de prueba

--verificar llama al endpoint real de servidorweb.py (con el cliente de pruebas
de Flask, sin pasar por gunicorn) contra la base de datos real, asi que prueba
el codigo de este checkout aunque el servicio web no se haya reiniciado.

Repetir el insertado es seguro: (device_id, timestamp_gps) es unico y los
duplicados se ignoran.
"""
import argparse
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from dotenv import load_dotenv

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
sys.path.insert(0, RAIZ)

import enviar_rutas_prueba  # noqa: E402
from enviar_rutas_prueba import TRAZADOS  # noqa: E402
from insertar_rutas_prueba import (  # noqa: E402
    IP_ORIGEN, SQL_BORRAR, SQL_INSERTAR, conectar, nombre_bd, verificar_candado,
)

DEVICE_POR_DEFECTO = "carro-prueba-1s"
INTERVALO_S = 10  # el mismo que pide el frontend (INTERVALO_MUESTREO_S en App.jsx)
FORMATO = "%Y-%m-%d %H:%M:%S"


def ahora_bogota():
    # Hora de Bogota sin zona: asi la guarda el sniffer
    return datetime.now(enviar_rutas_prueba.BOGOTA).replace(tzinfo=None, microsecond=0)


def construir_lecturas(minutos, saltar):
    """(fecha, lat, lon) cada segundo durante `minutos`, terminando hace 1 s.
    `saltar` es la fraccion de segundos sin lectura (un GPS real a veces no
    reporta), para que haya bloques de 10 s incompletos."""
    # muestrear() lee CADA_SEGUNDOS del modulo: aqui la ruta va a 1 por segundo
    enviar_rutas_prueba.CADA_SEGUNDOS = 1
    puntos = enviar_rutas_prueba.muestrear(TRAZADOS["uninorte_centro"], minutos, 21)
    inicio = ahora_bogota() - timedelta(seconds=len(puntos))
    azar = random.Random(7)
    lecturas = []
    for i, (lat, lon) in enumerate(puntos):
        # El primero y el ultimo siempre se insertan
        if 0 < i < len(puntos) - 1 and azar.random() < saltar:
            continue
        lecturas.append((inicio + timedelta(seconds=i), lat, lon))
    return lecturas


def insertar(lecturas, device):
    conexion = conectar()
    try:
        cursor = conexion.cursor()
        insertadas = 0
        for fecha, lat, lon in lecturas:
            cursor.execute(SQL_INSERTAR, (device, IP_ORIGEN, lat, lon, fecha, fecha))
            insertadas += cursor.rowcount
        conexion.commit()
        cursor.close()
        print(f"\nFilas insertadas: {insertadas} de {len(lecturas)} "
              f"({len(lecturas) - insertadas} ya existian)")
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


def borrar(device):
    conexion = conectar()
    try:
        cursor = conexion.cursor()
        cursor.execute(SQL_BORRAR, (device,))
        print(f"\nFilas borradas: {cursor.rowcount}")
        conexion.commit()
        cursor.close()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


# ---------- verificacion ----------

def verificar(device):
    import servidorweb  # importado aqui: --dry-run no necesita Flask

    if not hasattr(servidorweb, "muestrear_sql"):
        sys.exit("ABORTADO: este servidorweb.py no tiene el muestreo (intervalo_s). "
                 "Actualiza el checkout a la version con el FEATURE 2.")

    cliente = servidorweb.app.test_client()

    def pedir(consulta):
        r = cliente.get(f"/api/historial-ubicaciones?device_id={device}&{consulta}")
        if r.status_code != 200:
            sys.exit(f"El endpoint respondio {r.status_code}: {r.get_json()}")
        return r.get_json()

    def fecha(fila):
        return datetime.strptime(fila["timestamp_gps"][:19], FORMATO)

    # Extremos de la ruta, para pedirla entera como rango explicito
    conexion = conectar()
    try:
        cursor = conexion.cursor()
        cursor.execute("SELECT MIN(timestamp_gps), MAX(timestamp_gps) FROM ubicaciones "
                       "WHERE device_id = %s", (device,))
        minimo, maximo = cursor.fetchone()
        cursor.close()
    finally:
        conexion.close()
    if minimo is None:
        sys.exit(f"No hay filas de '{device}'. Inserta primero la ruta (sin --verificar).")

    rango = (f"desde={minimo.strftime(FORMATO)}&hasta={maximo.strftime(FORMATO)}")
    crudos = [fecha(f) for f in pedir(rango)]
    muestreados = [fecha(f) for f in pedir(f"{rango}&intervalo_s={INTERVALO_S}")]

    def bloque(t):
        return servidorweb.inicio_bloque(t, INTERVALO_S)

    # Primer punto real de cada bloque, segun los datos crudos
    primeros = {}
    for t in crudos:
        primeros.setdefault(bloque(t), t)

    errores = []

    def comprobar(condicion, texto):
        print(f"  [{'OK' if condicion else 'FALLA'}] {texto}")
        if not condicion:
            errores.append(texto)

    por_bloque = defaultdict(int)
    for t in muestreados:
        por_bloque[bloque(t)] += 1

    print(f"\nPuntos crudos en la BD:          {len(crudos)}")
    print(f"Puntos con intervalo_s={INTERVALO_S}:     {len(muestreados)}")
    print(f"Bloques de {INTERVALO_S} s con datos:        {len(primeros)}\n")

    comprobar(muestreados == sorted(muestreados), "orden cronologico")
    comprobar(len(muestreados) == len(set(muestreados)), "sin timestamp_gps repetidos")
    comprobar(all(n == 1 for n in por_bloque.values()), "como maximo 1 punto por bloque")
    comprobar(set(por_bloque) == set(primeros), "ningun bloque con datos se queda sin punto")
    comprobar(all(primeros[bloque(t)] == t for t in muestreados), "el punto de cada bloque es el primero")

    # Consultas incrementales como las del frontend (despues_de = ultimo - 60 s),
    # con cortes a mitad de bloque: no deben aparecer puntos que no esten en la
    # carga completa, ni faltar los que si estan.
    conjunto = set(muestreados)
    pasos = list(range(len(crudos) // 4, len(crudos), max(1, len(crudos) // 8)))
    extra = faltan = 0
    for i in pasos:
        corte = crudos[i] - timedelta(seconds=60) + timedelta(seconds=3)
        nuevos = [fecha(f) for f in pedir(
            f"despues_de={corte.strftime(FORMATO)}&intervalo_s={INTERVALO_S}")]
        extra += sum(1 for t in nuevos if t not in conjunto)
        esperados = {t for t in muestreados if t >= bloque(corte)}
        faltan += len(esperados - set(nuevos))
    comprobar(extra == 0, f"consultas incrementales sin puntos de mas ({len(pasos)} cortes a mitad de bloque)")
    comprobar(faltan == 0, "consultas incrementales sin puntos perdidos")

    if errores:
        sys.exit(f"\nRESULTADO: FALLA ({len(errores)} comprobaciones)")
    print("\nRESULTADO: OK")


def main():
    ap = argparse.ArgumentParser(description="Ruta a 1 punto por segundo para probar intervalo_s")
    ap.add_argument("--device", default=DEVICE_POR_DEFECTO, help=f"device_id (por defecto {DEVICE_POR_DEFECTO})")
    ap.add_argument("--minutos", type=int, default=10, help="duracion de la ruta (por defecto 10)")
    ap.add_argument("--saltar", type=float, default=0.05,
                    help="fraccion de segundos sin lectura, como un GPS real (por defecto 0.05)")
    ap.add_argument("--dry-run", action="store_true", help="muestra lo que haria, sin conectarse a la BD")
    ap.add_argument("--verificar", action="store_true", help="comprueba el muestreo de la ruta ya insertada")
    ap.add_argument("--borrar", action="store_true", help="borra las filas de ese device_id")
    ap.add_argument("--si", action="store_true", help="no pedir confirmacion")
    args = ap.parse_args()

    load_dotenv(os.path.join(RAIZ, ".env"))
    verificar_candado()

    print(f"Base de datos: {nombre_bd()} @ {os.getenv('rdshost')}")
    print(f"Dispositivo:   {args.device}")

    if args.verificar:
        verificar(args.device)
        return

    if args.borrar:
        accion = "BORRAR"
        print(f"Accion:        BORRAR todas las filas de {args.device}")
    else:
        accion = "INSERTAR"
        lecturas = construir_lecturas(args.minutos, args.saltar)
        print(f"Accion:        INSERTAR {len(lecturas)} lecturas (1 por segundo, "
              f"~{args.saltar:.0%} sin lectura)")
        print(f"Desde:         {lecturas[0][0]:%Y-%m-%d %H:%M:%S}")
        print(f"Hasta:         {lecturas[-1][0]:%Y-%m-%d %H:%M:%S}")

    if args.dry_run:
        print("\n--dry-run: no se conecto a la base de datos ni se cambio nada.")
        return

    if not args.si and input(f"\nEscribe 's' para {accion.lower()}: ").strip().lower() != "s":
        print("Cancelado.")
        sys.exit(1)

    if args.borrar:
        borrar(args.device)
    else:
        insertar(lecturas, args.device)
        print(f"Ahora ejecuta:  python pruebas/insertar_ruta_1s_prueba.py --verificar"
              + (f" --device {args.device}" if args.device != DEVICE_POR_DEFECTO else ""))


if __name__ == "__main__":
    main()
