## Clone and Configure the Project
To obtain the project on the EC2 instance, clone the repository:
```bash
git clone https://github.com/al-zoriuq/location-tracking-system.git
cd location-tracking-system
```
The repository includes a setup script (`script.sh`) that installs the required Python packages, creates the virtual environment, and installs the project dependencies.
Give the script execution permissions and run it:
```bash
chmod +x script.sh
./script.sh
```
Once the script finishes, activate the virtual environment:
```bash
source venv/bin/activate
```
The virtual environment must be activated again whenever a new EC2 session is started:
```bash
source venv/bin/activate
```

### RDS Configuration
Create the `.env` file from the provided template:
```bash
cp .env-template .env
```
Edit the file and add your RDS credentials:
```bash
nano .env
```
The `.env` file should contain:
```env
rdspass="YOUR_RDS_PASSWORD"
rdsdbname="YOUR_DB_NAME"
rdshost="YOUR_RDS_ENDPOINT"
rdsuser="YOUR_RDS_USER"
```
The `.env` file contains sensitive information and should **not** be uploaded to GitHub. Make sure it is included in `.gitignore`.

The RDS SSL certificate (`global-bundle.pem`) must also be present in the project directory because the application uses it to establish a secure connection with the PostgreSQL RDS database:
```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

### Run the UDP Backend
With the virtual environment activated, start the UDP listener:
```bash
python snifferwpostgresql.py
```
This listens for UDP location updates on port `5000` and stores them in the PostgreSQL RDS database.

## Production Deployment (Nginx + Gunicorn)
The web dashboard (`servidorweb.py`) is served with Gunicorn behind Nginx, not with Flask's development server.

### 1. Build the frontend
```bash
cd disenop2web
npm install
npm run build
cd ..
```
This generates `disenop2web/dist/`, which `servidorweb.py` serves directly.

### 2. Install Nginx and Gunicorn
```bash
sudo apt install nginx -y
pip install -r requirements.txt   # already includes gunicorn
```

### 3. Configure Nginx as a reverse proxy
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

### 4. Systemd service for Gunicorn
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

### Zona horaria de los timestamps

Los paquetes GPS traen la hora con offset explícito (p. ej. `-05:00`). El sniffer conserva la hora local y descarta el offset, sin convertir a UTC:

```python
timestamp_gps = timestamp_gps.replace(tzinfo=None)
```

- `timestamp_gps` se guarda como **hora de Bogotá sin zona** (UTC−5 todo el año).
- `timestamp_recepcion` se guarda en **UTC** (la RDS corre en UTC).
- Toda comparación con "ahora" debe usar `NOW() AT TIME ZONE 'America/Bogota'` en el servidor, o `-05:00` al interpretar la fecha en el navegador. Comparar `timestamp_gps` con `NOW()` directamente desplaza el resultado 5 horas.

---

## 5. Frontend Build & State Management

La aplicación frontend en React (`disenop2web`) cuenta con:

- **Base Path Resolution:** `base: '/'` estandarizado en `vite.config.js` para eliminar errores 404 de assets durante la distribución.
- **Environment Variables:** Configuradas vía `.env` (p. ej. `VITE_NOMBRE_PERSONA=Sthefany`) para renderizar dinámicamente el branding individual de cada cliente.
- **Real-time Map & Route Plotting:** `MapContainer` de Leaflet, marcadores SVG/CSS pulsantes personalizados (`iconoActual`), marcadores estáticos (`iconoInicio`) y trazados `Polyline` que rastrean el movimiento histórico de coordenadas.
- **Dynamic Auto-Fitting (AjustarVista):** Usa el hook `useMap` de Leaflet y una guarda con `useRef` para realizar un `fitBounds` inicial al cargar la ruta, sin sobrescribir las interacciones manuales de pan/zoom durante los ciclos de polling de 10 segundos.
- **Relative Time Calculation:** Las funciones `parsearFechaUTC` y `calcularEstado` calculan estados relativos en línea ("en línea", "hace X min") e indicadores visuales de salud (`dot-fresh`, `dot-medium`, `dot-old`).

---

### Interfaz de usuario

- **Rutas:** el historial se divide en viajes (más de 1 h sin datos, más de 1 km entre puntos o velocidad implícita mayor a 180 km/h). Se navega con anterior, siguiente y un selector con todas.
- **Filtros:** rango de fecha y hora (el fin debe ser posterior al inicio, sin fechas futuras) y búsqueda de lugar, combinables. Si el filtro corta un viaje, se marca con extremos huecos y un aviso con «Ver viaje completo».
- **Mapa:** marcadores de inicio, fin y posición actual, paradas (5 min dentro de 50 m), visitas a un lugar, reproductor del recorrido, ajuste a vías y seguimiento del punto actual.
- **Diseño adaptable:** en pantallas pequeñas los paneles se compactan, el selector de fechas se abre como hoja inferior, el historial como hoja inferior en el celular y como columna lateral en pantalla ancha, y hay un botón para ocultar los paneles.
- **Ayuda:** botón «?» en la barra superior; su texto (`AyudaModal.jsx`) debe actualizarse cuando cambie la interfaz.

## 6. Branch Management & Workflow Integration

1. **Development & Isolation:** Las features y pruebas de integración se desarrollan en branches de staging (p. ej. `sthefany-test`).
2. **Synchronization with Main:** Los merges de branches traen los cambios entrantes desde `main` (`git fetch origin` → `git merge origin/main`), resolviendo conflictos localmente (p. ej. `App.jsx`, migraciones de esquema) antes de hacer push.
3. **Automated Continuous Deployment:** Hacer push o mergear Pull Requests hacia `main` dispara automáticamente `deploy-main.yml`, ejecutando scripts de despliegue SSH en paralelo hacia todos los targets EC2 configurados.
