#!/bin/bash

set -e

# Actualizar paquetes
sudo apt update
sudo apt upgrade -y

python3 -m venv venv

source venv/bin/activate

pip install --upgrade pip

pip install -r requirements.txt

echo "Entorno virtual creado e instalación completada."
echo "Para activarlo:"
echo "source venv/bin/activate"