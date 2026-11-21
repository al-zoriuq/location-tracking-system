# parche_camara.py
# 1) La posicion se reenvia desde un hilo aparte: sigue saliendo aunque la camara se trabe
#    o la deteccion este en PAUSA (antes se detenia junto con la camara).
# 2) Vigilante: si la camara no entrega cuadros en 20 s, el programa se cierra para que
#    el servicio (systemd) lo vuelva a abrir solo a los 3 s.
# Guarda copia en pipeline_pi_antes_camara.py. Si algo no cuadra, NO cambia nada.
import shutil
import sys

ARCHIVO = "pipeline_pi.py"
s = open(ARCHIVO, encoding="utf-8").read()
if "ULTIMO_CUADRO" in s:
    print("Ya tenia el parche de la camara: no habia nada que cambiar")
    sys.exit(0)
faltan = []


def rep(viejo, nuevo):
    global s
    if s.count(viejo) == 1:
        s = s.replace(viejo, nuevo)
    else:
        faltan.append(viejo.strip().splitlines()[0][:70])


rep('PAUSADO = False ',
    'ULTIMO_CUADRO = 0.0       # time.monotonic() del ultimo cuadro de la camara (vigilante)\n'
    'CAMARA_MAX_S = 20.0       # sin cuadros este tiempo -> se cierra y systemd lo reinicia\n'
    'PAUSADO = False ')
rep('    enviador = Enviador(enviar_udp)\n',
    '    enviador = Enviador(enviar_udp)\n'
    '\n'
    '    def hilo_posicion():\n'
    '        """Reenvia la posicion y vigila la camara, aparte del bucle de la camara."""\n'
    '        global ULTIMO_CUADRO\n'
    '        import os as _os\n'
    '        ULTIMO_CUADRO = time.monotonic() + 30      # margen para cargar modelos y camara\n'
    '        while True:\n'
    '            try:\n'
    '                enviador.tick(time.time())\n'
    '            except Exception as e:\n'
    '                log(f"[ENVIO] error: {e}")\n'
    '            if PAUSADO:\n'
    '                ULTIMO_CUADRO = time.monotonic()\n'
    '            elif time.monotonic() - ULTIMO_CUADRO > CAMARA_MAX_S:\n'
    '                log(f"[CAMARA] sin cuadros hace {CAMARA_MAX_S:.0f} s: se reinicia el programa")\n'
    '                _os._exit(1)\n'
    '            time.sleep(0.5)\n'
    '\n'
    '    threading.Thread(target=hilo_posicion, daemon=True).start()\n')
rep('                frame_bgr = cam.capture_array()\n',
    '                frame_bgr = cam.capture_array()\n'
    '                global ULTIMO_CUADRO\n'
    '                ULTIMO_CUADRO = time.monotonic()\n')
rep('                enviador.tick(ahora)\n', '')

if faltan:
    print("NO SE CAMBIO NADA. No encontre:")
    for f in faltan:
        print("   -", f)
    sys.exit(1)
compile(s, ARCHIVO, "exec")
shutil.copy(ARCHIVO, "pipeline_pi_antes_camara.py")
open(ARCHIVO, "w", encoding="utf-8").write(s)
print("Listo: posicion en hilo aparte + vigilante de camara (copia en pipeline_pi_antes_camara.py)")
