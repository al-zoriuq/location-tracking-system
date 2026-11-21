"""
ocr_digitos.py
==============
OCR propio para límites de velocidad (Proyecto 3). Reemplaza a Tesseract, que
no funciona bien con recortes reales pequeños (48x48, de noche, desenfocados).

Cómo funciona:
  1) preprocesar(): canal rojo + CLAHE + Otsu dentro del disco central.
     En el canal rojo el aro rojo y el fondo blanco se ven CLAROS y solo los
     números quedan OSCUROS, así que el aro desaparece solo.
  2) segmentar(): separa cada dígito (componentes conectados, de izq. a der.).
     Si dos dígitos quedaron pegados (ej. "80"), los parte.
  3) Cada dígito -> 20x20 -> HOG (forma de los bordes) -> red neuronal pequeña
     (MLP) que dice 0-9 o "x" (no es dígito: letras como la "t" de 10t, puntos...).
  4) leer_numero(): repite 1-3 con 3 combinaciones de canal y umbral y acepta el número solo
     si al menos 2 lecturas coinciden. Devuelve "60", un texto inválido ("1x")
     para que pipeline_pi.py lo rechace, o None si no está seguro.

Solo necesita OpenCV y NumPy (la red se ejecuta con NumPy, sin TensorFlow).
Los pesos del modelo están en ocr_digitos_modelo.npz (generado por entrenar_ocr.py).
"""

import os
import time
import cv2
import numpy as np

LADO = 192            # tamaño al que se escala el recorte
R_DISCO = 0.33        # radio del disco central (fracción del lado) donde están los números
# Se lee con VARIOS umbrales (factor sobre Otsu): con uno bajo los números gruesos
# o borrosos salen limpios; con uno alto no desaparecen los números delgados.
# Cada lectura = (canal, factor sobre el umbral de Otsu).
#   canal "r": rojo   -> el aro rojo desaparece; bueno con interior blanco/rosado
#   canal "v": máximo -> también sirve con interior cian
LECTURAS = (("r", 0.95), ("v", 0.85), ("v", 0.95))
MIN_ACUERDO = 2       # cuántas lecturas tienen que coincidir para aceptar el número
TAM_DIGITO = 20       # cada dígito se normaliza a 20x20
CLASES = list("0123456789") + ["x"]

PROB_MIN = 0.90       # probabilidad mínima de CADA dígito (0.95 = casi sin errores pero lee menos)

_RUTA_MODELO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_digitos_modelo.npz")
_modelo = None

# OpenCV 5 quito HOGDescriptor: hay que usar OpenCV 4 (pip install "opencv-python<5").
# En la Raspberry, python3-opencv de apt es OpenCV 4.
if not hasattr(cv2, "HOGDescriptor"):
    raise ImportError(f"OpenCV {cv2.__version__} no tiene HOGDescriptor: instala OpenCV 4 con "
                      f'pip install "opencv-python<5"')
_hog = cv2.HOGDescriptor((TAM_DIGITO, TAM_DIGITO), (10, 10), (5, 5), (5, 5), 9)

# Se calculan UNA vez (antes se recalculaban en cada lectura)
_C, _R = LADO // 2, int(LADO * R_DISCO)
_DISCO = np.zeros((LADO, LADO), np.uint8)
cv2.circle(_DISCO, (_C, _C), _R, 255, -1)
_EN_DISCO = _DISCO > 0
_yy, _xx = np.mgrid[:LADO, :LADO]
_BORDE = np.hypot(_xx - _C, _yy - _C) > 0.85 * _R      # anillo pegado al borde del disco
_CLAHE = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
_H_MIN, _H_MAX, _A_MIN = 0.12 * LADO, 0.6 * LADO, 0.0015 * LADO * LADO   # 0.12: deja pasar los digitos de 100 y 120 (mas pequenos)


# ---------------------------------------------------------------------------
# 1) Preprocesamiento
# ---------------------------------------------------------------------------
def _escalar(img_bgr):
    return cv2.resize(img_bgr, (LADO, LADO), interpolation=cv2.INTER_CUBIC)


