"""Deterministic simulated GPS data for local development (MODO_DEMO=1).

Nothing here touches the real database. Every point is a pure function of
(fixed seed, today's date, current time), so several Gunicorn workers produce
exactly the same data without sharing any in-memory state.

Timestamps are naive Bogota wall-clock datetimes, exactly like the real
timestamp_gps column.
"""
import bisect
import math
import random
from datetime import datetime, timedelta
from functools import lru_cache

from analisis_lugar import haversine_m

SEMILLA = 2026
INTERVALO_S = 10  # the Android app sends one point every 10 s

DEVICE_PRINCIPAL = "demo-vehiculo-01"
DEVICE_SECUNDARIO = "demo-vehiculo-02"
# TEST-NET-1 (RFC 5737): reserved for documentation, never a real host
IP_DEMO = "192.0.2.10"

RADIO_TIERRA_M = 6371008.8
M_POR_GRADO = RADIO_TIERRA_M * math.pi / 180  # ~111 195 m per degree

# ---------------------------------------------------------------------------
# Places in Barranquilla (approximate coordinates)
# ---------------------------------------------------------------------------
UNINORTE = (11.0190, -74.8505)
CASA = (11.0035, -74.8075)            # El Prado
BUENAVISTA = (11.0138, -74.8274)
VILLA_CAMPESTRE = (11.0270, -74.8650)
PUERTO_COLOMBIA = (11.0000, -74.9530)
CENTRO = (10.9870, -74.7810)
MALECON = (10.9985, -74.7760)
ESTADIO = (10.9270, -74.8000)
AEROPUERTO = (10.8896, -74.7808)

# Road-like waypoint chains between the places above
CASA_A_BUENAVISTA = [CASA, (11.0068, -74.8130), (11.0112, -74.8210), BUENAVISTA]
BUENAVISTA_A_UNINORTE = [BUENAVISTA, (11.0160, -74.8380), (11.0178, -74.8450), UNINORTE]
UNINORTE_A_CAMPESTRE = [UNINORTE, (11.0215, -74.8560), VILLA_CAMPESTRE]
UNINORTE_A_PUERTO = [UNINORTE, (11.0215, -74.8560), (11.0195, -74.8750),
                     (11.0120, -74.9000), (11.0050, -74.9300), PUERTO_COLOMBIA]
CENTRO_A_BUENAVISTA = [CENTRO, (10.9935, -74.7890), (11.0010, -74.8000),
                       (11.0080, -74.8120), BUENAVISTA]
AEROPUERTO_A_CASA = [AEROPUERTO, (10.9100, -74.7850), (10.9400, -74.7900),
                     (10.9700, -74.7950), (10.9900, -74.8000), CASA]
CASA_A_ESTADIO = [CASA, (10.9900, -74.8000), (10.9600, -74.8020), ESTADIO]
CASA_A_MALECON = [CASA, (11.0010, -74.7950), (11.0000, -74.7850), MALECON]
MALECON_A_CENTRO = [MALECON, (10.9930, -74.7790), CENTRO]
CENTRO_A_CASA = [CENTRO, (10.9935, -74.7890), (10.9990, -74.8000), CASA]
# Straight north-south line whose middle waypoint is exactly Uninorte
CRUCE_NORTE_SUR = [(11.0100, -74.8505), UNINORTE, (11.0290, -74.8505)]

# Closed loops used by the "live" vehicle (they are more than 2.5 km apart)
CIRCUITO_NORTE = [(11.0100, -74.8150), (11.0160, -74.8150), (11.0160, -74.8050),
                  (11.0100, -74.8000), (11.0050, -74.8050), (11.0050, -74.8150)]
CIRCUITO_SUR = [(10.9700, -74.7950), (10.9780, -74.7850), (10.9720, -74.7780),
                (10.9640, -74.7850), (10.9620, -74.7930)]


