import os
import sys
from datetime import datetime

import psycopg2
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import servidorweb


def test_app_existe():
    assert servidorweb.app is not None


def test_ruta_api_registrada():
    rutas = [str(regla) for regla in servidorweb.app.url_map.iter_rules()]
    assert any("api/ultima-ubicacion" in ruta for ruta in rutas)


# Fake DB connection: records what was executed and returns canned rows,
# so no test ever needs a real PostgreSQL.
class CursorFalso:
    def __init__(self, filas):
        self.filas = filas
        self.ejecutadas = []

    def execute(self, sql, params=None):
        self.ejecutadas.append((sql, params))

    def fetchall(self):
        return [dict(f) for f in self.filas]

    def fetchone(self):
        return dict(self.filas[0]) if self.filas else None

    def close(self):
        pass


class ConexionFalsa:
    def __init__(self, filas=()):
        self.cursor_falso = CursorFalso(filas)
        self.cerrada = False

    def cursor(self, **kwargs):
        return self.cursor_falso

    def close(self):
        self.cerrada = True


AHORA = datetime(2026, 9, 25, 10, 5, 20)


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
    # Any attempt to open a connection fails the test
    def prohibido():
        raise AssertionError("Must not open a DB connection for invalid parameters")
    monkeypatch.setattr(servidorweb, "obtener_conexion", prohibido)


# ---------- /api/historial-ubicaciones: validation of desde/hasta ----------

def test_historial_rango_valido(cliente, conexion):
    r = cliente.get("/api/historial-ubicaciones?desde=2026-09-25 08:00:00&hasta=2026-09-25 09:30:59")
    assert r.status_code == 200
    assert r.get_json()[0]["timestamp_gps"] == "2026-09-25 09:00:00"
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params == (datetime(2026, 9, 25, 8, 0, 0), datetime(2026, 9, 25, 9, 30, 59))


def test_historial_acepta_formato_datetime_local(cliente, conexion):
    # <input type="datetime-local"> sends "YYYY-MM-DDTHH:MM" (no seconds)
    r = cliente.get("/api/historial-ubicaciones?desde=2026-09-25T08:00&hasta=2026-09-25T09:30")
    assert r.status_code == 200
    _, params = conexion.cursor_falso.ejecutadas[0]
    assert params[0] == datetime(2026, 9, 25, 8, 0, 0)
    # "hasta" without seconds covers the whole minute
    assert params[1] == datetime(2026, 9, 25, 9, 30, 59, 999999)


def test_historial_hasta_en_el_minuto_actual_no_es_futuro(cliente, conexion):
    # now is 10:05:20; "hasta" = 10:05 -> 10:05:59 must still be accepted
    r = cliente.get("/api/historial-ubicaciones?desde=2026-09-25T09:00&hasta=2026-09-25T10:05")
    assert r.status_code == 200


@pytest.mark.parametrize("desde,hasta", [
    ("ayer", "2026-09-25 09:00:00"),
    ("2026-09-25 08:00:00", "no-es-fecha"),
    ("2026-13-45 08:00:00", "2026-09-25 09:00:00"),
    ("2026-09-25", "2026-09-25 09:00:00"),
])
def test_historial_formato_invalido_da_400(cliente, sin_bd, desde, hasta):
    r = cliente.get("/api/historial-ubicaciones", query_string={"desde": desde, "hasta": hasta})
    assert r.status_code == 400
    assert "Formato de fecha inválido" in r.get_json()["error"]


def test_historial_hasta_anterior_a_desde_da_400(cliente, sin_bd):
    r = cliente.get("/api/historial-ubicaciones?desde=2026-09-25T09:00&hasta=2026-09-25T08:00")
    assert r.status_code == 400
    assert "anterior" in r.get_json()["error"]


def test_historial_hasta_futuro_da_400(cliente, sin_bd):
    r = cliente.get("/api/historial-ubicaciones?desde=2026-09-25T09:00&hasta=2026-09-25T10:06")
    assert r.status_code == 400
    assert "futuras" in r.get_json()["error"]


def test_historial_desde_futuro_da_400(cliente, sin_bd):
    r = cliente.get("/api/historial-ubicaciones?desde=2026-09-26T00:00&hasta=2026-09-26T01:00")
    assert r.status_code == 400
    assert "futuras" in r.get_json()["error"]


@pytest.mark.parametrize("consulta", ["desde=2026-09-25T09:00", "hasta=2026-09-25T09:00"])
def test_historial_par_incompleto_da_400(cliente, sin_bd, consulta):
    r = cliente.get("/api/historial-ubicaciones?" + consulta)
    assert r.status_code == 400
    assert "juntos" in r.get_json()["error"]


def test_historial_sin_rango_sigue_usando_ultimas_horas(cliente, conexion):
    r = cliente.get("/api/historial-ubicaciones")
    assert r.status_code == 200
    sql, params = conexion.cursor_falso.ejecutadas[0]
    assert "NOW()" in sql
    assert params == (24,)


