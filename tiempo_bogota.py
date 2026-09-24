"""Single source of truth for Bogota time handling.

The database stores timestamp_gps as Bogota wall-clock time WITHOUT a time
zone (the sniffer does replace(tzinfo=None)). Every "now" we compare against
those values must therefore also be a naive Bogota datetime.

Colombia has used UTC-05:00 with no daylight saving time since 1993, so a
fixed offset is exact. We avoid zoneinfo("America/Bogota") because on Windows
it needs the extra 'tzdata' package.
"""
from datetime import datetime, timedelta, timezone

BOGOTA = timezone(timedelta(hours=-5), "America/Bogota")

# Format used for every timestamp exchanged with the frontend
FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"


def ahora_bogota():
    """Current Bogota wall-clock time as a naive datetime (no microseconds)."""
    return datetime.now(BOGOTA).replace(tzinfo=None, microsecond=0)


def formatear(fecha):
    """Naive datetime -> 'YYYY-MM-DD HH:MM:SS' (drops fractional seconds)."""
    return fecha.strftime(FORMATO_FECHA)
