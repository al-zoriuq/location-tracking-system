# GPSLink — Live GPS Location Tracking

> 🇪🇸 The Spanish README ([README.md](README.md)) documents the CI/CD pipeline, server setup and database
> schema in depth. This document is the English overview of the application: what it does, how it is
> built, how to run and test it, and how to load sample data.

GPSLink receives GPS positions from an Android app over UDP, stores them in PostgreSQL and shows them on a
live map with the route history, route navigation, date filtering and place search.

## Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [API](#api)
4. [Time zone](#time-zone)
5. [Running locally](#running-locally)
6. [Tests](#tests)
7. [Sample data](#sample-data)
8. [Frontend structure](#frontend-structure)
9. [Deployment](#deployment)
10. [Known limitations](#known-limitations)

## Features

- **Live map** with the current position, start and end of each route and the route line. A status
  badge shows how fresh the last reading is ("en línea", "hace 15 min", "hace 3 h").
- **Routes.** The history is split into routes: a new route starts after more than 1 hour without data or a
  jump of more than 1 km. Physically impossible jumps (over 180 km/h, i.e. GPS glitches) are left out of the
  drawn line. Browse them with **Previous / Next**, jump to the newest with **Current**, or open the route
  list (click the "Ruta 3 de 10" title) to jump to any route in one click, with its date, time range and
  number of points.
- **Date and time filter.** A themed calendar with labelled *Hour*, *Minutes* and *a. m. / p. m.* fields.
  Future dates are not selectable, and the range is validated in the browser and in the API.
- **Place filter.** Search a city or address (OpenStreetMap Nominatim) and keep only the routes that pass
  through it. Suggestions are tagged *Con historial* / *Sin historial* using the whole history, and the page
  always explains an empty result ("never visited" vs. "visited, but not in the selected range").
- **Keep the point centered.** Follows the latest point without changing the zoom. If you pan away, the map
  returns to the point after about 4 seconds without interaction.
- **Snap to roads** (OSRM map matching) redraws the route along real streets. The stored coordinates are never
  modified.
- **Visible error handling.** Toasts for no connection, server errors, invalid filters and empty ranges,
  without repeating while a failure persists, and with a notice when the connection recovers. The backend
  answers JSON errors instead of HTML tracebacks.
- **Help dialog** ("Ayuda") explaining every part of the page in plain language (Spanish UI).
- **Responsive layout** for phones, tablets and desktop (breakpoints at 900 px and 640 px), with touch
  targets of at least 44 px and a foldable history list on small screens.

## Architecture

| Layer | Technology | Notes |
| --- | --- | --- |
| Android app | Kotlin (`gpslink-android/`) | Sends `Device: <id>, Lat: <lat>, Lon: <lon>, Timestamp GPS: <ts>` over UDP to port 5000 |
| Ingestion | Python (`snifferwpostgresql.py`) | Parses packets and inserts into `ubicaciones` (duplicates per device + timestamp are ignored) |
| Backend | Flask + Gunicorn (`servidorweb.py`) | REST API on port 5001; also serves the built React app |
| Database | PostgreSQL on AWS RDS | Table `ubicaciones` (`device_id`, `ip_origen`, `latitud`, `longitud`, `timestamp_gps`, `timestamp_recepcion`) |
| Frontend | React + Vite + Leaflet (`disenop2web/`) | Plain CSS, no UI framework |
| Web server | Nginx + Certbot | TLS termination and reverse proxy to Gunicorn |

## API

All responses are JSON. Errors have the form `{"error": "<message>"}`.

| Endpoint | Description |
| --- | --- |
| `GET /api/ultima-ubicacion` | The most recent point. `404` if the table is empty. |
| `GET /api/historial-ubicaciones` | Points ordered oldest to newest. Query: `desde` and `hasta` (explicit range, must be sent together), or `horas` (last N hours, default 24); optional `device_id` (defaults to the device of the latest point). |
| `GET /api/lugar-visitado` | `{"visitado": true/false}`: whether the device has **ever** been inside a bounding box. Query: `lat_min`, `lat_max`, `lon_min`, `lon_max`; optional `device_id`. Uses `EXISTS … LIMIT 1` over the whole history. |
| `GET /api/buscar-lugar?q=` | Geocoding through Nominatim: up to 5 places with a bounding box. |

Validation of `desde` / `hasta`: formats `YYYY-MM-DD HH:MM[:SS]` (a space or `T` as separator). A range end
without seconds covers the whole minute. The API answers `400` for an invalid format, an end before the start,
a missing half of the pair or a future date. Database failures answer `503` (cannot connect) or `500`, and the
connection is always closed.

## Time zone

`timestamp_gps` is stored as **America/Bogota wall-clock time without a time zone**: the Android app sends
`… -05:00` and the sniffer drops the offset without converting. The frontend and the API validation are
written for that (`ZONA_DATOS` / `ahora_local()` in `servidorweb.py`, `ZONA` in `App.jsx`). Do not compare
these values against UTC.

## Running locally

Requirements: Python 3.11+, Node 20.19+ (required by Vite 8), access to a PostgreSQL database.

```bash
# Backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env-template .env    # then fill in rdshost, rdsdbname, rdsuser, rdspass
# sslmode=verify-full needs the RDS CA bundle saved as ./global-bundle.pem

# Frontend (the API is called with relative URLs, so build it and let Flask serve it)
cd disenop2web && npm install && npm run build && cd ..

python servidorweb.py    # http://127.0.0.1:5001
```

Environment variables:

| Variable | Used by | Purpose |
| --- | --- | --- |
| `rdshost`, `rdsdbname`, `rdsuser`, `rdspass` | backend, sniffer | Database connection |
| `VITE_NOMBRE_PERSONA` | frontend (build time) | Name shown in the page title and top bar |
| `BASE_PATH` | frontend (build time) | Sub-path the app is served from (`/` by default, `/test/` on the test server) |

## Tests

```bash
pip install pytest
pytest                   # backend + sample-data scripts, no real database needed
cd disenop2web && npm run build
```

The tests mock the database connection. They cover the date-range validation, the JSON error handling,
`/api/lugar-visitado` and the safety lock of the sample-data script.

## Sample data

Two scripts in `pruebas/` load the same set of **10 sample routes** (942 readings): long road trips
Barranquilla ⇄ Santa Marta and Barranquilla → Cartagena with stops, urban trips, a route split by distance, a
GPS glitch that must be discarded and a single-point route. Dates are always in the past.

| Script | What it does |
| --- | --- |
| `enviar_rutas_prueba.py` | Sends the readings over UDP in the Android app's format, so they go through the sniffer. Use `--dry-run` to preview. |
| `insertar_rutas_prueba.py` | Inserts them straight into the database of the `.env` in that folder, with the sniffer's SQL. **It refuses to run unless the database name ends in `_test`.** `--borrar` removes them again. |

```bash
python pruebas/insertar_rutas_prueba.py --dry-run
python pruebas/insertar_rutas_prueba.py
```

> Sending over UDP to a server whose sniffer feeds the production database would put sample data in
> production. Prefer `insertar_rutas_prueba.py` against a test database.

## Frontend structure

| File | Purpose |
| --- | --- |
| `App.jsx` | Main component: map, polling, routes, filters, place search |
| `SelectorFechaHora.jsx` | Date and time picker (calendar + hour / minutes) |
| `SelectorRuta.jsx` | Route list that opens from the route bar |
| `AyudaModal.jsx` | Accessible modal (Esc, click outside, focus trap) and the help content |
| `Toasts.jsx`, `useToasts.js` | Toast stack and the hook that de-duplicates repeated failures |
| `api.js` | `fetch` wrapper that classifies failures (offline, server error, empty, rejected request) |
| `App.css` | All styles; media queries live at the end of the file |

## Deployment

GitHub Actions deploys over SSH: `deploy-main.yml` on every push to `main` (production servers) and
`deploy-test.yml` on `sthefany-test` (served under `/test/`). Each run pulls the branch, installs the
dependencies, builds the frontend and restarts Gunicorn. See the [Spanish README](README.md#2-cicd--multi-node-deployment-strategy)
for the full pipeline.

> The deploy script runs `git pull` on the server. If the server working tree has local edits to files that
> the incoming commits change, the pull aborts, but the remaining steps still run and the job is reported as
> successful with the old code. Keep server checkouts clean.

## Known limitations

- **Snap to roads** uses the public OSRM demo server, which accepts at most 10 coordinates and a 40 m search
  radius per request. Routes are matched in chunks of 10 points (3 requests at a time, cached), and trips that
  would need more than 60 requests are not snapped. For heavy use, run your own OSRM server and change the URL
  and the `OSRM_*` constants at the top of `App.jsx`.
- The default history window (`?horas=N`) compares against PostgreSQL `NOW()`, which is UTC, while the data is
  stored in Bogotá local time, so the effective window is about 5 hours shorter than requested.
- `npm run lint` reports a few `react-hooks/set-state-in-effect` errors that predate these changes.
- `/api/lugar-visitado` scans the table when nothing matches; an index on `(latitud, longitud)` would speed it
  up on large tables.
