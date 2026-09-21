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
```bash
sudo systemctl daemon-reload
sudo systemctl enable gunicorn-location
sudo systemctl start gunicorn-location
```
