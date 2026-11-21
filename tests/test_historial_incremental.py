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


# ---------- intervalo_s (one point per block of N seconds) ----------

def test_sin_intervalo_la_consulta_no_cambia(cliente, conexion):
    cliente.get("/api/historial-ubicaciones?horas=24&device_id=abc")
    sql, _ = conexion.cursor_falso.ejecutadas[0]
    assert "DISTINCT ON" not in sql


@pytest.mark.parametrize("consulta, params", [
    ("horas=24&device_id=abc", (24, "abc")),
    ("horas=24", (24,)),
    # despues_de is moved back to the start of its block (see the test below)
    ("despues_de=2026-09-25 09:00:00&device_id=abc", (datetime(2026, 9, 25, 8, 59, 59, 999999), "abc")),
    ("despues_de=2026-09-25 09:00:00", (datetime(2026, 9, 25, 8, 59, 59, 999999),)),
    (RANGO + "&device_id=abc", (datetime(2026, 9, 25, 8, 0, 0), datetime(2026, 9, 25, 9, 30, 59), "abc")),
    (RANGO, (datetime(2026, 9, 25, 8, 0, 0), datetime(2026, 9, 25, 9, 30, 59))),
])
def test_intervalo_muestrea_todas_las_variantes(cliente, conexion, consulta, params):
    r = cliente.get(f"/api/historial-ubicaciones?{consulta}&intervalo_s=10")
    assert r.status_code == 200
    sql, params_sql = conexion.cursor_falso.ejecutadas[0]
    assert "DISTINCT ON (FLOOR(EXTRACT(EPOCH FROM t.timestamp_gps) / 10))" in sql
    # The first point of each block, and the result in chronological order
    assert "t.timestamp_gps ASC" in sql
    assert sql.rstrip().endswith("ORDER BY timestamp_gps ASC")
    # The original query is wrapped, not changed: same parameters
    assert params_sql == params


def test_intervalo_conserva_las_columnas(cliente, conexion):
    r = cliente.get("/api/historial-ubicaciones?horas=24&device_id=abc&intervalo_s=10")
    fila = r.get_json()[0]
    assert set(fila) == {"ip_origen", "latitud", "longitud", "timestamp_gps"}


@pytest.mark.parametrize("valor", ["0", "301", "-5", "diez", "1.5", ""])
def test_intervalo_invalido_da_400(cliente, sin_bd, valor):
    r = cliente.get(f"/api/historial-ubicaciones?horas=24&intervalo_s={valor}")
    assert r.status_code == 400
    assert "intervalo_s" in r.get_json()["error"]


@pytest.mark.parametrize("valor", ["1", "300"])
def test_intervalo_en_los_limites_es_valido(cliente, conexion, valor):
    r = cliente.get(f"/api/historial-ubicaciones?horas=24&intervalo_s={valor}")
    assert r.status_code == 200


def test_intervalo_alinea_despues_de_al_inicio_del_bloque(cliente, conexion):
    cliente.get("/api/historial-ubicaciones?despues_de=2026-09-25 09:00:27&device_id=abc&intervalo_s=10")
    sql, params = conexion.cursor_falso.ejecutadas[0]
    assert "timestamp_gps > %s" in sql
    # 09:00:27 belongs to the block 09:00:20-09:00:29: the whole block is included
    assert params == (datetime(2026, 9, 25, 9, 0, 19, 999999), "abc")


def test_sin_intervalo_despues_de_no_se_alinea(cliente, conexion):
    cliente.get("/api/historial-ubicaciones?despues_de=2026-09-25 09:00:27&device_id=abc")
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params == (datetime(2026, 9, 25, 9, 0, 27), "abc")
