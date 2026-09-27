"""Validation of API query parameters.

Every problem raises ErrorValidacion with a Spanish message that the API
returns as HTTP 400, so the frontend can show it as-is.
"""
import math
import re
from datetime import datetime

from tiempo_bogota import FORMATO_FECHA

HORAS_MIN = 1
HORAS_MAX = 720  # 30 days

RADIO_MIN_M = 20
RADIO_MAX_M = 2000
RADIO_POR_DEFECTO_M = 100

BUSQUEDA_MIN = 3
BUSQUEDA_MAX = 100

# Same character set the sniffer accepts for the device id: [\w-]+
PATRON_DEVICE_ID = re.compile(r"[\w-]{1,64}")


class ErrorValidacion(ValueError):
    """Invalid user input. The message is shown to the user (HTTP 400)."""


def parsear_fecha(texto, nombre):
    """'YYYY-MM-DD HH:MM:SS' (Bogota time) -> naive datetime."""
    try:
        return datetime.strptime(texto.strip(), FORMATO_FECHA)
    except ValueError:
        raise ErrorValidacion(
            f"Formato de fecha inválido en '{nombre}'. "
            "Usa AAAA-MM-DD HH:MM:SS (hora de Bogotá)."
        ) from None


def leer_rango(args):
    """Reads the optional 'desde'/'hasta' pair. Returns (None, None) if absent.

    Both must come together: a range with only one end is ambiguous.
    """
    desde_texto = args.get("desde", "").strip()
    hasta_texto = args.get("hasta", "").strip()

    if not desde_texto and not hasta_texto:
        return None, None
    if not desde_texto or not hasta_texto:
        raise ErrorValidacion("Debes enviar 'desde' y 'hasta' juntos.")

    desde = parsear_fecha(desde_texto, "desde")
    hasta = parsear_fecha(hasta_texto, "hasta")
    if desde >= hasta:
        raise ErrorValidacion("'desde' debe ser anterior a 'hasta'.")
    return desde, hasta


def leer_horas(args, por_defecto=24):
    """Reads the optional 'horas' window size (integer, 1 to 720)."""
    texto = args.get("horas", "").strip()
    if not texto:
        return por_defecto
    try:
        horas = int(texto)
    except ValueError:
        raise ErrorValidacion("'horas' debe ser un número entero.") from None
    if not HORAS_MIN <= horas <= HORAS_MAX:
        raise ErrorValidacion(f"'horas' debe estar entre {HORAS_MIN} y {HORAS_MAX}.")
    return horas


def leer_device_id(args):
    """Reads the optional 'device_id'. Returns None if absent."""
    device_id = args.get("device_id", "").strip()
    if not device_id:
        return None
    if not PATRON_DEVICE_ID.fullmatch(device_id):
        raise ErrorValidacion("'device_id' inválido.")
    return device_id


def _leer_numero(args, nombre, minimo, maximo, por_defecto=None):
    """Reads a finite float within [minimo, maximo]; required if no default."""
    texto = args.get(nombre, "").strip()
    if not texto:
        if por_defecto is None:
            raise ErrorValidacion(f"Falta el parámetro '{nombre}'.")
        return por_defecto
    try:
        valor = float(texto)
    except ValueError:
        raise ErrorValidacion(f"'{nombre}' debe ser un número.") from None
    # float() accepts "nan" and "inf". Every comparison with NaN is False, so a
    # check written as (valor < minimo or valor > maximo) would let NaN through;
    # isfinite() rejects it explicitly, whatever the form of the range check.
    if not math.isfinite(valor) or not minimo <= valor <= maximo:
        raise ErrorValidacion(f"'{nombre}' debe estar entre {minimo} y {maximo}.")
    return valor


def leer_lugar(args):
    """Reads the place of Entrega 2: lat, lon (required) and radio in meters."""
    lat = _leer_numero(args, "lat", -90, 90)
    lon = _leer_numero(args, "lon", -180, 180)
    radio = _leer_numero(args, "radio", RADIO_MIN_M, RADIO_MAX_M, RADIO_POR_DEFECTO_M)
    return lat, lon, radio


def leer_busqueda(args):
    """Reads the free-text place search 'q' (3 to 100 characters)."""
    texto = " ".join(args.get("q", "").split())  # collapse repeated spaces
    if len(texto) < BUSQUEDA_MIN:
        raise ErrorValidacion(f"Escribe al menos {BUSQUEDA_MIN} caracteres para buscar.")
    if len(texto) > BUSQUEDA_MAX:
        raise ErrorValidacion(f"La búsqueda no puede tener más de {BUSQUEDA_MAX} caracteres.")
    return texto
