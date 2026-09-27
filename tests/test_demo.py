import math
import os
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import datos_demo  # noqa: E402
import servidorweb  # noqa: E402
from datos_demo import DEVICE_PRINCIPAL, UNINORTE, distancia_m  # noqa: E402
from repositorio import RepositorioDemo  # noqa: E402

# Fixed "now" so every test is reproducible regardless of the real clock
AHORA = datetime(2026, 9, 24, 15, 37, 20)


@pytest.fixture
def puntos():
    return datos_demo.puntos_demo(AHORA)


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(servidorweb, "repositorio", RepositorioDemo())
    return servidorweb.app.test_client()


def _principal(puntos):
    return [p for p in puntos if p["device_id"] == DEVICE_PRINCIPAL]


def _dist_segmento_m(centro, a, b):
    """Distance from centro to segment ab, in local meters (equirectangular)."""
    cos0 = math.cos(math.radians(centro[0]))

    def xy(p):
        return ((p[1] - centro[1]) * datos_demo.M_POR_GRADO * cos0,
                (p[0] - centro[0]) * datos_demo.M_POR_GRADO)

    (ax, ay), (bx, by) = xy(a), xy(b)
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx, ay + t * dy)


def _latlon(p):
    return (p["latitud"], p["longitud"])


def test_datos_deterministicos():
    assert datos_demo.puntos_demo(AHORA) == datos_demo.puntos_demo(AHORA)


def test_timestamps_en_formato_de_la_base(puntos):
    inicio = AHORA - timedelta(days=10)
    for p in puntos:
        t = p["timestamp_gps"]
        assert t.tzinfo is None and t.microsecond == 0
        assert inicio <= t <= AHORA
    tiempos = [p["timestamp_gps"] for p in puntos]
    assert tiempos == sorted(tiempos)


def test_al_menos_cuatro_dias_pasando_por_uninorte(puntos):
    cerca = [p for p in _principal(puntos) if distancia_m(_latlon(p), UNINORTE) <= 100]
    dias = {p["timestamp_gps"].date() for p in cerca}
    horas = {p["timestamp_gps"].hour for p in cerca}
    assert len(dias) >= 4
    assert len(horas) >= 4


def test_parada_de_ocho_minutos_en_uninorte(puntos):
    mejor = timedelta(0)
    inicio = None
    for p in _principal(puntos):
        if distancia_m(_latlon(p), UNINORTE) < 40:
            inicio = inicio or p["timestamp_gps"]
            mejor = max(mejor, p["timestamp_gps"] - inicio)
        else:
            inicio = None
    assert timedelta(minutes=7, seconds=30) <= mejor <= timedelta(minutes=9)


def test_cruce_rapido_sin_puntos_dentro_de_50_m(puntos):
    cruce_dia = (AHORA - timedelta(days=5)).date()
    viaje = [p for p in _principal(puntos) if p["timestamp_gps"].date() == cruce_dia]
    assert viaje
    assert min(distancia_m(_latlon(p), UNINORTE) for p in viaje) > 50
    assert min(_dist_segmento_m(UNINORTE, _latlon(a), _latlon(b))
               for a, b in zip(viaje, viaje[1:])) < 5


def test_hay_saltos_imposibles(puntos):
    principal = _principal(puntos)
    saltos = 0
    for a, b in zip(principal, principal[1:]):
        dt = (b["timestamp_gps"] - a["timestamp_gps"]).total_seconds()
        if dt and distancia_m(_latlon(a), _latlon(b)) / dt * 3.6 > 180:
            saltos += 1
    # Each glitch shows up twice: jumping away and jumping back
    assert saltos >= 2


def test_velocidades_realistas_fuera_de_saltos(puntos):
    principal = _principal(puntos)
    for a, b in zip(principal, principal[1:]):
        dt = (b["timestamp_gps"] - a["timestamp_gps"]).total_seconds()
        if dt == datos_demo.INTERVALO_S:
            v = distancia_m(_latlon(a), _latlon(b)) / dt * 3.6
            assert v < 70 or v > 180  # realistic, or one of the injected glitches


