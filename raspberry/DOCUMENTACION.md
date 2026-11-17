# Proyecto 3 — Raspberry Pi Zero 2 W: detector de señales con ubicación del celular

Documentación de los cambios del 16/11/2026 y guía para la sustentación.
Carpeta `raspberry/` del repositorio `location-tracking-system`.

---

## 1. Resumen

La Raspberry Pi detecta señales de tránsito (PARE, CEDA EL PASO y límites de velocidad) con
la cámara y manda cada detección al servidor del proyecto con **el mismo formato de mensaje que
la ESP32**. Así la base de datos y la página web las tratan igual, sin importar qué equipo las
detectó.

Hasta el 10/11 la Pi tomaba la ubicación de una antena GPS NEO-6M. En la prueba en carro esa
antena perdió el fix casi todo el recorrido, así que el 16/11 se cambió el diseño:

- **La ubicación ahora la da el celular.** La app Android GPSLink, que ya manda su ruta al
  servidor, también le manda su posición a la Pi por UDP (puerto 5000). La Pi ya no usa la antena.
- **La app controla la Pi.** Tiene botones Estado, Pausa, Reanudar y Apagar, que mandan
  comandos a la Pi y muestran su respuesta.
- **Arranque automático.** La Pi arranca sola al recibir energía del carro (servicio `systemd`)
  y se apaga de forma ordenada desde la app.
- **Mensaje igualado al de la ESP32.** Hora sin fracciones de segundo y el mismo Device que la
  app, para que las señales queden sobre la ruta de ese carro en la página.

---

## 2. Arquitectura final: envío doble

```
Vehículo 2 (sin Pi):  App ──ruta cada 1 s──────────────────────────► Servidor 52.71.39.197:5000 ──► BD ──► página
Vehículo 1 (con Pi):  App ──ruta cada 1 s──────────────────────────► Servidor 52.71.39.197:5000
                      App ──ruta cada 1 s──► Pi :5000 (UDP)
                                             Pi ──solo detecciones──► Servidor 52.71.39.197:5000
                      App ──CMD,ESTADO|PAUSA|REANUDA|APAGAR──► Pi :5000 ──EST,...──► App
```

**Por qué envío doble y no unificado.** Hay dos vehículos, y uno no lleva Pi. Si la ruta pasara
por la Pi (modo unificado, `--reenviar`), se perdería cada vez que la Pi falle o se apague. Con
envío doble, la ruta depende solo de la app, igual en los dos carros, y la Pi solo agrega las
señales. El modo unificado sigue disponible en el código como alternativa.

| Quién manda | A dónde | Puerto | Qué |
|---|---|---|---|
| App GPSLink | Servidor `52.71.39.197` | 5000/UDP | Ruta, un punto por segundo |
| App GPSLink | Pi (`172.20.10.3` con el hotspot del iPhone) | 5000/UDP | La misma posición, para la Pi |
| App GPSLink | Pi | 5000/UDP | Comandos `CMD,...` |
| Pi | App (a la IP y puerto de donde llegó el comando) | — | Respuesta `EST,...` |
| Pi | Servidor `52.71.39.197` | 5000/UDP | Detecciones |
| Navegador (celular o PC) | Pi | 8000/TCP | Visor web de la cámara |

En la app, los servidores se guardan como `172.20.10.3;52.71.39.197`, con **la Pi primero**,
porque los botones mandan los comandos a la primera IP de la lista.

Requisito de red: la app y la Pi deben estar en la misma red. Se usa el hotspot del iPhone, que
da internet a los dos; el Android que corre la app se conecta a ese wifi.

---

## 3. Formato de los mensajes

**Posición** (la manda la app; la Pi la manda solo en el modo unificado):
```
Device: e3c1a1f3-00d1-4527-859f-825c4922f760, Lat: 11.010328, Lon: -74.798813, Timestamp GPS: 2026-11-16 21:10:29.000000 -0500
```

**Detección** (la manda la Pi). Es la posición más los datos de la señal:
```
Device: e3c1a1f3-..., Lat: 11.030190, Lon: -74.859845, Timestamp GPS: 2026-11-16 21:40:28.000000 -0500, Senal: LIMITE 30, Conf: 0.99, Vel GPS: 32, Vel MPU: NA, Usa: GPS, EXCEDE
```

