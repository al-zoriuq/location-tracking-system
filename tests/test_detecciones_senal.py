"""Tests for /api/detecciones-senal (traffic sign detections). No real database."""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import servidorweb

AHORA = datetime(2026, 11, 3, 10, 0, 0)


class CursorFalso:
    def __init__(self, filas):
        self.filas = filas
        self.ejecutadas = []

    def execute(self, sql, params=None):
        self.ejecutadas.append((sql, params))

    def fetchall(self):
        return [dict(f) for f in self.filas]

    def close(self):
        pass


class ConexionFalsa:
    def __init__(self, filas=()):
        self.cursor_falso = CursorFalso(filas)

    def cursor(self, **kwargs):
        return self.cursor_falso

    def close(self):
        pass


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(servidorweb, "ahora_local", lambda: AHORA)
    return servidorweb.app.test_client()


@pytest.fixture
def conexion(monkeypatch):
    con = ConexionFalsa([{
        "id": 1, "latitud": 11.03, "longitud": -74.86,
        "timestamp_evento": datetime(2026, 11, 3, 7, 50, 28),
        "senal_texto": "LIMITE 30", "senal_tipo": "LIMITE", "senal_valor": 30,
        "velocidad": 2.0, "cumplimiento": "SI",
    }])
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: con)
    return con


@pytest.fixture
def sin_bd(monkeypatch):
    def prohibido():
        raise AssertionError("No debe abrir conexion a la BD con parametros invalidos")
    monkeypatch.setattr(servidorweb, "obtener_conexion", prohibido)


def test_ruta_registrada():
    rutas = [str(r) for r in servidorweb.app.url_map.iter_rules()]
    assert "/api/detecciones-senal" in rutas


def test_por_defecto_ultimas_24h_del_ultimo_dispositivo(cliente, conexion):
    r = cliente.get("/api/detecciones-senal")
    assert r.status_code == 200
    fila = r.get_json()[0]
    assert fila["timestamp_evento"] == "2026-11-03 07:50:28"
    assert fila["senal_valor"] == 30
    sql, params = conexion.cursor_falso.ejecutadas[0]
    assert "FROM detecciones_senal" in sql
    assert "ORDER BY id DESC LIMIT 1" in sql  # same device rule as the history
    assert params == (24,)


def test_horas_y_device(cliente, conexion):
    r = cliente.get("/api/detecciones-senal?horas=72&device_id=ESP32S3-SIM7670G")
    assert r.status_code == 200
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params == (72, "ESP32S3-SIM7670G")


def test_rango_explicito(cliente, conexion):
    r = cliente.get("/api/detecciones-senal?desde=2026-11-03T07:00&hasta=2026-11-03T08:00")
    assert r.status_code == 200
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params == (datetime(2026, 11, 3, 7, 0), datetime(2026, 11, 3, 8, 0, 59, 999999))


def test_margen_se_recorta_a_ahora(cliente, conexion):
    r = cliente.get("/api/detecciones-senal?desde=2026-11-03T07:00&hasta=2026-11-03T08:00"
                    "&margen_horas=72")
    assert r.status_code == 200
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params == (datetime(2026, 10, 31, 7, 0), AHORA)


@pytest.mark.parametrize("consulta", [
    "desde=2026-11-03T09:00",                               # par incompleto
    "desde=ayer&hasta=2026-11-03T09:00",                    # formato invalido
    "desde=2026-11-03T09:00&hasta=2026-11-03T08:00",        # hasta < desde
    "desde=2026-11-03T09:00&hasta=2026-11-03T10:01",        # futuro
])
def test_rango_invalido_da_400_sin_tocar_bd(cliente, sin_bd, consulta):
    r = cliente.get("/api/detecciones-senal?" + consulta)
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_tabla_sin_crear_devuelve_lista_vacia(cliente, monkeypatch):
    # Production databases that have not run the migration yet
    import psycopg2.errors

    class CursorSinTabla(CursorFalso):
        def execute(self, sql, params=None):
            raise psycopg2.errors.UndefinedTable("relation \"detecciones_senal\" does not exist")

    con = ConexionFalsa()
    con.cursor_falso = CursorSinTabla([])
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: con)
    r = cliente.get("/api/detecciones-senal")
    assert r.status_code == 200
    assert r.get_json() == []
