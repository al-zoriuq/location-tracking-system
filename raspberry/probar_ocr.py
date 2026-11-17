# probar_ocr.py
# Mide EN LA RASPBERRY cuanto tarda y cuanto acierta el OCR (ocr_limite.py) con los
# recortes reales de la camara que estan en fotos_prueba/ (el nombre empieza por el valor).
# No necesita camara, GPS ni modelos .eim.
#
# Uso:  source ~/ei-env/bin/activate
#       python probar_ocr.py                 (usa fotos_prueba/)
#       python probar_ocr.py otra_carpeta
#
# Nota: el modelo final se entreno tambien con estas fotos, asi que el % de aciertos
# aqui es optimista. Lo importante de esta prueba es el TIEMPO en la Pi Zero 2 W.

import glob
import os
import sys
import time

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import ocr_limite as o        # noqa: E402

carpeta = sys.argv[1] if len(sys.argv) > 1 else os.path.join(AQUI, "fotos_prueba")
archivos = sorted(f for f in glob.glob(os.path.join(carpeta, "*"))
                  if f.lower().endswith((".png", ".jpg", ".jpeg")))
if not archivos:
    sys.exit(f"No hay imagenes en {carpeta}")

imagenes = [(os.path.basename(f), cv2.imread(f)) for f in archivos]
o.leer_numero(imagenes[0][1])                    # calentar (primera llamada)

aciertos = sin_lectura = errores = 0
tiempos = []
for nombre, img in imagenes:
    t0 = time.perf_counter()
    texto = o.leer_numero(img)
    tiempos.append((time.perf_counter() - t0) * 1000)
    real = nombre.split(".")[0]
    if texto == real:
        aciertos += 1
    elif texto is None:
        sin_lectura += 1
    else:
        errores += 1
        print(f"  distinto: {nombre} -> {texto}")

# Tiempo con recortes del tamano tipico en la camara (senal de 40, 80 y 120 px)
for lado in (48, 96, 144):
    img = cv2.resize(imagenes[0][1], (lado, lado), interpolation=cv2.INTER_CUBIC)
    t = []
    for _ in range(20):
        t0 = time.perf_counter()
        o.leer_numero(img)
        t.append((time.perf_counter() - t0) * 1000)
    print(f"Recorte de {lado}x{lado} px: mediana {np.median(t):.1f} ms")

n = len(imagenes)
print(f"\nImagenes: {n} | correctas {aciertos} | sin lectura {sin_lectura} | distintas {errores}")
print(f"Tiempo por lectura: mediana {np.median(tiempos):.1f} ms | p95 {np.percentile(tiempos, 95):.1f} ms"
      f" | maximo {max(tiempos):.1f} ms")
