## Clone and Configure the Project

To obtain the project on the EC2 instance, clone the `feature/rds-conn` branch directly:

```bash
git clone -b feature/rds-conn https://github.com/al-zoriuq/location-tracking-system.git
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

Edit the file and add the RDS database password:

```bash
nano .env
```

The `.env` file should contain:

```env
rdspass=YOUR_RDS_PASSWORD
```

The `.env` file contains sensitive information and should **not** be uploaded to GitHub. Make sure it is included in `.gitignore`.

The RDS SSL certificate (`global-bundle.pem`) must also be present in the project directory because the application uses it to establish a secure connection with the PostgreSQL RDS database.

### Run the Backend

With the virtual environment activated, start the UDP server:

```bash
python backendwmysql.py
```

The server will listen for UDP location updates on port `5000` and store the received data in the PostgreSQL RDS database.
