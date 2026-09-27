import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import geocodificacion  # noqa: E402
import servidorweb  # noqa: E402
from geocodificacion import URL_NOMINATIM, URL_PHOTON, ErrorGeocodificacion  # noqa: E402

# Canned answers: the tests never reach the internet
PHOTON_FRISBY = {"features": [
    {"geometry": {"coordinates": [-74.83649, 11.01385]},
     "properties": {"name": "Frisby", "street": "Calle 106", "district": "Riomar",
                    "city": "Barranquilla"}},
    {"geometry": {"coordinates": [-74.83649, 11.01385]},  # duplicate
     "properties": {"name": "Frisby", "city": "Barranquilla"}},
    {"geometry": {"coordinates": [-74.0721, 4.7110]},  # Bogota: outside the area
     "properties": {"name": "Frisby", "city": "Bogotá"}},
]}
NOMINATIM_ESTADIO = [{
    "name": "Estadio Metropolitano Roberto Meléndez",
    "display_name": "Estadio Metropolitano Roberto Meléndez, Vía Estadio, Ciudadela 20 de Julio, Barranquilla",
    "lat": "10.92695", "lon": "-74.80051",
}]


@pytest.fixture
def servicios(monkeypatch):
    """Replaces the HTTP call with canned answers; records what was asked."""
    respuestas = {}
    llamadas = []

    def falso(url, parametros):
        llamadas.append((url, parametros))
        respuesta = respuestas.get(url)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    monkeypatch.setattr(geocodificacion, "_pedir_json", falso)
    geocodificacion._buscar_normalizado.cache_clear()
    yield respuestas, llamadas
    geocodificacion._buscar_normalizado.cache_clear()


@pytest.fixture
def cliente():
    return servidorweb.app.test_client()


def test_photon_resultados_limpios(servicios):
    respuestas, _ = servicios
    respuestas[URL_PHOTON] = PHOTON_FRISBY
    resultados = geocodificacion.buscar_lugares("frisby calle 64")
    # Duplicate and out-of-area results are dropped
    assert resultados == [{"nombre": "Frisby", "detalle": "Calle 106, Riomar, Barranquilla",
                           "lat": 11.01385, "lon": -74.83649}]


def test_nominatim_como_respaldo_si_photon_no_encuentra(servicios):
    respuestas, llamadas = servicios
    respuestas[URL_PHOTON] = {"features": []}
    respuestas[URL_NOMINATIM] = NOMINATIM_ESTADIO
    resultados = geocodificacion.buscar_lugares("estadio metropolitano")
    assert [u for u, _ in llamadas] == [URL_PHOTON, URL_NOMINATIM]
    assert resultados[0]["nombre"] == "Estadio Metropolitano Roberto Meléndez"
    assert resultados[0]["lat"] == pytest.approx(10.92695)


def test_nominatim_como_respaldo_si_photon_falla(servicios):
    respuestas, _ = servicios
    respuestas[URL_PHOTON] = ErrorGeocodificacion("timeout")
    respuestas[URL_NOMINATIM] = NOMINATIM_ESTADIO
    assert len(geocodificacion.buscar_lugares("estadio")) == 1


def test_busquedas_repetidas_usan_cache(servicios):
    respuestas, llamadas = servicios
    respuestas[URL_PHOTON] = PHOTON_FRISBY
    geocodificacion.buscar_lugares("Frisby  Calle 64")
    geocodificacion.buscar_lugares("frisby calle 64")  # same text once normalized
    assert len(llamadas) == 1


def test_texto_viaja_solo_como_parametro(servicios):
    respuestas, llamadas = servicios
    respuestas[URL_PHOTON] = {"features": []}
    respuestas[URL_NOMINATIM] = []
    geocodificacion.buscar_lugares("http://otro-servidor.com/x")
    # Hosts are fixed; the user's text is only the "q" parameter
    assert {u for u, _ in llamadas} == {URL_PHOTON, URL_NOMINATIM}
    assert all(p["q"] == "http://otro-servidor.com/x" for _, p in llamadas)


def test_endpoint_devuelve_resultados(servicios, cliente):
    respuestas, _ = servicios
    respuestas[URL_PHOTON] = PHOTON_FRISBY
    datos = cliente.get("/api/buscar-lugar", query_string={"q": "  frisby   calle 64 "}).get_json()
    assert datos["consulta"] == "frisby calle 64"
    assert datos["resultados"][0]["nombre"] == "Frisby"


@pytest.mark.parametrize("q, mensaje", [
    ("", "al menos 3 caracteres"),
    ("ab", "al menos 3 caracteres"),
    ("x" * 101, "más de 100 caracteres"),
])
def test_endpoint_valida_el_texto(cliente, q, mensaje):
    respuesta = cliente.get("/api/buscar-lugar", query_string={"q": q})
    assert respuesta.status_code == 400
    assert mensaje in respuesta.get_json()["error"]


def test_endpoint_servicios_caidos_da_502(servicios, cliente):
    respuestas, _ = servicios
    respuestas[URL_PHOTON] = ErrorGeocodificacion("sin red")
    respuestas[URL_NOMINATIM] = ErrorGeocodificacion("sin red")
    respuesta = cliente.get("/api/buscar-lugar", query_string={"q": "frisby"})
    assert respuesta.status_code == 502
    assert "No se pudo buscar la dirección" in respuesta.get_json()["error"]


def test_formato_inesperado_da_502_y_no_500(servicios, cliente):
    respuestas, _ = servicios
    respuestas[URL_PHOTON] = {"features": [{"sin": "geometria"}]}
    respuestas[URL_NOMINATIM] = [{"sin": "coordenadas"}]
    assert cliente.get("/api/buscar-lugar", query_string={"q": "frisby"}).status_code == 502
