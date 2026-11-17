# Raspberry Pi: modo celular (envío doble)

Usuario `gpslink`, todo en `/home/gpslink/`. Entorno: `~/ei-env`. Modelos: `~/detector.eim`, `~/clasificador.eim`.

**Código de la Pi:** `pipeline_pi.py` (versión 10/11 + arreglo ZUPT), `ocr_limite.py` y los `.eim` viven en la Raspberry
y no están en esta carpeta. Para tener una copia:
```
scp gpslink@172.20.10.3:~/pipeline_pi.py gpslink@172.20.10.3:~/ocr_limite.py .
```
Aquí van los scripts que modifican y prueban ese pipeline.

## Archivos de esta carpeta
| Archivo | Para qué |
|---|---|
| `parche_celular.py` | Agrega a `pipeline_pi.py` el modo `--celular` (ubicación desde la app, comandos, `--device-celular`, `--sin-monitor`, `--no-apagar`, `--reenviar`). Si ya está aplicado, no hace nada. |
| `probar_celular.py` | Simula la app: manda posiciones cada 1 s o un comando (`ESTADO`, `PAUSA`, `REANUDA`, `APAGAR`) al puerto 5000. |
| `detector.service` | Servicio systemd para que el detector arranque solo al encender. |
| `010-gpslink-shutdown` | Regla sudoers para que el botón Apagar funcione sin contraseña. |

## Pasos
1. **Copiar los archivos a la Pi** (desde el PC, en esta carpeta):
   ```
   scp parche_celular.py probar_celular.py detector.service 010-gpslink-shutdown gpslink@172.20.10.3:~/
   ```
2. **Aplicar el parche** (solo si el pipeline aún no tiene `--celular`):
   ```
   cd ~ && source ~/ei-env/bin/activate
   cp pipeline_pi.py pipeline_pi_respaldo.py
   python parche_celular.py
   python pipeline_pi.py --help | grep -E "celular|device-celular|sin-monitor"
   ```
3. **Probar a mano** (con la app enviando, o con `python probar_celular.py 127.0.0.1` en otra terminal):
   ```
   python pipeline_pi.py ~/detector.eim ~/clasificador.eim --celular 5000 --udp --device-celular --no-apagar
   ```
   Debe salir `[CELULAR] mensajes desde ...` y el contador `celular N msj` subiendo cada ~1 s.
   `python probar_celular.py 127.0.0.1 ESTADO` → `Respuesta: EST,...,ACTIVO,N`.
4. **Permiso para Apagar:**
   ```
   sudo install -m 440 -o root -g root 010-gpslink-shutdown /etc/sudoers.d/010-gpslink-shutdown
   sudo visudo -c
   sudo -n shutdown --help > /dev/null && echo "SIN CLAVE: OK"
   ```
5. **Arranque automático:**
   ```
   sudo cp detector.service /etc/systemd/system/detector.service
   sudo systemctl daemon-reload && sudo systemctl enable --now detector
   journalctl -u detector -f
   ```
   Para correrlo a mano otra vez: `sudo systemctl stop detector` primero.
6. **En el carro:** `vcgencmd get_throttled` debe dar `throttled=0x0`. Revisar en la página que la ruta y las señales salen sobre el mismo carro.
7. **Al final, overlay (solo lectura)**, cuando todo funcione:
   ```
   sudo raspi-config nonint enable_overlayfs && sudo raspi-config nonint enable_bootro && sudo reboot
   ```
   Para cambiar algo después: `disable_bootro`, `disable_overlayfs`, reboot, cambios, y volver a activarlo.

Nota: no usar `--reenviar` en este esquema. Con envío doble la ruta la manda la app; `--reenviar` es solo para el esquema
en que la app manda únicamente a la Pi.