def _cadena(*tramos):
    """Joins waypoint chains, dropping the repeated joint waypoint."""
    resultado = list(tramos[0])
    for tramo in tramos[1:]:
        resultado.extend(tramo[1:])
    return resultado


def _reverso(tramo):
    return list(reversed(tramo))


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def distancia_m(a, b):
    """Haversine distance in meters between (lat, lon) pairs."""
    return haversine_m(*a, *b)


def _desplazar(lat, lon, este_m, norte_m):
    """Moves a coordinate a few meters east/north (flat-earth approximation)."""
    return (lat + norte_m / M_POR_GRADO,
            lon + este_m / (M_POR_GRADO * math.cos(math.radians(lat))))


class Recorrido:
    """Polyline in local meters that can be sampled by arc length."""

    def __init__(self, waypoints, cerrado=False):
        self.lat0, self.lon0 = waypoints[0]
        self.cos0 = math.cos(math.radians(self.lat0))
        puntos = [self._a_metros(lat, lon) for lat, lon in waypoints]
        if cerrado:
            puntos.append(puntos[0])
        self.puntos = puntos
        self.acumulado = [0.0]
        for (x1, y1), (x2, y2) in zip(puntos, puntos[1:]):
            self.acumulado.append(self.acumulado[-1] + math.hypot(x2 - x1, y2 - y1))
        self.longitud = self.acumulado[-1]

    def _a_metros(self, lat, lon):
        return ((lon - self.lon0) * M_POR_GRADO * self.cos0,
                (lat - self.lat0) * M_POR_GRADO)

    def distancia_hasta(self, indice_waypoint):
        return self.acumulado[indice_waypoint]

    def posicion(self, s):
        """(lat, lon) at arc length s meters from the first waypoint."""
        s = min(max(s, 0.0), self.longitud)
        i = min(bisect.bisect_right(self.acumulado, s) - 1, len(self.puntos) - 2)
        largo = self.acumulado[i + 1] - self.acumulado[i]
        f = (s - self.acumulado[i]) / largo if largo else 0.0
        (x1, y1), (x2, y2) = self.puntos[i], self.puntos[i + 1]
        x, y = x1 + f * (x2 - x1), y1 + f * (y2 - y1)
        return (self.lat0 + y / M_POR_GRADO,
                self.lon0 + x / (M_POR_GRADO * self.cos0))


