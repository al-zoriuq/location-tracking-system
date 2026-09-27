"""Place search for the location filter: text ("frisby calle 64",
"universidad del norte") -> candidate places with coordinates.

Uses two free OpenStreetMap geocoders, no API key:
- Photon (photon.komoot.io): tolerant of informal text and business names.
- Nominatim (nominatim.openstreetmap.org): fallback, better with formal
  names. Its usage policy asks for an identifying User-Agent and at most one
  request per second, so it is only called when Photon finds nothing, and
  repeated searches are answered from a cache.

Security: the user's text only travels as a URL-encoded query parameter to
these two FIXED hosts, never as part of the host or path (no SSRF).
Only the standard library is used (urllib), no new dependency.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

USER_AGENT = "GPSLink-proyecto-universitario/1.0 (rama marcela-test)"
TIEMPO_ESPERA_S = 8
MAX_RESULTADOS = 5

# Barranquilla metropolitan area: results are restricted to this box
LON_MIN, LAT_MIN, LON_MAX, LAT_MAX = -74.98, 10.85, -74.70, 11.10
CENTRO_LAT, CENTRO_LON = 10.99, -74.81

URL_PHOTON = "https://photon.komoot.io/api/"
URL_NOMINATIM = "https://nominatim.openstreetmap.org/search"


class ErrorGeocodificacion(Exception):
    """The geocoding services could not be reached (the API answers 502)."""


def _pedir_json(url, parametros):
    consulta = urllib.parse.urlencode(parametros)
    peticion = urllib.request.Request(f"{url}?{consulta}", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(peticion, timeout=TIEMPO_ESPERA_S) as respuesta:
            return json.load(respuesta)
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise ErrorGeocodificacion(str(error)) from error


def _dentro_del_area(lat, lon):
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def _unir(*partes):
    return ", ".join(p for p in partes if p)


def _buscar_photon(texto):
    datos = _pedir_json(URL_PHOTON, {
        "q": texto,
        "limit": MAX_RESULTADOS,
        "lat": CENTRO_LAT,  # location bias: closer results rank higher
        "lon": CENTRO_LON,
        "bbox": f"{LON_MIN},{LAT_MIN},{LON_MAX},{LAT_MAX}",
    })
    resultados = []
    for f in datos.get("features", []):
        p = f.get("properties", {})
        lon, lat = f["geometry"]["coordinates"]
        calle = " ".join(x for x in (p.get("street"), p.get("housenumber")) if x)
        nombre = p.get("name") or calle or "Lugar sin nombre"
        resultados.append({
            "nombre": nombre,
            "detalle": _unir(calle if calle != nombre else "",
                             p.get("district") or p.get("locality"), p.get("city")),
            "lat": lat,
            "lon": lon,
        })
    return resultados


def _buscar_nominatim(texto):
    datos = _pedir_json(URL_NOMINATIM, {
        "q": texto,
        "format": "jsonv2",
        "limit": MAX_RESULTADOS,
        "countrycodes": "co",
        "viewbox": f"{LON_MIN},{LAT_MAX},{LON_MAX},{LAT_MIN}",
        "bounded": 1,
    })
    resultados = []
    for r in datos:
        partes = r.get("display_name", "").split(", ")
        resultados.append({
            "nombre": r.get("name") or partes[0],
            "detalle": _unir(*partes[1:3]),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
        })
    return resultados


@lru_cache(maxsize=256)
def _buscar_normalizado(texto):
    """Cached on the normalized text; errors are not cached (lru_cache never
    stores exceptions), so a temporary failure is retried next time."""
    # An unexpected answer format (missing field) counts as a failed service
    formato_inesperado = (KeyError, TypeError, ValueError)
    try:
        resultados = _buscar_photon(texto)
    except (ErrorGeocodificacion, *formato_inesperado):
        resultados = []
    if not resultados:
        try:
            resultados = _buscar_nominatim(texto)
        except formato_inesperado as error:
            raise ErrorGeocodificacion(f"respuesta inesperada: {error}") from error

    # Keep only the metro area and drop duplicates (same name, ~same spot)
    vistos = set()
    unicos = []
    for r in resultados:
        clave = (r["nombre"].lower(), round(r["lat"], 4), round(r["lon"], 4))
        if _dentro_del_area(r["lat"], r["lon"]) and clave not in vistos:
            vistos.add(clave)
            unicos.append(r)
    return tuple(unicos[:MAX_RESULTADOS])


def buscar_lugares(texto):
    """Candidate places for a free-text search, best match first."""
    return list(_buscar_normalizado(" ".join(texto.lower().split())))
