#!/bin/bash

# Actualizar paquetes
sudo apt update
sudo apt upgrade -y

# Instalar Python, pip y herramientas necesarias
sudo apt install -y python3 python3-pip python3-venv

# Crear entorno virtual
python3 -m venv venv

# Activar entorno virtual
source venv/bin/activate

# Actualizar pip
pip install --upgrade pip

# Instalar librerías del proyecto
pip install psycopg2-binary boto3 python-dotenv Flask

echo "======================================"
echo "Instalación completada"
echo "======================================"
echo "Python:"
python3 --version
echo "Pip:"
pip --version
echo "Entorno virtual creado en ./venv"