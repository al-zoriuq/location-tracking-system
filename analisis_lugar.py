"""Entrega 2: when did the vehicle pass through a given place?

Pure functions only (no Flask, no database), so every step can be unit
tested and explained on its own.

Why segments and not only points: with one point every 10 s, at 50 km/h
there are ~139 m between consecutive points. A circle of radius 50 m can be
crossed through its center with both points ~69.5 m away, i.e. no point
inside. So each pair of consecutive points is treated as a straight segment
and intersected with the circle.

Input rows (one per GPS point, ordered by time) carry the point and its real
neighbors, as produced by LAG()/LEAD() in SQL:
    lat, lon, ts, lat_ant, lon_ant, ts_ant, lat_sig, lon_sig, ts_sig
Timestamps are naive Bogota datetimes; neighbor fields may be None.
"""
import math
from dataclasses import dataclass
from datetime import timedelta

RADIO_TIERRA_M = 6371008.8
M_POR_GRADO = RADIO_TIERRA_M * math.pi / 180

# Invalid-segment thresholds. They MUST match disenop2web/src/utils/viajes.js
# (MAX_PAUSA_MS, MAX_SALTO_M, MAX_VELOCIDAD_KMH) so the frontend's trips and
# the backend's detections agree on what counts as continuous movement.
MAX_PAUSA_S = 3600          # more than 1 h between points: not a continuous trip
MAX_SALTO_M = 1000          # more than 1 km between points: not a continuous trip
MAX_VELOCIDAD_KMH = 180     # faster: GPS error

# Grouping of detections into passes
MAX_SEPARACION_PASO_S = 600     # detections <= 10 min apart are one pass
# A pass is a stop when the time actually spent INSIDE the circle adds up to
# >= 5 min. Not entry-to-exit: two quick crossings 5 min apart are grouped
# into one pass lasting ~5 min, but the vehicle never stopped there.
MIN_TIEMPO_DENTRO_PARADA_S = 300


# ---------------------------------------------------------------- geometry