| Campo | Significado |
|---|---|
| `Device` | ID del vehículo. Con `--device-celular` es el mismo ID que usa la app, así la señal queda sobre la ruta de ese carro |
| `Lat`, `Lon` | Última posición recibida del celular |
| `Timestamp GPS` | Hora del fix del celular + el tiempo que pasó desde que llegó, es decir, la hora de la detección. Sin fracciones de segundo, como la ESP32 |
| `Senal` | `PARE`, `CEDA`, `LIMITE 30`... (el número sale del OCR o del clasificador) |
| `Conf` | Confianza del clasificador (0–1) |
| `Vel GPS` | Velocidad del celular en km/h, o `NA` si el último punto tiene más de 3 s |
| `Vel MPU` | Velocidad del acelerómetro MPU-6050, o `NA` si no está conectado o no se ha calibrado con GPS en los últimos 10 s |
| `Usa` | Qué velocidad se usó para evaluar: `GPS`, `MPU` o `NA` |
| Último campo | `SI` (cumple), `EXCEDE` (supera el límite + 3 km/h de tolerancia) o `NA` (PARE/CEDA, límite sin número o sin velocidad) |
| `pos-Ns` (opcional) | Se agrega si la posición tiene más de 30 s |

**Comandos de la app a la Pi y respuesta:**
```
CMD,ESTADO   →  EST,<device>,ACTIVO,<señales reportadas>
CMD,PAUSA    →  EST,<device>,PAUSADO,<n>
CMD,REANUDA  →  EST,<device>,ACTIVO,<n>
CMD,APAGAR   →  EST,<device>,APAGANDO,<n>    (la Pi se apaga a los 2 s)
```

---

## 4. Archivos de esta carpeta

| Archivo | Qué es |
|---|---|
| `pipeline_pi.py` | El programa de la Pi: cámara, detector, clasificador, OCR, sensores, envío, comandos y visor web. Es la versión del 10/11 con los dos parches ya aplicados y el servidor en el puerto 5000 |
| `parche_celular.py` | Parche que agregó el modo celular sobre la versión del 10/11 (se deja como referencia de qué se cambió) |
| `parche_camara.py` | Parche que movió el reenvío de posición a un hilo aparte y agregó el vigilante de la cámara |
| `ocr_limite.py`, `ocr_digitos.py`, `ocr_digitos_modelo.npz` | OCR propio del equipo para leer el número de los límites (HOG + red MLP, sin Tesseract) |
| `probar_ocr.py` | Prueba del OCR con señales sintéticas |
| `probar_celular.py` | Simula al celular: manda posiciones o un comando a la Pi (puerto 5000) |
| `detector.service` | Servicio `systemd` para que el detector arranque solo |
| `010-gpslink-shutdown` | Regla de `sudo` que deja apagar la Pi sin clave (solo el comando `shutdown`) |

En la Pi van en `/home/gpslink/`, junto con los modelos `detector.eim` y `clasificador.eim`
(Edge Impulse) y el entorno de Python `~/ei-env`.

---

## 5. Qué se hizo, paso a paso (16/11)

1. **Mensaje igual al de la ESP32:** `DEVICE_ID = "ESP32S3-SIM7670G"` por defecto y hora con
   `.000000`.
2. **Modo celular (`--celular`):** nueva clase `Celular`, que recibe la posición por UDP y
   reemplaza a la clase `GPS` sin tocar el resto del programa.
3. **Comandos de la app:** PAUSA, REANUDA, APAGAR y ESTADO, con respuesta `EST`.
4. **Puerto 5000** en la Pi, porque la app tiene ese puerto fijo para todos sus servidores.
5. **Servidor en 5000:** `SERVIDOR_UDP = ("52.71.39.197", 5000)`, el puerto del sniffer de
   producción (`PORT = 5000` en `snifferwpostgresql.py`).
6. **Decisión de envío doble:** `--device-celular` y sin `--reenviar`.
7. **Robustez de la cámara:** posición en un hilo aparte y vigilante que reinicia el programa
   si la cámara se traba.
8. **Sistema operativo:** servicio `systemd`, permiso de apagado y visor web siempre disponible.
9. **App (compañero de equipo):** `UbicacionService.kt` (GPS cada 1 s sin distancia mínima, en
   un servicio en primer plano) y botones en `MainActivity.kt`.

---

## 6. Explicación del código (para la sustentación)

### 6.1 Repaso: cómo detecta una señal

Por cada cuadro de la cámara (640×480, unos 30 fps):

1. **Zona de detección.** Se toma el cuadrado **derecho** de la imagen (`ZONA = "derecha"`),
   porque en Colombia las señales van a la derecha de la vía. Igual que la ESP32.
