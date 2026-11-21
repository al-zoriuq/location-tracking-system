# GPSLink · Location Tracking System

Sistema de rastreo de vehículos en tiempo real. Los dispositivos de cada vehículo (celular con la app GPSLink, Raspberry Pi, ESP32-S3) envían su ubicación por UDP; un servidor la guarda en PostgreSQL y una página web muestra en un mapa la posición actual, las rutas, las paradas y las señales de tránsito detectadas.

Este documento explica cómo ponerlo en marcha desde cero, cómo probarlo y cómo se despliega.

---

## 1. Cómo funciona

```
 Celular (GPSLink) ─┐
 Raspberry Pi      ─┼─ UDP :5000 ─► snifferwpostgresql.py ─► PostgreSQL (RDS)
 ESP32-S3          ─┘                                              ▲
                                                                   │
 Navegador ◄── HTTP ── Nginx :80 ──► Gunicorn ── servidorweb.py ───┘
                                     (API /api/* + página React compilada)
```

- **`snifferwpostgresql.py`**: servidor UDP (puerto `5000`). Lee cada mensaje, guarda la ubicación en `ubicaciones` y, si trae una señal de tránsito, la guarda en `detecciones_senal`. También asigna el alias de cada dispositivo nuevo (ver [Alias de vehículos](#alias-de-vehículos)).
- **`servidorweb.py`**: API en Flask (servida con Gunicorn detrás de Nginx). Sirve también la página compilada (`disenop2web/dist/`).
- **`disenop2web/`**: página web en React + Leaflet (Vite). Consulta la API cada 10 s.

| Carpeta / archivo | Contenido |
|---|---|
| `snifferwpostgresql.py` | Servidor UDP que guarda los mensajes |
| `servidorweb.py` | API y servidor de la página |
| `disenop2web/` | Frontend (React) |
| `tests/` | Tests automáticos (pytest) |
| `pruebas/` | Scripts para enviar o insertar datos de prueba |
| `gpslink-android/` | App Android GPSLink (ver [Dispositivos en el vehículo](#11-dispositivos-en-el-vehículo)) |
| `raspberry/` | Scripts de la Raspberry Pi que detecta señales |
| `.github/workflows/` | Despliegue automático a las EC2 |
| `script.sh` | Instala el entorno de Python en una EC2 nueva |

---

## 2. Requisitos

- **Servidor:** EC2 con Ubuntu, Python 3.11 o superior, Node.js 20 o superior y npm.
- **Base de datos:** PostgreSQL en Amazon RDS (conexión con SSL).
- **Puertos abiertos en el Security Group de la EC2:**

| Puerto | Protocolo | Para qué |
|---|---|---|
| 22 | TCP | SSH (los workflows lo abren solo durante el despliegue) |
| 80 | TCP | Página web (Nginx) |
| 5000 | **UDP** | Mensajes de los dispositivos al sniffer |

---

## 3. Puesta en marcha (primera vez)

### 3.1 Clonar e instalar

```bash
git clone https://github.com/al-zoriuq/location-tracking-system.git
cd location-tracking-system
chmod +x script.sh
./script.sh
source venv/bin/activate
```

`script.sh` actualiza los paquetes, crea el entorno virtual `venv` e instala `requirements.txt`. El entorno se activa con `source venv/bin/activate` en cada sesión nueva de SSH.

### 3.2 Credenciales de la base de datos

```bash
cp .env-template .env
nano .env
```

```env
rdspass="CONTRASEÑA"
rdsdbname="NOMBRE_DE_LA_BASE"
rdshost="ENDPOINT_DE_LA_RDS"
rdsuser="USUARIO"
```

El `.env` tiene datos sensibles: **nunca** se sube a GitHub (ya está en `.gitignore`).

Certificado SSL de RDS, necesario para conectarse (va en la raíz del proyecto):

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

### 3.3 Base de datos

Las tablas se crean a mano con `psql`. **Créalas antes de arrancar el sniffer y la página.** Todo el SQL se puede ejecutar varias veces sin problema (`IF NOT EXISTS`).

> Las 4 EC2 de producción comparten una sola base de datos: las tablas se crean **una vez** ahí. Una base de pruebas debe llamarse `*_test` (los scripts de `pruebas/` se niegan a escribir en cualquier otra).

#### `ubicaciones`

Un punto GPS por fila. `(device_id, timestamp_gps)` es único, así que un paquete repetido se ignora.

```sql
CREATE TABLE IF NOT EXISTS ubicaciones (
    id                   SERIAL PRIMARY KEY,
    ip_origen            VARCHAR(45),
    latitud              DOUBLE PRECISION,
    longitud             DOUBLE PRECISION,
    timestamp_gps        TIMESTAMP,          -- hora de Bogotá, sin zona (ver sección 7)
    timestamp_recepcion  TIMESTAMP,          -- UTC
    device_id            TEXT,
    CONSTRAINT ubicacion_unica UNIQUE (device_id, timestamp_gps)
);
```

Es el esquema tal como está en producción: las columnas admiten `NULL`, aunque el sniffer actual siempre rellena `device_id`, `latitud`, `longitud` y `timestamp_gps`. Las filas antiguas sin `device_id` no reciben alias y no aparecen en la página.

#### `detecciones_senal`

Señales de tránsito detectadas por la cámara del ESP32 (ver sección 7).

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS detecciones_senal (
    id                   BIGSERIAL PRIMARY KEY,
    device_id            TEXT             NOT NULL,  -- mismo tipo que ubicaciones.device_id
    ip_origen            VARCHAR(45),
    latitud              DOUBLE PRECISION NOT NULL,
    longitud             DOUBLE PRECISION NOT NULL,
    timestamp_gps        TIMESTAMP        NOT NULL,  -- hora de la ubicación enviada con la señal
    edad_posicion_s      INTEGER,                    -- existe en producción; el código actual no la rellena
    timestamp_evento     TIMESTAMP,                  -- existe en producción; el código actual no la rellena
    timestamp_recepcion  TIMESTAMP,                  -- existe en producción; el código actual no la rellena
    senal_texto          VARCHAR(50)      NOT NULL,  -- "LIMITE 30"
    senal_tipo           VARCHAR(20)      NOT NULL,  -- LIMITE, PARE, CEDA...
    senal_valor          SMALLINT,                   -- 30 (NULL para PARE/CEDA)
    confianza            REAL             NOT NULL CHECK (confianza BETWEEN 0 AND 1),
    vel_gps              REAL,                       -- NULL cuando llega NA
    vel_mpu              REAL,
    vel_fuente           VARCHAR(5)       NOT NULL,  -- "Usa": GPS / MPU / NA
    cumplimiento         VARCHAR(10)      NOT NULL,  -- SI / EXCEDE / NA
    extra                TEXT,                       -- campos adicionales del firmware, tal cual (p. ej. "pos-45s")
    CONSTRAINT detecciones_senal_unica UNIQUE (device_id, timestamp_gps, senal_texto)
);

-- Consulta de la página: un dispositivo en un rango de fechas
CREATE INDEX IF NOT EXISTS idx_detecciones_device_gps
    ON detecciones_senal (device_id, timestamp_gps);

-- Para contar o resaltar rápido los excesos de velocidad
CREATE INDEX IF NOT EXISTS idx_detecciones_excesos
    ON detecciones_senal (device_id, timestamp_gps)
    WHERE cumplimiento = 'EXCEDE';

COMMIT;
```

Si esta tabla no existe, el sniffer guarda solo las ubicaciones y lo avisa; cuando se crea, empieza a guardar señales en menos de un minuto, sin reiniciarlo.

#### `alias_dispositivos`

**Obligatoria para la página.** La página nunca muestra el `device_id`: cada dispositivo recibe un alias (`A01`, `A02`…), que se muestra como «Vehículo A01». Si esta tabla no existe, la API responde un error 503 y la página no muestra vehículos (el sniffer sigue guardando ubicaciones).

```sql
CREATE TABLE IF NOT EXISTS alias_dispositivos (
    numero     INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id  TEXT NOT NULL UNIQUE,
    creado_en  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

Opcional: numerar ya los dispositivos que existen, por orden de aparición (si no, la página los numera sola la primera vez que se abre):

```sql
INSERT INTO alias_dispositivos (device_id)
SELECT device_id FROM ubicaciones
WHERE device_id IS NOT NULL
  AND device_id NOT IN (SELECT device_id FROM alias_dispositivos)
GROUP BY device_id
ORDER BY MIN(id);

SELECT numero, device_id, creado_en FROM alias_dispositivos ORDER BY numero;
```

Si un `INSERT` falla con la tabla todavía vacía, la secuencia ya habrá gastado números; antes de repetirlo, reiníciala (solo con la tabla vacía): `ALTER TABLE alias_dispositivos ALTER COLUMN numero RESTART WITH 1;`

#### Permisos

Si la aplicación se conecta con un usuario distinto al que creó las tablas:

```sql
GRANT SELECT, INSERT ON ubicaciones, detecciones_senal, alias_dispositivos TO <usuario>;
GRANT USAGE ON SEQUENCE ubicaciones_id_seq, detecciones_senal_id_seq, alias_dispositivos_numero_seq TO <usuario>;
```

### 3.4 Compilar la página

```bash
cd disenop2web
npm install
npm run build
cd ..
```

Genera `disenop2web/dist/`, que `servidorweb.py` sirve directamente.

- **Nombre en la cabecera:** opcional, con `VITE_NOMBRE_PERSONA=Nombre` en un archivo `disenop2web/.env` (por defecto «GPSLink»). Se lee al compilar.
- **Servir bajo una subruta** (p. ej. el entorno de test en `/test/`): compilar con `BASE_PATH=/test/ npm run build`.

### 3.5 Nginx

```bash
sudo apt install nginx -y
```

Crea `/etc/nginx/sites-available/location-tracker`:

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/location-tracker /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 3.6 Servicio de Gunicorn

Crea `/etc/systemd/system/gunicorn-location.service`:

```ini
[Unit]
Description=Gunicorn instance to serve location-tracking-system
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/location-tracking-system
Environment="PATH=/home/ubuntu/location-tracking-system/venv/bin"
ExecStart=/home/ubuntu/location-tracking-system/venv/bin/gunicorn --bind 127.0.0.1:8000 servidorweb:app

[Install]
WantedBy=multi-user.target
```

Actívalo y arráncalo:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gunicorn-location
sudo systemctl status gunicorn-location
```

> El nombre del servicio debe coincidir con el `service` de tu servidor en `.github/workflows/deploy-main.yml` (`gunicorn-location` o `gunicorn`), porque el despliegue automático lo reinicia por ese nombre.

### 3.7 Sniffer UDP

```bash
source venv/bin/activate
python snifferwpostgresql.py              # puerto 5000
python snifferwpostgresql.py --puerto 5006 # otro puerto, p. ej. para probar una versión nueva
```

Debe quedar corriendo de forma permanente (en una sesión de `tmux`/`screen` o como servicio de systemd). Al arrancar avisa si falta alguna tabla.

- Acepta los dos formatos de mensaje: solo ubicación (app Android, firmware antiguo) y ubicación + señal de tránsito (ESP32-S3). Ver el lector de mensajes al principio de `snifferwpostgresql.py`.
- Descarta los paquetes mal formados sin detenerse y se reconecta solo si se cae la conexión con la base de datos.
- La primera vez que ve un `device_id` le asigna su alias. Si eso falla, la ubicación se guarda igual.

**El despliegue automático no reinicia el sniffer.** Después de actualizar su código hay que detenerlo y arrancarlo de nuevo a mano en cada servidor.

---

## 4. Comprobar que funciona

```bash
# La API responde y cada vehículo sale con su alias (nunca con su device_id)
curl http://localhost/api/dispositivos

# Enviar rutas de prueba por UDP, como un celular (¡solo contra un sniffer de PRUEBAS!)
python pruebas/enviar_rutas_prueba.py --dry-run
python pruebas/enviar_rutas_prueba.py --host <IP-del-sniffer> --device <id-de-prueba>
```

Luego abre `http://<IP-de-la-EC2>/`: debe aparecer «Vehículo A0X» con su ruta más reciente.

### Tests

```bash
pip install pytest
pytest tests/ -v                        # backend: no necesita base de datos (usa una simulada)
node --test disenop2web/src/*.test.js   # funciones del frontend
cd disenop2web && npm run lint && npm run build
```

El despliegue de test ejecuta `pytest tests/` antes de desplegar; si un test falla, no se despliega.

---

## 5. Entorno de pruebas

- **Base de datos:** una base `*_test` con las mismas tablas (sección 3.3).
- **Servidor de test:** el workflow `deploy-test.yml` despliega la rama de test en `/home/ubuntu/location-tracking-system-test`, compila con `BASE_PATH=/test/` y reinicia el servicio `gunicorn-test`. Nginx debe dirigir `/test/` a ese Gunicorn.
- **Scripts de `pruebas/`** (los `insertar_*` escriben directo en la base y se niegan si su nombre no termina en `_test`; los `enviar_*` mandan por UDP al sniffer que indiques, así que comprueba que sea uno de pruebas):

| Script | Qué hace |
|---|---|
| `enviar_rutas_prueba.py` | Envía por UDP rutas de varios días (viajes, paradas, un salto GPS imposible) |
| `enviar_senales_prueba.py` | Envía por UDP mensajes con señales de tránsito |
| `insertar_rutas_prueba.py` | Inserta las mismas rutas directo en la base (sin pasar por el sniffer) |
| `insertar_dos_carros_prueba.py` | Dos vehículos; con `--vivo N` los mueve en tiempo real durante N minutos |
| `insertar_senales_dos_carros_prueba.py` | Señales de tránsito para los dos vehículos |
| `insertar_salto_prueba.py` | Dos puntos GPS erróneos muy lejos (Azores) antes de una ruta real en Cartagena |
| `insertar_ruta_1s_prueba.py` | Ruta a 1 punto por segundo; `--verificar` comprueba el muestreo de 10 s contra la base real |

Todos tienen `--dry-run` (no tocan nada) y los que insertan tienen `--borrar` para limpiar sus datos.

---

## 6. Despliegue automático

| Acción | Workflow | Despliega en | Reinicia |
|---|---|---|---|
| Push a la rama de test (`alba-test`) | `deploy-test.yml` | EC2 de test (`/test/`) | `gunicorn-test` |
| Merge / push a `main` | `deploy-main.yml` | **Las 4 EC2 de producción a la vez** | `gunicorn` / `gunicorn-location` |

Cada despliegue hace `git pull`, `pip install -r requirements.txt`, `npm install`, `npm run build` y reinicia Gunicorn.

**Importante:**

1. **Solo se reinicia Gunicorn, nunca el sniffer.** Si el cambio toca `snifferwpostgresql.py`, reinícialo a mano en cada EC2.
2. **Los cambios en la base de datos van antes del despliegue:** primero en la base `*_test` (antes del push a test) y luego en la base de producción (**antes del merge a `main`**). Si el código nuevo llega sin su tabla, las 4 páginas de producción fallan a la vez.
3. El código web sigue funcionando con un sniffer antiguo todavía corriendo (por ejemplo, los alias que falten los asigna la página).

---

## 7. Datos y convenciones

### Zona horaria

Los paquetes GPS traen la hora con offset explícito (p. ej. `-05:00`). El sniffer conserva la hora local y descarta el offset, sin convertir a UTC:

```python
timestamp_gps = timestamp_gps.replace(tzinfo=None)
```

- `timestamp_gps` se guarda como **hora de Bogotá sin zona** (UTC−5 todo el año).
- `timestamp_recepcion` se guarda en **UTC** (la RDS corre en UTC).
- Toda comparación con «ahora» debe usar `NOW() AT TIME ZONE 'America/Bogota'` en el servidor, o `-05:00` al interpretar la fecha en el navegador (`parsearFechaBogota` en `disenop2web/src/utils/tiempo.js`). Comparar `timestamp_gps` con `NOW()` directamente desplaza el resultado 5 horas.

### Alias de vehículos

- La API **nunca** devuelve el `device_id`. Cada vehículo se identifica por su alias (`vehiculo: "A01"`) y se muestra con su nombre (`nombre: "Vehículo A01"`).
- Formato: `A01`…`A99`, luego `B01`…`B99`, …, `Z99`, `AA01`… El número sale de `alias_dispositivos.numero`, que crece por orden de aparición y **nunca se reutiliza**, aunque se borre una fila.
- Lo asigna el sniffer al ver un dispositivo nuevo y, como respaldo, `/api/dispositivos` a los que aún no tengan.
- Los endpoints aceptan `?vehiculo=A01`. `?device_id=` se sigue aceptando para los scripts de prueba, pero ninguna respuesta lo incluye.

### Muestreo de puntos (dispositivos que reportan cada segundo)

La app GPSLink envía la ubicación cada segundo. La base guarda **todos** los puntos, pero la página pide el historial con `intervalo_s=10`: el servidor devuelve solo el primer punto de cada bloque de 10 s por vehículo. Así la página recibe unas 10 veces menos datos sin perder ni duplicar puntos. Los bloques están alineados al reloj, así que el mismo bloque devuelve siempre el mismo punto, también en las consultas incrementales (`despues_de`).

### Señales de tránsito (ESP32-S3)

El ESP32 agrega al mensaje de ubicación la señal que detectó su cámara (`Senal: LIMITE 30, Conf: 0.99, Vel GPS: 2, Vel MPU: 22, Usa: GPS, SI`). Se guardan en `detecciones_senal`, aparte de `ubicaciones`, en la misma transacción.

- La página asigna cada señal a su ruta por hora (`disenop2web/src/senales.js`), la dibuja en el mapa (`MarcadoresSenal.jsx`) y la lista en el panel lateral (`PanelSenales.jsx`).
- Prueba sin el ESP32: `tests/sniffer_udpforesp32.py --guardar` (solo bases `*_test`) o `snifferwpostgresql.py --puerto N`, con `pruebas/enviar_senales_prueba.py --puerto N`.

### Dirección aproximada

Las tarjetas de los vehículos muestran la dirección de su último punto.

- `GET /api/direccion?lat=..&lon=..` consulta Nominatim (OpenStreetMap) y devuelve `{"direccion": "Calle 72 #57-43, Alto Prado, Barranquilla", "completa": "..."}`. `direccion` es `null` si el punto no tiene dirección.
- Para respetar la política de uso de Nominatim (máximo 1 consulta por segundo y uso de caché), las coordenadas se redondean a 4 decimales (~11 m), cada punto se consulta una sola vez por proceso del servidor y las consultas se separan al menos 1 s.
- En el navegador: `disenop2web/src/useDireccion.js`.

---

## 8. API

Todas las respuestas son JSON. Los errores tienen la forma `{"error": "mensaje"}`: 400 parámetros inválidos, 404 sin datos o vehículo inexistente, 503 base de datos no disponible o falta la tabla de alias.

| Endpoint | Para qué | Parámetros |
|---|---|---|
| `GET /api/dispositivos` | Último punto de cada vehículo, con `vehiculo` y `nombre` | — |
| `GET /api/historial-ubicaciones` | Puntos de un vehículo, del más antiguo al más reciente | `vehiculo`, `horas` (por defecto 24), `desde` + `hasta` (`AAAA-MM-DD HH:MM[:SS]`, hora de Bogotá, sin fechas futuras), `margen_horas` (amplía el rango, máx. 168), `despues_de` (solo los puntos nuevos), `intervalo_s` (1–300, un punto por bloque) |
| `GET /api/detecciones-senal` | Señales de tránsito de un vehículo (`[]` si la tabla no existe) | `vehiculo`, `horas`, `desde` + `hasta`, `margen_horas` |
| `GET /api/lugar-visitado` | Si el vehículo pasó alguna vez por un área | `vehiculo`, `lat_min`, `lat_max`, `lon_min`, `lon_max` |
| `GET /api/buscar-lugar` | Busca una ciudad o dirección (Nominatim) | `q` |
| `GET /api/direccion` | Dirección aproximada de un punto | `lat`, `lon` |
| `GET /api/ultima-ubicacion` | Último punto recibido (la página no lo usa) | `vehiculo` |

Sin `vehiculo`, los endpoints de un vehículo usan el del último punto recibido.

---

## 9. Interfaz de usuario

- **Vehículos:** con dos vehículos, cada uno tiene su color (por orden de alias) en su tarjeta, su ruta y su marcador. Arriba se elige qué ver: «Ambos» muestra las dos rutas a la vez, actualizándose en tiempo real; el botón de cada vehículo muestra solo ese. Las herramientas trabajan sobre el vehículo activo (tarjeta resaltada). Cambiar de vehículo o de pestaña conserva el zoom.
- **Rutas:** al abrir se ve la ruta más reciente de cada vehículo. El historial se divide en viajes (más de 1 h sin datos, más de 1 km entre puntos o velocidad implícita mayor a 180 km/h). Se navega con anterior, siguiente, «Actual» y un selector con todas; cambiar de ruta reencuadra el mapa en ella.
- **Filtros:** rango de fecha y hora (al abrirlo, por defecto desde hoy a las 00:00 hasta la hora actual; el fin debe ser posterior al inicio, sin fechas futuras) y lugar (búsqueda de ciudad o dirección, o un pin en el mapa con un área de 300 m), combinables. Si el filtro corta un viaje, se marca con extremos huecos y un aviso con «Ver viaje completo».
- **Mapa:** marcadores de inicio, fin y posición actual, paradas (5 min dentro de 50 m), visitas a un lugar, reproductor del recorrido, ajuste a vías y seguimiento del punto actual.
- **Barra de herramientas** (`BarraHerramientas.jsx`): «Señales» (con el número de excesos; solo aparece si la ruta mostrada tiene señales), «Puntos», «Reproducir» y «Capas». Vertical a la derecha en pantalla ancha y horizontal abajo en modo compacto. El ojo (ocultar paneles) y el seguimiento van aparte, en la esquina inferior derecha.
- **Panel lateral:** «Señales» y «Puntos» se abren juntos o por separado; columna a la derecha en pantalla ancha y hoja inferior en el celular.
- **Ayuda:** botón «?» en la barra superior. Su texto (`AyudaModal.jsx`) debe actualizarse cuando cambie la interfaz.

---

## 10. Ramas y flujo de trabajo

1. **Desarrollo:** cada persona trabaja en su rama de test (p. ej. `alba-test`, `sthefany-test`), que se despliega en su EC2 de test.
2. **Sincronizar con `main`:** antes de abrir el Pull Request, traer los cambios de `main` (`git fetch origin` → `git merge origin/main`) y resolver los conflictos localmente.
3. **Producción:** el merge del Pull Request a `main` despliega en las 4 EC2. Antes del merge: crear en la base de producción las tablas o columnas nuevas, y después del merge reiniciar el sniffer si cambió (sección 6).

---

## 11. Dispositivos en el vehículo

- [`gpslink-android/`](gpslink-android/): app GPSLink, envía la ubicación cada 1 s. El APK está en [`gpslink-android/releases/`](gpslink-android/releases/).
- [`raspberry/`](raspberry/): scripts y servicio de la Raspberry Pi que detecta señales de tránsito (el `pipeline_pi.py` completo vive en la Pi).

Formato del mensaje de ubicación (lo que espera el sniffer):

```
Device: <id>, Lat: 11.03, Lon: -74.85, Timestamp GPS: 2026-11-03 07:50:28.000 -05:00
```