def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters."""
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = f2 - f1
    dl = math.radians(lon2 - lon1)
    h = math.sin(df / 2) ** 2 + math.cos(f1) * math.cos(f2) * math.sin(dl / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(math.sqrt(h))


def proyectar(lat, lon, lat0, lon0):
    """Local equirectangular projection to meters, origin at (lat0, lon0).

    x = R * dLon * cos(lat0), y = R * dLat. Over a few km the error against
    Haversine is centimeters, and it turns the problem into plane geometry.
    """
    x = (lon - lon0) * M_POR_GRADO * math.cos(math.radians(lat0))
    y = (lat - lat0) * M_POR_GRADO
    return x, y


def interseccion_segmento_circulo(a, b, radio):
    """Part of segment a->b inside the circle centered at the origin.

    Segment: P(t) = A + t*D, t in [0, 1], D = B - A.
    On the border |P(t)|^2 = r^2, which expands to the quadratic
        (D.D) t^2 + 2 (A.D) t + (A.A - r^2) = 0
    Returns (t_entrada, t_salida) clamped to [0, 1], or None if the segment
    never enters the circle.
    """
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    qa = dx * dx + dy * dy
    qb = 2 * (ax * dx + ay * dy)
    qc = ax * ax + ay * ay - radio * radio

    if qa == 0:  # both points at the same position
        return (0.0, 1.0) if qc <= 0 else None

    discriminante = qb * qb - 4 * qa * qc
    if discriminante < 0:  # the line misses the circle
        return None

    raiz = math.sqrt(discriminante)
    t1 = (-qb - raiz) / (2 * qa)
    t2 = (-qb + raiz) / (2 * qa)
    if t1 > 1 or t2 < 0:  # the line crosses it, but beyond the segment's ends
        return None
    return max(t1, 0.0), min(t2, 1.0)


def punto_mas_cercano(a, b):
    """(t, distance) of the point of segment a->b closest to the origin.

    Minimizes |A + t*D|^2: t* = -(A.D) / (D.D), clamped to [0, 1].
    """
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    qa = dx * dx + dy * dy
    t = 0.0 if qa == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / qa))
    return t, math.hypot(ax + t * dx, ay + t * dy)


def interpolar_tiempo(t0, t1, fraccion):
    """Linear time interpolation (assumes constant speed over the segment)."""
    return t0 + (t1 - t0) * fraccion


def caja_circulo(lat, lon, radio):
    """Bounding box (lat_min, lat_max, lon_min, lon_max) of the circle, +1 %."""
    radio *= 1.01
    dlat = radio / M_POR_GRADO
    dlon = radio / (M_POR_GRADO * math.cos(math.radians(lat)))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


# ------------------------------------------------------------ validity

def velocidad_kmh(distancia_m, dt_s):
    return distancia_m / dt_s * 3.6


def segmento_valido(dt_s, distancia_m):
    """A segment is continuous movement only if it is short in time and space
    and physically possible."""
    return (0 < dt_s <= MAX_PAUSA_S
            and distancia_m <= MAX_SALTO_M
            and velocidad_kmh(distancia_m, dt_s) <= MAX_VELOCIDAD_KMH)


def es_salto_gps(fila):
    """True if the point looks like a GPS error: every neighbor within 1 h
    implies an impossible speed (e.g. a single fix 6 km away between two
    normal fixes). A point whose neighbors are simply far in time is NOT an
    error: it is an isolated point and still counts."""
    velocidades = []
    for sufijo in ("ant", "sig"):
        ts_vecino = fila[f"ts_{sufijo}"]
        if ts_vecino is None:
            continue
        dt = abs((fila["ts"] - ts_vecino).total_seconds())
        if dt == 0 or dt > MAX_PAUSA_S:
            continue
        distancia = haversine_m(fila["lat"], fila["lon"],
                                fila[f"lat_{sufijo}"], fila[f"lon_{sufijo}"])
        velocidades.append(velocidad_kmh(distancia, dt))
    return bool(velocidades) and all(v > MAX_VELOCIDAD_KMH for v in velocidades)


# ------------------------------------------------------------ detection

@dataclass
class Deteccion:
    entrada: object
    salida: object
    distancia_m: float
    momento: object
    puntos: int
    segundos_dentro: float  # time inside the circle (0 for a lone point)


def detectar(filas, lat, lon, radio):
    """Every moment the vehicle was inside the circle, before grouping.

    Two sources:
    - each valid segment that intersects the circle (entry/exit interpolated)
    - each point inside the circle that is not a GPS error (this is what
      catches an isolated point whose segments are all invalid)
    """
    detecciones = []
    for fila in filas:
        a = proyectar(fila["lat"], fila["lon"], lat, lon)

        if fila["ts_sig"] is not None:
            dt = (fila["ts_sig"] - fila["ts"]).total_seconds()
            distancia = haversine_m(fila["lat"], fila["lon"], fila["lat_sig"], fila["lon_sig"])
            if segmento_valido(dt, distancia):
                b = proyectar(fila["lat_sig"], fila["lon_sig"], lat, lon)
                cruce = interseccion_segmento_circulo(a, b, radio)
                if cruce:
                    t_cerca, d_min = punto_mas_cercano(a, b)
                    t0, t1 = fila["ts"], fila["ts_sig"]
                    detecciones.append(Deteccion(
                        entrada=interpolar_tiempo(t0, t1, cruce[0]),
                        salida=interpolar_tiempo(t0, t1, cruce[1]),
                        distancia_m=d_min,
                        momento=interpolar_tiempo(t0, t1, t_cerca),
                        puntos=0,
                        segundos_dentro=dt * (cruce[1] - cruce[0]),
                    ))

        distancia_centro = math.hypot(*a)
        if distancia_centro <= radio and not es_salto_gps(fila):
            detecciones.append(Deteccion(fila["ts"], fila["ts"], distancia_centro, fila["ts"], 1, 0.0))
    return detecciones


def agrupar(detecciones):
    """Merges detections separated by <= 10 min into a single pass."""
    grupos = []
    for d in sorted(detecciones, key=lambda d: d.entrada):
        ultimo = grupos[-1] if grupos else None
        if ultimo and (d.entrada - ultimo.salida).total_seconds() <= MAX_SEPARACION_PASO_S:
            ultimo.salida = max(ultimo.salida, d.salida)
            ultimo.puntos += d.puntos
            # Consecutive segments only share an endpoint, so adding up their
            # inside-time never counts the same second twice
            ultimo.segundos_dentro += d.segundos_dentro
            if d.distancia_m < ultimo.distancia_m:
                ultimo.distancia_m, ultimo.momento = d.distancia_m, d.momento
        else:
            grupos.append(Deteccion(d.entrada, d.salida, d.distancia_m, d.momento,
                                    d.puntos, d.segundos_dentro))
    return grupos


def _al_segundo(fecha):
    """Rounds an interpolated datetime to the nearest whole second."""
    return (fecha + timedelta(microseconds=500_000)).replace(microsecond=0)


def analizar_pasos(filas, lat, lon, radio):
    """Rows with neighbors -> passes in chronological order."""
    pasos = []
    for g in agrupar(detectar(filas, lat, lon, radio)):
        entrada, salida = _al_segundo(g.entrada), _al_segundo(g.salida)
        duracion = int((salida - entrada).total_seconds())
        pasos.append({
            "entrada": entrada,
            "salida": salida,
            "duracion_s": duracion,
            "momento_mas_cercano": _al_segundo(g.momento),
            "distancia_minima_m": round(g.distancia_m, 1),
            "puntos": g.puntos,
            "tipo": "parada" if g.segundos_dentro >= MIN_TIEMPO_DENTRO_PARADA_S else "paso",
        })
    return pasos


# ------------------------------------- helpers for the in-memory (demo) path

def filas_con_vecinos(puntos):
    """[(lat, lon, ts), ...] ordered by ts -> rows with LAG/LEAD neighbors,
    exactly what the SQL window functions return."""
    filas = []
    for i, (lat, lon, ts) in enumerate(puntos):
        ant = puntos[i - 1] if i > 0 else (None, None, None)
        sig = puntos[i + 1] if i + 1 < len(puntos) else (None, None, None)
        filas.append({
            "lat": lat, "lon": lon, "ts": ts,
            "lat_ant": ant[0], "lon_ant": ant[1], "ts_ant": ant[2],
            "lat_sig": sig[0], "lon_sig": sig[1], "ts_sig": sig[2],
        })
    return filas


def filtrar_por_caja(filas, caja):
    """Keeps rows whose segment bounding box touches the circle's box.
    Mirrors the SQL: GREATEST/LEAST ignore the missing next point."""
    lat_min, lat_max, lon_min, lon_max = caja

    def extremos(a, b):
        valores = [v for v in (a, b) if v is not None]
        return min(valores), max(valores)

    resultado = []
    for f in filas:
        la_min, la_max = extremos(f["lat"], f["lat_sig"])
        lo_min, lo_max = extremos(f["lon"], f["lon_sig"])
        if la_max >= lat_min and la_min <= lat_max and lo_max >= lon_min and lo_min <= lon_max:
            resultado.append(f)
    return resultado
