# GPSLink — Rama `ci-cd-deploy`

Este documento reúne toda la infraestructura de despliegue automático (CI/CD), HTTPS y configuración de esta rama, junto con el contenido completo de cada archivo, para que cualquiera del grupo pueda entender y replicar el sistema sin tener que ir a buscar cada pieza por separado.

---

## 1. Qué se agregó en esta rama, respecto a `main`

### Servicios de systemd (carpeta `deploy/`)

Los tres procesos del backend dejaron de correrse manualmente en una terminal y ahora corren como servicios administrados por el sistema operativo, para que sigan vivos aunque se cierre la sesión SSH y se reinicien solos si fallan:

- `deploy/sniffer.service` — corre el sniffer UDP (`snifferwpostgresql.py`), escuchando el puerto 5000.
- `deploy/gunicorn.service` — corre el backend Flask con Gunicorn, en el puerto 5001.
- `deploy/vite-preview.service` — corre el build de producción del frontend (React + Vite), en el puerto 4173.

Estos archivos se copian automáticamente a `/etc/systemd/system/` en cada despliegue.

### NGINX como puerta de entrada única (`deploy/nginx.conf`)

NGINX recibe todo el tráfico público (puertos 80 y 443) y lo reparte:
- `/api/` → reenvía a Gunicorn (puerto 5001)
- `/` → reenvía al frontend servido por Vite (puerto 4173)
- `/.well-known/acme-challenge/` → sirve los archivos de verificación de Let's Encrypt (necesario para el HTTPS)

Este archivo tiene el texto `DOMAIN_PLACEHOLDER` y `server_name _;` como marcadores — el workflow los reemplaza automáticamente por el dominio real de cada persona.

### HTTPS con Let's Encrypt / Certbot

Cada instancia tiene su propio certificado SSL, generado con Certbot, usando su propio dominio de DuckDNS. Este paso es manual y no se puede automatizar (Let's Encrypt necesita verificar que cada quien controla su dominio), así que cada integrante debe correrlo una sola vez en su propio servidor (ver comando en la sección 3 más abajo).

### Despliegue automático con GitHub Actions (`.github/workflows/deploy.yml`)

Cada push a la rama `ci-cd-deploy` dispara un workflow que, en cada instancia registrada:
1. Trae el código más reciente (`git pull`)
2. Reinstala dependencias de Python (`pip install -r requirements.txt`)
3. Recompila el frontend (`npm install && npm run build`)
4. Copia los archivos de configuración de `deploy/` a su ubicación real en el servidor
5. Reemplaza el dominio en `nginx.conf` con el de cada persona
6. Reinicia los 3 servicios (`sniffer`, `gunicorn`, `vite-preview`) y recarga NGINX

El workflow tiene un step independiente por cada integrante del grupo, cada uno usando su propio set de credenciales. Si el despliegue de una persona falla, no afecta el de las demás.

### Título de pestaña personalizado por instancia

`disenop2web/src/App.jsx` lee una variable de entorno para mostrar el nombre de cada persona en el título de la pestaña del navegador:

```jsx
const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";
document.title = `GPSLink - ${nombre}`;
```

Cada quien define su propio nombre en su `disenop2web/.env` (archivo local, nunca se sube a GitHub).

### `vite.config.js` — dominios permitidos

Como Vite bloquea por defecto peticiones que no vengan de `localhost`, se agregó la lista de dominios del grupo (o `allowedHosts: true`) para que el servidor de preview acepte conexiones desde los dominios reales de cada instancia.

---

## 2. Cómo unirse al despliegue automático (para cada integrante nuevo)

### En tu propio EC2:

**a) Traer el código:**
```bash
git fetch origin
git checkout ci-cd-deploy
git pull origin ci-cd-deploy
```

**b) Crear tu `.env` de base de datos** (raíz del proyecto, con tus datos de RDS):
```
rdshost=...
rdsdbname=...
rdsuser=...
rdspass=...
```

**c) Crear tu `.env` del frontend** (`disenop2web/.env`):
```
VITE_NOMBRE_PERSONA=TuNombre
```

**d) Crear y activar los 3 servicios:**
```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/
sudo cp deploy/vite-preview.service /etc/systemd/system/
sudo cp deploy/sniffer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sniffer gunicorn vite-preview
sudo systemctl start sniffer gunicorn vite-preview
```

**e) Configurar NGINX con tu dominio:**
```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-enabled/default
sudo sed -i "s#DOMAIN_PLACEHOLDER#TU_DOMINIO#g; s#server_name _;#server_name TU_DOMINIO;#g" /etc/nginx/sites-enabled/default
```
Antes de recargar, comenta o borra temporalmente el bloque `listen 443 ssl { ... }` (el certificado todavía no existe), valida y recarga solo con el bloque HTTP:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

**f) Pedir tu certificado HTTPS:**
```bash
sudo mkdir -p /var/www/certbot
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot certonly --webroot -w /var/www/certbot -d TU_DOMINIO --non-interactive --agree-tos -m tu-correo@ejemplo.com
```

**g) Una vez tengas el certificado, restaura el `nginx.conf` completo (con el bloque 443) y recarga:**
```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-enabled/default
sudo sed -i "s#DOMAIN_PLACEHOLDER#TU_DOMINIO#g; s#server_name _;#server_name TU_DOMINIO;#g" /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

**h) Generar tu llave SSH dedicada para GitHub Actions:**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy_key -N ""
cat ~/.ssh/github_deploy_key.pub >> ~/.ssh/authorized_keys
cat ~/.ssh/github_deploy_key
```
(copia la llave privada completa que se muestra, con `-----BEGIN...` y `-----END...`)

