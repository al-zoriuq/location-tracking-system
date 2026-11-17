# parche_celular.py
# Agrega a pipeline_pi.py (version 10/11 + arreglo ZUPT) el MODO CELULAR UNIFICADO:
#   --celular   la ubicacion llega desde la app por UDP al puerto 5006 (no se usa la antena GPS)
#   --reenviar  la Pi reenvia esa posicion al servidor (5005) con su Device, junto con las senales
#   + comandos de la app (CMD,PAUSA / REANUDA / APAGAR / ESTADO), --sin-monitor, --no-apagar
#   + mensaje con Device ESP32S3-SIM7670G y hora sin fracciones de segundo.
# Guarda una copia en pipeline_pi_antes_celular.py. Si algo no cuadra, NO cambia nada.
# Se puede correr varias veces (y sirve tambien si ya habias corrido una version anterior).
import re
import shutil
import sys

ARCHIVO = "pipeline_pi.py"
s = open(ARCHIVO, encoding="utf-8").read()
if "REENVIAR = False" in s:
    print("Ya tenia el modo celular completo: no habia nada que cambiar")
    sys.exit(0)
faltan = []


def rep(viejo, nuevo, obligatorio=True):
    global s
    if s.count(viejo) == 1:
        s = s.replace(viejo, nuevo)
    elif obligatorio:
        faltan.append(viejo.strip().splitlines()[0][:70])


if "class Celular(" not in s:
    # 1) Mensaje: Device de la ESP32 y hora sin fracciones de segundo
    s = re.sub(r'^DEVICE_ID = ".*"', 'DEVICE_ID = "ESP32S3-SIM7670G"', s, count=1, flags=re.M)

    if "replace(microsecond=0)" not in s:
        rep('    hora = d["hora"].strftime("%Y-%m-%d %H:%M:%S.%f %z")\n',
            '    hora = d["hora"].replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S.%f %z")\n')

    # 2) Imports que faltan
    for mod in ("math", "re", "subprocess"):
        if not re.search(rf"^import {mod}$", s, flags=re.M):
            s = s.replace("import socket\n", f"import socket\nimport {mod}\n", 1)

    # 3) Variables globales nuevas
    rep('POS_FIJA = None',
        'MODO_CELULAR = False      # --celular: la posicion la manda la app (no se reenvia cada 10 s)\n'
        'PAUSADO = False           # CMD,PAUSA desde la app: no se procesan cuadros\n'
        'N_EVENTOS = 0             # senales reportadas (para EST,...)\n'
        'POS_FIJA = None')

    # 4) Clase Celular (antes de la clase del MPU)
    CEL = '''

# ---------------------------------------------------------------- posicion desde el celular (--celular)
_RE_APP = re.compile(r"Device:\\s*(?P<dev>[^,]+),\\s*Lat:\\s*(?P<lat>-?\\d+(?:\\.\\d+)?),\\s*"
                     r"Lon:\\s*(?P<lon>-?\\d+(?:\\.\\d+)?),\\s*Timestamp GPS:\\s*(?P<ts>[^,]+)")


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
'''
    rep("\n\n# ---------------------------------------------------------------- MPU6050",
        CEL + "\n\n# ---------------------------------------------------------------- MPU6050")

    # 5) En modo celular la Pi no reenvia la posicion cada 10 s (ya la manda la app)
    rep('        fresca = POS_FIJA is not None or',
        '        if MODO_CELULAR:\n'
        '            return          # la app ya manda su posicion al servidor: no se duplica\n'
        '        fresca = POS_FIJA is not None or')
    rep('                + (f" | NMEA ok {gps.n_ok} malas {gps.n_mal} sinfix {gps.n_sin_fix}" if gps else ""))\n',
        '                + (f" | celular {gps.n_ok} msj" if MODO_CELULAR and gps else\n'
        '                   f" | NMEA ok {gps.n_ok} malas {gps.n_mal} sinfix {gps.n_sin_fix}" if gps else ""))\n',
        obligatorio=False)

    # 6) Contar las senales reportadas
    rep('    def reportar(clase, conf, votos):\n',
        '    def reportar(clase, conf, votos):\n        global N_EVENTOS\n        N_EVENTOS += 1\n')

    # 7) Pausa en el bucle principal
    rep('            while True:\n                t0 = time.perf_counter()\n',
        '            while True:\n'
        '                if PAUSADO:                     # CMD,PAUSA desde la app\n'
        '                    time.sleep(0.2)\n'
        '                    continue\n'
        '                t0 = time.perf_counter()\n')

    # 8) Opciones nuevas de la linea de comandos
    rep('    ap.add_argument("--bus-i2c"',
        '    ap.add_argument("--celular", nargs="?", const=5006, type=int, default=None, metavar="PUERTO",\n'
        '                    help="usar la ubicacion que manda la app por UDP (puerto 5006 por defecto)")\n'
        '    ap.add_argument("--device-celular", action="store_true",\n'
        '                    help="las detecciones salen con el mismo Device que manda la app")\n'
        '    ap.add_argument("--vel-edad", type=float, default=None, metavar="S",\n'
        '                    help="usar la velocidad de la app si el punto tiene <= S s (por defecto 3)")\n'
        '    ap.add_argument("--no-apagar", action="store_true", help="CMD,APAGAR solo pausa (para pruebas)")\n'
        '    ap.add_argument("--sin-monitor", action="store_true", help="no abrir la pagina web del monitor")\n'
        '    ap.add_argument("--bus-i2c"')
    rep('    if not args.sin_gps and not args.pos:\n',
        '    if args.vel_edad:\n'
        '        VEL_GPS_MAX_EDAD_S = args.vel_edad\n'
        '    if args.celular:\n'
        '        MODO_CELULAR = True\n'
        '        gps = Celular(args.celular, apagar=not args.no_apagar,\n'
        '                      device_del_celular=args.device_celular)\n'
        '        gps.start()\n'
        '    elif not args.sin_gps and not args.pos:\n')
    rep('    threading.Thread(target=correr, daemon=True).start()\n'
        '    print(f"Monitor en: http://raspberrypi.local:{PUERTO}/")\n'
        '    crear_app().run(host="0.0.0.0", port=PUERTO, threaded=True)',
        '    hilo = threading.Thread(target=correr, daemon=True)\n'
        '    hilo.start()\n'
        '    if args.sin_monitor:\n'
        '        print("Sin monitor (--sin-monitor). Ctrl + C para salir.", flush=True)\n'
        '        try:\n'
        '            hilo.join()\n'
        '        except KeyboardInterrupt:\n'
        '            print("\\nFin.")\n'
        '    else:\n'
        '        print(f"Monitor en: http://raspberrypi.local:{PUERTO}/")\n'
        '        crear_app().run(host="0.0.0.0", port=PUERTO, threaded=True)')