def test_vivo_depende_solo_del_reloj():
    antes = datos_demo.puntos_demo(AHORA)
    despues = datos_demo.puntos_demo(AHORA + timedelta(seconds=10))
    # Ten seconds later: exactly one new live point, and the past is unchanged
    assert despues[:-1] == antes
    assert despues[-1]["timestamp_gps"] == antes[-1]["timestamp_gps"] + timedelta(seconds=10)
    assert antes[-1]["device_id"] == DEVICE_PRINCIPAL


def test_sesiones_en_vivo_consecutivas_separadas_mas_de_1_km():
    # 13:58 is the last sample of the 12:00 session; 14:00 starts the next one
    puntos = _principal(datos_demo.puntos_demo(datetime(2026, 9, 24, 14, 0, 0)))
    a, b = puntos[-2], puntos[-1]
    assert b["timestamp_gps"] - a["timestamp_gps"] == timedelta(minutes=2)
    assert distancia_m(_latlon(a), _latlon(b)) > 1000


def test_hay_un_segundo_dispositivo(puntos):
    assert {p["device_id"] for p in puntos} == {DEVICE_PRINCIPAL, datos_demo.DEVICE_SECUNDARIO}


def test_endpoint_ultima_ubicacion_demo(cliente):
    respuesta = cliente.get("/api/ultima-ubicacion")
    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert datos["device_id"] == DEVICE_PRINCIPAL
    datetime.strptime(datos["timestamp_gps"], "%Y-%m-%d %H:%M:%S")


def test_endpoint_historial_demo_ordenado(cliente):
    datos = cliente.get("/api/historial-ubicaciones").get_json()
    assert datos
    tiempos = [d["timestamp_gps"] for d in datos]
    assert tiempos == sorted(tiempos)


def test_modo_demo_no_necesita_psycopg2_ni_certificado(tmp_path):
    # Runs in a clean interpreter where importing psycopg2 fails on purpose,
    # from a folder without global-bundle.pem.
    codigo = (
        "import sys; sys.modules['psycopg2'] = None; "
        f"sys.path.insert(0, {RAIZ!r}); "
        "import servidorweb; "
        "r = servidorweb.app.test_client().get('/api/ultima-ubicacion'); "
        "assert r.status_code == 200, r.status_code; print('ok')"
    )
    entorno = dict(os.environ, MODO_DEMO="1")
    resultado = subprocess.run([sys.executable, "-c", codigo], cwd=tmp_path,
                               env=entorno, capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr
    assert "ok" in resultado.stdout


def _inicio_sesion_actual(puntos):
    """Timestamp where the last live session starts (after the last > 60 s gap)."""
    principal = _principal(puntos)
    inicio = principal[0]["timestamp_gps"]
    for a, b in zip(principal, principal[1:]):
        if (b["timestamp_gps"] - a["timestamp_gps"]).total_seconds() > 60:
            inicio = b["timestamp_gps"]
    return inicio


def test_sin_variable_las_sesiones_empiezan_en_hora_par(monkeypatch):
    monkeypatch.delenv("DEMO_INICIO_VIVO", raising=False)
    assert _inicio_sesion_actual(datos_demo.puntos_demo(AHORA)) == datetime(2026, 9, 24, 14, 0, 0)


def test_demo_inicio_vivo_arranca_una_ruta_en_ese_momento(monkeypatch):
    inicio = AHORA - timedelta(minutes=5)  # 15:32:20
    monkeypatch.setenv("DEMO_INICIO_VIVO", inicio.strftime("%Y-%m-%d %H:%M:%S"))
    puntos = datos_demo.puntos_demo(AHORA)
    assert _inicio_sesion_actual(puntos) == inicio
    # One point every 10 s from the start up to now: 5 min -> 31 points
    en_vivo = [p for p in _principal(puntos) if p["timestamp_gps"] >= inicio]
    assert len(en_vivo) == 31


def test_demo_inicio_vivo_acepta_comillas(monkeypatch):
    monkeypatch.setenv("DEMO_INICIO_VIVO", '"2026-09-24 15:30:00"')
    assert _inicio_sesion_actual(datos_demo.puntos_demo(AHORA)) == datetime(2026, 9, 24, 15, 30, 0)


def test_demo_inicio_vivo_invalido_usa_el_origen_por_defecto(monkeypatch):
    monkeypatch.setenv("DEMO_INICIO_VIVO", "mañana temprano")
    assert _inicio_sesion_actual(datos_demo.puntos_demo(AHORA)) == datetime(2026, 9, 24, 14, 0, 0)
