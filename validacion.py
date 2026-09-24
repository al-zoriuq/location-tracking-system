"""Validation of API query parameters.

Every problem raises ErrorValidacion with a Spanish message that the API
returns as HTTP 400, so the frontend can show it as-is.
"""
import re
from datetime import datetime

from tiempo_bogota import FORMATO_FECHA

HORAS_MIN = 1
HORAS_MAX = 720  # 30 days

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
