import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datos_demo  # noqa: E402
import repositorio as repo_mod  # noqa: E402
import servidorweb  # noqa: E402
from repositorio import RepositorioDemo, RepositorioRDS  # noqa: E402

# Fixed "now" for the demo data (MODO_DEMO-equivalent: in-memory repository)
AHORA = datetime(2026, 9, 24, 15, 37, 20)
UNINORTE = {"lat": "11.0190", "lon": "-74.8505"}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(repo_mod, "ahora_bogota", lambda: AHORA)
    monkeypatch.setattr(servidorweb, "ahora_bogota", lambda: AHORA)
    monkeypatch.setattr(servidorweb, "repositorio", RepositorioDemo())
    return servidorweb.app.test_client()


def _get(cliente, **params):
    return cliente.get("/api/pasos-por-lugar", query_string=params)


@pytest.mark.parametrize("params, mensaje", [
    ({}, "Falta el parámetro 'lat'"),
    ({"lat": "11.0190"}, "Falta el parámetro 'lon'"),
    ({"lat": "abc", "lon": "-74.85"}, "'lat' debe ser un número"),
    ({"lat": "95", "lon": "-74.85"}, "'lat' debe estar entre -90 y 90"),
    ({"lat": "nan", "lon": "-74.85"}, "'lat' debe estar entre"),
    ({"lat": "11", "lon": "-200"}, "'lon' debe estar entre -180 y 180"),
    ({**UNINORTE, "radio": "10"}, "'radio' debe estar entre 20 y 2000"),
    ({**UNINORTE, "radio": "5000"}, "'radio' debe estar entre 20 y 2000"),
    ({**UNINORTE, "radio": "cien"}, "'radio' debe ser un número"),
    ({**UNINORTE, "desde": "2026-09-20 00:00:00"}, "juntos"),
    ({**UNINORTE, "desde": "2026-09-21 00:00:00", "hasta": "2026-09-20 00:00:00"},
     "anterior a 'hasta'"),
    ({**UNINORTE, "desde": "20/09/2026", "hasta": "2026-09-21 00:00:00"}, "Formato de fecha"),
    ({**UNINORTE, "device_id": "a b"}, "'device_id' inválido"),
])
def test_parametros_invalidos_dan_400_en_espanol(cliente, params, mensaje):
    respuesta = _get(cliente, **params)
    assert respuesta.status_code == 400
    assert mensaje in respuesta.get_json()["error"]


def test_respuesta_por_defecto(cliente):
    datos = _get(cliente, **UNINORTE).get_json()
    assert datos["lugar"] == {"lat": 11.019, "lon": -74.8505, "radio": 100}
    # Default period: last 30 days in Bogota time
    assert datos["rango"] == {"desde": "2026-08-25 15:37:20", "hasta": "2026-09-24 15:37:20"}
    assert datos["total"] == len(datos["pasos"]) >= 5
    entradas = [p["entrada"] for p in datos["pasos"]]
    assert entradas == sorted(entradas)
    campos = {"entrada", "salida", "duracion_s", "momento_mas_cercano",
              "distancia_minima_m", "puntos", "tipo"}
    for p in datos["pasos"]:
        assert set(p) == campos
        datetime.strptime(p["entrada"], "%Y-%m-%d %H:%M:%S")


def test_demo_cruce_rapido_detectado_sin_puntos(cliente):
    datos = _get(cliente, **UNINORTE, radio="50",
                 desde="2026-09-19 00:00:00", hasta="2026-09-19 23:59:59").get_json()
    assert datos["total"] == 1
    assert datos["pasos"][0]["puntos"] == 0
    assert datos["pasos"][0]["tipo"] == "paso"


def test_demo_parada_en_uninorte(cliente):
    datos = _get(cliente, **UNINORTE,
                 desde="2026-09-17 00:00:00", hasta="2026-09-17 23:59:59").get_json()
    assert datos["total"] == 1
    assert datos["pasos"][0]["tipo"] == "parada"


def test_otro_dispositivo_no_paso_por_uninorte(cliente):
    datos = _get(cliente, **UNINORTE, device_id=datos_demo.DEVICE_SECUNDARIO).get_json()
    assert datos["total"] == 0 and datos["pasos"] == []


def test_lugar_sin_pasos(cliente):
    datos = _get(cliente, lat="10.5", lon="-75.5").get_json()
    assert datos["total"] == 0


def test_rds_sql_usa_lead_y_parametros(monkeypatch):
    import types

    registro = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            registro.append((sql, params))

        def fetchall(self):
            return []

    falso = types.ModuleType("psycopg2")
    falso.Error = Exception
    falso.connect = lambda **config: types.SimpleNamespace(
        cursor=lambda cursor_factory=None: Cursor(), close=lambda: None)
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = object
    monkeypatch.setitem(sys.modules, "psycopg2", falso)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)

    desde, hasta = datetime(2026, 9, 1), datetime(2026, 9, 2)
    RepositorioRDS().segmentos_cerca("disp-1", desde, hasta, (1.0, 2.0, 3.0, 4.0))
    sql, params = registro[0]
    assert "LEAD(latitud)" in sql and "WINDOW w AS (ORDER BY timestamp_gps)" in sql
    assert "GREATEST(lat, lat_sig) >= %s" in sql
    assert params == ("disp-1", desde, hasta, 1.0, 2.0, 3.0, 4.0)
    assert "disp-1" not in sql and "2026" not in sql
