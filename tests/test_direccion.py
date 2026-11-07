"""Tests for /api/direccion (reverse geocoding for the last-position card).
Nominatim is never called: requests.get is replaced by a fake."""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import servidorweb

RESPUESTA_PRADO = {
    "display_name": "Carrera 51B, El Prado, Localidad Norte Centro Histórico, Barranquilla, Atlántico, Colombia",
    "address": {
        "road": "Carrera 51B",
        "house_number": "82-10",
        "neighbourhood": "El Prado",
        "city_district": "Localidad Norte Centro Histórico",
        "city": "Barranquilla",
        "state": "Atlántico",
        "country": "Colombia",
    },
}


class RespuestaFalsa:
    def __init__(self, datos, estado=200):
        self.datos = datos
        self.estado = estado

    def raise_for_status(self):
        if self.estado >= 400:
            raise requests.HTTPError(f"{self.estado}")

    def json(self):
        return self.datos


@pytest.fixture
def cliente(monkeypatch):
    servidorweb._cache_direcciones.clear()
    monkeypatch.setattr(servidorweb.time, "sleep", lambda s: None)
    return servidorweb.app.test_client()


@pytest.fixture
def nominatim(monkeypatch):
    llamadas = []

    def falso(url, params=None, headers=None, timeout=None):
        llamadas.append(params)
        return RespuestaFalsa(RESPUESTA_PRADO)

    monkeypatch.setattr(servidorweb.requests, "get", falso)
    return llamadas


def test_direccion_corta(cliente, nominatim):
    r = cliente.get("/api/direccion?lat=11.0001&lon=-74.8001")
    assert r.status_code == 200
    assert r.get_json()["direccion"] == "Carrera 51B #82-10, El Prado, Barranquilla"
    assert nominatim[0]["accept-language"] == "es"


def test_puntos_cercanos_usan_la_cache(cliente, nominatim):
    # Both round to (11.0001, -74.8001): only one call to Nominatim
    cliente.get("/api/direccion?lat=11.00012&lon=-74.80011")
    r = cliente.get("/api/direccion?lat=11.00008&lon=-74.80009")
    assert r.status_code == 200
    assert len(nominatim) == 1


def test_sin_calle_usa_barrio_y_ciudad():
    assert servidorweb.armar_direccion(
        {"address": {"suburb": "Riomar", "city": "Barranquilla"}}
    ) == "Riomar, Barranquilla"


def test_sin_partes_usa_display_name():
    assert servidorweb.armar_direccion(
        {"display_name": "Vía 40, Atlántico, Colombia, 080001"}
    ) == "Vía 40, Atlántico, Colombia"


def test_punto_sin_datos(cliente, monkeypatch):
    monkeypatch.setattr(servidorweb.requests, "get",
                        lambda *a, **k: RespuestaFalsa({"error": "Unable to geocode"}))
    r = cliente.get("/api/direccion?lat=12.5&lon=-76")
    assert r.status_code == 200
    assert r.get_json()["direccion"] is None


def test_fallo_de_nominatim_da_502_y_no_se_guarda(cliente, monkeypatch):
    def caido(*a, **k):
        raise requests.ConnectionError("sin red")
    monkeypatch.setattr(servidorweb.requests, "get", caido)
    r = cliente.get("/api/direccion?lat=11&lon=-74.8")
    assert r.status_code == 502
    assert "error" in r.get_json()
    assert servidorweb._cache_direcciones == {}


@pytest.mark.parametrize("consulta", [
    "", "lat=11", "lat=abc&lon=-74", "lat=nan&lon=-74", "lat=91&lon=-74", "lat=11&lon=181",
])
def test_parametros_invalidos_dan_400(cliente, monkeypatch, consulta):
    def prohibido(*a, **k):
        raise AssertionError("No debe consultar Nominatim con parametros invalidos")
    monkeypatch.setattr(servidorweb.requests, "get", prohibido)
    r = cliente.get("/api/direccion?" + consulta)
    assert r.status_code == 400