# ---------------------------------------------------------------------------
# Historic trips
# ---------------------------------------------------------------------------
def _simular_viaje(rng, inicio, waypoints, paradas=None, velocidad_fija_kmh=None,
                   desfase_m=0.0, ruido_m=3.0):
    """Samples a trip every INTERVALO_S seconds.

    paradas: {waypoint_index: seconds_stopped}. Speed does a bounded random
    walk between 20 and 60 km/h unless velocidad_fija_kmh is given.
    Returns a list of (timestamp, lat, lon).
    """
    ruta = Recorrido(waypoints)
    pendientes = sorted((ruta.distancia_hasta(i), dur) for i, dur in (paradas or {}).items())
    velocidad = velocidad_fija_kmh or rng.uniform(28, 45)
    puntos = []
    t = inicio
    s = desfase_m

    def ruido():
        if not ruido_m:
            return 0.0
        return max(-3 * ruido_m, min(3 * ruido_m, rng.gauss(0, ruido_m)))

    while True:
        lat, lon = ruta.posicion(s)
        puntos.append((t, *_desplazar(lat, lon, ruido(), ruido())))
        if s >= ruta.longitud:
            break
        t += timedelta(seconds=INTERVALO_S)
        if not velocidad_fija_kmh:
            velocidad = min(60.0, max(20.0, velocidad + rng.uniform(-4, 4)))
        siguiente = s + velocidad / 3.6 * INTERVALO_S

        if pendientes and s < pendientes[0][0] <= siguiente:
            # The vehicle reaches a stop: stay there (with GPS jitter) for its duration
            s_parada, duracion = pendientes.pop(0)
            lat_p, lon_p = ruta.posicion(s_parada)
            for _ in range(duracion // INTERVALO_S):
                puntos.append((t, *_desplazar(lat_p, lon_p, ruido(), ruido())))
                t += timedelta(seconds=INTERVALO_S)
            siguiente = s_parada
        s = min(siguiente, ruta.longitud)
    return puntos


def _desfase_para_cruce(waypoints, indice_lugar, velocidad_kmh):
    """Initial offset so the place falls exactly halfway between two samples."""
    paso = velocidad_kmh / 3.6 * INTERVALO_S
    distancia = Recorrido(waypoints).distancia_hasta(indice_lugar)
    return (distancia - paso / 2) % paso


def _aplicar_salto(puntos, indice, dlat, dlon):
    """Replaces one sample with an impossible jump (simulated GPS error)."""
    t, lat, lon = puntos[indice]
    puntos[indice] = (t, lat + dlat, lon + dlon)


# (days ago, "HH:MM", waypoints, options, device)
VIAJES = [
    (9, "06:40", _cadena(CASA_A_BUENAVISTA, BUENAVISTA_A_UNINORTE, UNINORTE_A_CAMPESTRE),
     {}, DEVICE_PRINCIPAL),
    (8, "13:15", CENTRO_A_BUENAVISTA, {"salto": (25, 0.045, 0.030)}, DEVICE_PRINCIPAL),
    # Index 6 of this chain is UNINORTE: 8-minute stop there
    (7, "07:20", _cadena(CASA_A_BUENAVISTA, BUENAVISTA_A_UNINORTE, UNINORTE_A_PUERTO),
     {"paradas": {6: 480}}, DEVICE_PRINCIPAL),
    (6, "18:05", AEROPUERTO_A_CASA, {}, DEVICE_PRINCIPAL),
    # Fast crossing at 60 km/h: no sample within 50 m of Uninorte
    (5, "10:30", CRUCE_NORTE_SUR, {"cruce_rapido": 1}, DEVICE_PRINCIPAL),
    (4, "17:45", _cadena(_reverso(UNINORTE_A_CAMPESTRE), _reverso(BUENAVISTA_A_UNINORTE)),
     {}, DEVICE_PRINCIPAL),
    (3, "08:00", _cadena(CASA_A_ESTADIO, _reverso(CASA_A_ESTADIO)),
     {"paradas": {3: 720}, "salto": (40, -0.050, 0.040)}, DEVICE_PRINCIPAL),
    (3, "14:00", CASA_A_BUENAVISTA, {}, DEVICE_SECUNDARIO),
    (2, "19:20", _cadena(_reverso(UNINORTE_A_PUERTO), _reverso(BUENAVISTA_A_UNINORTE),
                         _reverso(CASA_A_BUENAVISTA)), {}, DEVICE_PRINCIPAL),
    (1, "12:00", _cadena(CASA_A_MALECON, MALECON_A_CENTRO), {}, DEVICE_PRINCIPAL),
    (1, "16:30", CENTRO_A_CASA, {}, DEVICE_PRINCIPAL),
]


@lru_cache(maxsize=4)
def _viajes_historicos(hoy):
    """All historic rows for a given 'today' (a date). Cached per day."""
    rng = random.Random(SEMILLA)
    filas = []
    medianoche = datetime(hoy.year, hoy.month, hoy.day)
    for dias, hora, waypoints, opciones, device in VIAJES:
        hh, mm = map(int, hora.split(":"))
        inicio = medianoche - timedelta(days=dias) + timedelta(hours=hh, minutes=mm)
        if "cruce_rapido" in opciones:
            puntos = _simular_viaje(
                rng, inicio, waypoints, velocidad_fija_kmh=60.0, ruido_m=0.0,
                desfase_m=_desfase_para_cruce(waypoints, opciones["cruce_rapido"], 60.0))
        else:
            puntos = _simular_viaje(rng, inicio, waypoints, paradas=opciones.get("paradas"))
        if "salto" in opciones:
            _aplicar_salto(puntos, *opciones["salto"])
        filas.extend(_fila(device, t, lat, lon) for t, lat, lon in puntos)
    return tuple(filas)


# ---------------------------------------------------------------------------
# Live vehicle: position is a pure function of the clock
# ---------------------------------------------------------------------------
SESION_S = 2 * 3600              # a new live "session" starts every 2 h
CONDUCCION_S = SESION_S - 120    # 2 silent minutes between sessions
INICIO_VIVO_HORA = 5             # sessions shown from 05:00 of the current day
VELOCIDAD_BASE_MS = 32 / 3.6     # 32 km/h average
AMPLITUD_M = 143.0               # speed oscillates ~±11 km/h (21-43 km/h)
PERIODO_S = 300.0
_EPOCA = datetime(2000, 1, 1)    # Bogota wall-clock origin for session numbering

_CIRCUITOS = (Recorrido(CIRCUITO_NORTE, cerrado=True), Recorrido(CIRCUITO_SUR, cerrado=True))


def _posicion_viva(sesion, tau):
    """(lat, lon) of the live vehicle tau seconds after its session started.

    Even sessions drive the north loop, odd ones the south loop, so two
    consecutive sessions are >1 km apart and the frontend splits them.
    """
    circuito = _CIRCUITOS[sesion % 2]
    s = VELOCIDAD_BASE_MS * tau + AMPLITUD_M * math.sin(2 * math.pi * tau / PERIODO_S)
    lat, lon = circuito.posicion(s % circuito.longitud)
    # Jitter seeded by (session, sample) so it never depends on call order
    rng = random.Random(SEMILLA * 1_000_003 + sesion * 10_007 + int(tau))
    return _desplazar(lat, lon, rng.gauss(0, 2.5), rng.gauss(0, 2.5))


def _viaje_en_vivo(ahora):
    """Rows of the live sessions of today (from 05:00) up to 'ahora'."""
    sesion_actual = int((ahora - _EPOCA).total_seconds()) // SESION_S
    limite = datetime(ahora.year, ahora.month, ahora.day, INICIO_VIVO_HORA)
    filas = []
    sesion = sesion_actual
    while True:
        inicio = _EPOCA + timedelta(seconds=sesion * SESION_S)
        if sesion != sesion_actual and inicio < limite:
            break
        fin = min(ahora, inicio + timedelta(seconds=CONDUCCION_S))
        pasos = int((fin - inicio).total_seconds()) // INTERVALO_S
        bloque = [_fila(DEVICE_PRINCIPAL, inicio + timedelta(seconds=k * INTERVALO_S),
                        *_posicion_viva(sesion, k * INTERVALO_S))
                  for k in range(pasos + 1)]
        filas = bloque + filas
        sesion -= 1
    return filas


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def _fila(device_id, timestamp, lat, lon):
    return {
        "device_id": device_id,
        "ip_origen": IP_DEMO,
        "latitud": round(lat, 6),
        "longitud": round(lon, 6),
        "timestamp_gps": timestamp,
        "timestamp_recepcion": timestamp + timedelta(seconds=1),
    }


def puntos_demo(ahora):
    """Every demo row with timestamp_gps <= ahora, ordered by timestamp_gps.

    'ahora' is a naive Bogota datetime. Rows get a sequential id, mimicking
    the SERIAL column of the real table.
    """
    filas = [f for f in _viajes_historicos(ahora.date()) if f["timestamp_gps"] <= ahora]
    filas += _viaje_en_vivo(ahora)
    filas.sort(key=lambda f: f["timestamp_gps"])
    return [dict(f, id=i) for i, f in enumerate(filas, start=1)]