2. **Detector FOMO** (`detector.eim`, 96×96): dice **dónde** hay una señal, en unos 7 ms.
3. **Clasificador** (`clasificador.eim`, 48×48 en grises): dice **qué** señal es, entre 14
   clases (10…120, ceda, pare, otro). Solo corre cuando el detector encontró algo.
4. **Filtro de forma y umbral por clase** (`UMBRAL_PARE = 0.5`, `UMBRAL_LIMITE = 0.7`...), que
   descarta falsos positivos.
5. **OCR del número** en los límites (`ocr_limite.py`): si lee un valor válido, gana sobre el
   clasificador.
6. **Votación por evento** (clase `Evento`): una señal física se ve en muchos cuadros, pero se
   reporta **una sola vez**. Se cierra el evento cuando la señal desaparece 2.5 s
   (`FIN_EVENTO_S`), se exigen al menos 2 votos (`VOTOS_MINIMO`) y la misma clase no se repite
   antes de 15 s (`NO_REPETIR_S`).
7. **Reporte:** `reportar()` arma la línea con posición y velocidades del momento, la guarda en
   `eventos.csv` y la manda por UDP.

### 6.2 La clase `Celular`: un reemplazo del GPS con la misma interfaz

La idea clave del cambio: el resto del programa (MPU, `leer_sensores`, `Enviador`, monitor) ya
usaba un objeto `gps` con atributos `fix`, `seq`, `sats`, `ok`, `n_ok`... La clase `Celular`
**expone exactamente esos mismos atributos**, así que se cambia la fuente de la ubicación sin
modificar a nadie más. Es polimorfismo por interfaz ("duck typing" en Python): a quien usa
`gps.fix` no le importa si el dato vino de la antena o del celular.

```python
class Celular(threading.Thread):
    def __init__(self, puerto, apagar=True, device_del_celular=False):
        super().__init__(daemon=True)
        self.fix = None            # {"lat", "lon", "kmh", "utc", "t_mono", "sats"} igual que GPS
        self.sats = 0              # el celular no lo dice: queda en 0
        self.seq = 0               # sube con cada punto nuevo (el MPU lo usa para calibrarse)
        self.n_ok = self.n_mal = self.n_sin_fix = 0
        self.hist = deque(maxlen=20)   # ultimos puntos, para calcular la velocidad
```

En `__main__`, la única diferencia es qué objeto se crea:

```python
if args.celular:
    MODO_CELULAR = True
    gps = Celular(args.celular, apagar=not args.no_apagar,
                  device_del_celular=args.device_celular)
    gps.start()
elif not args.sin_gps and not args.pos:
    gps = GPS(args.gps, args.baudios)      # antena NEO-6M (modo anterior)
    gps.start()
```

Es un **hilo** (`threading.Thread`, `daemon=True`): escucha la red en paralelo, sin frenar el
ciclo de la cámara, y se cierra solo cuando termina el programa.

### 6.3 Recibir por UDP

```python
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # UDP
sock.bind(("0.0.0.0", self.puerto))                       # escucha en todas las interfaces
while True:
    datos, origen = sock.recvfrom(2048)                   # bloquea hasta que llegue un paquete
    texto = datos.decode("utf-8", errors="ignore").strip()
    if texto.upper().startswith("CMD,"):
        self._comando(texto[4:].strip().upper(), sock, origen)
    elif not self._posicion(texto):
        self.n_mal += 1
```

- **Por qué UDP.** Es lo que ya usaban la app y el servidor, no necesita conexión y un paquete
  perdido no frena nada: llega otro al segundo siguiente.
- `recvfrom` devuelve también **`origen`** (IP y puerto de quien mandó). Con eso la Pi le
  contesta los comandos al celular sin necesitar su IP de antemano.
- El mismo socket sirve para recibir posiciones y comandos. Se distinguen por el prefijo `CMD,`.

### 6.4 Leer el mensaje de la app: expresión regular

La app manda su mensaje de siempre. La Pi lo lee con una expresión regular:

```python
_RE_APP = re.compile(r"Device:\s*(?P<dev>[^,]+),\s*Lat:\s*(?P<lat>-?\d+(?:\.\d+)?),\s*"
                     r"Lon:\s*(?P<lon>-?\d+(?:\.\d+)?),\s*Timestamp GPS:\s*(?P<ts>[^,]+)")
```