def _canal(img_escalada, canal):
    """Canal rojo o V (máximo de B, G, R): el aro rojo y el interior salen CLAROS
    y solo los números grises quedan OSCUROS. Devuelve (imagen, umbral de Otsu)."""
    b, g, r = cv2.split(img_escalada)
    if canal == "v":
        r = cv2.max(cv2.max(b, g), r)        # igual a img.max(axis=2) pero mucho más rápido
    r = cv2.GaussianBlur(_CLAHE.apply(r), (5, 5), 0)
    t, _ = cv2.threshold(r[_EN_DISCO].reshape(-1, 1), 0, 255,
                         cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return r, t


def _mascara(r, t, k_umbral):
    """Máscara (255 = número) con el umbral t * k_umbral, sin ruido ni arcos del aro."""
    numeros = ((r < t * k_umbral) & _EN_DISCO).astype(np.uint8) * 255
    n, et, st, _ = cv2.connectedComponentsWithStats(numeros)
    limpio = np.zeros_like(numeros)
    for k in range(1, n):
        x, y, w, h, a = st[k]
        if not (_H_MIN <= h <= _H_MAX and a >= _A_MIN):
            continue
        sub = et[y:y + h, x:x + w] == k                 # solo el recuadro del componente
        if _BORDE[y:y + h, x:x + w][sub].mean() > 0.35:  # arco del aro, no dígito
            continue
        limpio[y:y + h, x:x + w][sub] = 255
    return limpio


def preprocesar(img_bgr, canal="v", k_umbral=0.90):
    """Devuelve una máscara (255 = número) del tamaño LADO x LADO."""
    r, t = _canal(_escalar(img_bgr), canal)
    return _mascara(r, t, k_umbral)


# ---------------------------------------------------------------------------
# 2) Segmentación en dígitos
# ---------------------------------------------------------------------------
def _normalizar(digito):
    """Recorte de un dígito -> cuadrado 20x20 conservando la proporción."""
    h, w = digito.shape
    lado = int(max(h, w) * 1.15) + 2
    lienzo = np.zeros((lado, lado), np.uint8)
    y0, x0 = (lado - h) // 2, (lado - w) // 2
    lienzo[y0:y0 + h, x0:x0 + w] = digito
    return cv2.resize(lienzo, (TAM_DIGITO, TAM_DIGITO), interpolation=cv2.INTER_AREA)


def segmentar(mascara):
    """Lista de dígitos 20x20 de izquierda a derecha."""
    n, et, st, _ = cv2.connectedComponentsWithStats(mascara)
    cajas = sorted([tuple(st[k][:4]) for k in range(1, n)], key=lambda b: b[0])

    # Unir piezas del mismo dígito (se solapan mucho en horizontal)
    unidas = []
    for b in cajas:
        if unidas:
            x, y, w, h = unidas[-1]
            solape = min(x + w, b[0] + b[2]) - max(x, b[0])
            if solape > 0.6 * min(w, b[2]):
                x0, y0 = min(x, b[0]), min(y, b[1])
                x1, y1 = max(x + w, b[0] + b[2]), max(y + h, b[1] + b[3])
                unidas[-1] = (x0, y0, x1 - x0, y1 - y0)
                continue
        unidas.append(b)

    digitos = []
    for x, y, w, h in unidas:
        # Si la caja es muy ancha, son varios dígitos pegados: se parte en partes iguales
        partes = max(1, int(round(w / (0.62 * h))))
        for i in range(partes):
            xa, xb = x + i * w // partes, x + (i + 1) * w // partes
            pieza = mascara[y:y + h, xa:xb]
            if pieza.size:
                digitos.append(_normalizar(pieza))
    return digitos


# ---------------------------------------------------------------------------
# 3) Clasificador de dígitos (HOG + MLP en NumPy)
# ---------------------------------------------------------------------------
def caracteristicas(digito20):
    return _hog.compute(digito20).ravel()


def _cargar_modelo():
    global _modelo
    if _modelo is None:
        d = np.load(_RUTA_MODELO)
        _modelo = {k: d[k] for k in d.files}
    return _modelo


def clasificar(digitos):
    """Probabilidades (n_digitos x 11) para la lista de dígitos."""
    m = _cargar_modelo()
    x = np.array([caracteristicas(d) for d in digitos], np.float32)
    x = (x - m["media"]) / m["desv"]
    for i in range(int(m["n_capas"])):
        x = x @ m[f"W{i}"] + m[f"b{i}"]
        if i < int(m["n_capas"]) - 1:
            x = np.maximum(x, 0)                              # ReLU
    x = np.exp(x - x.max(axis=1, keepdims=True))
    return x / x.sum(axis=1, keepdims=True)                   # softmax


# ---------------------------------------------------------------------------
# 4) Función para pipeline_pi.py
# ---------------------------------------------------------------------------
def _leer_una(mascara):
    """Una lectura: (texto o None, probabilidad mínima)."""
    digitos = segmentar(mascara)
    if not 1 <= len(digitos) <= 4:
        return None, 0.0
    p = clasificar(digitos)
    idx = p.argmax(axis=1)
    prob = float(p[np.arange(len(idx)), idx].min())
    if prob < PROB_MIN:
        return None, prob
    return "".join(CLASES[i] for i in idx), prob


def leer_numero(recorte_bgr, devolver_detalle=False):
    """
    Lee con cada (canal, umbral) de LECTURAS y acepta el texto si al menos
    MIN_ACUERDO lecturas coinciden.
    "60"  -> lectura segura de un número
    "1x"  -> hay algo que no es dígito (ej. la "t" de 10t): pipeline_pi.py lo rechaza
    None  -> no hay acuerdo suficiente (no se pudo leer con seguridad)
    Con devolver_detalle=True devuelve (texto, prob_media_del_ganador, ms).

    Rendimiento: el recorte se escala una sola vez, cada canal se procesa una sola
    vez (las lecturas con el mismo canal reutilizan CLAHE, desenfoque y Otsu) y se
    para en cuanto MIN_ACUERDO lecturas coinciden (el resultado es el mismo).
    """
    t0 = time.perf_counter()
    img = _escalar(recorte_bgr)
    canales, votos = {}, {}
    texto, prob = None, 0.0
    for i, (canal, k) in enumerate(LECTURAS):
        if canal not in canales:
            canales[canal] = _canal(img, canal)
        t_leido, p_leido = _leer_una(_mascara(*canales[canal], k))
        if t_leido is not None:
            votos.setdefault(t_leido, []).append(p_leido)
            if len(votos[t_leido]) >= MIN_ACUERDO:          # ya hay acuerdo: no hace falta seguir
                break
        # Si ya no es posible llegar a MIN_ACUERDO con las lecturas que faltan, parar
        faltan = len(LECTURAS) - i - 1
        mejor = max((len(v) for v in votos.values()), default=0)
        if mejor + faltan < MIN_ACUERDO:
            break
    if votos:
        ganador = max(votos, key=lambda t: (len(votos[t]), sum(votos[t])))
        if len(votos[ganador]) >= MIN_ACUERDO:
            texto, prob = ganador, float(np.mean(votos[ganador]))
    ms = round((time.perf_counter() - t0) * 1000, 1)
    return (texto, round(prob, 3), ms) if devolver_detalle else texto