**i) Confirmar que los reinicios no piden contraseña:**
```bash
sudo -n systemctl restart sniffer
sudo -n systemctl restart gunicorn
sudo -n systemctl restart vite-preview
```

### En GitHub (quien tenga acceso a Settings):

Crear 4 secrets con tu nombre como sufijo:
- `EC2_HOST_TUNOMBRE`
- `EC2_USER_TUNOMBRE`
- `EC2_SSH_KEY_TUNOMBRE`
- `EC2_DOMAIN_TUNOMBRE`

Y agregar un nuevo `step` al workflow en `.github/workflows/deploy.yml`, copiando el patrón de los steps existentes (ver contenido completo en la sección 3).

---

## 3. Contenido completo de cada archivo (referencia)

### `deploy/sniffer.service`

```ini
[Unit]
Description=Sniffer UDP - GPSLink
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/location-tracking-system
ExecStart=/home/ubuntu/location-tracking-system/venv/bin/python3 snifferwpostgresql.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### `deploy/gunicorn.service`

```ini
[Unit]
Description=Gunicorn - GPSLink Backend
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/location-tracking-system
ExecStart=/home/ubuntu/location-tracking-system/venv/bin/gunicorn --bind 0.0.0.0:5001 servidorweb:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### `deploy/vite-preview.service`

```ini
[Unit]
Description=Vite Preview Server - GPSLink
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/location-tracking-system/disenop2web
ExecStart=/usr/bin/npm run preview -- --host
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### `deploy/nginx.conf`

```nginx
server {
    listen 80;
    server_name _;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/privkey.pem;

    location /api/ {
        proxy_pass http://127.0.0.1:5001/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:4173/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### `.github/workflows/deploy.yml`

```yaml
name: Deploy to EC2

on:
  push:
    branches: [ci-cd-deploy]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Marcela's EC2
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets.EC2_HOST }}
          username: ${{ secrets.EC2_USER }}
          key: ${{ secrets.EC2_SSH_KEY }}
          script: |
            cd /home/ubuntu/location-tracking-system
            git fetch origin
            git checkout ci-cd-deploy
            git pull origin ci-cd-deploy
            source venv/bin/activate
            pip install -r requirements.txt
            cd disenop2web
            npm install
            npm run build
            cd ..
            sudo mkdir -p /var/www/certbot
            sudo apt-get install -y certbot python3-certbot-nginx
            sudo cp deploy/gunicorn.service /etc/systemd/system/gunicorn.service
            sudo cp deploy/vite-preview.service /etc/systemd/system/vite-preview.service
            sudo cp deploy/sniffer.service /etc/systemd/system/sniffer.service
            sudo cp deploy/nginx.conf /etc/nginx/sites-enabled/default
            DOMAIN=$(echo "${{ secrets.EC2_DOMAIN_MARCELA }}" | tr -d '\r\n ')
            sudo sed -i "s#DOMAIN_PLACEHOLDER#$DOMAIN#g; s#server_name _;#server_name $DOMAIN;#g" /etc/nginx/sites-enabled/default
            sudo nginx -t
            sudo systemctl daemon-reload
            sudo systemctl restart sniffer
            sudo systemctl restart gunicorn
            sudo systemctl restart vite-preview
            sudo systemctl reload nginx

      - name: Deploy to Alba's EC2
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets.EC2_HOST_ALBA }}
          username: ${{ secrets.EC2_USER_ALBA }}
          key: ${{ secrets.EC2_SSH_KEY_ALBA }}
          script: |
            cd /home/ubuntu/location-tracking-system
            git fetch origin
            git checkout ci-cd-deploy
            git pull origin ci-cd-deploy
            source venv/bin/activate
            pip install -r requirements.txt
            cd disenop2web
            npm install
            npm run build
            cd ..
            sudo mkdir -p /var/www/certbot
            sudo apt-get install -y certbot python3-certbot-nginx
            sudo cp deploy/gunicorn.service /etc/systemd/system/gunicorn.service
            sudo cp deploy/vite-preview.service /etc/systemd/system/vite-preview.service
            sudo cp deploy/sniffer.service /etc/systemd/system/sniffer.service
            sudo cp deploy/nginx.conf /etc/nginx/sites-enabled/default
            DOMAIN=$(echo "${{ secrets.EC2_DOMAIN_ALBA }}" | tr -d '\r\n ')
            sudo sed -i "s#DOMAIN_PLACEHOLDER#$DOMAIN#g; s#server_name _;#server_name $DOMAIN;#g" /etc/nginx/sites-enabled/default
            sudo nginx -t
            sudo systemctl daemon-reload
            sudo systemctl restart sniffer
            sudo systemctl restart gunicorn
            sudo systemctl restart vite-preview
            sudo systemctl reload nginx
```

*(cuando Taufic y Sthefany completen su configuración, se agrega un step idéntico por cada uno, con sus propios secrets.)*

---

## 4. Instancias actualmente configuradas

| Persona | Dominio |
|---|---|
| Marcela | marcelamgps.duckdns.org |
| Alba | albagps.duckdns.org |

*(agregar aquí a Taufic y Sthefany cuando completen su configuración)*