- `(?P<lat>...)` son **grupos con nombre**: después se lee `m["lat"]`.
- `-?\d+(?:\.\d+)?` es un número con signo opcional y decimales opcionales.
- La hora se convierte con `strptime("%Y-%m-%d %H:%M:%S.%f %z")`. `%z` acepta `-0500` y
  `-05:00` (la app manda el segundo), y `%f` acepta 3 o 6 decimales.
- También se acepta un formato corto, `GPS,lat,lon[,kmh[,epoch_ms]]`, por si en el futuro la app
  manda la velocidad real del celular.
- Validación: se descartan coordenadas fuera de rango y el punto (0, 0), que es lo que mandan
  algunos GPS cuando no tienen fix.

### 6.5 Velocidad a partir de posiciones (haversine)

El mensaje de la app no trae velocidad, así que la Pi la calcula: distancia entre dos puntos
dividida por el tiempo entre ellos.

```python
def _distancia_m(lat1, lon1, lat2, lon2):
    r = 6371000.0                                   # radio medio de la Tierra (m)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
```

Es la **fórmula de haversine**: distancia sobre una esfera entre dos coordenadas. A distancias
cortas da prácticamente lo mismo que medir en un plano, pero no falla en ningún caso.

```python
for u0, m0, la0, lo0 in self.hist:          # del punto mas viejo al mas nuevo
    dt = (utc - u0).total_seconds()
    if dt <= 0:
        dt = ahora - m0                     # horas iguales o repetidas: tiempo de llegada
    if 0.9 <= dt <= 8:
        kmh = _distancia_m(la0, lo0, lat, lon) / dt * 3.6
        break
```

**Por qué no se usa el punto inmediatamente anterior.** La posición del celular varía unos
metros de una lectura a otra, aunque esté quieto. Con 1 s entre puntos, 3 m de error ya son
unos 11 km/h falsos. Usando el punto más viejo dentro de 8 s, el error se reparte en más tiempo
y la velocidad sale estable. En la prueba quieta dio `GPS 0 km/h`, y con el simulador a 9 m/s
dio exactamente `32 km/h`.

### 6.6 La hora de la detección

```python
edad = time.monotonic() - f["t_mono"]                 # cuanto paso desde que llego el punto
hora = (f["utc"] + timedelta(seconds=edad)).astimezone(ZONA_COL)
```

La hora del mensaje es la del fix del celular **más su edad**, es decir, el momento en que se
detectó la señal, y no el de la última posición. Se usa `time.monotonic()` porque no salta si
cambia el reloj del sistema. Esto importa porque la Pi no tiene reloj con batería, y al
arrancar sin internet su hora puede estar mal. La hora buena siempre viene del GPS del celular.
Luego `replace(microsecond=0)` deja la hora sin fracciones, como la ESP32.

### 6.7 Qué velocidad se usa (`leer_sensores`)

```python
if edad <= VEL_GPS_MAX_EDAD_S:          # 3 s, igual que la ESP32
    d["v_gps"] = f["kmh"]
...
if d["v_gps"] is not None:
    d["usa"], d["v"] = "GPS", d["v_gps"]
elif mpu_ok:                             # MPU calibrado con un fix en los ultimos 10 s
    d["usa"], d["v"] = "MPU", mpu.v_resp * 3.6
```

- La velocidad del celular solo vale si el punto tiene 3 s o menos. Si no, sale `NA`: es mejor
  no evaluar que evaluar con una velocidad vieja.
- El MPU-6050 es el respaldo. Integra la aceleración, y eso acumula error, así que solo se usa
  si un fix lo calibró hace 10 s o menos. Mientras no esté conectado, `Vel MPU: NA`.
- **Cumplimiento** (`linea_deteccion`): `EXCEDE` si `v > límite + 3 km/h`; `SI` si no; `NA`
  para PARE/CEDA o si no hay velocidad.

### 6.8 Comandos de la app

```python
def _comando(self, cmd, sock, origen):
    global PAUSADO
    if cmd == "PAUSA":
        PAUSADO = True
    elif cmd == "REANUDA":
        PAUSADO = False
    elif cmd == "APAGAR":
        PAUSADO = True
        self._responder(sock, origen, "APAGANDO")           # contesta ANTES de apagarse
        if self.apagar:
            threading.Timer(2.0, lambda: subprocess.run(
                ["sudo", "-n", "shutdown", "-h", "now"])).start()
        return
    self._responder(sock, origen, "PAUSADO" if PAUSADO else "ACTIVO")
```

