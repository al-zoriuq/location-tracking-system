"""Tests for the vehicle aliases (A01, A02... B01): format, assignment and
that no API response ever includes a device_id."""
import os
import sys
from datetime import datetime

import psycopg2.errors
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import servidorweb  # noqa: E402


# ---------- format ----------

@pytest.mark.parametrize("numero, alias", [
    (1, "A01"), (2, "A02"), (99, "A99"), (100, "B01"), (198, "B99"),
    (199, "C01"), (2574, "Z99"), (2575, "AA01"),
])
def test_alias_de_numero_y_vuelta(numero, alias):
    assert servidorweb.alias_de_numero(numero) == alias
    assert servidorweb.numero_de_alias(alias) == numero


def test_numero_de_alias_acepta_minusculas_y_espacios():
    assert servidorweb.numero_de_alias(" a07 ") == 7


@pytest.mark.parametrize("texto", ["", "A", "A1", "A001", "A00", "01", "1A", "Á01", "A-1", None])
def test_numero_de_alias_invalido(texto):
    assert servidorweb.numero_de_alias(texto) is None


def test_los_alias_ordenan_igual_que_sus_numeros():
    alias = [servidorweb.alias_de_numero(n) for n in range(1, 2575)]
    assert alias == sorted(alias)
    assert len(set(alias)) == len(alias)


# ---------- fake database with an alias table ----------

class BD:
    def __init__(self, ubicaciones, alias=None, tabla_alias=True):
        # ubicaciones: [(id, device_id, timestamp_gps)]
        self.ubicaciones = ubicaciones
        self.alias = dict(alias or {})  # device_id -> numero
        self.siguiente = max(self.alias.values(), default=0) + 1
        self.tabla_alias = tabla_alias
        self.ejecutadas = []
        self.commits = 0


class Cursor:
    def __init__(self, bd, conexion):
        self.bd = bd
        self.connection = conexion
        self.filas = []

    def execute(self, sql, params=None):
        bd = self.bd
        bd.ejecutadas.append((sql, params))
        if "alias_dispositivos" in sql and not bd.tabla_alias:
            raise psycopg2.errors.UndefinedTable('relation "alias_dispositivos" does not exist')
        if "INSERT INTO alias_dispositivos" in sql:
            pedidos = set(params[0])
            primero = {}
            for id_, dev, _ in bd.ubicaciones:
                if dev in pedidos and dev not in bd.alias:
                    primero[dev] = min(primero.get(dev, id_), id_)
            for dev in sorted(primero, key=primero.get):
                bd.alias[dev] = bd.siguiente
                bd.siguiente += 1
        elif "FROM alias_dispositivos WHERE numero" in sql:
            dev = next((d for d, n in bd.alias.items() if n == params[0]), None)
            self.filas = [{"device_id": dev}] if dev else []
        elif "DISTINCT ON (u.device_id)" in sql or "LIMIT 1" in sql and "LEFT JOIN alias" in sql:
            ultimos = {}
            for id_, dev, ts in bd.ubicaciones:
                if params and dev != params[0]:
                    continue
                if dev not in ultimos or (ts, id_) > ultimos[dev][:2]:
                    ultimos[dev] = (ts, id_, dev)
            filas = sorted(ultimos.values(), key=lambda x: x[2])
            if "LIMIT 1" in sql:
                filas = sorted(ultimos.values(), key=lambda x: x[1])[-1:]
            self.filas = [{
                "device_id": dev, "numero": bd.alias.get(dev), "ip_origen": "1.2.3.4",
                "latitud": 10.9, "longitud": -74.8, "timestamp_gps": ts, "timestamp_recepcion": ts,
            } for ts, _, dev in filas]
        else:
            self.filas = [{"ip_origen": "1.2.3.4", "latitud": 10.9, "longitud": -74.8,
                           "timestamp_gps": datetime(2026, 9, 25, 9, 0, 0), "visitado": True}]

    def fetchall(self):
        return [dict(f) for f in self.filas]

    def fetchone(self):
        return dict(self.filas[0]) if self.filas else None

    def close(self):
        pass


class Conexion:
    def __init__(self, bd):
        self.bd = bd

    def cursor(self, **kwargs):
        return Cursor(self.bd, self)

    def commit(self):
        self.bd.commits += 1

    def close(self):
        pass


T = datetime(2026, 9, 25, 9, 0, 0)


@pytest.fixture
def cliente(monkeypatch):
    servidorweb._cache_alias.clear()
    monkeypatch.setattr(servidorweb, "ahora_local", lambda: datetime(2026, 9, 25, 10, 0, 0))
    yield servidorweb.app.test_client()
    servidorweb._cache_alias.clear()


def usar(monkeypatch, bd):
    monkeypatch.setattr(servidorweb, "obtener_conexion", lambda: Conexion(bd))
    return bd


# ---------- /api/dispositivos ----------

