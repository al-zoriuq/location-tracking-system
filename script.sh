#!/bin/bash

# Actualizar paquetes
sudo apt update
sudo apt upgrade -y

# Instalar Python y pip
sudo apt install -y python3 python3-pip

# Actualizar pip
python3 -m pip install --upgrade pip

# Instalar librerías del proyecto
python3 -m pip install psycopg2-binary boto3 python-dotenv Flask

echo "======================================"
echo "Instalación completada"
echo "======================================"

echo "Python:"
python3 --version

echo "Pip:"
python3 -m pip --version

echo "Librerías instaladas:"
python3 -m pip list