- **PAUSA** pone una bandera global. El ciclo de la cámara la revisa al inicio de cada vuelta y,
  si está activa, duerme 0.2 s sin procesar nada. Así se ahorra CPU sin cerrar el programa:
  ```python
  while True:
      if PAUSADO:
          time.sleep(0.2)
          continue
      frame_bgr = cam.capture_array()
  ```
- **APAGAR** primero contesta y después programa el apagado a los 2 s con un `Timer`, para que
  la respuesta alcance a llegar al celular.
- `sudo -n` significa "no pidas clave": si falta el permiso, falla en vez de quedarse esperando
  una clave que nadie va a escribir. El permiso está en `010-gpslink-shutdown` y **solo**
  permite `shutdown`, nada más.
- `--no-apagar` sirve para probar el botón sin que la Pi se apague (solo pausa).
- El número de la respuesta (`N_EVENTOS`) cuenta las señales reportadas desde que arrancó el
  programa. Con el botón Estado se puede comprobar que detecta sin abrir ninguna terminal.

### 6.9 `--device-celular`

```python
if dev != self.device_app:
    self.device_app = dev
    if self.device_del_celular:
        global DEVICE_ID
        DEVICE_ID = dev
```

Con el primer mensaje de la app, la Pi adopta su Device (un UUID que la app genera una vez por
instalación). Desde ese momento, las detecciones salen con el mismo ID que la ruta del carro y
la web las dibuja encima. Antes de ese primer mensaje, el ID es `ESP32S3-SIM7670G`, pero en ese
lapso no se manda nada, porque sin posición no hay envío.

El sniffer guarda la ubicación y la detección en tablas distintas, con
`ON CONFLICT DO NOTHING`. Si la app y la Pi mandan el mismo punto con el mismo Device y la
misma hora, la ubicación repetida se ignora y la detección se guarda igual.

### 6.10 Envío (`Enviador`) y el hilo de posición

```python
def enviar(self, linea, d):
    if not self.activo:        estado_txt = "SIN ENVIO (usa --udp)"
    elif d["lat"] is None:     estado_txt = "SIN GPS (no se envia)"   # el servidor exige Lat/Lon
    else:
        self.sock.sendto(linea.encode(), SERVIDOR_UDP)
        estado_txt = "ENVIADO"
    log(f"[ENVIO] {linea} | {estado_txt}")
```

`tick()` se encarga de la posición periódica. En modo celular **no** manda la ruta, porque ya la
manda la app, salvo en el modo unificado (`--reenviar`). En ese caso manda solo cuando llega un
punto nuevo (`gps.seq` cambió), para no repetir el mismo punto con horas distintas.

**Hilo aparte y vigilante de la cámara.** Antes, `tick()` se llamaba dentro del ciclo de la
cámara. Si la cámara se trababa (pasó con la cinta floja: `Camera frontend has timed out`), se
trababa todo lo demás. Ahora corre en su propio hilo, cada 0.5 s:

```python
def hilo_posicion():
    ULTIMO_CUADRO = time.monotonic() + 30          # margen para cargar modelos y camara
    while True:
        enviador.tick(time.time())
        if PAUSADO:
            ULTIMO_CUADRO = time.monotonic()       # en pausa no hay cuadros y esta bien
        elif time.monotonic() - ULTIMO_CUADRO > CAMARA_MAX_S:     # 20 s
            log("[CAMARA] sin cuadros hace 20 s: se reinicia el programa")
            _os._exit(1)
        time.sleep(0.5)
```

Si la cámara no entrega cuadros en 20 s, el programa se cierra a propósito, y `systemd`
(`Restart=always`) lo vuelve a abrir a los 3 s. Reiniciar la cámara suele recuperar un fallo
pasajero.

### 6.11 Opciones de línea de comandos

| Opción | Qué hace |
|---|---|
| `detector.eim clasificador.eim` | Rutas a los modelos. **Con ruta completa** (`~/detector.eim`): Edge Impulse los ejecuta como programas, y sin `/` Linux no los busca en la carpeta actual |
| `--udp` | Manda al servidor. Sin esto solo muestra en pantalla (`SIN ENVIO`) |
| `--celular 5000` | Toma la ubicación de la app en ese puerto. Sin número usa 5006, por eso siempre se escribe `5000` |
| `--device-celular` | Las detecciones salen con el Device de la app (envío doble) |
| `--reenviar [S]` | Modo unificado: la Pi reenvía la ruta al servidor (cada S s, por defecto 2) |
| `--vel-edad S` | Acepta la velocidad del celular si el punto tiene hasta S s (por defecto 3) |
| `--no-apagar` | APAGAR solo pausa (para probar) |
| `--sin-monitor` | No abre el visor web |
| `--sin-mpu`, `--sin-gps`, `--pos lat,lon` | Pruebas sin sensores |

