import os
import sys
import types
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datos_demo  # noqa: E402
import repositorio as repo_mod  # noqa: E402
import servidorweb  # noqa: E402
from repositorio import ErrorBaseDatos, RepositorioDemo, RepositorioRDS  # noqa: E402

# Fixed "now" for the demo data, so tests do not depend on the real clock
AHORA = datetime(2026, 9, 24, 15, 37, 20)


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(repo_mod, "ahora_bogota", lambda: AHORA)
    monkeypatch.setattr(servidorweb, "repositorio", RepositorioDemo())
    return servidorweb.app.test_client()


def _get(cliente, **params):
    return cliente.get("/api/historial-ubicaciones", query_string=params)


# ---------------------------------------------------------------- validation

@pytest.mark.parametrize("params, mensaje", [
    ({"desde": "2026-09-20", "hasta": "2026-09-21 00:00:00"}, "Formato de fecha inválido en 'desde'"),
    ({"desde": "2026-09-20 00:00:00", "hasta": "ayer"}, "Formato de fecha inválido en 'hasta'"),
    ({"desde": "2026-02-30 00:00:00", "hasta": "2026-03-01 00:00:00"}, "Formato de fecha inválido"),
    ({"desde": "2026-09-21 00:00:00", "hasta": "2026-09-20 00:00:00"}, "anterior a 'hasta'"),
    ({"desde": "2026-09-21 00:00:00", "hasta": "2026-09-21 00:00:00"}, "anterior a 'hasta'"),
    ({"desde": "2026-09-21 00:00:00"}, "juntos"),
    ({"hasta": "2026-09-21 00:00:00"}, "juntos"),
    ({"horas": "abc"}, "número entero"),
    ({"horas": "0"}, "entre 1 y 720"),
    ({"horas": "-5"}, "entre 1 y 720"),
    ({"horas": "721"}, "entre 1 y 720"),
    ({"device_id": "x' OR '1'='1"}, "'device_id' inválido"),
])
def test_parametros_invalidos_dan_400_en_espanol(cliente, params, mensaje):
    respuesta = _get(cliente, **params)
    assert respuesta.status_code == 400
    assert mensaje in respuesta.get_json()["error"]


# ------------------------------------------------------------------- results

def test_rango_filtra_y_ordena(cliente):
    datos = _get(cliente, desde="2026-09-17 07:00:00", hasta="2026-09-17 08:30:00").get_json()
    assert datos
    tiempos = [d["timestamp_gps"] for d in datos]
    assert tiempos == sorted(tiempos)
    assert tiempos[0] >= "2026-09-17 07:00:00" and tiempos[-1] <= "2026-09-17 08:30:00"


def test_rango_es_inclusivo_en_ambos_extremos(cliente):
    # The 07:20 trip starts exactly at 07:20:00 (BETWEEN includes both ends)
    datos = _get(cliente, desde="2026-09-17 07:20:00", hasta="2026-09-17 07:20:10").get_json()
    assert [d["timestamp_gps"] for d in datos] == ["2026-09-17 07:20:00", "2026-09-17 07:20:10"]


def test_rango_vacio_devuelve_lista_vacia(cliente):
    datos = _get(cliente, desde="2026-09-10 00:00:00", hasta="2026-09-10 23:59:59").get_json()
    assert datos == []


def test_sin_rango_devuelve_ultimas_24_horas(cliente):
    datos = _get(cliente).get_json()
    corte = (AHORA - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    assert datos[0]["timestamp_gps"] >= corte
    assert datos[-1]["timestamp_gps"] == AHORA.strftime("%Y-%m-%d %H:%M:%S")


def test_horas_cambia_la_ventana(cliente):
    corto = _get(cliente, horas="1").get_json()
    largo = _get(cliente, horas="48").get_json()
    assert 0 < len(corto) < len(largo)


def test_sin_device_id_usa_el_del_ultimo_registro(cliente):
    datos = _get(cliente, desde="2026-09-21 00:00:00", hasta="2026-09-21 23:59:59").get_json()
    assert {d["device_id"] for d in datos} == {datos_demo.DEVICE_PRINCIPAL}


def test_device_id_explicito_filtra(cliente):
    datos = _get(cliente, desde="2026-09-21 00:00:00", hasta="2026-09-21 23:59:59",
                 device_id=datos_demo.DEVICE_SECUNDARIO).get_json()
    assert datos and {d["device_id"] for d in datos} == {datos_demo.DEVICE_SECUNDARIO}


def test_ultima_ubicacion_por_device(cliente):
    principal = cliente.get("/api/ultima-ubicacion").get_json()
    secundario = cliente.get("/api/ultima-ubicacion",
                             query_string={"device_id": datos_demo.DEVICE_SECUNDARIO}).get_json()
    assert principal["device_id"] == datos_demo.DEVICE_PRINCIPAL
    assert principal["timestamp_gps"] == AHORA.strftime("%Y-%m-%d %H:%M:%S")
    assert secundario["device_id"] == datos_demo.DEVICE_SECUNDARIO


def test_device_inexistente_da_404(cliente):
    respuesta = cliente.get("/api/ultima-ubicacion", query_string={"device_id": "no-existe"})
    assert respuesta.status_code == 404


def test_error_de_base_de_datos_da_503_en_json(monkeypatch):
    class RepositorioCaido:
        def ultimo_device_id(self):
            raise ErrorBaseDatos("connection refused")

    monkeypatch.setattr(servidorweb, "repositorio", RepositorioCaido())
    respuesta = servidorweb.app.test_client().get("/api/historial-ubicaciones")
    assert respuesta.status_code == 503
    assert respuesta.get_json() == {"error": "No se pudo consultar la base de datos."}


# ------------------------------------------- SQL of the real RDS repository

class _CursorFalso:
    """Records every execute() instead of talking to PostgreSQL."""

    def __init__(self, registro):
        self.registro = registro

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.registro.append((sql, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


@pytest.fixture
def sql_ejecutado(monkeypatch):
    registro = []
    conexion = types.SimpleNamespace(cursor=lambda cursor_factory=None: _CursorFalso(registro),
                                     close=lambda: None)
    falso = types.ModuleType("psycopg2")
    falso.Error = Exception
    falso.connect = lambda **config: conexion
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = object
    monkeypatch.setitem(sys.modules, "psycopg2", falso)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)
    return registro


def test_rds_rango_usa_between_parametrizado(sql_ejecutado):
    desde, hasta = datetime(2026, 9, 20, 8, 0), datetime(2026, 9, 20, 9, 0)
    RepositorioRDS().historial("disp-1", desde, hasta)
    sql, params = sql_ejecutado[0]
    assert "BETWEEN %s AND %s" in sql
    assert params == ("disp-1", desde, hasta)
    # The values travel as parameters, never inside the SQL text
    assert "2026" not in sql and "disp-1" not in sql


def test_rds_sin_rango_usa_hora_de_bogota(sql_ejecutado):
    RepositorioRDS().historial("disp-1", horas=24)
    sql, params = sql_ejecutado[0]
    assert "NOW() AT TIME ZONE 'America/Bogota'" in sql
    assert "make_interval(hours => %s)" in sql
    assert params == ("disp-1", 24)


def test_rds_ultimo_registro_por_hora_gps(sql_ejecutado):
    RepositorioRDS().ultimo_device_id()
    RepositorioRDS().ultima_ubicacion("disp-1")
    assert all("ORDER BY timestamp_gps DESC" in sql for sql, _ in sql_ejecutado)
    assert sql_ejecutado[1][1] == ("disp-1",)
