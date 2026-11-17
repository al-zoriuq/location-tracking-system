# pipeline_pi.py
# Dos etapas en Raspberry Pi Zero 2 W, con la misma logica que la ESP32 (detector_envio.ino):
#   1) detector FOMO (detector.eim, 96x96 RGB, etiqueta "senal") -> donde esta la senal
#   2) borde rojo real + clasificador (clasificador.eim, 48x48 grises) -> que senal es
#   3) filtro de forma (PARE / CEDA / LIMITE), umbral por clase, confirmacion en
#      2 cuadros seguidos y votacion: se reporta UNA vez cada senal fisica
#   3b) OCR propio (ocr_limite.py -> ocr_digitos.py + ocr_digitos_modelo.npz, solo
#      OpenCV y NumPy) lee el numero de los limites. El OCR va PRIMERO: si lee un
#      valor valido gana; si no lee, queda el numero del clasificador; si no, "LIMITE".
#      Rendimiento: no lee senales muy pequenas (OCR_MIN_PX) y, cuando el mismo numero
#      ya salio OCR_LECTURAS_SUFICIENTES veces en la misma senal, lo reutiliza.
#   4) mensaje con el MISMO formato que la ESP32 (Device, Lat, Lon, Timestamp GPS,
#      Senal, Conf, Vel GPS, Vel MPU, Usa, SI/EXCEDE/NA) y envio UDP opcional al sniffer
# Monitor en el navegador (http://raspberrypi.local:8000): video con las cajas en los
# colores del visor de la ESP32, panel de rendimiento/CPU/RAM, senales confirmadas y log.
# Guarda tiempos_pipeline.csv y eventos.csv (con la linea de cada deteccion).
#
# Uso:  source ~/ei-env/bin/activate
#       python pipeline_pi.py ~/detector.eim ~/clasificador.eim              # solo monitor
#       python pipeline_pi.py ~/detector.eim ~/clasificador.eim --udp       # con GPS + envio
#       python pipeline_pi.py ... --udp --pos 11.0196,-74.8234                # envio sin GPS (prueba)
#       python pipeline_pi.py ~/detector.eim ~/clasificador.eim --celular 5000 --udp --device-celular
#                                                         # ubicacion desde la app (lo que corre el servicio)
# GPS: modulo NMEA por serial (--gps /dev/serial0, --baudios 9600).
# MPU6050: I2C bus 1 (pin 3 SDA, pin 5 SCL, 3.3 V), velocidad de respaldo como la ESP32.
# Dependencias extra: pip install pyserial smbus2 flask
# Activar en la Pi: sudo raspi-config -> Interface Options -> Serial Port
#   (login por serial: NO, puerto serial: SI) e I2C: SI; reiniciar.
#
# Original: compañera de equipo. Ajustes 07/11/2026 para igualarlo a la ESP32; monitor, mensaje, GPS y MPU 09/11.
# 10/11: OCR propio (sin Tesseract), OCR primero, cache de OCR por senal, tiempos del OCR
#        en el monitor y en tiempos_pipeline.csv.
# 10/11 (manana): el ZUPT ya no renueva la confianza del MPU; solo un fix del GPS lo hace.
#        Sin GPS, el MPU deja de usarse a los 10 s (Usa: NA) en vez de usarse para siempre.
#
# Hora de las detecciones: "Timestamp GPS" = hora del ultimo fix + su edad (la hora de la
# deteccion). Si la posicion tiene mas de 30 s se agrega "pos-Ns". El sniffer NO le suma
# la edad a la hora (solo guarda "pos-Ns" en el campo extra), asi que no hay doble conteo.
#
# 16/11: MODO CELULAR (--celular 5000): la ubicacion la manda la app GPSLink por UDP al puerto
#        5000 de la Pi (ya no se usa la antena NEO-6M). Comandos de la app: CMD,PAUSA /
#        CMD,REANUDA / CMD,APAGAR / CMD,ESTADO, respuesta EST,<device>,<estado>,<senales>.
#        --device-celular: las detecciones salen con el Device de la app (envio doble).
#        --reenviar: alternativa (modo unificado) en la que la Pi reenvia la ruta.
#        Mensaje: Device por defecto ESP32S3-SIM7670G y Timestamp sin fracciones.
#        Servidor: 52.71.39.197:5000 (sniffer de produccion).
# 16/11 (noche): la posicion se reenvia en un hilo aparte y un vigilante cierra el
#        programa si la camara no entrega cuadros en 20 s (systemd lo reabre).

import argparse
import csv
import socket
import subprocess
import re
import math
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

# ---------------------------------------------------------------- ajustes
# (mismos valores que la ESP32; ver ESTADO_PROYECTO_P3.md, seccion 8)
RESOLUCION = (640, 480)
ZONA = "derecha"          # "derecha" (como la ESP32: las senales van a la derecha) o "centro"

UMBRAL_FOMO = 0.5         # score minimo de una caja "senal"
ETIQUETA_FOMO = "senal"
MARGEN_BORDE = 2          # px (en 96x96): cajas que tocan el borde de la zona se descartan
MAX_CAJAS = 3             # cajas por cuadro que se clasifican (CPU de la Pi Zero)

UMBRAL_LIMITE = 0.7
UMBRAL_PARE = 0.5
UMBRAL_CEDA = 0.7
CONF_UNA_ESCALA = 0.95    # si el 1.er recorte ya da esto, no se prueba el 2.o
CONF_UN_CUADRO = 0.99     # con esto basta 1 cuadro (si no, 2 cuadros seguidos)
FACTORES_RECORTE = (1.2, 1.45)   # recorte = borde rojo x factor

# Clase unica "limite": el clasificador solo dice "es un limite" y el numero lo lee
# el OCR (leer_numero). Sirve con el modelo nuevo (etiqueta "limite") y con el viejo
# de 14 clases: si JUNTAR_LIMITES es True, se suman las probabilidades de 10..120.
JUNTAR_LIMITES = True
# OCR del numero. Prioridad del valor: 1) lectura valida del OCR, 2) numero del
# clasificador (NUMERO_CLASIFICADOR), 3) "LIMITE" sin numero.
# Se activa solo si existe ocr_limite.py (misma carpeta) con leer_numero(recorte_bgr).
OCR_ACTIVO = False
# Con el modelo de 14 clases y JUNTAR_LIMITES, el mejor numero del clasificador se usa
# si el OCR no leyo nada (o no hay OCR). False = "LIMITE" sin numero.
NUMERO_CLASIFICADOR = True
# Valores de limite que se aceptan del OCR
VALORES_VALIDOS = {"10", "20", "30", "40", "50", "60", "70", "80", "90", "100", "120"}
# Rendimiento del OCR
OCR_MIN_PX = 36               # borde rojo de menos px (senal lejana): no se lee (de lejos se equivoca mas)
OCR_LECTURAS_SUFICIENTES = 3  # mismo numero leido 3 veces en la misma senal: se reutiliza sin leer
OCR_REVISAR_S = 1.0           # ... pero se vuelve a leer al menos cada 1 s (si cambia, se anula)
OCR_NO_LIMITE_MIN = 2         # el OCR leyo "peso/altura" (10T, 3.5M) 2+ veces en la senal: se descarta

VOTOS_REPORTE = 3         # votos para reportar una senal
VOTOS_MINIMO = 2          # si la senal se va antes, se reporta la de mas votos con este minimo
FIN_EVENTO_S = 2.5        # s sin ver senales = fin del evento
NO_REPETIR_S = 15.0       # la misma clase no se reporta otra vez antes de esto

# Filtro de forma (revisar_forma en la ESP32)
ASPECTO_MIN, ASPECTO_MAX = 0.7, 1.45
PARE_RELLENO_MIN = 0.40
PARE_TEXTO_MIN = 0.60
PARE_LETRAS_MIN = 0.12
PARE_CENTRO_ROJO_MAX = 0.90
CEDA_BLANCO_MIN = 0.25
CEDA_TRIANGULO = 1.4      # rojo arriba >= 1.4 x rojo abajo (triangulo invertido)
LIMITE_BLANCO_MIN = 0.25
LIMITE_CENTRO_ROJO_MAX = 0.30

PUERTO = 8000
VIDEO_FPS = 5             # imagenes/s que comprime el monitor; 0 = sin video (el panel sigue)
RESUMEN_CADA = 5.0

ultimo_jpg = None
t_cliente = 0.0           # ultima vez que un navegador pidio video (sin nadie mirando no se comprime)
candado = threading.Lock()
REENVIAR = False          # --reenviar: la Pi reenvia al servidor la posicion de la app
MODO_CELULAR = False      # --celular: la posicion la manda la app (no se reenvia cada 10 s)
ULTIMO_CUADRO = 0.0       # time.monotonic() del ultimo cuadro de la camara (vigilante)
CAMARA_MAX_S = 20.0       # sin cuadros este tiempo -> se cierra y systemd lo reinicia
PAUSADO = False           # CMD,PAUSA desde la app: no se procesan cuadros
N_EVENTOS = 0             # senales reportadas (para EST,...)
POS_FIJA = None           # (lat, lon[, km/h]) de --pos (pruebas sin GPS)


# ---------------------------------------------------------------- color
def es_rojo(bgr, flojo=False):
    """Rojo como en la ESP32 (en RGB, no en HSV):
    normal: r >= 60 y r - max(g, b) >= 22
    flojo (atardecer / contraluz, borde rosado): r >= 50 y r - max(g, b) >= 12"""
    b = bgr[..., 0].astype(np.int16)
    g = bgr[..., 1].astype(np.int16)
    r = bgr[..., 2].astype(np.int16)
    dif = r - np.maximum(g, b)
    if flojo:
        return (r >= 50) & (dif >= 12)
    return (r >= 60) & (dif >= 22)


