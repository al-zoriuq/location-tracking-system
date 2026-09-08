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
The `.env` file contains sensitive information and should **not** be uploaded to GitHub.

The RDS SSL certificate (`global-bundle.pem`) must also be present in the project directory:
```bash
curl -o global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

### Run the UDP Backend
With the virtual environment activated, start the UDP listener:
```bash
python snifferwpostgresql.py
```
This listens for UDP location updates on port `5000` and stores them in the PostgreSQL RDS database.

### Run the Web Dashboard (Production)
The dashboard (`servidorweb.py`) is served via Gunicorn behind Nginx, not the Flask dev server.

1. Install Nginx: `sudo apt install nginx -y`
2. Install Gunicorn (inside the venv): `pip install gunicorn`
3. Configure Nginx as a reverse proxy — see `/etc/nginx/sites-available/location-tracker` (proxies port 80 to `127.0.0.1:8000`)
4. Run Gunicorn via the systemd service `gunicorn-location.service`, which starts automatically and restarts on failure:
```bash
sudo systemctl enable gunicorn-location
sudo systemctl start gunicorn-location
```
