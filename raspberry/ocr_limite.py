# ocr_limite.py
# Puente entre pipeline_pi.py y el OCR propio (ocr_digitos.py + ocr_digitos_modelo.npz).
# pipeline_pi.py hace "from ocr_limite import leer_numero".
#
# Solo necesita OpenCV y NumPy (NO Tesseract). Los tres archivos van en la misma carpeta:
#   ocr_limite.py  ocr_digitos.py  ocr_digitos_modelo.npz
#
# - Si falta el modelo, el import falla con ImportError y pipeline_pi.py sigue sin OCR
#   (usa el numero del clasificador).
# - Un error del OCR en plena marcha nunca detiene el pipeline: devuelve None.
# - Sin cache global: cada senal se lee por separado (el cache por senal lo maneja
#   pipeline_pi.py, que sabe cuantas senales hay en el cuadro).

import os
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
if not os.path.exists(os.path.join(_AQUI, "ocr_digitos_modelo.npz")):
    raise ImportError("falta ocr_digitos_modelo.npz junto a ocr_limite.py")

import ocr_digitos as _od          # noqa: E402

_od._cargar_modelo()               # cargar los pesos ya (no en la primera senal)

IMPRIMIR = False                   # True = mostrar cada lectura en la terminal
_ultimo = {"ms": 0.0, "texto": None}


def leer_numero(recorte_bgr):
    """Recorte BGR (1.2x el borde rojo) -> "50", "10T" (no es limite: peso/altura) o None.
    El OCR propio marca con "x" lo que no es un digito (la "t" de 10t, la "m" de 3.5m);
    aqui se convierte en "T" para que interpretar_ocr() de pipeline_pi.py lo rechace."""
    t0 = time.perf_counter()
    try:
        texto = _od.leer_numero(recorte_bgr)
    except Exception as e:         # nunca tumbar el pipeline por el OCR
        print(f"[OCR] error: {e}", flush=True)
        texto = None
    if texto is not None:
        texto = texto.replace("x", "T")
    _ultimo.update(ms=(time.perf_counter() - t0) * 1000, texto=texto)
    if IMPRIMIR:
        print(f"[OCR] leyo {texto} en {_ultimo['ms']:.1f} ms", flush=True)
    return texto


def ultimo_tiempo_ms():
    return _ultimo["ms"]