def es_claro(bgr, brillo_rojo):
    """Blanco fijo (>150 en los tres canales) o blanco RELATIVO: poco saturado y al
    menos 25 niveles mas brillante que el rojo de la misma senal (sombra, poca luz)."""
    c = bgr.astype(np.int16)
    mn, mx = c.min(axis=2), c.max(axis=2)
    brillo = c.mean(axis=2)
    fijo = mn > 150
    relativo = ((mx - mn) <= 50) & (brillo >= brillo_rojo + 25)
    return fijo | relativo


# ---------------------------------------------------------------- borde rojo
def _buscar_componente(frame_bgr, cx, cy, ventana, flojo):
    alto, ancho = frame_bgr.shape[:2]
    x0, y0 = max(cx - ventana // 2, 0), max(cy - ventana // 2, 0)
    x1, y1 = min(cx + ventana // 2, ancho), min(cy + ventana // 2, alto)
    sub = frame_bgr[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    mascara = es_rojo(sub, flojo).astype(np.uint8)
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, etiquetas, stats, centros = cv2.connectedComponentsWithStats(mascara, connectivity=8)
    lx, ly = cx - x0, cy - y0
    area_min = max(40, int(0.002 * sub.shape[0] * sub.shape[1]))

    # El centro del FOMO suele caer en el interior blanco de la senal, asi que se
    # toma la region roja mas grande cuyo recuadro contiene el centro; si ninguna
    # lo contiene, la mas cercana (a menos de 1/3 de la ventana).
    contienen, cercanas = [], []
    for k in range(1, n):
        x, y, w, h, area = stats[k]
        if area < area_min:
            continue
        if x <= lx <= x + w and y <= ly <= y + h:
            contienen.append((area, k))
        else:
            d = float(np.hypot(centros[k][0] - lx, centros[k][1] - ly))
            if d < ventana / 3:
                cercanas.append((d, k))
    if contienen:
        mejor = max(contienen)[1]
    elif cercanas:
        mejor = min(cercanas)[1]
    else:
        return None
    x, y, w, h, _ = stats[mejor]
    toca = bool(x == 0 or y == 0 or x + w >= sub.shape[1] or y + h >= sub.shape[0])
    comp = etiquetas[y:y + h, x:x + w] == mejor
    return {"bbox": (int(x0 + x), int(y0 + y), int(w), int(h)), "comp": comp, "flojo": flojo, "toca": toca}


def medir_senal_roja(frame_bgr, cx, cy, ventana):
    """Region roja conectada alrededor de (cx, cy): tamano real de la senal.
    Primero rojo normal; si no hay, rojo flojo. Si la region toca el borde de la
    ventana (senal cercana y grande) se repite con una ventana del doble."""
    max_ventana = min(frame_bgr.shape[:2])
    for flojo in (False, True):
        v = ventana
        while True:
            res = _buscar_componente(frame_bgr, cx, cy, v, flojo)
            if res is None or not res["toca"] or v >= max_ventana:
                break
            v = min(v * 2, max_ventana)
        if res is not None:
            return res
    return None


def medir_forma(frame_bgr, senal):
    """Medidas de color y forma sobre el recuadro de la region roja (medir_forma en la ESP32)."""
    x, y, w, h = senal["bbox"]
    sub = frame_bgr[y:y + h, x:x + w]
    comp = senal["comp"]
    rojo = es_rojo(sub, senal["flojo"])
    brillo_rojo = float(sub.astype(np.int16).mean(axis=2)[comp].mean())
    claro = es_claro(sub, brillo_rojo)

    cy0, cy1 = int(0.3 * h), max(int(0.7 * h), int(0.3 * h) + 1)
    cx0, cx1 = int(0.3 * w), max(int(0.7 * w), int(0.3 * w) + 1)
    by0, by1 = int(0.35 * h), max(int(0.65 * h), int(0.35 * h) + 1)
    bx0, bx1 = int(0.1 * w), max(int(0.9 * w), int(0.1 * w) + 1)
    cuarto = max(h // 4, 1)
    banda = claro[by0:by1, bx0:bx1]
    return {
        "aspecto": w / h if h else 0.0,
        "relleno": float(comp.mean()),
        "rojo_centro": float(rojo[cy0:cy1, cx0:cx1].mean()),
        "claro_centro": float(claro[cy0:cy1, cx0:cx1].mean()),
        "banda_texto": float(banda.any(axis=0).mean()),
        "letras": float(banda.mean()),
        "rojo_arriba": float(comp[:cuarto].mean()),
        "rojo_abajo": float(comp[-cuarto:].mean()),
    }


def tipo_de(clase):
    if clase == "limite" or clase.isdigit():
        return "limite"
    if clase in ("pare", "ceda"):
        return clase
    return "otro"          # otro, otro_rojos, ... nunca se reportan


def revisar_forma(clase, m):
    """La clase tiene que cuadrar con lo que se ve. Devuelve None si pasa, o el motivo."""
    if m is None:
        return "sin_rojo"
    if not ASPECTO_MIN <= m["aspecto"] <= ASPECTO_MAX:
        return "aspecto"
    t = tipo_de(clase)
    if t == "pare":
        if m["relleno"] < PARE_RELLENO_MIN:
            return "pare_hueco"
        if m["banda_texto"] < PARE_TEXTO_MIN:
            return "sin_texto"
        if m["letras"] < PARE_LETRAS_MIN or m["rojo_centro"] > PARE_CENTRO_ROJO_MAX:
            return "sin_letras"
    elif t == "ceda":
        if m["claro_centro"] < CEDA_BLANCO_MIN:
            return "ceda_lleno"
        if m["rojo_arriba"] < CEDA_TRIANGULO * m["rojo_abajo"]:
            return "no_triang"
    elif t == "limite":
        if m["rojo_centro"] > LIMITE_CENTRO_ROJO_MAX:
            return "no_aro"
        if m["claro_centro"] < LIMITE_BLANCO_MIN:
            return "sin_blanco"
    return None


def umbral_de(clase):
    t = tipo_de(clase)
    return {"limite": UMBRAL_LIMITE, "pare": UMBRAL_PARE, "ceda": UMBRAL_CEDA}.get(t, 2.0)


def nombre_senal(clase):
    t = tipo_de(clase)
    if t == "limite":
        return f"LIMITE {clase}" if clase.isdigit() else "LIMITE"
    return t.upper()


def juntar_limites(p):
    """{'10': .1, '50': .7, 'pare': .1, ...} -> {'limite': .8, 'pare': .1, ...}"""
    q = {}
    for clase, v in p.items():
        k = "limite" if clase.isdigit() else clase
        q[k] = q.get(k, 0.0) + float(v)
    return q


def leer_numero(recorte_bgr):
    """OCR del valor del limite (ocr_limite.py). Recibe el recorte de la senal en BGR
    (1.2x el borde rojo) y devuelve el numero como texto ("50"), un texto que no es
    limite ("10T") o None. Si devuelve None queda el numero del clasificador o "LIMITE"."""
    return None


try:
    from ocr_limite import leer_numero          # noqa: F811  OCR propio del equipo
    OCR_ACTIVO = True
    print("[OCR] activo (ocr_limite.py)", flush=True)
except ImportError as e:
    print(f"[OCR] desactivado ({e}): se usa el numero del clasificador", flush=True)


def interpretar_ocr(texto):
    """Lectura del OCR -> ("valor", "50") si es un limite valido,
    ("no_limite", txt) si es claramente otra senal (peso "10t", altura "3.5m", "4.50"),
    o ("nada", None) si no se pudo leer (se sigue con el clasificador)."""
    if texto is None:
        return "nada", None
    t = str(texto).strip().upper().replace(" ", "")
    if not t:
        return "nada", None
    sin_kmh = t.replace("KM/H", "").replace("KMH", "")
    if any(ch in sin_kmh for ch in ".,TM"):
        return "no_limite", t
    digitos = "".join(ch for ch in sin_kmh if ch.isdigit())
    if digitos in VALORES_VALIDOS:
        return "valor", digitos
    return "nada", None


def decidir_numero(frame_bgr, bbox, clase, num_cls, evento=None, usar_cache=False):
    """Valor de una senal de limite ya validada por el clasificador y el filtro de forma.
    Prioridad: 1) lectura valida del OCR, 2) numero del clasificador, 3) "limite".
    evento: lleva la cuenta de lo que el OCR leyo en la senal actual.
    usar_cache: solo si hay UN limite en el cuadro (dos senales nunca comparten numero).
    Devuelve (clase, valida, motivo, info_ocr) ; info_ocr = {"ms", "txt"} o None."""
    valida, motivo, info = True, None, None
    if OCR_ACTIVO:
        seguro = evento.ocr_seguro() if (evento is not None and usar_cache) else None
        x, y, w, h = bbox
        if seguro is not None:
            clase, info = seguro, {"ms": 0.0, "txt": f"{seguro}(cache)"}
        elif max(w, h) < OCR_MIN_PX:
            info = {"ms": 0.0, "txt": "pequena"}           # muy lejos: queda el clasificador
        else:
            rec, _ = recorte_cuadrado(frame_bgr, bbox, FACTORES_RECORTE[0])
            t0 = time.perf_counter()
            texto = leer_numero(rec)
            info = {"ms": (time.perf_counter() - t0) * 1000, "txt": str(texto)}
            if evento is not None:
                evento.ocr_intento()
            tipo_ocr, lectura = interpretar_ocr(texto)
            if tipo_ocr == "valor":
                clase = lectura
                if evento is not None:
                    evento.ocr_leido(lectura)
            elif tipo_ocr == "no_limite":
                # peso ("10t") o altura ("3.5m"): no es un limite
                valida, motivo = False, f"ocr_{lectura}"
                if evento is not None:
                    evento.ocr_no_limite()
            # "nada": no se pudo leer; queda el clasificador ("50" o "limite")
    if valida and clase == "limite" and NUMERO_CLASIFICADOR and num_cls:
        clase = num_cls          # sin lectura del OCR: numero del clasificador
    return clase, valida, motivo, info


# ---------------------------------------------------------------- entradas de los modelos
def zona_deteccion(ancho, alto):
    lado = min(ancho, alto)
    zx = ancho - lado if ZONA == "derecha" else (ancho - lado) // 2
    zy = (alto - lado) // 2
    return zx, zy, lado


def features_de(img, canales):
    """Empaqueta los pixeles como los espera Edge Impulse (0xRRGGBB por pixel).
    img: RGB (H, W, 3) si canales == 3, o gris (H, W) si canales == 1.
    Se hace aqui y no con get_features_from_image para controlar el recorte y la
    conversion a gris (el SDK pasa a gris con COLOR_BGR2GRAY aunque le den RGB)."""
    if canales == 1:
        p = img.astype(np.uint32)
        return (p * 0x010101).flatten().tolist()
    p = img.astype(np.uint32)
    return ((p[..., 0] << 16) | (p[..., 1] << 8) | p[..., 2]).flatten().tolist()


def recorte_cuadrado(img, bbox, factor):
    """Recorte cuadrado centrado en el borde rojo, lado = max(w, h) * factor.
    Si se sale de la imagen se rellena repitiendo el borde (no se corre el centro)."""
    x, y, w, h = bbox
    lado = max(int(round(max(w, h) * factor)), 8)
    cx, cy = x + w / 2, y + h / 2
    x0, y0 = int(round(cx - lado / 2)), int(round(cy - lado / 2))
    x1, y1 = x0 + lado, y0 + lado
    alto, ancho = img.shape[:2]
    pad = (max(0, -y0), max(0, y1 - alto), max(0, -x0), max(0, x1 - ancho))
    rec = img[max(y0, 0):min(y1, alto), max(x0, 0):min(x1, ancho)]
    if any(pad):
        rec = cv2.copyMakeBorder(rec, *pad, cv2.BORDER_REPLICATE)
    return rec, (x0, y0, x1, y1)


def clasificar_senal(cls, info, frame_bgr, frame_gris, bbox):
    """Clasifica en 1 o 2 tamanos (1.2x y 1.45x). Si se prueban los dos, gana la
    clase que coincide en ambos, o la de mayor confianza."""
    w_in, h_in, canales = info
    base = frame_gris if canales == 1 else cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    resultados, t_ms, caja, numeros = [], 0, None, []
    for factor in FACTORES_RECORTE:
        rec, caja_f = recorte_cuadrado(base, bbox, factor)
        rec = cv2.resize(rec, (w_in, h_in), interpolation=cv2.INTER_AREA)
        r = cls.classify(features_de(rec, canales))
        t_ms += r["timing"]["dsp"] + r["timing"]["classification"]
        p = r["result"]["classification"]
        digitos = {k: v for k, v in p.items() if k.isdigit()}
        if digitos:                       # modelo de 14 clases: su mejor numero (respaldo del OCR)
            numeros.append(max(digitos, key=digitos.get))
        if JUNTAR_LIMITES:
            p = juntar_limites(p)
        clase = max(p, key=p.get)
        resultados.append((clase, float(p[clase])))
        if caja is None:
            caja = caja_f
        if p[clase] >= CONF_UNA_ESCALA:
            break
    if len(resultados) == 2 and resultados[0][0] == resultados[1][0]:
        clase, conf = resultados[0][0], max(resultados[0][1], resultados[1][1])
    else:
        clase, conf = max(resultados, key=lambda c: c[1])
    return clase, conf, t_ms, caja, len(resultados), (numeros[0] if numeros else None)


# ---------------------------------------------------------------- confirmacion y votacion
def llave_de(clase):
    """Todas las lecturas de limite (50, 30, "limite") son la MISMA senal para la
    confirmacion y la votacion; el valor se decide al reportar."""
    return "limite" if tipo_de(clase) == "limite" else clase


class Evento:
    """Una senal fisica se ve en muchos cuadros: cada confirmacion es un voto y se
    reporta UNA sola senal (evento_voto / evento_tick en la ESP32).
    Para los limites se suman los votos de todas las lecturas y al reportar gana el
    numero con mas votos (OCR o clasificador); "LIMITE" sin numero solo si no hubo
    ninguno. Con OCR_ACTIVO se espera a tener al menos un numero antes de reportar
    (o al final del evento)."""

    def __init__(self, reportar):
        self.reportar = reportar
        self.votos, self.conf = {}, {}
        self.reportado = set()      # llaves ya reportadas en este evento (pare, limite...)
        self.t_visto = 0.0
        self.t_ultimo_reporte = {}
        self.ocr = {}               # numero -> veces que el OCR lo leyo en este evento
        self.ocr_no = 0             # veces que el OCR leyo algo que NO es limite (10T, 3.5M)
        self.t_ocr = 0.0            # ultima lectura REAL del OCR (no del cache)

    def visto(self, ahora):
        self.t_visto = ahora

    def ocr_leido(self, numero):
        """Cuenta las lecturas validas del OCR en la senal actual."""
        self.ocr[numero] = self.ocr.get(numero, 0) + 1

    def ocr_no_limite(self):
        """El OCR leyo peso/altura en la senal actual."""
        self.ocr_no += 1

    def _es_peso_o_altura(self):
        """La senal 'limite' es en realidad de peso/altura: el OCR lo leyo varias veces
        y al menos tantas veces como leyo un limite valido."""
        return self.ocr_no >= OCR_NO_LIMITE_MIN and self.ocr_no >= sum(self.ocr.values())

    def ocr_intento(self):
        """Marca que se hizo una lectura real del OCR (valga o no)."""
        self.t_ocr = time.monotonic()

    def ocr_seguro(self):
        """Numero que el OCR ya leyo OCR_LECTURAS_SUFICIENTES veces en esta senal (y
        ningun otro numero), o None. Sirve para no volver a leer en cada cuadro.
        Cada OCR_REVISAR_S se exige una lectura real: si sale otro numero, el cache
        se anula solo (ya hay dos numeros distintos)."""
        if time.monotonic() - self.t_ocr >= OCR_REVISAR_S:
            return None
        if len(self.ocr) == 1:
            numero, veces = next(iter(self.ocr.items()))
            if veces >= OCR_LECTURAS_SUFICIENTES:
                return numero
        return None

    def _total(self, llave):
        return sum(v for c, v in self.votos.items() if llave_de(c) == llave)

    def _elegir(self, llave):
        if llave != "limite":
            return llave
        numeros = [c for c in self.votos if c.isdigit()]
        if numeros:
            # Gana el numero que el OCR leyo mas veces; despues, el de mas votos
            # (asi el numero del clasificador en cuadros lejanos no le gana al OCR)
            return max(numeros, key=lambda c: (self.ocr.get(c, 0), self.votos[c], self.conf[c]))
        return "limite"

    def voto(self, clase, conf, ahora):
        self.votos[clase] = self.votos.get(clase, 0) + 1
        self.conf[clase] = max(self.conf.get(clase, 0.0), conf)
        llave = llave_de(clase)
        if llave in self.reportado or self._total(llave) < VOTOS_REPORTE:
            return
        elegida = self._elegir(llave)
        if llave == "limite" and OCR_ACTIVO and self._total(llave) < 2 * VOTOS_REPORTE:
            # Esperar unos cuadros mas al OCR si: todavia no hay numero, el numero solo
            # viene del clasificador (el OCR no lo ha confirmado) o el OCR ya vio peso/altura
            if not elegida.isdigit() or elegida not in self.ocr or self.ocr_no:
                return
        if llave == "limite" and self._es_peso_o_altura():
            return          # se decide al final del evento (tick)
        self._reportar(elegida, ahora)

    def tick(self, ahora):
        if ahora - self.t_visto < FIN_EVENTO_S:
            return
        if not self.votos:
            # Sin votos (p. ej. una senal de peso que el OCR rechazo en todos los cuadros):
            # igual se limpia lo que leyo el OCR para que no pase a la siguiente senal
            self.ocr, self.ocr_no, self.t_ocr = {}, 0, 0.0
            return
        # Un PARE y un limite en el mismo poste son dos senales: cada una se reporta
        for llave in {llave_de(c) for c in self.votos} - self.reportado:
            if llave == "limite" and self._es_peso_o_altura():
                log(f"[RECHAZO] senal descartada: el OCR leyo peso/altura {self.ocr_no} veces "
                    f"(limites validos: {sum(self.ocr.values())})")
                continue
            if self._total(llave) >= VOTOS_MINIMO:
                self._reportar(self._elegir(llave), ahora)
        self.votos, self.conf, self.reportado, self.ocr, self.ocr_no, self.t_ocr = {}, {}, set(), {}, 0, 0.0

    def _reportar(self, clase, ahora):
        self.reportado.add(llave_de(clase))
        if ahora - self.t_ultimo_reporte.get(clase, -1e9) < NO_REPETIR_S:
            return
        self.t_ultimo_reporte[clase] = ahora
        conf = max(v for c, v in self.conf.items() if llave_de(c) == llave_de(clase))
        self.reportar(clase, conf, dict(self.votos))


# ---------------------------------------------------------------- mensaje (mismo formato que la ESP32)
# Detección:
#   Device: RPIZERO2W, Lat: 11.019607, Lon: -74.823385, Timestamp GPS: 2026-11-09 16:41:48.000000 -0500,
#   Senal: LIMITE, Conf: 0.98, Vel GPS: NA, Vel MPU: NA, Usa: NA, NA
# Posición (cada 10 s): la misma línea hasta "Timestamp GPS".
# Sin OCR el límite va como "LIMITE" sin número, y el cumplimiento como NA.
# Con OCR va "LIMITE 50" y, si hay velocidad, SI / EXCEDE (límite + 3 km/h).
DEVICE_ID = "ESP32S3-SIM7670G"
SERVIDOR_UDP = ("52.71.39.197", 5000)
POS_CADA_S = 10.0
TOLERANCIA_KMH = 3
ZONA_COL = timezone(timedelta(hours=-5))


VEL_GPS_MAX_EDAD_S = 3.0   # la velocidad GPS se usa si el fix tiene <= 3 s (como la ESP32)
POS_VIEJA_S = 30.0         # posicion de mas de 30 s -> campo extra "pos-Ns"
MPU_MAX_SIN_GPS_S = 10.0   # sin un fix GPS en este tiempo, la velocidad del MPU no se usa (NA)
MPU_VEL_MAX_KMH = 180.0    # mas que esto es error de integracion -> NA y se reinicia
QUIETO_STD = 0.12          # m/s2: desviacion de la aceleracion por debajo = carro quieto
QUIETO_S = 1.5             # ... durante este tiempo -> velocidad 0 y nuevo sesgo (ZUPT)


# ---------------------------------------------------------------- GPS (modulo NMEA por serial)
def _nmea_ok(linea):
    """Verifica el checksum *XX de una sentencia NMEA."""
    if not linea.startswith("$") or "*" not in linea:
        return False
    cuerpo, _, chk = linea[1:].partition("*")
    x = 0
    for ch in cuerpo:
        x ^= ord(ch)
    try:
        return x == int(chk[:2], 16)
    except ValueError:
        return False


def _grados(valor, hemi):
    """ddmm.mmmm / dddmm.mmmm -> grados decimales."""
    if not valor:
        return None
    p = valor.index(".")
    g = float(valor[:p - 2]) + float(valor[p - 2:]) / 60
    return -g if hemi in ("S", "W") else g


class GPS(threading.Thread):
    """Lee un modulo GPS por serial (NEO-6M/7M/M8N, etc.): $xxRMC da posicion, hora UTC
    y velocidad; $xxGGA da los satelites. Funciona con GP, GN, GL..."""

    def __init__(self, puerto, baudios):
        super().__init__(daemon=True)
        self.puerto, self.baudios = puerto, baudios
        self.fix = None          # dict(lat, lon, kmh, utc, t_mono, sats)
        self.sats = 0
        self.seq = 0             # sube con cada fix nuevo (lo usa el MPU)
        self.ok = False
        self.error = None
        self.n_ok = self.n_mal = self.n_sin_fix = 0   # diagnostico (checksum malo = UART)

    def run(self):
        try:
            import serial
        except ImportError:
            self.error = "falta pyserial (pip install pyserial)"
            log(f"[GPS] {self.error}")
            return
        while True:
            try:
                with serial.Serial(self.puerto, self.baudios, timeout=1) as s:
                    self.ok, self.error = True, None
                    log(f"[GPS] leyendo {self.puerto} a {self.baudios}")
                    while True:
                        l = s.readline().decode("ascii", errors="ignore").strip()
                        if l:
                            self._procesar(l)
            except Exception as e:      # puerto desconectado: reintentar
                if self.error != str(e):
                    log(f"[GPS] {e}")
                self.ok, self.error = False, str(e)
                time.sleep(3)

    def _procesar(self, l):
        if not _nmea_ok(l):
            if l.startswith("$"):
                self.n_mal += 1
            return
        self.n_ok += 1
        c = l.split("*")[0].split(",")
        tipo = c[0][3:]
        if tipo == "GGA" and len(c) > 7:
            self.sats = int(c[7]) if c[7].isdigit() else 0
        elif tipo == "RMC" and len(c) > 9:
            if c[2] != "A":            # V = sin fix
                self.n_sin_fix += 1
                return
            try:
                utc = datetime.strptime(c[9] + c[1].split(".")[0], "%d%m%y%H%M%S").replace(
                    tzinfo=timezone.utc)
                fix = {"lat": _grados(c[3], c[4]), "lon": _grados(c[5], c[6]),
                       "kmh": float(c[7]) * 1.852 if c[7] else None,
                       "utc": utc, "t_mono": time.monotonic(), "sats": self.sats}
            except (ValueError, IndexError):
                return
            self.fix = fix
            self.seq += 1


# ---------------------------------------------------------------- posicion desde el celular (--celular)
_RE_APP = re.compile(r"Device:\s*(?P<dev>[^,]+),\s*Lat:\s*(?P<lat>-?\d+(?:\.\d+)?),\s*"
                     r"Lon:\s*(?P<lon>-?\d+(?:\.\d+)?),\s*Timestamp GPS:\s*(?P<ts>[^,]+)")


def _distancia_m(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos puntos (formula de haversine)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Celular(threading.Thread):
    """Recibe la posicion del celular por UDP y se comporta igual que la clase GPS
    (mismos atributos: fix, seq, sats, ok, error, n_ok...), asi el resto no cambia.
    Acepta dos formatos:
      1) el mismo mensaje que la app ya manda al servidor:
         Device: X, Lat: 11.03, Lon: -74.85, Timestamp GPS: 2026-11-03 07:50:28.000000 -0500
      2) GPS,lat,lon[,kmh[,epoch_ms]]
    Y comandos de la app: CMD,PAUSA | CMD,REANUDA | CMD,APAGAR | CMD,ESTADO
    (contesta al celular: EST,<device>,<ACTIVO|PAUSADO|APAGANDO>,<senales>)."""

    def __init__(self, puerto, apagar=True, device_del_celular=False):
        super().__init__(daemon=True)
        self.puerto, self.apagar, self.device_del_celular = puerto, apagar, device_del_celular
        self.fix = None
        self.sats = 0              # el celular no lo dice: queda en 0
        self.seq = 0
        self.ok = False
        self.error = None
        self.n_ok = self.n_mal = self.n_sin_fix = 0
        self.origen = None         # ultima IP del celular
        self.device_app = None
        self.hist = deque(maxlen=20)   # (utc, t_mono, lat, lon) para calcular la velocidad

    def run(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", self.puerto))
        except OSError as e:
            self.error = f"no se pudo abrir el puerto UDP {self.puerto}: {e}"
            log(f"[CELULAR] {self.error}")
            return
        self.ok = True
        log(f"[CELULAR] esperando la ubicacion de la app en el puerto UDP {self.puerto}")
        while True:
            try:
                datos, origen = sock.recvfrom(2048)
            except OSError:
                continue
            texto = datos.decode("utf-8", errors="ignore").strip()
            if self.origen != origen[0]:
                log(f"[CELULAR] mensajes desde {origen[0]}")
            self.origen = origen[0]
            if texto.upper().startswith("CMD,"):
                self._comando(texto[4:].strip().upper(), sock, origen)
            elif not self._posicion(texto):
                self.n_mal += 1

    # ---- posicion
    def _posicion(self, texto):
        lat = lon = kmh = utc = None
        m = _RE_APP.search(texto)
        if m:
            lat, lon = float(m["lat"]), float(m["lon"])
            try:
                utc = datetime.strptime(m["ts"].strip(), "%Y-%m-%d %H:%M:%S.%f %z").astimezone(timezone.utc)
            except ValueError:
                utc = None
            dev = m["dev"].strip()
            if dev != self.device_app:
                self.device_app = dev
                log(f"[CELULAR] la app se identifica como Device: {dev}")
                if self.device_del_celular:
                    global DEVICE_ID
                    DEVICE_ID = dev
                    log(f"[CELULAR] las detecciones saldran con Device: {dev}")
        elif texto.upper().startswith("GPS,"):
            p = [x.strip() for x in texto.split(",")]
            try:
                lat, lon = float(p[1]), float(p[2])
                if len(p) > 3 and p[3] not in ("", "NA"):
                    kmh = float(p[3])
                if len(p) > 4 and p[4]:
                    utc = datetime.fromtimestamp(int(p[4]) / 1000, tz=timezone.utc)
            except (ValueError, IndexError):
                return False
        else:
            return False
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            self.n_sin_fix += 1
            return True
        ahora = time.monotonic()
        if utc is None:
            utc = datetime.now(timezone.utc)
        # Sin velocidad en el mensaje: se calcula con un punto de hace 1-8 s (promedia el
        # ruido de la posicion del celular; con puntos de 1 s el ruido da km/h falsos)
        if kmh is None:
            for u0, m0, la0, lo0 in self.hist:          # del mas viejo al mas nuevo
                dt = (utc - u0).total_seconds()
                if dt <= 0:
                    dt = ahora - m0
                if 0.9 <= dt <= 8:
                    kmh = _distancia_m(la0, lo0, lat, lon) / dt * 3.6
                    break
        self.hist.append((utc, ahora, lat, lon))
        self.fix = {"lat": lat, "lon": lon, "kmh": kmh, "utc": utc, "t_mono": ahora,
                    "sats": self.sats}
        self.seq += 1
        self.n_ok += 1
        return True

    # ---- comandos
    def _comando(self, cmd, sock, origen):
        global PAUSADO
        if cmd == "PAUSA":
            PAUSADO = True
            log("[CELULAR] PAUSA: deteccion detenida")
        elif cmd == "REANUDA":
            PAUSADO = False
            log("[CELULAR] REANUDA: deteccion activa")
        elif cmd == "APAGAR":
            PAUSADO = True
            self._responder(sock, origen, "APAGANDO")
            if self.apagar:
                log("[CELULAR] APAGAR: la Raspberry se apaga en 2 s")
                threading.Timer(2.0, lambda: subprocess.run(
                    ["sudo", "-n", "shutdown", "-h", "now"])).start()
            else:
                log("[CELULAR] APAGAR recibido (--no-apagar: no se apaga, solo se pausa)")
            return
        elif cmd != "ESTADO":
            log(f"[CELULAR] comando desconocido: {cmd}")
        self._responder(sock, origen, "PAUSADO" if PAUSADO else "ACTIVO")

    def _responder(self, sock, origen, estado_txt):
        try:
            sock.sendto(f"EST,{DEVICE_ID},{estado_txt},{N_EVENTOS}".encode(), origen)
        except OSError:
            pass


# ---------------------------------------------------------------- MPU6050 (velocidad de respaldo)
class MPU(threading.Thread):
    """MPU6050 por I2C (bus 1: pin 3 SDA, pin 5 SCL, 3.3 V), igual que tareaMPU en la ESP32:
    - 50 Hz; sesgo promediando 100 lecturas al arrancar (carro quieto).
    - v_resp: integra la aceleracion "adelante" y se reajusta a la velocidad GPS en cada fix.
    - v_libre: integra solo con el MPU; vuelve a 0 cuando el GPS dice quieto (< 1 km/h)
      o cuando la aceleracion casi no varia 1.5 s (ZUPT, sirve tambien sin GPS).
    - Eje adelante automatico: compara dv/dt del GPS con la media de X e Y y, tras 15
      aceleraciones o frenadas, elige el eje y el signo (el MPU debe ir plano)."""
    DIR = 0x68
    G = 9.80665

    def __init__(self, gps, bus=1):
        super().__init__(daemon=True)
        self.gps, self.nbus = gps, bus
        self.ok = False
        self.eje, self.signo, self.eje_auto = 0, 1, False   # empieza en X+
        self.v_resp = self.v_libre = 0.0                     # m/s
        self.sesgo = [0.0, 0.0]

    def _acel(self):
        d = self.bus.read_i2c_block_data(self.DIR, 0x3B, 4)
        ax = int.from_bytes(bytes(d[0:2]), "big", signed=True)
        ay = int.from_bytes(bytes(d[2:4]), "big", signed=True)
        return ax / 16384 * self.G, ay / 16384 * self.G       # +-2 g

    def _iniciar(self):
        from smbus2 import SMBus
        self.bus = SMBus(self.nbus)
        for intento in range(5):
            try:
                time.sleep(0.1)
                quien = self.bus.read_byte_data(self.DIR, 0x75)     # WHO_AM_I
                if quien in (0x68, 0x70, 0x72, 0x98):
                    break
            except OSError:
                quien = None
        else:
            raise OSError(f"MPU6050 no responde en 0x68 (WHO_AM_I={quien})")
        self.bus.write_byte_data(self.DIR, 0x6B, 0)      # despertar
        self.bus.write_byte_data(self.DIR, 0x1A, 3)      # filtro pasa bajos ~44 Hz
        self.bus.write_byte_data(self.DIR, 0x1C, 0)      # +-2 g
        time.sleep(0.1)
        sx = sy = 0.0
        for _ in range(100):
            ax, ay = self._acel()
            sx, sy = sx + ax, sy + ay
            time.sleep(0.01)
        self.sesgo = [sx / 100, sy / 100]
        log(f"[MPU] MPU6050 en 0x68 (bus {self.nbus}), sesgo x={self.sesgo[0]:.2f} y={self.sesgo[1]:.2f} m/s2")

    def run(self):
        try:
            self._iniciar()
        except Exception as e:
            log(f"[MPU] no disponible: {e}")
            return
        self.ok = True
        seq_gps, v_gps_ant, t_gps_ant = self.gps.seq if self.gps else 0, None, None
        suma, n_suma = [0.0, 0.0], 0                 # media de X, Y entre dos fix
        votos = [0.0, 0.0]; n_votos = 0
        quieto = []
        ventana = deque(maxlen=int(QUIETO_S * 50))   # ultimas lecturas crudas para el ZUPT
        self.t_zupt = 0.0
        t_ant = time.monotonic()
        while True:
            time.sleep(0.02)
            ahora = time.monotonic()
            dt, t_ant = ahora - t_ant, ahora
            try:
                ax, ay = self._acel()
            except OSError:
                continue
            a = [ax - self.sesgo[0], ay - self.sesgo[1]]
            suma[0] += a[0]; suma[1] += a[1]; n_suma += 1
            af = self.signo * a[self.eje]
            self.v_resp = max(0.0, self.v_resp + af * dt)
            self.v_libre = max(0.0, self.v_libre + af * dt)

            # ZUPT: si la aceleracion casi no varia durante 1.5 s el carro esta quieto
            # (o el sensor se movio y quedo fijo): velocidad 0 y sesgo nuevo. Asi un
            # cambio de inclinacion (gravedad en X/Y) no se integra para siempre.
            ventana.append((ax, ay))
            if len(ventana) == ventana.maxlen and ahora - self.t_zupt > QUIETO_S:
                xs = [v[0] for v in ventana]; ys = [v[1] for v in ventana]
                mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
                sd = (sum((x - mx) ** 2 for x in xs) / len(xs)
                      + sum((y - my) ** 2 for y in ys) / len(ys)) ** 0.5
                f = self.gps.fix if self.gps else None
                gps_mueve = bool(f and f["kmh"] and f["kmh"] > 3
                                 and ahora - f["t_mono"] <= VEL_GPS_MAX_EDAD_S)
                # (a velocidad constante en via lisa tambien vibra poco: el GPS manda)
                if sd < QUIETO_STD and not gps_mueve:
                    self.v_resp = self.v_libre = 0.0
                    self.sesgo = [mx, my]
                    self.t_zupt = ahora
            if self.v_libre * 3.6 > MPU_VEL_MAX_KMH:      # integracion desbocada
                self.v_libre = 0.0
            if self.v_resp * 3.6 > MPU_VEL_MAX_KMH:
                self.v_resp = 0.0

            if self.gps and self.gps.seq != seq_gps and self.gps.fix:
                seq_gps = self.gps.seq
                fix = self.gps.fix
                v = (fix["kmh"] or 0) / 3.6
                if fix["kmh"] is not None:
                    self.v_resp = v                               # reajuste al GPS
                if fix["kmh"] is not None and fix["kmh"] < 1:
                    self.v_libre = 0.0
                    quieto.append((ax, ay))
                    if len(quieto) >= 5:                          # recalcular sesgo quieto
                        self.sesgo = [sum(q[0] for q in quieto) / len(quieto),
                                      sum(q[1] for q in quieto) / len(quieto)]
                        quieto = []
                else:
                    quieto = []
                # Eje automatico: dv/dt del GPS contra la media de X e Y en ese tramo
                if not self.eje_auto and v_gps_ant is not None and n_suma:
                    dtg = fix["t_mono"] - t_gps_ant
                    if 0 < dtg <= 2.0:
                        dv = (v - v_gps_ant) / dtg
                        if abs(dv) > 0.8:                         # acelera o frena de verdad
                            for k in (0, 1):
                                votos[k] += (suma[k] / n_suma) * dv
                            n_votos += 1
                            if n_votos >= 15:
                                k = 0 if abs(votos[0]) >= abs(votos[1]) else 1
                                self.eje, self.signo = k, (1 if votos[k] > 0 else -1)
                                self.eje_auto = True
                                log(f"[MPU] eje adelante: {'+' if self.signo > 0 else '-'}{'XY'[k]}")
                v_gps_ant, t_gps_ant = v, fix["t_mono"]
                suma, n_suma = [0.0, 0.0], 0

    def eje_txt(self):
        return f"{'+' if self.signo > 0 else '-'}{'XY'[self.eje]}{' (auto)' if self.eje_auto else ''}"


gps = None
mpu = None


def leer_sensores():
    """Foto de posicion, hora y velocidades EN EL MOMENTO de la deteccion."""
    d = {"lat": None, "lon": None, "edad": None, "v_gps": None, "v_mpu": None,
         "usa": "NA", "v": None, "hora": datetime.now(ZONA_COL)}
    if POS_FIJA:                                       # --pos (pruebas sin GPS)
        d["lat"], d["lon"] = POS_FIJA[0], POS_FIJA[1]
        if len(POS_FIJA) > 2:
            d["v_gps"] = POS_FIJA[2]
    elif gps and gps.fix:
        f = gps.fix
        edad = time.monotonic() - f["t_mono"]
        d.update(lat=f["lat"], lon=f["lon"], edad=edad,
                 hora=(f["utc"] + timedelta(seconds=edad)).astimezone(ZONA_COL))
        if edad <= VEL_GPS_MAX_EDAD_S:
            d["v_gps"] = f["kmh"]
    if d["v_gps"] is not None and d["v_gps"] > MPU_VEL_MAX_KMH:
        d["v_gps"] = None                                  # lectura absurda del GPS -> NA
    # El MPU solo sirve como respaldo corto: sin un fix GPS reciente (o un ZUPT) su
    # velocidad acumula error, asi que pasado MPU_MAX_SIN_GPS_S se reporta NA.
    mpu_ok = False
    if mpu and mpu.ok:
        # Solo un fix del GPS calibra al MPU (el ZUPT tambien se activa a velocidad constante)
        t_ref = gps.fix["t_mono"] if gps and gps.fix else -1e9
        mpu_ok = time.monotonic() - t_ref <= MPU_MAX_SIN_GPS_S
    if mpu_ok:
        d["v_mpu"] = mpu.v_libre * 3.6
    if d["v_gps"] is not None:
        d["usa"], d["v"] = "GPS", d["v_gps"]
    elif mpu_ok:
        d["usa"], d["v"] = "MPU", mpu.v_resp * 3.6
    return d


def _num(v):
    return f"{v:.0f}" if v is not None else "NA"


def linea_posicion(d):
    lat = f"{d['lat']:.6f}" if d["lat"] is not None else "NA"
    lon = f"{d['lon']:.6f}" if d["lon"] is not None else "NA"
    hora = d["hora"].replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S.%f %z")
    return f"Device: {DEVICE_ID}, Lat: {lat}, Lon: {lon}, Timestamp GPS: {hora}"


def linea_deteccion(clase, conf, d):
    if tipo_de(clase) == "limite" and clase.isdigit() and d["v"] is not None:
        cumple = "EXCEDE" if d["v"] > int(clase) + TOLERANCIA_KMH else "SI"
    else:
        cumple = "NA"        # PARE / CEDA, limite sin numero (sin OCR) o sin velocidad
    l = (f"{linea_posicion(d)}, Senal: {nombre_senal(clase)}, Conf: {conf:.2f}, "
         f"Vel GPS: {_num(d['v_gps'])}, Vel MPU: {_num(d['v_mpu'])}, Usa: {d['usa']}, {cumple}")
    if d["edad"] is not None and d["edad"] > POS_VIEJA_S:
        l += f", pos-{d['edad']:.0f}s"
    return l


class Enviador:
    """Manda por UDP al mismo servidor/sniffer de la ESP32. Sin posición no se manda
    (el servidor exige Lat/Lon), solo queda en el log, igual que en la ESP32."""

    def __init__(self, activo):
        self.activo = activo
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if activo else None
        self.t_pos = 0.0

    def enviar(self, linea, d):
        if not self.activo:
            estado_txt = "SIN ENVIO (usa --udp)"
        elif d["lat"] is None:
            estado_txt = "SIN GPS (no se envia)"
        else:
            try:
                self.sock.sendto(linea.encode(), SERVIDOR_UDP)
                estado_txt = "ENVIADO"
            except OSError as e:
                estado_txt = f"FALLO ({e})"
        log(f"[ENVIO] {linea} | {estado_txt}")

    def tick(self, ahora):
        if ahora - self.t_pos < POS_CADA_S:
            return
        self.t_pos = ahora
        d = leer_sensores()
        if d["lat"] is not None or d["v"] is not None:
            log(f"[VEL] GPS {_num(d['v_gps'])} km/h | MPU {_num(d['v_mpu'])} km/h | usa {d['usa']}"
                + (f" | eje {mpu.eje_txt()}" if mpu and mpu.ok else "")
                + (f" | celular {gps.n_ok} msj" if MODO_CELULAR and gps else
                   f" | NMEA ok {gps.n_ok} malas {gps.n_mal} sinfix {gps.n_sin_fix}" if gps else ""))
        # La posicion periodica solo sale con un fix reciente: con un fix viejo se
        # estaria reportando un punto donde el carro ya no esta.
        if MODO_CELULAR:
            if not REENVIAR:
                return      # la app ya manda su posicion al servidor: no se duplica
            if gps is None or gps.seq == getattr(self, "seq_enviado", -1):
                return      # no ha llegado un punto nuevo del celular
            self.seq_enviado = gps.seq
        fresca = POS_FIJA is not None or (d["edad"] is not None and d["edad"] <= POS_VIEJA_S)
        if self.activo and d["lat"] is not None and fresca:
            self.enviar(linea_posicion(d), d)
        elif self.activo and d["lat"] is not None:
            log(f"[ENVIO] posicion no enviada: fix de hace {d['edad']:.0f} s")


# ---------------------------------------------------------------- estado para el monitor
estado = {"fps": 0.0, "t_ciclo": 0.0, "t_fomo": 0.0, "t_clas": 0.0, "t_jpg": 0.0,
          "cuadros": 0, "senales": [], "log": [], "modelos": {}}
LOG = deque(maxlen=40)
SENALES = deque(maxlen=8)


def log(texto):
    linea = time.strftime("%H:%M:%S ") + texto
    print(linea, flush=True)
    with candado:
        LOG.append(linea)


class Recursos:
    """CPU por núcleo, temperatura y RAM leyendo /proc y /sys (sin psutil)."""

    def __init__(self):
        self.antes = self._cpu()

    @staticmethod
    def _cpu():
        d = {}
        try:
            for l in open("/proc/stat"):
                if l.startswith("cpu"):
                    p = l.split()
                    v = list(map(int, p[1:]))
                    d[p[0]] = (v[3] + v[4], sum(v))     # (ocioso, total)
        except OSError:
            pass
        return d

    def leer(self):
        ahora = self._cpu()
        cpu = {}
        for k, (oc, tot) in ahora.items():
            oc0, tot0 = self.antes.get(k, (0, 0))
            dt = tot - tot0
            cpu[k] = round(100 * (1 - (oc - oc0) / dt), 0) if dt > 0 else 0
        self.antes = ahora
        temp = None
        try:
            temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
        except (OSError, ValueError):
            pass
        mem = {}
        try:
            for l in open("/proc/meminfo"):
                k, v = l.split(":")
                mem[k] = int(v.split()[0]) * 1024
        except (OSError, ValueError):
            pass
        return {"cpu": cpu, "temp": temp, "ram_total": mem.get("MemTotal", 0),
                "ram_libre": mem.get("MemAvailable", 0)}


# ---------------------------------------------------------------- dibujo (mismos colores que ver_camara.py)
AMARILLO, VERDE, NARANJA, GRIS = (0, 220, 255), (0, 255, 0), (0, 150, 255), (160, 160, 160)


def dibujar(vista, zona, marcas):
    zx, zy, lado = zona
    cv2.rectangle(vista, (zx, zy), (zx + lado - 1, zy + lado - 1), AMARILLO, 2)
    for m in marcas:
        if m["estado"] == "ok":
            col, grosor, txt = VERDE, 4, f"{m['clase']} {m['conf']:.2f} OK"
        elif m["estado"] == "candidata":
            col, grosor, txt = NARANJA, 2, f"{m['clase']} {m['conf']:.2f} ?"
        elif m["estado"] == "rechazo":
            col, grosor, txt = GRIS, 1, f"{m['clase']} {m['conf']:.2f} X {m['motivo']}"
        else:
            col, grosor, txt = GRIS, 1, f"{m['clase']} {m['conf']:.2f}"
        x0, y0, x1, y1 = m["caja"]
        cv2.rectangle(vista, (x0, y0), (x1, y1), col, grosor)
        cv2.putText(vista, txt, (x0 + 2, max(y0 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, col, 1 if grosor < 2 else 2, cv2.LINE_AA)


# ---------------------------------------------------------------- bucle principal
def bucle(ruta_det, ruta_cls, enviar_udp):
    global ultimo_jpg
    from picamera2 import Picamera2
    from edge_impulse_linux.image import ImageImpulseRunner

    cam = Picamera2()
    # Ojo: en picamera2 "RGB888" entrega los bytes en orden B, G, R (lo que OpenCV
    # llama BGR). Por eso el cuadro se trata como BGR y se pasa a RGB para el FOMO.
    cam.configure(cam.create_video_configuration(
        main={"size": RESOLUCION, "format": "RGB888"}))
    cam.start()
    time.sleep(1)

    archivo = open("tiempos_pipeline.csv", "w", newline="")
    esc = csv.writer(archivo)
    esc.writerow(["hora", "det_dsp_ms", "det_inf_ms", "cls_ms", "recortes", "ciclo_ms",
                  "det_conf", "clase", "cls_conf", "motivo", "rojo_flojo", "confirmada",
                  "ocr_ms", "ocr_lectura"])
    arch_ev = open("eventos.csv", "w", newline="")
    esc_ev = csv.writer(arch_ev)
    esc_ev.writerow(["hora", "linea"])
    enviador = Enviador(enviar_udp)

    def hilo_posicion():
        """Reenvia la posicion y vigila la camara, aparte del bucle de la camara."""
        global ULTIMO_CUADRO
        import os as _os
        ULTIMO_CUADRO = time.monotonic() + 30      # margen para cargar modelos y camara
        while True:
            try:
                enviador.tick(time.time())
            except Exception as e:
                log(f"[ENVIO] error: {e}")
            if PAUSADO:
                ULTIMO_CUADRO = time.monotonic()
            elif time.monotonic() - ULTIMO_CUADRO > CAMARA_MAX_S:
                log(f"[CAMARA] sin cuadros hace {CAMARA_MAX_S:.0f} s: se reinicia el programa")
                _os._exit(1)
            time.sleep(0.5)

    threading.Thread(target=hilo_posicion, daemon=True).start()
    recursos = Recursos()

    def reportar(clase, conf, votos):
        global N_EVENTOS
        N_EVENTOS += 1
        d = leer_sensores()          # posicion y velocidades del momento de la deteccion
        linea = linea_deteccion(clase, conf, d)
        log(f"[EVENTO] {nombre_senal(clase)} {conf:.2f} | votos {votos}")
        with candado:
            SENALES.append(f"{time.strftime('%H:%M:%S')} {nombre_senal(clase)} {conf:.2f}")
        esc_ev.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), linea])
        arch_ev.flush()
        enviador.enviar(linea, d)

    evento = Evento(reportar)
    llaves_anteriores = set()   # tipos de senal (pare, ceda, limite) confirmables del cuadro anterior

    try:
        with ImageImpulseRunner(ruta_det) as det, ImageImpulseRunner(ruta_cls) as cls:
            info_det = det.init()
            info_cls = cls.init()
            p_det = info_det["model_parameters"]
            p_cls = info_cls["model_parameters"]
            log(f"Detector:     {info_det['project']['name']} | entrada "
                f"{p_det['image_input_width']}x{p_det['image_input_height']} | {p_det['labels']}")
            log(f"Clasificador: {info_cls['project']['name']} | entrada "
                f"{p_cls['image_input_width']}x{p_cls['image_input_height']} "
                f"x{p_cls['image_channel_count']} | {p_cls['labels']}")
            if ETIQUETA_FOMO not in p_det["labels"]:
                log(f"AVISO: el detector no tiene la etiqueta '{ETIQUETA_FOMO}'")
            with candado:
                estado["modelos"] = {"detector": info_det["project"]["name"],
                                     "clasificador": info_cls["project"]["name"],
                                     "clases": len(p_cls["labels"])}
            det_in = p_det["image_input_width"]
            info_c = (p_cls["image_input_width"], p_cls["image_input_height"],
                      p_cls["image_channel_count"])

            acumulado = {"det": [], "cls": [], "ciclo": [], "ocr": []}
            t_resumen = t_stats = time.time()
            t_rechazo = 0.0
            n_cuadros, t_jpg, t_video = 0, 0.0, 0.0

            while True:
                if PAUSADO:                     # CMD,PAUSA desde la app
                    time.sleep(0.2)
                    continue
                t0 = time.perf_counter()
                ahora = time.time()
                frame_bgr = cam.capture_array()
                global ULTIMO_CUADRO
                ULTIMO_CUADRO = time.monotonic()
                alto, ancho = frame_bgr.shape[:2]
                zx, zy, lado = zona_deteccion(ancho, alto)
                escala = lado / det_in

                # ---- Etapa 1: FOMO sobre la zona cuadrada, reducida a 96x96 RGB
                zona = cv2.cvtColor(frame_bgr[zy:zy + lado, zx:zx + lado], cv2.COLOR_BGR2RGB)
                zona = cv2.resize(zona, (det_in, det_in), interpolation=cv2.INTER_AREA)
                r_det = det.classify(features_de(zona, 3))
                det_dsp = r_det["timing"]["dsp"]
                det_inf = r_det["timing"]["classification"]
                cajas = []
                for c in r_det["result"].get("bounding_boxes", []):
                    if c["label"] != ETIQUETA_FOMO or c["value"] < UMBRAL_FOMO:
                        continue
                    # Descartar cajas que tocan el borde de la zona (senal cortada o luz)
                    if (c["x"] < MARGEN_BORDE or c["y"] < MARGEN_BORDE or
                            c["x"] + c["width"] > det_in - MARGEN_BORDE or
                            c["y"] + c["height"] > det_in - MARGEN_BORDE):
                        continue
                    cajas.append(c)
                cajas = sorted(cajas, key=lambda c: -c["value"])[:MAX_CAJAS]

                frame_gris = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if cajas else None
                if cajas:
                    evento.visto(ahora)

                marcas = []           # lo que se dibuja en el monitor
                mejores = {}          # llave (pare/ceda/limite) -> (clase, conf, indice en marcas)
                fila = ["", "", "", "", "", ""]
                cls_ms_cuadro, recortes = 0, 0
                ocr_ms_cuadro, ocr_txt = 0.0, []         # tiempo y lecturas del OCR en este cuadro
                candidatas = []       # senales con borde rojo ya clasificadas (paso 1)
                for c in cajas:
                    cx = int(zx + (c["x"] + c["width"] / 2) * escala)
                    cy = int(zy + (c["y"] + c["height"] / 2) * escala)
                    ventana = int(np.clip(4 * max(c["width"], c["height"]) * escala, 120, lado))
                    senal = medir_senal_roja(frame_bgr, cx, cy, ventana)
                    if senal is None:
                        lc = int(max(c["width"], c["height"]) * escala)
                        marcas.append({"caja": (cx - lc // 2, cy - lc // 2, cx + lc // 2, cy + lc // 2),
                                       "clase": "senal", "conf": c["value"],
                                       "estado": "rechazo", "motivo": "sin_rojo"})
                        fila = [round(c["value"], 2), "", "", "sin_rojo", "", ""]
                        continue

                    # ---- Etapa 2: clasificador sobre el recorte del borde rojo
                    clase, conf, t_ms, caja, n_rec, num_cls = clasificar_senal(
                        cls, info_c, frame_bgr, frame_gris, senal["bbox"])
                    cls_ms_cuadro += t_ms
                    recortes += n_rec
                    medidas = medir_forma(frame_bgr, senal)
                    motivo = revisar_forma(clase, medidas) if tipo_de(clase) != "otro" else None
                    valida = motivo is None and tipo_de(clase) != "otro" and conf >= umbral_de(clase)

                    if motivo and conf >= 0.7 and ahora - t_rechazo >= 1.0:
                        t_rechazo = ahora
                        log(f"[RECHAZO] {clase} {conf:.2f} {motivo} " +
                            " ".join(f"{k}={v:.2f}" for k, v in medidas.items()))
                    candidatas.append({"c": c, "senal": senal, "clase": clase, "conf": conf,
                                       "caja": caja, "num_cls": num_cls, "valida": valida,
                                       "motivo": motivo})

                # ---- Etapa 3: OCR del numero (paso 2, cuando ya se sabe cuantos limites hay)
                n_limites = sum(1 for k in candidatas if k["valida"] and tipo_de(k["clase"]) == "limite")
                for k in candidatas:
                    if k["valida"] and tipo_de(k["clase"]) == "limite":
                        k["clase"], k["valida"], k["motivo"], info = decidir_numero(
                            frame_bgr, k["senal"]["bbox"], k["clase"], k["num_cls"],
                            evento, usar_cache=(n_limites == 1))
                        if info:
                            ocr_ms_cuadro += info["ms"]
                            ocr_txt.append(info["txt"])

                    clase, conf, motivo = k["clase"], k["conf"], k["motivo"]
                    if k["valida"]:
                        est = "candidata"
                        llave = llave_de(clase)
                        if llave not in mejores or conf > mejores[llave][1]:
                            mejores[llave] = (clase, conf, len(marcas))
                    elif motivo:
                        est = "rechazo"
                    else:
                        est = "ignorada"
                    marcas.append({"caja": k["caja"], "clase": clase, "conf": conf,
                                   "estado": est, "motivo": motivo or "-"})
                    if fila[1] == "" or conf > (fila[2] or 0):
                        fila = [round(k["c"]["value"], 2), clase, round(conf, 2), motivo or "",
                                k["senal"]["flojo"], ""]

                # ---- Confirmacion: mismo tipo de senal 2 cuadros seguidos, o 1 cuadro >= 0.99.
                #      Cada tipo vota por separado: un PARE y un limite en el mismo poste
                #      son dos senales. Para limites cuenta la senal, no el numero: 50 y
                #      luego "limite" (OCR que no leyo en un cuadro) son la misma senal.
                for llave, (clase, conf, i) in mejores.items():
                    if llave in llaves_anteriores or conf >= CONF_UN_CUADRO:
                        fila[5] = True
                        marcas[i]["estado"] = "ok"
                        evento.voto(clase, conf, ahora)
                llaves_anteriores = set(mejores)
                evento.tick(ahora)

                if recortes:
                    acumulado["cls"].append(cls_ms_cuadro)
                if ocr_ms_cuadro > 0:
                    acumulado["ocr"].append(ocr_ms_cuadro)
                ciclo = (time.perf_counter() - t0) * 1000
                acumulado["det"].append(det_dsp + det_inf)
                acumulado["ciclo"].append(ciclo)
                n_cuadros += 1

                # ---- Monitor: imagen con cajas + estado para el panel
                # Comprimir JPEG cuesta tanto como los dos modelos: solo VIDEO_FPS por segundo
                ok = False
                if VIDEO_FPS > 0 and ahora - t_video >= 1.0 / VIDEO_FPS and ahora - t_cliente < 3:
                    t_video = ahora
                    t1 = time.perf_counter()
                    vista = frame_bgr.copy()
                    dibujar(vista, (zx, zy, lado), marcas)
                    ok, jpg = cv2.imencode(".jpg", vista, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    t_jpg = (time.perf_counter() - t1) * 1000
                with candado:
                    if ok:
                        ultimo_jpg = jpg.tobytes()
                    estado["t_ciclo"] = ciclo
                    estado["t_fomo"] = det_dsp + det_inf
                    estado["t_clas"] = cls_ms_cuadro
                    estado["ocr"] = OCR_ACTIVO
                    if ocr_txt:                          # se conserva la ultima lectura
                        estado["t_ocr"] = ocr_ms_cuadro
                        estado["ocr_ult"] = "/".join(ocr_txt)
                    estado["t_jpg"] = t_jpg
                    estado["dets"] = [f"{m['clase']} {m['conf']:.2f}"
                                      + (" OK" if m["estado"] == "ok" else "")
                                      + (f" X {m['motivo']}" if m["estado"] == "rechazo" else "")
                                      for m in marcas]
                if ahora - t_stats >= 1.0:
                    with candado:
                        estado["fps"] = n_cuadros / (ahora - t_stats)
                        estado.update(recursos.leer())
                        d = leer_sensores()
                        f = gps.fix if gps else None
                        estado["sensores"] = {
                            "gps": ("posicion fija (--pos)" if POS_FIJA else "sin modulo" if not gps else
                                    (gps.error or "sin fix") if not f else
                                    f"fix hace {time.monotonic() - f['t_mono']:.0f} s, {f['sats']} sat")
                                   + (f" | NMEA ok {gps.n_ok}, malas {gps.n_mal}, sin fix {gps.n_sin_fix}" if gps else ""),
                            "pos": (f"{d['lat']:.5f}, {d['lon']:.5f}" if d["lat"] is not None else "NA"),
                            "v_gps": _num(d["v_gps"]), "v_mpu": _num(d["v_mpu"]), "usa": d["usa"],
                            "mpu": (f"eje {mpu.eje_txt()}" if mpu and mpu.ok else "no disponible")}
                    n_cuadros, t_stats = 0, ahora

                esc.writerow([time.strftime("%H:%M:%S"), det_dsp, det_inf,
                              cls_ms_cuadro if recortes else "", recortes or "",
                              round(ciclo, 1)] + fila +
                             [round(ocr_ms_cuadro, 1) if ocr_txt else "", "/".join(ocr_txt)])

                if time.time() - t_resumen >= RESUMEN_CADA:
                    prom = lambda l: sum(l) / len(l) if l else 0
                    p_ciclo = prom(acumulado["ciclo"])
                    print(f"--- {len(acumulado['ciclo'])} cuadros | detector {prom(acumulado['det']):.1f} ms"
                          f" | clasificador {prom(acumulado['cls']):.1f} ms ({len(acumulado['cls'])} cuadros)"
                          f" | OCR {prom(acumulado['ocr']):.1f} ms ({len(acumulado['ocr'])} lecturas)"
                          f" | ciclo {p_ciclo:.1f} ms ({1000 / p_ciclo if p_ciclo else 0:.1f} fps)")
                    archivo.flush()
                    acumulado = {"det": [], "cls": [], "ciclo": [], "ocr": []}
                    t_resumen = time.time()
    finally:
        archivo.close()
        arch_ev.close()
        cam.stop()


# ---------------------------------------------------------------- monitor en el navegador
PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Monitor Pi Zero 2 W</title>
<style>
body{margin:0;background:#111;color:#ddd;font:14px system-ui,sans-serif}
#c{display:flex;flex-wrap:wrap;gap:8px;padding:8px}
#v{max-width:100%;width:640px;background:#000}
#p{background:#1e1e1e;padding:10px;width:320px;max-width:100%;box-sizing:border-box}
h4{color:#ffd84d;margin:10px 0 4px;font-size:13px}
.b{height:10px;border:1px solid #888;margin:2px 0 6px}.b div{height:100%}
#s div{color:#7CFC7C}#l{font:12px monospace;white-space:pre-wrap;padding:0 8px 8px;color:#bbb}
.ley span{display:inline-block;margin-right:10px}
</style></head><body>
<div id="c"><div><img id="v" src="/video"><div id="e">esperando cuadros...</div>
<div class="ley"><span style="color:#ffdc00">&#9632; zona FOMO</span><span style="color:#0f0">&#9632; confirmada OK</span>
<span style="color:#ff9600">&#9632; candidata ?</span><span style="color:#aaa">&#9632; otro / X rechazo</span></div></div>
<div id="p"></div></div><div id="l"></div>
<script>
const kb=v=>v<1048576?(v/1024).toFixed(0)+' KB':(v/1048576).toFixed(0)+' MB';
const bar=(f,c)=>`<div class="b"><div style="width:${Math.max(0,Math.min(100,f))}%;background:${c}"></div></div>`;
async function t(){try{const s=await (await fetch('/estado')).json();
let h=`<h4>RENDIMIENTO</h4>FPS: ${s.fps.toFixed(1)}<br>Cuadro total: ${s.t_ciclo.toFixed(0)} ms<br>
&nbsp;FOMO: ${s.t_fomo.toFixed(0)} ms &nbsp; clasificador: ${s.t_clas.toFixed(0)} ms<br>&nbsp;JPEG monitor: ${s.t_jpg.toFixed(0)} ms<br>
&nbsp;OCR: ${s.ocr===false?'desactivado':(s.t_ocr!=null?s.t_ocr.toFixed(0)+' ms (ultima lectura: '+s.ocr_ult+')':'sin limites aun')}`;
h+=`<h4>CPU${s.temp!=null?' ('+s.temp.toFixed(0)+' °C)':''}</h4>`;
Object.keys(s.cpu||{}).filter(k=>k!='cpu').forEach(k=>{h+=`Núcleo ${k.slice(3)}: ${s.cpu[k]} %`+bar(s.cpu[k],'#e8743b')});
if(s.ram_total){const u=s.ram_total-s.ram_libre;h+=`<h4>MEMORIA</h4>RAM usada: ${kb(u)} de ${kb(s.ram_total)}`+bar(100*u/s.ram_total,'#53c27a')}
if(s.sensores){const g=s.sensores;h+=`<h4>GPS Y VELOCIDAD</h4>GPS: ${g.gps}<br>Posición: ${g.pos}<br>Vel GPS: ${g.v_gps} km/h &nbsp; Vel MPU: ${g.v_mpu} km/h<br>Usa: ${g.usa} &nbsp; MPU: ${g.mpu}`}
if(s.modelos.detector)h+=`<h4>MODELOS</h4>${s.modelos.detector}<br>${s.modelos.clasificador} (${s.modelos.clases} clases)`;
h+=`<h4>SEÑALES CONFIRMADAS</h4><div id="s">${s.senales.slice().reverse().map(x=>'<div>'+x+'</div>').join('')}</div>`;
document.getElementById('p').innerHTML=h;
document.getElementById('e').textContent=new Date().toLocaleTimeString()+'  '+((s.dets||[]).join(', ')||'sin detecciones');
document.getElementById('l').textContent=s.log.slice().reverse().join('\\n');}catch(e){}}
setInterval(t,500);t();
</script></body></html>"""


def generar():
    global t_cliente
    anterior = None
    while True:
        t_cliente = time.time()
        with candado:
            jpg = ultimo_jpg
        if jpg is not None and jpg is not anterior:      # solo imagenes nuevas
            anterior = jpg
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
        time.sleep(0.05)


def crear_app():
    from flask import Flask, Response, jsonify
    app = Flask(__name__)

    @app.route("/")
    def inicio():
        return PAGINA

    @app.route("/video")
    def video():
        return Response(generar(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/estado")
    def ver_estado():
        with candado:
            s = dict(estado)
            s["senales"] = list(SENALES)
            s["log"] = list(LOG)
        return jsonify(s)

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Detector de senales en Raspberry Pi Zero 2 W")
    ap.add_argument("detector")
    ap.add_argument("clasificador")
    ap.add_argument("--udp", action="store_true",
                    help=f"enviar detecciones y posicion a {SERVIDOR_UDP[0]}:{SERVIDOR_UDP[1]}")
    ap.add_argument("--device", default=DEVICE_ID, help="ID del vehiculo en el mensaje")
    ap.add_argument("--pos", default=None, metavar="LAT,LON[,KMH]",
                    help="posicion fija para probar el envio sin GPS (ignora el modulo)")
    ap.add_argument("--gps", default="/dev/serial0", help="puerto serie del modulo GPS")
    ap.add_argument("--baudios", type=int, default=9600, help="baudios del GPS (NEO-6M: 9600)")
    ap.add_argument("--sin-gps", action="store_true", help="no abrir el GPS")
    ap.add_argument("--sin-mpu", action="store_true", help="no usar el MPU6050")
    ap.add_argument("--celular", nargs="?", const=5006, type=int, default=None, metavar="PUERTO",
                    help="usar la ubicacion que manda la app por UDP (puerto 5006 por defecto)")
    ap.add_argument("--device-celular", action="store_true",
                    help="las detecciones salen con el mismo Device que manda la app")
    ap.add_argument("--vel-edad", type=float, default=None, metavar="S",
                    help="usar la velocidad de la app si el punto tiene <= S s (por defecto 3)")
    ap.add_argument("--reenviar", nargs="?", const=2.0, type=float, default=None, metavar="S",
                    help="con --celular: reenviar la posicion de la app al servidor (cada S s, por defecto 2)")
    ap.add_argument("--no-apagar", action="store_true", help="CMD,APAGAR solo pausa (para pruebas)")
    ap.add_argument("--sin-monitor", action="store_true", help="no abrir la pagina web del monitor")
    ap.add_argument("--bus-i2c", type=int, default=1, help="bus I2C del MPU6050")
    args = ap.parse_args()
    DEVICE_ID = args.device
    if args.pos:
        POS_FIJA = tuple(float(v) for v in args.pos.split(","))
    if args.vel_edad:
        VEL_GPS_MAX_EDAD_S = args.vel_edad
    if args.celular:
        MODO_CELULAR = True
        if args.reenviar:
            REENVIAR = True
            POS_CADA_S = args.reenviar
        gps = Celular(args.celular, apagar=not args.no_apagar,
                      device_del_celular=args.device_celular)
        gps.start()
    elif not args.sin_gps and not args.pos:
        gps = GPS(args.gps, args.baudios)
        gps.start()
    if not args.sin_mpu:
        mpu = MPU(gps, args.bus_i2c)
        mpu.start()
    def correr():
        try:
            bucle(args.detector, args.clasificador, args.udp)
        except Exception as e:
            import os, traceback
            traceback.print_exc()
            log(f"[ERROR] el bucle se detuvo: {e}")
            time.sleep(2)
            os._exit(1)           # que no quede el monitor vivo sin detectar nada

    hilo = threading.Thread(target=correr, daemon=True)
    hilo.start()
    if args.sin_monitor:
        print("Sin monitor (--sin-monitor). Ctrl + C para salir.", flush=True)
        try:
            hilo.join()
        except KeyboardInterrupt:
            print("\nFin.")
    else:
        print(f"Monitor en: http://raspberrypi.local:{PUERTO}/")
        crear_app().run(host="0.0.0.0", port=PUERTO, threaded=True)