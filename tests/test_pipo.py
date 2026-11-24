"""Tests for /api/pipo (voice assistant). No real database and no real Groq."""
import os
import sys
from datetime import date, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipo
import servidorweb

PARE_HORA = datetime(2026, 11, 24, 15, 14, 0)

DETECCIONES = [
    {"id": 2, "timestamp_gps": datetime(2026, 11, 24, 15, 20, 5), "senal_texto": "LIMITE 30",
     "senal_tipo": "LIMITE", "senal_valor": 30, "vel_fuente": "GPS", "velocidad": 42.0,
     "cumplimiento": "EXCEDE"},
    {"id": 1, "timestamp_gps": PARE_HORA, "senal_texto": "PARE", "senal_tipo": "PARE",
     "senal_valor": None, "vel_fuente": "GPS", "velocidad": 18.0, "cumplimiento": "NA"},
]

# The car slows down to a stop right after the PARE (about 1 m per second, then still)
RUTA_PARE = [
    {"latitud": 11.0, "longitud": -74.8 + i * 0.00001 * max(0, 3 - i),
     "timestamp_gps": PARE_HORA + timedelta(seconds=i)}
    for i in range(6)
]


class CursorFalso:
    def __init__(self):
        self.ejecutadas = []
        self.ultimo = None
        self.connection = self

    def rollback(self):
        pass

    def execute(self, sql, params=None):
        self.ejecutadas.append((sql, params))
        self.ultimo = sql

    def fetchone(self):
        if "SELECT device_id FROM alias_dispositivos" in self.ultimo:
            # Only car A01 (numero 1) exists
            return {"device_id": "abc-123"} if self.ejecutadas[-1][1] == (1,) else None
        return {"numero": 1} if "alias_dispositivos" in self.ultimo else None

    def fetchall(self):
        if "WINDOW w" in self.ultimo:
            return [{"dia": date(2026, 11, 24), "desde": datetime(2026, 11, 24, 7, 5),
                     "hasta": datetime(2026, 11, 24, 18, 40), "km": 23.46, "vel_max": 61.2}]
        if "GROUP BY 1, 2" in self.ultimo:
            return [{"dia": date(2026, 11, 24), "senal_tipo": "PARE", "total": 3, "excesos": 0}]
        if "FROM alias_dispositivos a" in self.ultimo:
            return [{"numero": 1, "ultimo": datetime(2026, 11, 24, 18, 40)},
                    {"numero": 2, "ultimo": None}]
        if "GROUP BY senal_tipo" in self.ultimo:
            return [{"senal_tipo": "LIMITE", "total": 5, "excesos": 2, "vel_max": 55.0}]
        if "FROM detecciones_senal" in self.ultimo:
            return [dict(d) for d in DETECCIONES]
        if "FROM ubicaciones" in self.ultimo:
            return [dict(p) for p in RUTA_PARE]
        return []

    def close(self):
        pass


class ConexionFalsa:
    def __init__(self):
        self.cursor_falso = CursorFalso()

    def cursor(self, **kwargs):
        return self.cursor_falso

    def close(self):
        pass


class RespuestaGroq:
    def __init__(self, texto):
        self.texto = texto

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self.texto}}]}


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "clave-de-prueba")
    con = ConexionFalsa()
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: con)
    llamadas = []

    def post_falso(url, headers=None, json=None, timeout=None):
        llamadas.append(json)
        return RespuestaGroq("**Sí**, paraste en el pare.\n- Pero ojo con el límite de 30.")

    monkeypatch.setattr(pipo.requests, "post", post_falso)
    c = servidorweb.app.test_client()
    c.llamadas = llamadas
    return c


def pedir(cliente, **extra):
    cuerpo = {"device_id": "abc-123", "pregunta": "¿cumplí el pare?",
              "contexto": {"velocidad_kmh": 40, "limite_kmh": 30}}
    cuerpo.update(extra)
    return cliente.post("/api/pipo", json=cuerpo)


