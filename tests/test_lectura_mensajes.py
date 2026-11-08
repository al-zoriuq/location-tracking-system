"""Tests for the message reader of snifferwpostgresql.py (parsear)."""
import os
import sys
from datetime import datetime

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "tests"))

from snifferwpostgresql import parsear, MensajeInvalido  # noqa: E402
import sniffer_udpforesp32 as sniffer_pruebas  # noqa: E402

BASE = ("Device: ESP32S3-SIM7670G, Lat: 11.030190, Lon: -74.859845, "
        "Timestamp GPS: 2026-11-03 07:50:28.000000 -0500")


def test_mensaje_de_la_captura():
    u, d, aviso = parsear(BASE + ", Senal: LIMITE 30, Conf: 0.99, Vel GPS: 2, Vel MPU: 22, Usa: GPS, SI")
    assert aviso is None
    assert (u.device_id, u.latitud, u.longitud) == ("ESP32S3-SIM7670G", 11.030190, -74.859845)
    assert u.timestamp_gps == datetime(2026, 11, 3, 7, 50, 28)
    assert (d.senal_texto, d.senal_tipo, d.senal_valor) == ("LIMITE 30", "LIMITE", 30)
    assert (d.confianza, d.vel_gps, d.vel_mpu, d.vel_fuente, d.cumplimiento) == (0.99, 2.0, 22.0, "GPS", "SI")
    assert d.timestamp_evento == u.timestamp_gps
    assert d.edad_posicion_s is None and d.extra is None


def test_pare_de_la_segunda_captura():
    u, d, _ = parsear("Device: ESP32S3-SIM7670G, Lat: 11.024777, Lon: -74.848055, Timestamp GPS: "
                      "2026-11-03 07:57:24.000000 -0500, Senal: PARE, Conf: 1.00, Vel GPS: NA, "
                      "Vel MPU: 28, Usa: MPU, NA")
    assert (d.senal_tipo, d.senal_valor, d.vel_gps, d.vel_mpu, d.vel_fuente, d.cumplimiento) == \
        ("PARE", None, None, 28.0, "MPU", "NA")


def test_solo_ubicacion_esp32_y_android():
    assert parsear(BASE)[1] is None
    u, d, _ = parsear("Device: cel-1, Lat: 10.98, Lon: -74.12, Timestamp GPS: 2026-08-30 17:23:04.000 -05:00\n")
    assert d is None
    assert u.timestamp_gps == datetime(2026, 8, 30, 17, 23, 4)


def test_posicion_vieja():
    _, d, _ = parsear(BASE + ", Senal: LIMITE 30, Conf: 0.95, Vel GPS: 36, Vel MPU: 35, Usa: GPS, EXCEDE, pos-45s")
    assert d.edad_posicion_s == 45
    assert d.timestamp_evento == datetime(2026, 11, 3, 7, 51, 13)
    assert d.extra is None


def test_extra_desconocido_se_conserva():
    _, d, _ = parsear(BASE + ", Senal: CEDA, Conf: 0.88, Vel GPS: 12, Vel MPU: 14, Usa: GPS, NA, otro-dato")
    assert d.extra == "otro-dato"


def test_senal_ninguna():
    assert parsear(BASE + ", Senal: NINGUNA, Conf: 0.00, Vel GPS: 10, Vel MPU: 9, Usa: GPS, NA")[1] is None


@pytest.mark.parametrize("cola", [
    ", Senal: LIMITE 30, Conf: 1.50, Vel GPS: 2, Vel MPU: 2, Usa: GPS, SI",          # Conf > 1
    ", Senal: LIMITE 99999, Conf: 0.9, Vel GPS: 2, Vel MPU: 2, Usa: GPS, SI",        # no cabe en SMALLINT
    ", Senal: " + "X" * 60 + ", Conf: 0.9, Vel GPS: 2, Vel MPU: 2, Usa: GPS, SI",    # texto muy largo
    ", Senal: PARE, Conf: 0.9, Vel GPS: 2, Vel MPU: 2, Usa: GPSMPU, SI",             # Usa muy largo
])
def test_senal_invalida_conserva_la_ubicacion(cola):
    u, d, aviso = parsear(BASE + cola)
    assert u.device_id == "ESP32S3-SIM7670G"
    assert d is None
    assert aviso.startswith("senal descartada")


@pytest.mark.parametrize("mensaje", [
    "",
    "basura",
    "Device: X, Lat: 1, Lon: 2, Timestamp GPS: ayer",
    "Device: X, Lat: 95, Lon: 2, Timestamp GPS: 2026-11-03 07:50:28.000000 -0500",
])
def test_mensajes_sin_ubicacion_valida(mensaje):
    with pytest.raises(MensajeInvalido):
        parsear(mensaje)


@pytest.mark.parametrize("cola", [
    "",
    ", Senal: LIMITE 30, Conf: 0.99, Vel GPS: 2, Vel MPU: 22, Usa: GPS, SI",
    ", Senal: PARE, Conf: 1.00, Vel GPS: NA, Vel MPU: 28, Usa: MPU, NA",
    ", Senal: LIMITE 30, Conf: 0.95, Vel GPS: 36, Vel MPU: 35, Usa: GPS, EXCEDE, pos-45s",
])
def test_igual_que_el_sniffer_de_pruebas(cola):
    # Both readers must produce the same values for the database
    u, d, _ = parsear(BASE + cola)
    p = sniffer_pruebas.parsear(BASE + cola)
    assert (u.device_id, u.latitud, u.longitud, u.timestamp_gps) == \
        (p["device"], p["lat"], p["lon"], p["ts"].replace(tzinfo=None))
    if d:
        assert (d.senal_tipo, d.senal_valor, d.confianza, d.vel_gps, d.vel_mpu, d.vel_fuente, d.cumplimiento) == \
            (p["senal_tipo"].strip().upper(), int(p["senal_valor"]) if p["senal_valor"] is not None else None,
             p["conf"], p["vel_gps"], p["vel_mpu"], p["usa"], p["flag"])
