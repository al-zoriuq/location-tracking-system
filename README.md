# GPSLink · Location Tracking System

Real-time vehicle tracking. The devices in each vehicle (a phone running the GPSLink app, a Raspberry Pi, an ESP32-S3) send their location over UDP; a server stores it in PostgreSQL, and a web page shows the current position, routes, stops and detected traffic signs on a map.

This document explains how to set the project up from scratch, how to test it and how it is deployed.

---

## 1. How it works

```
 Phone (GPSLink) ──┐
 Raspberry Pi     ─┼─ UDP :5000 ─► snifferwpostgresql.py ─► PostgreSQL (RDS)
 ESP32-S3         ─┘                                              ▲
                                                                  │
 Browser ◄── HTTP ── Nginx :80 ──► Gunicorn ── servidorweb.py ────┘
                                   (API /api/* + built React page)
```

- **`snifferwpostgresql.py`**: UDP server (port `5000`). Parses each message, stores the location in `ubicaciones` and, if the message carries a traffic sign, stores it in `detecciones_senal`. It also assigns the alias of every new device (see [Vehicle aliases](#vehicle-aliases)).
- **`servidorweb.py`**: Flask API, served by Gunicorn behind Nginx. It also serves the built page (`disenop2web/dist/`).
- **`disenop2web/`**: web page in React + Leaflet (Vite). It polls the API every 10 s.

| Folder / file | Contents |
|---|---|
| `snifferwpostgresql.py` | UDP server that stores the messages |
| `servidorweb.py` | API and page server |
| `disenop2web/` | Frontend (React) |
| `tests/` | Automated tests (pytest) |
| `pruebas/` | Scripts that send or insert test data |
| `gpslink-android/` | GPSLink Android app (see [In-vehicle devices](#11-in-vehicle-devices)) |
| `raspberry/` | Scripts for the Raspberry Pi that detects traffic signs |
| `.github/workflows/` | Automatic deployment to the EC2 instances |
| `script.sh` | Sets up the Python environment on a new EC2 |

---

## 2. Requirements

- **Server:** EC2 running Ubuntu, with:
  - Python 3.11 (the version CI uses) and `python3-venv`;
  - Node.js **20.19+ or 22.13+** and npm (required by Vite 8 and ESLint 10);
  - `postgresql-client` (`psql`), to create the tables.
- **Database:** PostgreSQL on Amazon RDS (SSL connection).
- **Ports open in the EC2 Security Group:**

| Port | Protocol | Used for |
|---|---|---|
| 22 | TCP | SSH (the workflows open it only while deploying) |
| 80 | TCP | Web page (Nginx) |
| 5000 | **UDP** | Device messages to the sniffer |

---

## 3. First-time setup

### 3.1 Clone and install

```bash
git clone https://github.com/al-zoriuq/location-tracking-system.git
cd location-tracking-system
chmod +x script.sh
./script.sh
source venv/bin/activate
```

`script.sh` updates the system packages, creates the `venv` virtual environment and installs `requirements.txt`. Run `source venv/bin/activate` again in every new SSH session.

`script.sh` does **not** install Node.js or the PostgreSQL client. For example, with the NodeSource packages:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs postgresql-client
node --version   # must be 20.19+ or 22.13+
```

### 3.2 Database credentials

```bash
cp .env-template .env
nano .env
```

```env
rdspass="PASSWORD"
rdsdbname="DATABASE_NAME"
rdshost="RDS_ENDPOINT"
rdsuser="USER"
GROQ_API_KEY="gsk_..."   # Pipo (/api/pipo). Free key at console.groq.com
GROQ_MODEL=""            # optional, defaults to openai/gpt-oss-120b
```

The `.env` file holds secrets: **never** commit it (it is already in `.gitignore`).

The RDS SSL certificate is required to connect. It goes in the project root:

```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

### 3.3 Database

The tables are created by hand with `psql`. **Create them before starting the sniffer and the web page.** Every statement below can be run more than once safely (`IF NOT EXISTS`).

To open `psql` with the same SSL settings the application uses:

```bash
psql "host=<RDS_ENDPOINT> dbname=<DATABASE_NAME> user=<USER> sslmode=verify-full sslrootcert=global-bundle.pem"
```

> The 4 production EC2 instances share a single database: the tables are created **once** there. A test database must be named `*_test` (the `pruebas/` scripts refuse to write anywhere else).

#### `ubicaciones`

One GPS point per row. `(device_id, timestamp_gps)` is unique, so a repeated packet is ignored.

```sql
CREATE TABLE IF NOT EXISTS ubicaciones (
    id                   SERIAL PRIMARY KEY,
    ip_origen            VARCHAR(45),
    latitud              DOUBLE PRECISION,
    longitud             DOUBLE PRECISION,
    timestamp_gps        TIMESTAMP,          -- Bogotá time, without zone (see section 7)
    timestamp_recepcion  TIMESTAMP,          -- UTC
    device_id            TEXT,
    CONSTRAINT ubicacion_unica UNIQUE (device_id, timestamp_gps)
);
```

This is the schema as it exists in production. The columns allow `NULL`, but the current sniffer always fills `device_id`, `latitud`, `longitud` and `timestamp_gps`. Old rows without a `device_id` get no alias and do not appear on the page.

#### `detecciones_senal`

Traffic signs detected by the ESP32 camera (see section 7).

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS detecciones_senal (
    id                   BIGSERIAL PRIMARY KEY,
    device_id            TEXT             NOT NULL,  -- same type as ubicaciones.device_id
    ip_origen            VARCHAR(45),
    latitud              DOUBLE PRECISION NOT NULL,
    longitud             DOUBLE PRECISION NOT NULL,
    timestamp_gps        TIMESTAMP        NOT NULL,  -- time of the location sent with the sign
    edad_posicion_s      INTEGER,                    -- exists in production; not filled by the current code
    timestamp_evento     TIMESTAMP,                  -- exists in production; not filled by the current code
    timestamp_recepcion  TIMESTAMP,                  -- exists in production; not filled by the current code
    senal_texto          VARCHAR(50)      NOT NULL,  -- "LIMITE 30"
    senal_tipo           VARCHAR(20)      NOT NULL,  -- LIMITE, PARE, CEDA...
    senal_valor          SMALLINT,                   -- 30 (NULL for PARE/CEDA)
    confianza            REAL             NOT NULL CHECK (confianza BETWEEN 0 AND 1),
    vel_gps              REAL,                       -- NULL when the device sends NA
    vel_mpu              REAL,
    vel_fuente           VARCHAR(5)       NOT NULL,  -- "Usa": GPS / MPU / NA
    cumplimiento         VARCHAR(10)      NOT NULL,  -- SI / EXCEDE / NA
    extra                TEXT,                       -- extra firmware fields, stored as-is (e.g. "pos-45s")
    CONSTRAINT detecciones_senal_unica UNIQUE (device_id, timestamp_gps, senal_texto)
);

-- Page query: one device over a date range
CREATE INDEX IF NOT EXISTS idx_detecciones_device_gps
    ON detecciones_senal (device_id, timestamp_gps);

-- Fast counting / highlighting of speeding events
CREATE INDEX IF NOT EXISTS idx_detecciones_excesos
    ON detecciones_senal (device_id, timestamp_gps)
    WHERE cumplimiento = 'EXCEDE';

COMMIT;
```

If this table does not exist, the sniffer stores locations only and prints a warning. Once the table is created, it starts storing signs within a minute, without a restart.

#### `alias_dispositivos`

**Required by the web page.** The page never shows a `device_id`: each device gets an alias (`A01`, `A02`, …), displayed as "Vehículo A01". If this table does not exist, the API answers with a 503 error and the page shows no vehicles. The sniffer keeps storing locations.

```sql
CREATE TABLE IF NOT EXISTS alias_dispositivos (
    numero     INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id  TEXT NOT NULL UNIQUE,
    creado_en  TIMESTAMP NOT NULL DEFAULT NOW()
);
```

Optional: number the existing devices right away, in order of first appearance. Otherwise the web page numbers them the first time it is opened.

```sql
INSERT INTO alias_dispositivos (device_id)
SELECT device_id FROM ubicaciones
WHERE device_id IS NOT NULL
  AND device_id NOT IN (SELECT device_id FROM alias_dispositivos)
GROUP BY device_id
ORDER BY MIN(id);

SELECT numero, device_id, creado_en FROM alias_dispositivos ORDER BY numero;
```

If an `INSERT` fails while the table is still empty, the sequence has already used up numbers. Before trying again, reset it (only while the table is empty): `ALTER TABLE alias_dispositivos ALTER COLUMN numero RESTART WITH 1;`

#### Permissions

If the application connects with a different user than the one that created the tables:

```sql
GRANT SELECT, INSERT ON ubicaciones, detecciones_senal, alias_dispositivos TO <user>;
GRANT USAGE ON SEQUENCE ubicaciones_id_seq, detecciones_senal_id_seq, alias_dispositivos_numero_seq TO <user>;
```

### 3.4 Build the web page

```bash
cd disenop2web
npm install
npm run build
cd ..
```

This generates `disenop2web/dist/`, which `servidorweb.py` serves directly.

- **Name in the header:** optional, set `VITE_NOMBRE_PERSONA=Name` in a `disenop2web/.env` file (defaults to "GPSLink"). It is read at build time.
- **Serving under a sub-path** (e.g. the test environment at `/test/`): build with `BASE_PATH=/test/ npm run build`.

### 3.5 Nginx

```bash
sudo apt install nginx -y
```

Create `/etc/nginx/sites-available/location-tracker`:

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

### 3.6 Gunicorn service

Create `/etc/systemd/system/gunicorn-location.service`:

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

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gunicorn-location
sudo systemctl status gunicorn-location
```

> The service name must match the `service` of your server in `.github/workflows/deploy-main.yml` (`gunicorn-location` or `gunicorn`), because the automatic deployment restarts it by that name.

### 3.7 UDP sniffer

```bash
source venv/bin/activate
python snifferwpostgresql.py               # port 5000
python snifferwpostgresql.py --puerto 5006 # another port, e.g. to try a new version
```

It must keep running permanently, in a `tmux`/`screen` session or as a systemd service. On startup it warns if `detecciones_senal` or `alias_dispositivos` is missing.

- It accepts both message formats: location only (Android app, old firmware) and location + traffic sign (ESP32-S3). See the message parser at the top of `snifferwpostgresql.py`.
- It discards malformed packets without stopping, and reconnects on its own if the database connection drops.
- The first time it sees a `device_id` it assigns its alias. If that fails, the location is stored anyway.

**The automatic deployment does not restart the sniffer.** After updating its code, stop it and start it again by hand on every server.

---

## 4. Checking that it works

```bash
# The API answers, and each vehicle comes with its alias (never with its device_id)
curl http://localhost/api/dispositivos

# Send test routes over UDP, like a phone would (ONLY to a TEST sniffer!)
python pruebas/enviar_rutas_prueba.py --dry-run
python pruebas/enviar_rutas_prueba.py --host <sniffer-IP> --device <test-id>
```

Then open `http://<EC2-IP>/`: you should see "Vehículo A0X" with its most recent route.

### Tests

```bash
pip install pytest
pytest tests/ -v                        # backend: needs no database (uses a fake one)
node --test disenop2web/src/*.test.js   # frontend helper functions
cd disenop2web && npm run lint && npm run build
```

The test deployment runs `pytest tests/` first; if any test fails, nothing is deployed.

---

## 5. Test environment

- **Database:** a `*_test` database with the same tables (section 3.3).
- **Test server:**
  - the `deploy-test.yml` workflow deploys the test branch to `/home/ubuntu/location-tracking-system-test`;
  - it builds with `BASE_PATH=/test/` and restarts the `gunicorn-test` service;
  - Nginx must route `/test/` to that Gunicorn.
- **`pruebas/` scripts:**
  - the `insertar_*` scripts write straight to the database and refuse to run unless its name ends in `_test`;
  - the `enviar_*` scripts send over UDP to the sniffer you point them at, so make sure it is a test one.

| Script | What it does |
|---|---|
| `enviar_rutas_prueba.py` | Sends routes spread over several days over UDP (trips, stops, an impossible GPS jump) |
| `enviar_senales_prueba.py` | Sends messages with traffic signs over UDP |
| `insertar_rutas_prueba.py` | Inserts the same routes straight into the database (bypassing the sniffer) |
| `insertar_dos_carros_prueba.py` | Two vehicles; with `--vivo N` they move in real time for N minutes |
| `insertar_senales_dos_carros_prueba.py` | Traffic signs for the two vehicles |
| `insertar_salto_prueba.py` | Two wrong GPS points far away (Azores) before a real route in Cartagena |
| `insertar_ruta_1s_prueba.py` | A route at 1 point per second; `--verificar` checks the 10 s sampling against the real database |

All of them support `--dry-run` (touches nothing), and the inserting ones support `--borrar` to remove their data.

---

## 6. Automatic deployment

| Action | Workflow | Deploys to | Restarts |
|---|---|---|---|
| Push to the test branch (`alba-test`) | `deploy-test.yml` | Test EC2 (`/test/`) | `gunicorn-test` |
| Merge / push to `main` | `deploy-main.yml` | **All 4 production EC2 instances at once** | `gunicorn` / `gunicorn-location` |

Each deployment runs `git pull`, `pip install -r requirements.txt`, `npm install` and `npm run build`, and then restarts Gunicorn.

**Important:**

1. **Only Gunicorn is restarted, never the sniffer.** If a change touches `snifferwpostgresql.py`, restart it by hand on each EC2.
2. **Database changes go before the deployment:**
   - first in the `*_test` database, before pushing to the test branch;
   - then in the production database, **before merging to `main`**.

   If new code arrives without its table, the 4 production pages fail at the same time.
3. The web code keeps working while an older sniffer is still running. For example, the web page assigns any missing aliases itself.

---

## 7. Data and conventions

### Time zone

GPS packets carry the time with an explicit offset (e.g. `-05:00`). The sniffer keeps the local time and drops the offset, without converting to UTC:

```python
timestamp_gps = timestamp_gps.replace(tzinfo=None)
```

- `timestamp_gps` is stored as **Bogotá time without zone** (UTC−5 all year round).
- `timestamp_recepcion` is stored in **UTC** (the RDS runs in UTC).
- Any comparison with "now" must use:
  - on the server: `NOW() AT TIME ZONE 'America/Bogota'`;
  - in the browser: `-05:00` when parsing the date (`parsearFechaBogota` in `disenop2web/src/utils/tiempo.js`).

  Comparing `timestamp_gps` with `NOW()` directly shifts the result by 5 hours.

### Vehicle aliases

- The API **never** returns a `device_id`. Each vehicle is identified by its alias (`vehiculo: "A01"`) and displayed with its name (`nombre: "Vehículo A01"`).
- Format: `A01`…`A99`, then `B01`…`B99`, …, `Z99`, `AA01`…
- The number comes from `alias_dispositivos.numero`. It grows in order of first appearance and is **never reused**, even if a row is deleted.
- Who assigns it: the sniffer, when it sees a new device; and, as a fallback, `/api/dispositivos`, for any device that still has none.
- The endpoints accept `?vehiculo=A01`. `?device_id=` is still accepted for the test scripts, but no response includes it.

### Point sampling (devices that report every second)

The GPSLink app sends the location every second. The database keeps **every** point, but the page requests the history with `intervalo_s=10`, so the server returns only the first point of each 10 s block per vehicle:

- the page receives about 10 times less data, without losing or duplicating points;
- the blocks are aligned to the clock, so a block always returns the same point, including in incremental requests (`despues_de`).

### Traffic signs (ESP32-S3)

The ESP32 appends the sign its camera detected to the location message (`Senal: LIMITE 30, Conf: 0.99, Vel GPS: 2, Vel MPU: 22, Usa: GPS, SI`). Signs are stored in `detecciones_senal`, separate from `ubicaciones`, in the same transaction.

- The page:
  - assigns each sign to its route by time (`disenop2web/src/senales.js`);
  - draws it on the map (`MarcadoresSenal.jsx`);
  - lists it in the side panel (`PanelSenales.jsx`).
- Testing without the ESP32: run `tests/sniffer_udpforesp32.py --guardar` (`*_test` databases only), or `snifferwpostgresql.py --puerto N` together with `pruebas/enviar_senales_prueba.py --puerto N`.

### Approximate address

The vehicle cards show the address of each vehicle's last point.

- `GET /api/direccion?lat=..&lon=..` queries Nominatim (OpenStreetMap) and returns `{"direccion": "Calle 72 #57-43, Alto Prado, Barranquilla", "completa": "..."}`. `direccion` is `null` when the point has no address.
- To follow the Nominatim usage policy (at most 1 request per second, and caching):
  - coordinates are rounded to 4 decimals (~11 m);
  - each point is queried only once per server process;
  - requests are spaced at least 1 s apart.
- In the browser: `disenop2web/src/useDireccion.js`.

---

## 8. API

Every response is JSON. Errors look like `{"error": "message"}`:

| Code | Meaning |
|---|---|
| 400 | Invalid parameters |
| 404 | No data, or the vehicle does not exist |
| 503 | Database unavailable, or the alias table is missing |

| Endpoint | Purpose | Parameters |
|---|---|---|
| `GET /api/dispositivos` | Last point of each vehicle, with `vehiculo` and `nombre` | — |
| `GET /api/historial-ubicaciones` | A vehicle's points, oldest first | `vehiculo`, `horas` (default 24), `desde` + `hasta`, `margen_horas`, `despues_de`, `intervalo_s` (see below) |
| `GET /api/detecciones-senal` | A vehicle's traffic signs (`[]` if the table does not exist) | `vehiculo`, `horas`, `desde` + `hasta`, `margen_horas` |
| `GET /api/lugar-visitado` | Whether the vehicle has ever been inside an area | `vehiculo`, `lat_min`, `lat_max`, `lon_min`, `lon_max` |
| `GET /api/buscar-lugar` | Searches a city or address (Nominatim) | `q` |
| `GET /api/direccion` | Approximate address of a point | `lat`, `lon` |
| `GET /api/ultima-ubicacion` | Last point received (not used by the page) | `vehiculo` |

Date and sampling parameters of `/api/historial-ubicaciones`:

- `desde` + `hasta`: `YYYY-MM-DD HH:MM[:SS]`, in Bogotá time; future dates are rejected.
- `margen_horas`: widens the range on both sides, up to 168.
- `despues_de`: returns only the points newer than that time.
- `intervalo_s`: between 1 and 300; one point per block of that many seconds.

Without `vehiculo`, the per-vehicle endpoints use the device of the last point received.

---

## 9. User interface

- **Vehicles:**
  - with two vehicles, each one has its own colour (by alias order) on its card, its route and its marker;
  - the selector at the top chooses what to show: "Ambos" shows both routes at once, updating in real time, and each vehicle's button shows only that one;
  - the tools work on the active vehicle (the highlighted card);
  - switching vehicle or tab keeps the zoom.
- **Routes:**
  - on opening, the most recent route of each vehicle is shown;
  - the history is split into trips: a new trip starts after more than 1 h without data or more than 1 km between points, and points implying more than 180 km/h are discarded;
  - navigation: previous, next, "Actual" and a selector listing every route. Changing route re-fits the map to it.
- **Filters** (they can be combined):
  - date and time range: on opening it defaults to today 00:00 → now; the end must be after the start, and future dates are not allowed;
  - place: a city or address search, or a pin dropped on the map with a 300 m area around it.

  If a filter cuts a trip, its ends are drawn hollow and a notice offers "Ver viaje completo".
- **Map:** start, end and current-position markers, stops (5 min within 50 m), visits to a place, route player, snap-to-roads and follow the current point.
- **Toolbar** (`BarraHerramientas.jsx`):
  - buttons: "Señales" (with the number of speeding events; only shown when the route on screen has signs), "Puntos", "Reproducir" and "Capas";
  - vertical on the right on wide screens, horizontal at the bottom in compact mode;
  - the eye (hide panels) and the follow button sit apart, in the bottom-right corner.
- **Side panel:** "Señales" and "Puntos" open together or separately. A right-hand column on wide screens; a bottom sheet on phones.
- **Help:** the "?" button in the top bar. Its text (`AyudaModal.jsx`) must be updated whenever the interface changes.

---

## 10. Branches and workflow

1. **Development:** each person works on their own test branch (e.g. `alba-test`, `sthefany-test`), which deploys to their test EC2.
2. **Sync with `main`:** before opening the Pull Request, bring in the changes from `main` (`git fetch origin` → `git merge origin/main`) and resolve any conflicts locally.
3. **Production:** merging the Pull Request into `main` deploys to the 4 EC2 instances.
   - Before the merge: create any new tables or columns in the production database.
   - After the merge: restart the sniffer if it changed (section 6).

---

## 11. In-vehicle devices

- [`gpslink-android/`](gpslink-android/): GPSLink app, sends the location every 1 s. The APK is in [`gpslink-android/releases/`](gpslink-android/releases/).
- [`raspberry/`](raspberry/): scripts and service for the Raspberry Pi that detects traffic signs (the full `pipeline_pi.py` lives on the Pi).

Location message format (what the sniffer expects):

```
Device: <id>, Lat: 11.03, Lon: -74.85, Timestamp GPS: 2026-11-03 07:50:28.000 -05:00
```
