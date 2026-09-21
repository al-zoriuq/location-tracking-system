# Location & GPS Tracking System — CI/CD, Infrastructure & Multi-Node Deployment Audit

Este repositorio contiene la arquitectura full-stack, la automatización de despliegue y la definición del esquema de base de datos para el **GPS Location Tracking System**.

Este documento detalla el ciclo de vida completo de despliegue, la configuración de despliegue continuo multi-servidor (CI/CD) vía GitHub Actions, la configuración del servidor web (Nginx + Gunicorn + Certbot), la alineación del esquema de base de datos (PostgreSQL) y la integración del build del frontend.

## 📋 Tabla de Contenidos

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
   - UTC Timezone Standardization
5. [Frontend Build & State Management](#5-frontend-build--state-management)
6. [Branch Management & Workflow Integration](#6-branch-management--workflow-integration)

---

## 1. System Architecture Overview

El sistema captura, ingiere, procesa y muestra coordenadas GPS en tiempo real transmitidas vía sockets UDP. La arquitectura de alto nivel comprende:

- **Ingestion Layer (UDP Sniffer):** Script en Python que escucha en el puerto 5000 para capturar paquetes UDP entrantes de dispositivos GPS, parsear el payload e insertar coordenadas en PostgreSQL.
- **Backend API (Flask & Gunicorn):** Aplicación WSGI en Python corriendo en el puerto 5001 (u 8000), sirviendo endpoints REST (`/api/ultima-ubicacion`, `/api/historial-ubicaciones`) y sirviendo directamente el build de React vía `send_from_directory`.
- **Database Layer (AWS RDS PostgreSQL):** Base de datos PostgreSQL que almacena telemetría (tabla `ubicaciones`) con restricciones únicas estrictas y timestamping.
- **Web Server Layer (Nginx):** Maneja terminación SSL (HTTPS en el puerto 443), redirección HTTP-a-HTTPS (puerto 80) y reverse-proxy directo hacia Gunicorn.
- **Frontend Layer (React + Vite + Leaflet):** Single Page Application que renderiza mapas dinámicos, polylines de rutas, indicadores de estado activo y logs de historial con scroll.

---

## 2. CI/CD & Multi-Node Deployment Strategy

Para garantizar despliegues automatizados, sincronizados y sin downtime en la infraestructura de todos los miembros del equipo, se estableció un workflow de GitHub Actions basado en matrix (`deploy-main.yml`).

### AWS Security Group Ingress Automation

Para evitar mantener el puerto SSH (22) abierto a `0.0.0.0/0`, el pipeline implementa una regla de firewall dinámica:

1. Se autentica con AWS vía IAM Access Keys por nodo.
2. Obtiene la IP pública del runner de GitHub Actions.
3. Agrega temporalmente una regla de ingreso al Security Group de AWS objetivo (`aws ec2 authorize-security-group-ingress`).
4. Ejecuta los comandos de despliegue remoto vía SSH.
5. Revoca la regla de ingreso (`aws ec2 revoke-security-group-ingress`), garantizando la seguridad incluso si el build falla (`if: always()`).

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

Cada instancia EC2 corre tareas en segundo plano administradas por systemd.

**Gunicorn Service** (`/etc/systemd/system/gunicorn-location.service` o `gunicorn.service`)

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

En lugar de usar servidores web de desarrollo (p. ej. `vite preview` en el puerto 4173), los nodos de producción se estandarizaron para proxear todo el tráfico HTTP/HTTPS directamente a Flask/Gunicorn (`127.0.0.1:5001`), que sirve tanto los assets estáticos del build de React como los endpoints de la API.

**Configuración estandarizada** `/etc/nginx/sites-enabled/default`:

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

Certbot en modo automático (`certbot --nginx`) fue aplicado en todos los nodos:

```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.duckdns.org
```

Certbot inyecta automáticamente los bloques `listen 443 ssl;`, las rutas de las llaves SSL y configura una redirección automática 301 de HTTP a HTTPS.

---

## 4. Database & Backend Synchronization

### PostgreSQL Schema Alignment (device_id)

Para soportar identificación única de dispositivos y prevenir entradas de telemetría duplicadas, el esquema de base de datos fue alineado en todos los ambientes de producción y pruebas (`locationtracker_test` y `p2database`).

**Migración SQL ejecutada en los ambientes de base de datos:**

```sql
ALTER TABLE ubicaciones ADD COLUMN device_id text;
ALTER TABLE ubicaciones ADD CONSTRAINT ubicacion_unica UNIQUE (device_id, timestamp_gps);
```

### UTC Timezone Standardization

Se implementó un fix clave en `snifferwpostgresql.py` respecto al parseo de timestamps entrantes. Los paquetes GPS entrantes transmiten timestamps con offsets de zona horaria explícitos (p. ej. `-05:00`). Eliminar los metadatos de zona horaria directamente sin conversión causaba un desfase de 5 horas al ser consultados por el frontend.

**Fix aplicado:**

```python
# Parsear el string con formato de offset (%z)
timestamp_gps = datetime.strptime(timestamp_gps, "%Y-%m-%d %H:%M:%S.%f %z")

# Convertir a UTC explícito antes de remover los metadatos de tzinfo
timestamp_gps = timestamp_gps.astimezone(timezone.utc).replace(tzinfo=None)
```

Esto garantiza que tanto `timestamp_gps` como `timestamp_recepcion` se persistan en UTC real, permitiendo que el cliente frontend renderice correctamente la hora local de Colombia (`America/Bogota`).

---

## 5. Frontend Build & State Management

La aplicación frontend en React (`disenop2web`) cuenta con:

- **Base Path Resolution:** `base: '/'` estandarizado en `vite.config.js` para eliminar errores 404 de assets durante la distribución.
- **Environment Variables:** Configuradas vía `.env` (p. ej. `VITE_NOMBRE_PERSONA=Sthefany`) para renderizar dinámicamente el branding individual de cada cliente.
- **Real-time Map & Route Plotting:** `MapContainer` de Leaflet, marcadores SVG/CSS pulsantes personalizados (`iconoActual`), marcadores estáticos (`iconoInicio`) y trazados `Polyline` que rastrean el movimiento histórico de coordenadas.
- **Dynamic Auto-Fitting (AjustarVista):** Usa el hook `useMap` de Leaflet y una guarda con `useRef` para realizar un `fitBounds` inicial al cargar la ruta, sin sobrescribir las interacciones manuales de pan/zoom durante los ciclos de polling de 10 segundos.
- **Relative Time Calculation:** Las funciones `parsearFechaUTC` y `calcularEstado` calculan estados relativos en línea ("en línea", "hace X min") e indicadores visuales de salud (`dot-fresh`, `dot-medium`, `dot-old`).

---

## 6. Branch Management & Workflow Integration

1. **Development & Isolation:** Las features y pruebas de integración se desarrollan en branches de staging (p. ej. `sthefany-test`).
2. **Synchronization with Main:** Los merges de branches traen los cambios entrantes desde `main` (`git fetch origin` → `git merge origin/main`), resolviendo conflictos localmente (p. ej. `App.jsx`, migraciones de esquema) antes de hacer push.
3. **Automated Continuous Deployment:** Hacer push o mergear Pull Requests hacia `main` dispara automáticamente `deploy-main.yml`, ejecutando scripts de despliegue SSH en paralelo hacia todos los targets EC2 configurados.
