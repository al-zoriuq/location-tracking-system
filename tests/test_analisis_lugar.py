import math
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analisis_lugar import (  # noqa: E402
    M_POR_GRADO,
    analizar_pasos,
    caja_circulo,
    filas_con_vecinos,
    filtrar_por_caja,
    haversine_m,
    interseccion_segmento_circulo,
    punto_mas_cercano,
)

CENTRO = (11.0190, -74.8505)  # Universidad del Norte
T0 = datetime(2026, 9, 20, 8, 0, 0)
V_60_KMH = 60 / 3.6  # 16.67 m/s -> 166.7 m every 10 s


def coord(este_m, norte_m):
    """Point a few meters east/north of CENTRO (inverse of the projection)."""
    lat = CENTRO[0] + norte_m / M_POR_GRADO
    lon = CENTRO[1] + este_m / (M_POR_GRADO * math.cos(math.radians(CENTRO[0])))
    return lat, lon


def punto(este_m, norte_m, segundos):
    return (*coord(este_m, norte_m), T0 + timedelta(seconds=segundos))


def pasos(puntos, radio):
    return analizar_pasos(filas_con_vecinos(puntos), *CENTRO, radio)


def cruce(inicio_s, sentido=1):
    """West->east (or east->west) crossing through the center at 60 km/h,
    sampled every 10 s so the center falls exactly between two samples:
    the closest samples are 83.3 m away."""
    paso = V_60_KMH * 10
    xs = [-1.5 * paso, -0.5 * paso, 0.5 * paso, 1.5 * paso]
    if sentido < 0:
        xs.reverse()
    return [punto(x, 0, inicio_s + 10 * i) for i, x in enumerate(xs)]


# ------------------------------------------------------- pure geometry

def test_haversine_un_grado_de_latitud():
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-4)


def test_interseccion_por_el_centro():
    # From x=-100 to x=+100 with r=50: enters at t=0.25, leaves at t=0.75
    assert interseccion_segmento_circulo((-100, 0), (100, 0), 50) == pytest.approx((0.25, 0.75))


def test_interseccion_segmento_dentro_del_circulo():
    assert interseccion_segmento_circulo((-10, 0), (10, 0), 50) == (0.0, 1.0)


def test_interseccion_recta_corta_pero_segmento_no_llega():
    # The line would hit the circle, but the segment stops 150 m before it
    assert interseccion_segmento_circulo((-300, 0), (-200, 0), 50) is None


def test_interseccion_recta_que_no_toca():
    assert interseccion_segmento_circulo((-100, 60), (100, 60), 50) is None


def test_punto_mas_cercano_en_medio():
    t, d = punto_mas_cercano((-100, 30), (100, 30))
    assert t == pytest.approx(0.5) and d == pytest.approx(30)


# ------------------------------------------------------------- scenarios

def test_cruce_sin_ningun_punto_adentro():
    puntos = cruce(0)
    radio = 50
    assert all(haversine_m(lat, lon, *CENTRO) > radio for lat, lon, _ in puntos)

    resultado = pasos(puntos, radio)

    assert len(resultado) == 1
    p = resultado[0]
    # Segment 10 s -> 20 s goes from x=-83.3 to x=+83.3 at 16.67 m/s:
    # enters at x=-50 after 2 s, leaves at x=+50 after 8 s
    assert p["entrada"] == T0 + timedelta(seconds=12)
    assert p["salida"] == T0 + timedelta(seconds=18)
    assert p["momento_mas_cercano"] == T0 + timedelta(seconds=15)
    assert p["duracion_s"] == 6
    assert p["distancia_minima_m"] == pytest.approx(0, abs=0.1)
    assert p["puntos"] == 0
    assert p["tipo"] == "paso"


def test_segmento_que_no_toca_el_circulo():
    puntos = [punto(x, 60, i * 10) for i, x in enumerate((-250, -83, 83, 250))]
    assert pasos(puntos, 50) == []


def test_punto_aislado_adentro_cuenta():
    puntos = [
        punto(5000, 0, -2 * 3600),   # 2 h before, 5 km away
        punto(10, 0, 0),             # alone inside the circle
        punto(-5000, 0, 2 * 3600),   # 2 h after, 5 km away
    ]
    resultado = pasos(puntos, 50)
    assert len(resultado) == 1
    assert resultado[0]["entrada"] == resultado[0]["salida"] == T0
    assert resultado[0]["puntos"] == 1
    assert resultado[0]["duracion_s"] == 0
    assert resultado[0]["distancia_minima_m"] == pytest.approx(10, abs=0.1)


def test_punto_unico_sin_vecinos_cuenta():
    assert len(pasos([punto(0, 0, 0)], 50)) == 1


def test_dos_cruces_a_5_minutos_son_un_paso():
    # Goes east, U-turns 250 m away and comes back 5 minutes later
    puntos = cruce(0) + cruce(300, sentido=-1)
    resultado = pasos(puntos, 50)
    assert len(resultado) == 1
    # Entry to exit lasts > 5 min, but only 2 x 6 s were spent inside the
    # circle: it is a pass, not a stop
    assert resultado[0]["duracion_s"] >= 300
    assert resultado[0]["tipo"] == "paso"


def test_dos_cruces_a_30_minutos_son_dos_pasos():
    puntos = cruce(0) + cruce(1800, sentido=-1)
    resultado = pasos(puntos, 50)
    assert len(resultado) == 2
    assert resultado[0]["entrada"] < resultado[1]["entrada"]  # chronological


def test_estancia_de_8_minutos_es_parada():
    llegada = [punto(-300 + 50 * i, 0, 10 * i) for i in range(6)]          # x=-300..-50
    quieto = [punto(3 * ((-1) ** i), 2, 60 + 10 * i) for i in range(49)]    # 8 min near center
    salida = [punto(50 * i, 0, 60 + 490 + 10 * i) for i in range(1, 7)]    # x=50..300
    resultado = pasos(llegada + quieto + salida, 50)

    assert len(resultado) == 1
    p = resultado[0]
    assert p["tipo"] == "parada"
    assert 480 <= p["duracion_s"] <= 520
    assert p["puntos"] >= 49


def test_salto_imposible_ignorado():
    # Driving 2 km north of the place, with one GPS fix that jumps onto it
    puntos = [punto(-500 + 140 * i, 2000, 10 * i) for i in range(8)]
    lat, lon = coord(0, 0)
    puntos[4] = (lat, lon, puntos[4][2])
    assert pasos(puntos, 50) == []


def test_filtro_por_caja_no_cambia_el_resultado():
    puntos = [punto(x, 0, i * 10) for i, x in enumerate(range(-3000, 3001, 150))]
    radio = 50
    completas = filas_con_vecinos(puntos)
    filtradas = filtrar_por_caja(completas, caja_circulo(*CENTRO, radio))
    assert 0 < len(filtradas) < len(completas)
    assert analizar_pasos(filtradas, *CENTRO, radio) == analizar_pasos(completas, *CENTRO, radio)