def test_dispositivos_asigna_alias_por_orden_de_aparicion(cliente, monkeypatch):
    bd = usar(monkeypatch, BD([(5, "zeta", T), (1, "beta", T), (3, "alfa", T)]))
    datos = cliente.get("/api/dispositivos").get_json()
    # beta appeared first (id 1), then alfa (id 3), then zeta (id 5)
    assert bd.alias == {"beta": 1, "alfa": 2, "zeta": 3}
    assert [d["vehiculo"] for d in datos] == ["A01", "A02", "A03"]
    assert bd.commits == 1


def test_dispositivos_conserva_alias_existentes_y_no_reutiliza(cliente, monkeypatch):
    # "viejo" had number 4; numbers 1-3 belonged to devices with no points left
    bd = usar(monkeypatch, BD([(1, "viejo", T), (2, "nuevo", T)], alias={"viejo": 4}))
    datos = cliente.get("/api/dispositivos").get_json()
    assert bd.alias == {"viejo": 4, "nuevo": 5}
    assert [(d["vehiculo"], d["nombre"]) for d in datos] == [
        ("A04", "Vehículo A04"), ("A05", "Vehículo A05")]


def test_dispositivos_sin_faltantes_no_escribe(cliente, monkeypatch):
    bd = usar(monkeypatch, BD([(1, "a", T)], alias={"a": 1}))
    cliente.get("/api/dispositivos")
    assert not any("INSERT" in sql for sql, _ in bd.ejecutadas)
    assert bd.commits == 0


def test_ninguna_respuesta_incluye_device_id(cliente, monkeypatch):
    usar(monkeypatch, BD([(1, "secreto-123", T)], alias={"secreto-123": 1}))
    for ruta in ("/api/dispositivos", "/api/ultima-ubicacion",
                 "/api/historial-ubicaciones?vehiculo=A01",
                 "/api/lugar-visitado?vehiculo=A01&lat_min=1&lat_max=2&lon_min=1&lon_max=2"):
        r = cliente.get(ruta)
        assert r.status_code == 200, ruta
        assert b"secreto-123" not in r.data, ruta
        assert b"device_id" not in r.data, ruta


def test_sin_tabla_de_alias_da_503_sin_device_id(cliente, monkeypatch):
    usar(monkeypatch, BD([(1, "secreto-123", T)], tabla_alias=False))
    for ruta in ("/api/dispositivos", "/api/ultima-ubicacion", "/api/historial-ubicaciones?vehiculo=A01"):
        r = cliente.get(ruta)
        assert r.status_code == 503, ruta
        assert "alias" in r.get_json()["error"]
        assert b"secreto-123" not in r.data


# ---------- ?vehiculo= ----------

def test_vehiculo_se_traduce_a_device_id(cliente, monkeypatch):
    bd = usar(monkeypatch, BD([(1, "a", T), (2, "b", T)], alias={"a": 1, "b": 2}))
    r = cliente.get("/api/historial-ubicaciones?vehiculo=a02&horas=24")
    assert r.status_code == 200
    sql, params = bd.ejecutadas[-1]
    assert params == (24, "b")


def test_vehiculo_resuelto_se_guarda_en_cache(cliente, monkeypatch):
    bd = usar(monkeypatch, BD([(1, "a", T)], alias={"a": 1}))
    cliente.get("/api/historial-ubicaciones?vehiculo=A01")
    cliente.get("/api/historial-ubicaciones?vehiculo=A01")
    consultas = [sql for sql, _ in bd.ejecutadas if "WHERE numero" in sql]
    assert len(consultas) == 1


@pytest.mark.parametrize("ruta", [
    "/api/historial-ubicaciones?vehiculo={}",
    "/api/detecciones-senal?vehiculo={}",
    "/api/ultima-ubicacion?vehiculo={}",
    "/api/lugar-visitado?vehiculo={}&lat_min=1&lat_max=2&lon_min=1&lon_max=2",
])
def test_vehiculo_desconocido_da_404_e_invalido_400(cliente, monkeypatch, ruta):
    usar(monkeypatch, BD([(1, "a", T)], alias={"a": 1}))
    r = cliente.get(ruta.format("A09"))
    assert r.status_code == 404
    assert "A09" in r.get_json()["error"]
    r = cliente.get(ruta.format("carro-a"))
    assert r.status_code == 400
    assert "vehiculo" in r.get_json()["error"]


def test_vehiculo_no_abre_la_bd_si_otro_parametro_es_invalido(cliente, monkeypatch):
    def prohibido():
        raise AssertionError("No debe abrir conexion a la BD con parametros invalidos")
    monkeypatch.setattr(servidorweb, "obtener_conexion", prohibido)
    r = cliente.get("/api/historial-ubicaciones?vehiculo=A01&desde=ayer&hasta=hoy")
    assert r.status_code == 400


def test_device_id_sigue_aceptandose(cliente, monkeypatch):
    bd = usar(monkeypatch, BD([(1, "a", T)], alias={"a": 1}))
    r = cliente.get("/api/historial-ubicaciones?device_id=a&horas=24")
    assert r.status_code == 200
    assert bd.ejecutadas[-1][1] == (24, "a")