# ---------- database errors: JSON instead of an HTML traceback ----------

RUTAS_BD = [
    "/api/ultima-ubicacion",
    "/api/historial-ubicaciones",
]


@pytest.mark.parametrize("ruta", RUTAS_BD)
def test_bd_caida_da_503_json(cliente, monkeypatch, ruta):
    def falla():
        raise psycopg2.OperationalError("connection refused")
    monkeypatch.setattr(servidorweb, "obtener_conexion", falla)

    r = cliente.get(ruta)
    assert r.status_code == 503
    assert r.is_json
    assert "base de datos" in r.get_json()["error"]
    # nothing internal leaks to the client
    assert "connection refused" not in r.get_json()["error"]


@pytest.mark.parametrize("ruta", RUTAS_BD)
def test_error_de_consulta_da_500_json_y_cierra_conexion(cliente, monkeypatch, ruta):
    con = ConexionFalsa()

    def execute_falla(sql, params=None):
        raise psycopg2.ProgrammingError("relation does not exist")
    con.cursor_falso.execute = execute_falla
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: con)

    r = cliente.get(ruta)
    assert r.status_code == 500
    assert r.is_json
    assert "error" in r.get_json()
    assert con.cerrada


def test_conexion_se_cierra_en_caso_exitoso(cliente, conexion):
    cliente.get("/api/historial-ubicaciones")
    assert conexion.cerrada


def test_ultima_ubicacion_sin_datos_da_404_json(cliente, monkeypatch):
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: ConexionFalsa([]))
    r = cliente.get("/api/ultima-ubicacion")
    assert r.status_code == 404
    assert r.get_json()["error"] == "No hay ubicaciones registradas"


# ---------- /api/lugar-visitado ----------

CAJA = "lat_min=10.9&lat_max=11.0&lon_min=-74.9&lon_max=-74.7"


@pytest.mark.parametrize("existe", [True, False])
def test_lugar_visitado_devuelve_si_existe(cliente, monkeypatch, existe):
    con = ConexionFalsa([{"visitado": existe}])
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: con)

    r = cliente.get("/api/lugar-visitado?" + CAJA)

    assert r.status_code == 200
    assert r.get_json() == {"visitado": existe}
    assert con.cerrada


def test_lugar_visitado_consulta_historico_completo_con_exists(cliente, monkeypatch):
    con = ConexionFalsa([{"visitado": True}])
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: con)

    cliente.get("/api/lugar-visitado?" + CAJA)

    sql, params = con.cursor_falso.ejecutadas[0]
    assert "EXISTS" in sql and "LIMIT 1" in sql
    # whole history: no date condition at all
    assert "timestamp_gps" not in sql
    assert params == (10.9, 11.0, -74.9, -74.7)


def test_lugar_visitado_acepta_device_id(cliente, monkeypatch):
    con = ConexionFalsa([{"visitado": False}])
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: con)

    cliente.get("/api/lugar-visitado?" + CAJA + "&device_id=abc")

    sql, params = con.cursor_falso.ejecutadas[0]
    assert "device_id = %s" in sql
    assert params[-1] == "abc"


@pytest.mark.parametrize("consulta,fragmento", [
    ("lat_max=11&lon_min=-74.9&lon_max=-74.7", "lat_min"),
    ("lat_min=10.9&lat_max=11&lon_min=-74.9", "lon_max"),
    ("lat_min=abc&lat_max=11&lon_min=-74.9&lon_max=-74.7", "lat_min"),
    ("lat_min=nan&lat_max=11&lon_min=-74.9&lon_max=-74.7", "lat_min"),
    ("lat_min=10.9&lat_max=inf&lon_min=-74.9&lon_max=-74.7", "lat_max"),
    ("lat_min=10.9&lat_max=91&lon_min=-74.9&lon_max=-74.7", "latitud"),
    ("lat_min=-91&lat_max=11&lon_min=-74.9&lon_max=-74.7", "latitud"),
    ("lat_min=10.9&lat_max=11&lon_min=-74.9&lon_max=181", "longitud"),
    ("lat_min=11&lat_max=10.9&lon_min=-74.9&lon_max=-74.7", "mínimos"),
    ("lat_min=10.9&lat_max=11&lon_min=-74.7&lon_max=-74.9", "mínimos"),
])
def test_lugar_visitado_parametros_invalidos_dan_400(cliente, sin_bd, consulta, fragmento):
    r = cliente.get("/api/lugar-visitado?" + consulta)
    assert r.status_code == 400
    assert fragmento in r.get_json()["error"]


def test_lugar_visitado_bd_caida_da_503_json(cliente, monkeypatch):
    def falla():
        raise psycopg2.OperationalError("connection refused")
    monkeypatch.setattr(servidorweb, "obtener_conexion", falla)

    r = cliente.get("/api/lugar-visitado?" + CAJA)
    assert r.status_code == 503
    assert "error" in r.get_json()