def test_responde_limpio_para_voz(cliente):
    r = pedir(cliente)
    assert r.status_code == 200
    assert r.get_json()["respuesta"] == "Sí, paraste en el pare. Pero ojo con el límite de 30."


def test_le_pasa_a_groq_los_datos_del_vehiculo(cliente):
    pedir(cliente)
    datos = cliente.llamadas[0]["messages"][1]["content"]
    assert "Vehículo: A01" in datos
    assert "LIMITE 30, iba a 42 km/h, EXCEDIÓ el límite" in datos
    assert "PARE, iba a 18 km/h, SÍ paró" in datos
    assert "LIMITE: 5 (2 con exceso de velocidad, máximo 55 km/h)" in datos
    assert "ESTÁ EXCEDIENDO el límite por 10 km/h" in datos
    assert cliente.llamadas[0]["messages"][2]["content"] == "¿cumplí el pare?"


def test_gpt_oss_piensa_poco(cliente):
    pedir(cliente)
    assert cliente.llamadas[0]["model"] == pipo.MODELO_POR_DEFECTO
    assert cliente.llamadas[0]["reasoning_effort"] == "low"


@pytest.mark.parametrize("cuerpo", [
    {"device_id": "abc", "pregunta": ""},
    {"device_id": "no valido!", "pregunta": "hola"},
    {"pregunta": "hola"},
])
def test_rechaza_peticiones_malas(cliente, cuerpo):
    assert cliente.post("/api/pipo", json=cuerpo).status_code == 400


def test_desde_la_web_por_alias(cliente):
    r = cliente.post("/api/pipo", json={"vehiculo": "A01", "origen": "web",
                                        "pregunta": "¿cumplió el pare?", "contexto": {}})
    assert r.status_code == 200
    sistema = cliente.llamadas[0]["messages"][0]["content"]
    datos = cliente.llamadas[0]["messages"][1]["content"]
    assert "página web" in sistema
    assert "Vehículo: A01" in datos and "PARE" in datos
    assert "último dato del carro" in datos
    assert "24/11: de 07:05 a 18:40, 23.5 km, velocidad máxima unos 61 km/h" in datos
    assert "Señales: PARE 3" in datos
    assert "A01 (último dato 24/11 18:40); A02 (último dato nunca)" in datos


def test_desde_el_celular_no_manda_lo_de_la_web(cliente):
    assert pedir(cliente).status_code == 200
    datos = cliente.llamadas[0]["messages"][1]["content"]
    assert "Recorridos de los últimos" not in datos
    assert "página web" not in cliente.llamadas[0]["messages"][0]["content"]


def test_desde_la_web_alias_malo_o_inexistente(cliente):
    malo = cliente.post("/api/pipo", json={"vehiculo": "zz!", "pregunta": "hola"})
    assert malo.status_code == 400
    otro = cliente.post("/api/pipo", json={"vehiculo": "A02", "pregunta": "hola"})
    assert otro.status_code == 404
    assert otro.get_json()["respuesta"]
    assert cliente.llamadas == []


def test_sin_clave_de_groq(cliente, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY")
    r = pedir(cliente)
    assert r.status_code == 503
    assert "respuesta" in r.get_json()


def test_groq_caido_da_respuesta_hablable(cliente, monkeypatch):
    def falla(*a, **k):
        raise ConnectionError("sin red")
    monkeypatch.setattr(pipo.requests, "post", falla)
    r = pedir(cliente)
    assert r.status_code == 502
    assert r.get_json()["respuesta"]


def test_pare_sin_frenar():
    ruta = [{"latitud": 11.0, "longitud": -74.8 + i * 0.0001,  # ~11 m/s = ~39 km/h
             "timestamp_gps": PARE_HORA + timedelta(seconds=i)} for i in range(5)]

    class C(CursorFalso):
        def fetchall(self):
            return ruta

    v = pipo.evaluar_pare(C(), "abc", PARE_HORA)
    assert v > 30
    texto = pipo.linea_deteccion(DETECCIONES[1], v)
    assert "NO paró" in texto