# 9) Reenvio unificado de la posicion (--reenviar)
rep('MODO_CELULAR = False ',
    'REENVIAR = False          # --reenviar: la Pi reenvia al servidor la posicion de la app\n'
    'MODO_CELULAR = False ')
rep('        if MODO_CELULAR:\n'
    '            return          # la app ya manda su posicion al servidor: no se duplica\n',
    '        if MODO_CELULAR:\n'
    '            if not REENVIAR:\n'
    '                return      # la app ya manda su posicion al servidor: no se duplica\n'
    '            if gps is None or gps.seq == getattr(self, "seq_enviado", -1):\n'
    '                return      # no ha llegado un punto nuevo del celular\n'
    '            self.seq_enviado = gps.seq\n')
rep('    ap.add_argument("--no-apagar"',
    '    ap.add_argument("--reenviar", nargs="?", const=2.0, type=float, default=None, metavar="S",\n'
    '                    help="con --celular: reenviar la posicion de la app al servidor (cada S s, por defecto 2)")\n'
    '    ap.add_argument("--no-apagar"')
rep('    if args.celular:\n        MODO_CELULAR = True\n',
    '    if args.celular:\n        MODO_CELULAR = True\n'
    '        if args.reenviar:\n'
    '            REENVIAR = True\n'
    '            POS_CADA_S = args.reenviar\n')


if faltan:
    print("NO SE CAMBIO NADA. Tu pipeline_pi.py no tiene estas partes como se esperaba:")
    for f in faltan:
        print("   -", f)
    print("Mandame este mensaje y lo ajustamos.")
    sys.exit(1)
compile(s, ARCHIVO, "exec")
shutil.copy(ARCHIVO, "pipeline_pi_antes_celular.py")
open(ARCHIVO, "w", encoding="utf-8").write(s)
print("Listo: modo celular agregado (copia anterior en pipeline_pi_antes_celular.py)")
