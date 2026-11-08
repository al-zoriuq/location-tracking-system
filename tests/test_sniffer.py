"""Tests for snifferwpostgresql.py (the port-5000 UDP server) with a fake database."""
import os
import sys
from datetime import datetime

import psycopg2
import psycopg2.errors
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import snifferwpostgresql as sniffer  # noqa: E402

BASE = ("Device: ESP32S3-SIM7670G, Lat: 11.030190, Lon: -74.859845, "
        "Timestamp GPS: 2026-11-03 07:50:28.000000 -0500")
CON_SENAL = BASE + ", Senal: LIMITE 30, Conf: 0.99, Vel GPS: 2, Vel MPU: 22, Usa: GPS, SI"
RECEPCION = datetime(2026, 11, 3, 12, 50, 30)


class CursorFalso:
    def __init__(self, bd):
        self.bd = bd
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        bd = self.bd
        if bd.caida:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        if "to_regclass" in sql:
            self._uno = (bd.tabla_senales,)
            return
        if "detecciones_senal" in sql and not bd.tabla_senales:
            raise psycopg2.errors.UndefinedTable('relation "detecciones_senal" does not exist')
        if "INSERT INTO ubicaciones" in sql:
            clave = (params[0], params[4])
            self.rowcount = 0 if clave in bd.ubicaciones else 1
            bd.pendientes.append(("ubicaciones", clave, params))
        elif "INSERT INTO detecciones_senal" in sql:
            if bd.falla_detecciones:
                raise psycopg2.errors.CheckViolation("violates check constraint")
            clave = (params[0], params[6], params[8])
            self.rowcount = 0 if clave in bd.detecciones else 1
            bd.pendientes.append(("detecciones", clave, params))

    def fetchone(self):
        return self._uno


class ConexionFalsa:
    def __init__(self, bd):
        self.bd = bd
        self.cerrada = False

    def cursor(self):
        return CursorFalso(self.bd)

    def commit(self):
        if self.bd.caida:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        for tabla, clave, params in self.bd.pendientes:
            getattr(self.bd, tabla).setdefault(clave, params)
        self.bd.pendientes.clear()

    def rollback(self):
        self.bd.pendientes.clear()
        self.bd.rollbacks += 1

    def close(self):
        self.cerrada = True


class BDFalsa:
    def __init__(self, tabla_senales=True):
        self.tabla_senales = tabla_senales
        self.caida = False
        self.falla_detecciones = False
        self.ubicaciones = {}
        self.detecciones = {}
        self.pendientes = []
        self.rollbacks = 0
        self.conexiones = 0

    def conectar(self):
        if self.caida:
            raise psycopg2.OperationalError("could not connect to server")
        self.conexiones += 1
        return ConexionFalsa(self)


def almacen(bd):
    return sniffer.Almacen(conectar_bd=bd.conectar)


def test_mensaje_con_senal_guarda_ubicacion_y_deteccion():
    bd = BDFalsa()
    lineas = sniffer.procesar(CON_SENAL, "1.2.3.4", almacen(bd), RECEPCION)
    assert lineas[-1] == "BD: ubicación nueva, señal nueva"
    assert len(bd.ubicaciones) == 1 and len(bd.detecciones) == 1
    params = next(iter(bd.detecciones.values()))
    assert params[8:11] == ("LIMITE 30", "LIMITE", 30)
    assert params[7] == RECEPCION


def test_mensaje_sin_senal_solo_ubicacion():
    bd = BDFalsa()
    lineas = sniffer.procesar(BASE, "1.2.3.4", almacen(bd), RECEPCION)
    assert lineas[-1] == "BD: ubicación nueva"
    assert len(bd.ubicaciones) == 1 and bd.detecciones == {}


def test_senal_con_la_misma_hora_que_un_punto_ya_guardado():
    # The ESP32 sends a plain point and then the sign with the same GPS time
    bd = BDFalsa()
    a = almacen(bd)
    sniffer.procesar(BASE, "1.2.3.4", a, RECEPCION)
    lineas = sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)
    assert lineas[-1] == "BD: ubicación ya existía, señal nueva"
    assert len(bd.detecciones) == 1


