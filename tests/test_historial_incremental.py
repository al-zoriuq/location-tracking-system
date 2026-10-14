"""Tests for the incremental history (despues_de), the widened range
(margen_horas) and the Bogota-time "last N hours" window."""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import servidorweb

AHORA = datetime(2026, 9, 25, 10, 5, 20)
RANGO = "desde=2026-09-25 08:00:00&hasta=2026-09-25 09:30:59"


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
    con = ConexionFalsa([
        {"ip_origen": "1.2.3.4", "latitud": 10.9, "longitud": -74.8,
         "timestamp_gps": datetime(2026, 9, 25, 9, 0, 0)},
    ])
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: con)
    return con


@pytest.fixture
def sin_bd(monkeypatch):
    def prohibido():
        raise AssertionError("No debe abrir conexion a la BD con parametros invalidos")
    monkeypatch.setattr(servidorweb, "obtener_conexion", prohibido)


# ---------- despues_de ----------

def test_despues_de_es_mayor_estricto_y_sin_limite_superior(cliente, conexion):
    r = cliente.get("/api/historial-ubicaciones?despues_de=2026-09-25 09:00:00")
    assert r.status_code == 200
    sql, params = conexion.cursor_falso.ejecutadas[0]
    assert "timestamp_gps > %s" in sql
    assert "BETWEEN" not in sql
    assert params == (datetime(2026, 9, 25, 9, 0, 0),)


def test_despues_de_acepta_device_id(cliente, conexion):
    cliente.get("/api/historial-ubicaciones?despues_de=2026-09-25 09:00:00&device_id=abc")
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params == (datetime(2026, 9, 25, 9, 0, 0), "abc")


def test_despues_de_formato_invalido_da_400(cliente, sin_bd):
    r = cliente.get("/api/historial-ubicaciones?despues_de=ayer")
    assert r.status_code == 400
    assert "despues_de" in r.get_json()["error"]


def test_despues_de_futuro_no_es_error(cliente, conexion):
    # An open lower bound in the future just returns nothing: not a bad request
    r = cliente.get("/api/historial-ubicaciones?despues_de=2026-09-25 23:00:00")
    assert r.status_code == 200


# ---------- margen_horas ----------

def test_margen_amplia_el_rango_y_se_recorta_a_ahora(cliente, conexion):
    r = cliente.get(f"/api/historial-ubicaciones?{RANGO}&margen_horas=72")
    assert r.status_code == 200
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params == (datetime(2026, 9, 22, 8, 0, 0), AHORA)


def test_margen_se_limita_al_maximo(cliente, conexion):
    cliente.get(f"/api/historial-ubicaciones?{RANGO}&margen_horas=100000")
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params[0] == datetime(2026, 9, 18, 8, 0, 0)


def test_margen_no_afecta_un_rango_sin_espacio_a_la_derecha(cliente, conexion):
    # hasta is already "now": widening cannot push it past the server clock
    cliente.get("/api/historial-ubicaciones?desde=2026-09-25 08:00:00&hasta=2026-09-25 10:05:00&margen_horas=5")
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params == (datetime(2026, 9, 25, 3, 0, 0), AHORA)


def test_margen_sin_rango_se_ignora(cliente, conexion):
    r = cliente.get("/api/historial-ubicaciones?horas=6&margen_horas=72")
    assert r.status_code == 200
    sql, params = conexion.cursor_falso.ejecutadas[0]
    assert "NOW()" in sql
    assert params == (6,)


def test_par_incompleto_sigue_dando_400_con_margen(cliente, sin_bd):
    r = cliente.get("/api/historial-ubicaciones?desde=2026-09-25 08:00&margen_horas=72")
    assert r.status_code == 400
    assert "juntos" in r.get_json()["error"]


def test_margen_no_evita_la_validacion_de_fechas_futuras(cliente, sin_bd):
    r = cliente.get("/api/historial-ubicaciones?desde=2026-09-25 08:00&hasta=2026-09-25 23:00&margen_horas=72")
    assert r.status_code == 400
    assert "futuras" in r.get_json()["error"]


# ---------- ventana de "ultimas N horas" en hora de Bogota ----------

def test_ultimas_horas_se_calcula_en_hora_de_bogota(cliente, conexion):
    cliente.get("/api/historial-ubicaciones?horas=24")
    sql, _ = conexion.cursor_falso.ejecutadas[0]
    assert "AT TIME ZONE 'America/Bogota'" in sql


def test_ultimas_horas_con_device_id_tambien_usa_hora_de_bogota(cliente, conexion):
    cliente.get("/api/historial-ubicaciones?horas=24&device_id=abc")
    sql, params = conexion.cursor_falso.ejecutadas[0]
    assert "AT TIME ZONE 'America/Bogota'" in sql
    assert params == (24, "abc")