Comando del servicio:
```bash
/home/gpslink/ei-env/bin/python /home/gpslink/pipeline_pi.py /home/gpslink/detector.eim /home/gpslink/clasificador.eim --celular 5000 --udp --device-celular
```

### 6.12 Por qué los cambios se hicieron con "parches"

En vez de copiar un archivo nuevo encima del de la Pi, se usaron scripts (`parche_celular.py`,
`parche_camara.py`) que buscan fragmentos exactos del código y los reemplazan:

- **Todo o nada:** si un fragmento no aparece exactamente una vez, no cambia nada y dice cuál
  falta. Así no se rompe una versión distinta.
- **Copia de seguridad automática** (`pipeline_pi_antes_*.py`).
- **Se pueden correr varias veces:** si ya se aplicaron, avisan y no hacen nada.
- Se pegan por SSH en un solo bloque (`cat > archivo << 'EOF'`), sin necesidad de `scp`.

---

## 7. Configuración del sistema operativo

**Servicio `systemd` (`detector.service`).** Arranca el detector al encender la Pi
(`WantedBy=multi-user.target`), espera a que haya red (`network-online.target`), lo reinicia si
se cae (`Restart=always`, 3 s) y corre como el usuario `gpslink`, no como root.
`PYTHONUNBUFFERED=1` hace que los mensajes salgan enseguida en `journalctl`.
```bash
sudo systemctl enable --now detector     # activar
systemctl status detector                # ver estado
journalctl -u detector -f                # ver el log en vivo
sudo systemctl stop detector             # detener (necesario antes de correrlo a mano)
```

**Permiso de apagado (`/etc/sudoers.d/010-gpslink-shutdown`, permisos 440).** Permite **solo**
`shutdown` sin clave, para el botón APAGAR. Se valida con `sudo visudo -c`.

**Visor web.** El servicio corre sin `--sin-monitor`, así que desde cualquier equipo del hotspot
se abre `http://172.20.10.3:8000` y se ve la cámara con las cajas de detección. El video solo se
comprime mientras alguien lo está mirando, así que dejarlo activo no le quita rendimiento a la
detección.

**Hotspot nuevo sin borrar la SD.** NetworkManager guarda varias redes:
```bash
read -s -p "Clave: " CLAVE; echo
sudo nmcli connection add type wifi ifname wlan0 con-name hotspot-nuevo ssid "NOMBRE" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$CLAVE" connection.autoconnect yes connection.autoconnect-priority 10
unset CLAVE
```

**Overlay de solo lectura (pendiente, va de último).** El USB-C del carro corta la energía de
golpe. Con el overlay activo, la SD no se escribe durante el uso, así que el corte no la daña.
Lo que se escribe (logs, `eventos.csv`) queda en RAM y se pierde al apagar.
```bash
sudo raspi-config nonint enable_overlayfs && sudo raspi-config nonint enable_bootro && sudo reboot
```

---

## 8. Cambios en la app (hechos por un compañero)

- **`UbicacionService.kt`:** el GPS corre en un **servicio en primer plano** (con notificación),
  así que sigue enviando con la pantalla apagada. Usa
  `requestLocationUpdates(GPS_PROVIDER, 1000 ms, 0 m)`: un punto por segundo y **sin distancia
  mínima**, o sea que manda aunque el carro esté quieto en un semáforo. Un vigilante avisa
  "Sin señal GPS hace X s". Manda el mismo mensaje a cada IP de la lista (separadas por `;`),
  siempre al puerto 5000.
- **`MainActivity.kt`:** botones Estado, Pausa, Reanudar y Apagar (este último con
  confirmación). Mandan `CMD,...` a la primera IP de la lista y muestran la respuesta `EST`, con
  un tiempo de espera de 2 s.
- **Antes**, la app pedía un solo punto cada 10 s y se trababa si el GPS no respondía. Por eso
  en las primeras pruebas la Pi recibía 7 mensajes y se quedaba sin datos.
- El servidor ahora recibe 10 veces más ubicaciones (cada 1 s en vez de cada 10 s).

