# Location & GPS Tracking System — CI/CD, Infrastructure & Multi-Node Deployment Audit

This repository contains the full-stack architecture, the deployment automation and the database schema definition for the **GPS Location Tracking System**.

This document details the complete deployment lifecycle, the multi-server continuous deployment (CI/CD) setup via GitHub Actions, the web server configuration (Nginx + Gunicorn + Certbot), the database schema alignment (PostgreSQL) and the frontend build integration.

## 📋 Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [CI/CD & Multi-Node Deployment Strategy](#2-cicd--multi-node-deployment-strategy)
   - AWS Security Group Ingress Automation
   - GitHub Actions Workflow Architecture
3. [Server & Infrastructure Setup](#3-server--infrastructure-setup)
   - Systemd Services
   - Nginx & Reverse Proxy Configuration
   - SSL/TLS Certificate Setup (Certbot)
4. [Database & Backend Synchronization](#4-database--backend-synchronization)
   - PostgreSQL Schema Alignment (device_id)
   - Timestamp Time Zone
5. [Frontend Build & State Management](#5-frontend-build--state-management)
6. [Branch Management & Workflow Integration](#6-branch-management--workflow-integration)

---

## 1. System Architecture Overview

The system captures, ingests, processes and displays real-time GPS coordinates transmitted over UDP sockets. The high-level architecture comprises:

- **Ingestion Layer (UDP Sniffer):** Python script that listens on port 5000 to capture incoming UDP packets from GPS devices, parse the payload and insert the coordinates into PostgreSQL.
- **Backend API (Flask & Gunicorn):** Python WSGI application running on port 5001 (or 8000), serving REST endpoints (`/api/ultima-ubicacion`, `/api/historial-ubicaciones`, `/api/buscar-lugar`, `/api/lugar-visitado`) and serving the React build directly via `send_from_directory`.
- **Database Layer (AWS RDS PostgreSQL):** PostgreSQL database that stores telemetry (`ubicaciones` table) with strict unique constraints and timestamping.
- **Web Server Layer (Nginx):** Handles SSL termination (HTTPS on port 443), HTTP-to-HTTPS redirection (port 80) and direct reverse-proxying to Gunicorn.
- **Frontend Layer (React + Vite + Leaflet):** Single Page Application that renders dynamic maps, route polylines, active-status indicators and scrollable history logs.

---

## 2. CI/CD & Multi-Node Deployment Strategy

To guarantee automated, synchronized, zero-downtime deployments across every team member's infrastructure, a matrix-based GitHub Actions workflow (`deploy-main.yml`) was set up.

### AWS Security Group Ingress Automation

To avoid keeping the SSH port (22) open to `0.0.0.0/0`, the pipeline implements a dynamic firewall rule:

1. Authenticates with AWS via per-node IAM Access Keys.
2. Gets the public IP of the GitHub Actions runner.
3. Temporarily adds an ingress rule to the target AWS Security Group (`aws ec2 authorize-security-group-ingress`).
4. Runs the remote deployment commands over SSH.
5. Revokes the ingress rule (`aws ec2 revoke-security-group-ingress`), keeping things secure even if the build fails (`if: always()`).

### GitHub Actions Workflow Architecture (`deploy-main.yml`)

```yaml
name: Deploy to Production (all servers)

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          # --- Sthefany's server ---
          - persona: sthefany
            host_secret: EC2_HOST_STHEFANY
            user_secret: EC2_USER_STHEFANY
            key_secret: EC2_SSH_KEY_STHEFANY
            aws_key_secret: AWS_ACCESS_KEY_ID
            aws_secret_secret: AWS_SECRET_ACCESS_KEY
            sg_id: sg-040f40fef53b4b9f5
            service: gunicorn-location

          # --- Taufic's server ---
          - persona: taufic
            host_secret: EC2_HOST_TAUFIC
            user_secret: EC2_USER_TAUFIC
            key_secret: EC2_SSH_KEY_TAUFIC
            aws_key_secret: AWS_ACCESS_KEY_ID_TAUFIC
            aws_secret_secret: AWS_SECRET_ACCESS_KEY_TAUFIC
            sg_id: sg-0c4e91a324e3145e0
            service: gunicorn-location

          # --- Alba's server ---
          - persona: alba
            host_secret: EC2_HOST_ALBA
            user_secret: EC2_USER_ALBA
            key_secret: EC2_SSH_KEY_ALBA
            aws_key_secret: AWS_ACCESS_KEY_ID_ALBA
            aws_secret_secret: AWS_SECRET_ACCESS_KEY_ALBA
            sg_id: sg-000664e76aea40f3e
            service: gunicorn

          # --- Marcela's server ---
          - persona: marcela
            host_secret: EC2_HOST
            user_secret: EC2_USER
            key_secret: EC2_SSH_KEY
            aws_key_secret: AWS_ACCESS_KEY_ID_MARCELA
            aws_secret_secret: AWS_SECRET_ACCESS_KEY_MARCELA
            sg_id: sg-0e524eabd8e6036a2
            service: gunicorn

    steps:
      - name: Configure AWS credentials (${{ matrix.persona }})
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets[matrix.aws_key_secret] }}
          aws-secret-access-key: ${{ secrets[matrix.aws_secret_secret] }}
          aws-region: us-east-1

      - name: Get runner public IP
        id: ip
        run: echo "ip=$(curl -s https://checkip.amazonaws.com)/32" >> "$GITHUB_OUTPUT"

      - name: Open SSH port for this runner
        run: |
          aws ec2 authorize-security-group-ingress \
            --group-id ${{ matrix.sg_id }} \
            --protocol tcp --port 22 \
            --cidr ${{ steps.ip.outputs.ip }}

      - name: Wait for security group propagation
        run: sleep 5

      - name: Deploy to ${{ matrix.persona }}'s EC2
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets[matrix.host_secret] }}
          username: ${{ secrets[matrix.user_secret] }}
          key: ${{ secrets[matrix.key_secret] }}
          timeout: 60s
          script: |
            cd /home/ubuntu/location-tracking-system
            git fetch origin
            git checkout main
            git pull origin main
            source venv/bin/activate
            pip install -r requirements.txt
            cd disenop2web
            npm install
            npm run build
            cd ..
            sudo systemctl restart ${{ matrix.service }}

      - name: Close SSH port for this runner
        if: always()
        run: |
          aws ec2 revoke-security-group-ingress \
            --group-id ${{ matrix.sg_id }} \
            --protocol tcp --port 22 \
            --cidr ${{ steps.ip.outputs.ip }}
```

---

## 3. Server & Infrastructure Setup

### Systemd Services

Each EC2 instance runs background tasks managed by systemd.

**Gunicorn Service** (`/etc/systemd/system/gunicorn-location.service` or `gunicorn.service`)

```ini
[Unit]
Description=Gunicorn instance to serve location-tracking-system
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/location-tracking-system
ExecStart=/home/ubuntu/location-tracking-system/venv/bin/gunicorn --bind 0.0.0.0:5001 servidorweb:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**UDP Sniffer Service** (`/etc/systemd/system/sniffer-location.service`)

```ini
[Unit]
Description=Sniffer UDP para location-tracking-system (produccion)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/location-tracking-system
ExecStart=/home/ubuntu/location-tracking-system/venv/bin/python3 /home/ubuntu/location-tracking-system/snifferwpostgresql.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Nginx & Reverse Proxy Configuration

Instead of using development web servers (e.g. `vite preview` on port 4173), the production nodes were standardized to proxy all HTTP/HTTPS traffic directly to Flask/Gunicorn (`127.0.0.1:5001`), which serves both the static assets of the React build and the API endpoints.

**Standardized configuration** `/etc/nginx/sites-enabled/default`:

```nginx
server {
    listen 80;
    server_name yourdomain.duckdns.org;

    location / {
        proxy_pass http://127.0.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### SSL/TLS Certificate Setup (Certbot)

Certbot in automatic mode (`certbot --nginx`) was applied on every node:

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.duckdns.org
```

Certbot automatically injects the `listen 443 ssl;` blocks and the SSL key paths, and sets up an automatic 301 redirect from HTTP to HTTPS.

---

## 4. Database & Backend Synchronization

### PostgreSQL Schema Alignment (device_id)

To support unique device identification and prevent duplicate telemetry entries, the database schema was aligned across all production and test environments (`locationtracker_test` and `p2database`).

**SQL migration run on the database environments:**

```sql
ALTER TABLE ubicaciones ADD COLUMN device_id text;
ALTER TABLE ubicaciones ADD CONSTRAINT ubicacion_unica UNIQUE (device_id, timestamp_gps);
```

### Timestamp Time Zone

GPS packets carry the time with an explicit offset (e.g. `-05:00`). The sniffer keeps the local time and drops the offset, without converting to UTC:

```python
timestamp_gps = timestamp_gps.replace(tzinfo=None)
```

- `timestamp_gps` is stored as **Bogotá local time without a time zone** (UTC−5 all year round).
- `timestamp_recepcion` is stored in **UTC** (the RDS instance runs in UTC).
- Any comparison with "now" must use `NOW() AT TIME ZONE 'America/Bogota'` on the server, or `-05:00` when parsing the date in the browser. Comparing `timestamp_gps` directly with `NOW()` shifts the result by 5 hours.

---

## 5. Frontend Build & State Management

The React frontend application (`disenop2web`) features:

- **Base Path Resolution:** `base` in `vite.config.js` takes the `BASE_PATH` variable (`/` by default), so each environment can serve the app from its own path without asset 404 errors.
- **Environment Variables:** Configured via `.env` (e.g. `VITE_NOMBRE_PERSONA=Sthefany`) to dynamically render each client's individual branding.
- **Real-time Map & Route Plotting:** Leaflet `MapContainer`, custom pulsing SVG/CSS markers (`iconoActual`), static markers (`iconoInicio`) and `Polyline` traces that follow the historical movement of the coordinates.
- **Dynamic Auto-Fitting (AjustarVista):** Uses Leaflet's `useMap` hook and a `useRef` guard to perform an initial `fitBounds` when the route loads, without overriding manual pan/zoom interactions during the 10-second polling cycles.
- **Relative Time Calculation:** The `parsearFechaUTC` and `calcularEstado` functions compute relative online states ("en línea" — online, "hace X min" — X min ago) and visual health indicators (`dot-fresh`, `dot-medium`, `dot-old`).

---

### User Interface

The interface itself is in Spanish; button and notice labels are quoted as they appear on screen.

- **Routes:** the history is split into trips (more than 1 h without data, more than 1 km between points, or an implied speed above 180 km/h). Navigation is done with previous, next and a picker listing all of them.
- **Filters:** date and time range (the end must be later than the start, no future dates) and place (a city or address search, or a pin dropped on the map with a 300 m area around it), which can be combined. If the filter cuts a trip, it is marked with hollow ends and a notice with «Ver viaje completo» (see the full trip).
- **Map:** start, end and current-position markers, stops (5 min within 50 m), visits to a place, the point-filter pin (with its dotted search area), a route player (the map follows the point while it plays or while the bar is dragged), snap-to-roads, and following of the current point.
- **Responsive design:** on small screens the panels become compact, the date picker opens as a bottom sheet, the history opens as a bottom sheet on phones and as a side column on wide screens, the player switches to two rows (progress bar on top; play, time, speed and close below) between the left edge and the column of round buttons, and there is a button to hide the panels. It is tested in Safari (iOS) and Chrome (Android).
- **Help:** «?» button in the top bar; its text (`AyudaModal.jsx`) must be updated whenever the interface changes.


## 6. Branch Management & Workflow Integration

1. **Development & Isolation:** Features and integration tests are developed on staging branches (e.g. `sthefany-test`).
2. **Synchronization with Main:** Branch merges bring in the incoming changes from `main` (`git fetch origin` → `git merge origin/main`), resolving conflicts locally (e.g. `App.jsx`, schema migrations) before pushing.
3. **Automated Continuous Deployment:** Pushing or merging Pull Requests into `main` automatically triggers `deploy-main.yml`, running the SSH deployment scripts in parallel against every configured EC2 target.