def test_paquete_repetido_no_duplica():
    bd = BDFalsa()
    a = almacen(bd)
    sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)
    lineas = sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)
    assert lineas[-1] == "BD: ubicación ya existía, señal repetida (ignorada)"
    assert len(bd.ubicaciones) == 1 and len(bd.detecciones) == 1


def test_mensaje_invalido_no_toca_la_bd():
    bd = BDFalsa()
    lineas = sniffer.procesar("hola", "1.2.3.4", almacen(bd), RECEPCION)
    assert lineas == ["Mensaje descartado: formato de mensaje no reconocido"]
    assert bd.ubicaciones == {}


def test_senal_invalida_guarda_la_ubicacion():
    bd = BDFalsa()
    msg = BASE + ", Senal: LIMITE 30, Conf: 1.50, Vel GPS: 2, Vel MPU: 2, Usa: GPS, SI"
    lineas = sniffer.procesar(msg, "1.2.3.4", almacen(bd), RECEPCION)
    assert any(linea.startswith("AVISO: senal descartada") for linea in lineas)
    assert lineas[-1] == "BD: ubicación nueva"
    assert len(bd.ubicaciones) == 1 and bd.detecciones == {}


def test_sin_tabla_guarda_solo_ubicaciones_y_la_detecta_despues(monkeypatch):
    # Production database before the migration
    bd = BDFalsa(tabla_senales=False)
    a = almacen(bd)
    lineas = sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)
    assert lineas[-1] == "BD: ubicación nueva, señal NO guardada (falta la tabla detecciones_senal)"
    assert len(bd.ubicaciones) == 1 and bd.detecciones == {}

    # Migration applied while the sniffer runs: picked up on the next check
    bd.tabla_senales = True
    monkeypatch.setattr(sniffer, "REVISAR_TABLA_CADA_S", 0)
    otro = CON_SENAL.replace("07:50:28", "07:50:40")
    lineas = sniffer.procesar(otro, "1.2.3.4", a, RECEPCION)
    assert lineas[-1] == "BD: ubicación nueva, señal nueva"
    assert len(bd.detecciones) == 1


def test_tabla_borrada_con_el_sniffer_corriendo():
    bd = BDFalsa()
    a = almacen(bd)
    bd.tabla_senales = False
    lineas = sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)
    assert lineas[-1] == "BD: ubicación nueva, señal NO guardada (falta la tabla detecciones_senal)"
    assert len(bd.ubicaciones) == 1


def test_error_de_datos_hace_rollback_y_sigue():
    bd = BDFalsa()
    a = almacen(bd)
    bd.falla_detecciones = True
    lineas = sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)
    assert lineas[-1].startswith("BD: NO guardado")
    assert bd.rollbacks == 1 and bd.ubicaciones == {}
    # The connection is still usable for the next packet
    bd.falla_detecciones = False
    assert sniffer.procesar(BASE.replace("07:50:28", "07:51:00"), "1.2.3.4", a, RECEPCION)[-1] == "BD: ubicación nueva"


def test_reconecta_si_se_cae_la_conexion():
    bd = BDFalsa()
    a = almacen(bd)
    vieja = a.conn
    vieja_caida = ConexionFalsa(BDFalsa())
    vieja_caida.bd.caida = True
    a.conn = vieja_caida  # this connection is dead; the database itself is fine
    lineas = sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)
    assert lineas[-1] == "BD: ubicación nueva, señal nueva (tras reconectar)"
    assert a.conn is not vieja and len(bd.detecciones) == 1


def test_bd_caida_no_detiene_el_servidor():
    bd = BDFalsa()
    a = almacen(bd)
    bd.caida = True
    lineas = sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)
    assert lineas[-1].startswith("BD: NO guardado, sin conexión")
    # When the database comes back, the next packet is saved
    bd.caida = False
    assert sniffer.procesar(CON_SENAL, "1.2.3.4", a, RECEPCION)[-1].startswith("BD: ubicación nueva")