---

## 9. Pruebas realizadas

| Prueba | Resultado |
|---|---|
| Parche sobre la versión del 10/11 (con y sin los cambios previos del mensaje) | Mismo resultado en los dos casos; compila |
| Mensajes simulados (`probar_celular.py`) | La Pi recibe, calcula 32 km/h (velocidad simulada) y responde ESTADO, PAUSA, REANUDA y APAGAR |
| Modo unificado contra un servidor simulado | La Pi reenvía `Device: ESP32S3-SIM7670G, ...` cada 2 s |
| Rendimiento en la Pi | Detector de unos 7 ms; unos 30 fps con el modo celular activo |
| App real, primera versión | Llegaba desde `172.20.10.4`, pero paraba a los 7 mensajes (problema de la app) |
| App real, cadena completa | `[ENVIO] ... \| ENVIADO` al servidor con la posición del celular |
| App nueva (envío cada 1 s) | El contador sube 10 por cada 10 s; `GPS 0 km/h \| usa GPS` estando quieta |
| Servicio | Corre con `systemd` y recibe la ubicación de la app (`celular N msj` subiendo) |
| Botones de la app | Responden con `EST,...` |
| **Por confirmar** | Detección de señales de punta a punta (señal frente a la cámara → página): en la última prueba en la mesa no detectaba; revisar con el visor que la señal quede en la zona derecha |
| **Pendiente** | Prueba en carro con este esquema, `vcgencmd get_throttled`, MPU conectado y overlay |

---

## 10. Problemas encontrados y solución

| Problema | Causa | Solución |
|---|---|---|
| La antena NEO-6M perdía el fix en el carro | Ubicación de la antena e interferencia | Se usa la ubicación del celular (`--celular`) |
| `FileNotFoundError: 'detector.eim'` | Edge Impulse ejecuta el `.eim` como programa; sin `/`, Linux lo busca en el PATH y no en la carpeta | Rutas completas: `~/detector.eim` |
| `probar_celular.py`: "Sin respuesta" | El script apuntaba al 5006 y la Pi escuchaba en el 5000 | `sed` a 5000 |
| La app no le llegaba a la Pi | El Android no estaba en el hotspot del iPhone, o apuntaba a la IP del servidor | Mismo wifi e IP de la Pi en la app |
| La app paraba a los 7 mensajes | Pedía un solo punto cada 10 s y se trababa sin GPS | App nueva: escucha continua cada 1 s, sin distancia mínima |
| `Camera frontend has timed out` | Cinta de la cámara floja por vibración | Reasentar y fijar la cinta; vigilante que reinicia el programa |
| La ruta se cortaba si la cámara se trababa o en PAUSA (modo unificado) | El reenvío estaba dentro del ciclo de la cámara | Hilo aparte (`parche_camara.py`) |
| "No detecta" con la señal centrada | La zona de detección es el cuadrado derecho | Poner la señal a la derecha; verificar en el visor |
| `[MPU] no disponible` | MPU sin conectar | Funciona igual (`Vel MPU: NA`); al conectarlo se detecta solo |
| Primera versión del plan con el puerto 5005 | El sniffer de producción usa `PORT = 5000` | Servidor en 5000 |

---

## 11. Limitaciones y riesgos

- **UDP no confirma la entrega.** Una detección enviada sin red se pierde; queda solo en
  `eventos.csv`, y con el overlay eso también se borra al apagar. Mejora futura: confirmación
  `DET`/`ACK` con la app como respaldo.
- **Si se cae el hotspot**, la Pi se queda sin posición y sin internet: se pierden las señales
  de ese tramo. La ruta sigue, porque la manda la app.
- **Cualquier equipo en el hotspot puede mandar `CMD,APAGAR`.** El riesgo es bajo porque el
  hotspot tiene clave.
- **La velocidad se calcula con posiciones**, así que en curvas cerradas o con mala señal es
  menos precisa que la velocidad que mide el propio celular (`location.speed`).
- **Detecta a unos 30 fps**, pero a velocidades altas una señal pequeña queda pocos cuadros
  en la zona de detección.

---

## 12. Preguntas probables en la sustentación

**¿Por qué cambiaron la antena GPS por el celular?**
En la prueba en carro del 10/11 la NEO-6M perdió el fix casi todo el recorrido. El celular ya
tiene un GPS mejor (GPS, GLONASS, Galileo y asistencia por red), ya estaba en el carro y ya
mandaba su ruta al servidor. Además se liberó la UART de la Pi.

