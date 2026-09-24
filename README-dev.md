# Entorno local de desarrollo (Windows / PowerShell)

Guía para correr el backend y el frontend en tu computador **con datos simulados**,
sin conectarse a la RDS compartida.

## Requisitos

- Python 3.11 o superior (`python --version`)
- Node.js LTS, que incluye `npm` (`node --version`). Si no lo tienes:
  `winget install OpenJS.NodeJS.LTS` y **cierra y vuelve a abrir** la terminal.

Todos los comandos se ejecutan desde la raíz del repositorio
(`location-tracking-system`), salvo donde se indique.

## 1. Entorno virtual de Python (solo la primera vez)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest
```

Si `Activate.ps1` falla con un error de "ejecución de scripts deshabilitada":

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

(`-Scope Process` solo afecta a esa ventana de PowerShell.)

## 2. Backend en modo demo (terminal 1)

```powershell
.\venv\Scripts\Activate.ps1
$env:MODO_DEMO = "1"
python servidorweb.py
```

Debe aparecer `MODO_DEMO=1: usando datos simulados, sin conexión a la RDS` y
`Running on http://127.0.0.1:5001`. Compruébalo en el navegador:
<http://127.0.0.1:5001/api/ultima-ubicacion>

`MODO_DEMO` también puede ir en el `.env` local de la raíz (línea `MODO_DEMO=1`).
Una variable definida con `$env:` tiene prioridad sobre el `.env`.
Con `MODO_DEMO=1` no se necesitan credenciales ni `global-bundle.pem`.

## 3. Frontend (terminal 2)

La primera vez:

```powershell
cd disenop2web
npm install
[IO.File]::WriteAllText("$PWD\.env.local", "VITE_NOMBRE_PERSONA=`"Marcela (test)`"`n")
```

> Se usa `WriteAllText` y no `Set-Content`/`Out-File` porque en PowerShell 5.1
> esos comandos escriben un BOM (UTF-8) o UTF-16, y Vite no reconocería la variable.
> `.env.local` ya está ignorado por git (`disenop2web/.gitignore`, patrón `*.local`).

Cada vez:

```powershell
cd disenop2web
npm run dev
```

Abre <http://localhost:5173>. Vite reenvía `/api/...` al backend de la terminal 1
(`server.proxy` en `disenop2web/vite.config.js`), así que el backend debe estar corriendo.
Si cambias `.env.local`, reinicia `npm run dev`.

## 4. Pruebas y verificación antes de un commit

Desde la raíz, con el entorno virtual activo:

```powershell
python -m pytest tests -q
cd disenop2web
npm run build
npm run lint
```

## Qué contienen los datos demo

Generados por `datos_demo.py` con semilla fija (siempre los mismos para una misma fecha):

| Qué | Cuándo (días atrás, hora) |
|---|---|
| Pasos cerca de Uninorte (11.0190, -74.8505) | 9 d 06:40 · 7 d 07:20 · 4 d 17:45 · 2 d 19:20 |
| Parada de 8 min a menos de 40 m de Uninorte | 7 d, de 07:28 a 07:36 |
| Cruce rápido a 60 km/h sin ningún punto a menos de 50 m (los más cercanos a ~83 m) | 5 d 10:30 |
| Saltos imposibles de GPS | 8 d 13:15 · 3 d 08:00 |
| Parada de 12 min en el estadio | 3 d 08:00 |
| Segundo dispositivo (`demo-vehiculo-02`) | 3 d 14:00 |
| Vehículo "en vivo" (sesiones de 2 h que empiezan en horas pares, desde las 06:00 de hoy; circuitos norte y sur alternados) | hoy, hasta la hora actual |

Los horarios son de Bogotá, sin zona horaria, igual que `timestamp_gps` en la base real.