**¿Cómo le llega la ubicación a la Pi?**
La app manda su mensaje normal por UDP a la IP de la Pi, puerto 5000. Un hilo en la Pi (clase
`Celular`) escucha ese puerto, lee el mensaje con una expresión regular y guarda el último punto
en `fix`, con los mismos campos que usaba la clase `GPS`.

**¿Por qué no tuvieron que reescribir el resto del programa?**
Porque `Celular` tiene la misma interfaz que `GPS` (`fix`, `seq`, `sats`...). El resto del
código solo lee `gps.fix`, así que no le importa de dónde viene el dato.

**¿Cómo calculan la velocidad si la app no la manda?**
Con la distancia de haversine entre el punto actual y uno de hace 1 a 8 s, dividida por el
tiempo entre ellos. Usar un punto más viejo reduce el efecto del ruido de posición.

**¿Qué hora lleva cada detección?**
La del último fix del celular más el tiempo que pasó desde que llegó, medido con
`time.monotonic()`. La Pi no tiene reloj con batería, así que no se usa su reloj.

**¿Por qué envío doble y no que todo pase por la Pi?**
Porque hay un vehículo sin Pi, y porque la ruta no debe depender de la Pi. En el modo doble, si
la Pi falla, solo se pierden las señales; la ruta sigue llegando desde la app.

**¿Cómo se relaciona una señal con la ruta del carro en la web?**
Por el `Device`. Con `--device-celular`, la Pi usa el mismo ID que la app, y el sniffer guarda
la detección en su propia tabla, con ese Device, posición y hora.

**¿Qué pasa si el carro se apaga de golpe?**
El servicio vuelve a arrancar solo al encender. Para no dañar la SD está el botón APAGAR (apagado
ordenado) y, al final, el overlay de solo lectura, con el que un corte no escribe nada en la SD.

**¿Cómo apaga la app a la Pi sin darle permisos de administrador?**
Una regla de `sudoers` permite al usuario `gpslink` ejecutar **solo** `shutdown` sin clave. El
programa usa `sudo -n`, que nunca se queda esperando una clave.

**¿Qué pasa si la cámara se traba?**
Un hilo vigila que lleguen cuadros. Si pasan 20 s sin cuadros, el programa se cierra y `systemd`
lo reabre a los 3 s.

**¿Cómo saben que está funcionando sin conectarse por SSH?**
Con el botón Estado (`Pi: ACTIVO · señales: N`, el contador sube con cada señal), el visor web
en `http://IP_PI:8000` y la página del proyecto.

**¿Por qué UDP y no TCP?**
Es lo que ya usaban la ESP32, la app y el sniffer. No necesita mantener una conexión que se cae
con la red móvil, y para datos que se repiten cada segundo un paquete perdido no importa. Para
las detecciones sí es una limitación, que se reconoce en la sección 11.

**¿Por qué la misma señal no se reporta muchas veces?**
La clase `Evento` agrupa todos los cuadros de una misma señal física, vota la clase y la reporta
una vez cuando la señal sale de la imagen. La misma clase no se repite antes de 15 s.

---

## 13. Comandos rápidos

```bash
# Ver si está corriendo solo (servicio)
systemctl is-active detector                  # active
ps -eo pid,ppid,etime,cmd | grep [p]ipeline_pi   # PPID 1 = lo lanzó systemd
journalctl -u detector -f                     # log en vivo (Ctrl+C solo cierra la vista)

# Correrlo a mano (para probar)
sudo systemctl stop detector
cd ~ && source ~/ei-env/bin/activate
python pipeline_pi.py ~/detector.eim ~/clasificador.eim --celular 5000 --udp --device-celular --no-apagar
sudo systemctl start detector                 # al terminar, dejar el servicio otra vez

# Simular el celular (en la Pi)
python probar_celular.py 127.0.0.1            # posiciones (ojo: con --udp van al servidor real)
python probar_celular.py 127.0.0.1 ESTADO     # o PAUSA, REANUDA, APAGAR

# Revisar
hostname -I                                   # IP de la Pi
grep -n "^SERVIDOR_UDP" ~/pipeline_pi.py      # ("52.71.39.197", 5000)
vcgencmd get_throttled                        # 0x0 = alimentación correcta
i2cdetect -y 1                                # 68 = MPU conectado
sudo tcpdump -ni wlan0 -A udp port 5000       # ver lo que llega del celular
```
