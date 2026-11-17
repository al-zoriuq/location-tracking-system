# GPSLink (Android app)

Sends the phone's location over UDP (port `5000`) to the server and, in the car that carries the Raspberry Pi, also to the Pi.

## APK

| Version | Date | File | Changes |
|---|---|---|---|
| v1.1-pi-1s | 2026-11-16 | [`releases/GPSLink-v1.1-pi-1s.apk`](releases/GPSLink-v1.1-pi-1s.apk) | Sends every 1 s, Raspberry Pi buttons |

- This is a *debug* APK (signed with Android Studio's debug key). Installing it requires allowing "install unknown apps".
- Inside the APK `versionName` is still `1.0`; the version in the table is the release name.

## Changes in v1.1-pi-1s

1. **Sends every 1 s.** Before, it requested a single GPS fix every 10 s and, if the GPS never answered (indoors), the app waited forever. Now it listens to the GPS continuously (1 s, no minimum distance) and sends every new fix, even when the phone stands still. If fixes stop arriving, the app and the notification show "Sin señal GPS hace N s".
2. **Pi buttons.** Estado / Pausa / Reanudar / Apagar send `CMD,ESTADO|PAUSA|REANUDA|APAGAR` over UDP to the **first saved IP** (port 5000) and show the Pi's reply (`EST,<device>,<ACTIVO|PAUSADO|APAGANDO>,<signs>`). Apagar (shutdown) asks for confirmation.
3. **The message format did not change:** `Device: <uuid>, Lat: ..., Lon: ..., Timestamp GPS: yyyy-MM-dd HH:mm:ss.SSS -05:00`.

## Phone setup

- Settings → Apps → GPSLink → Battery → **Unrestricted**; Location → **Allow all the time** and **precise**.
- Car with Pi: save `PI_IP;SERVER_IP` (the Pi **first**, so the buttons talk to it).
- Car without Pi: save only the server IP.

The Raspberry Pi side is in [`../raspberry/`](../raspberry/).

## Build

Open this folder in Android Studio, or:

```bash
./gradlew assembleDebug   # output: app/build/outputs/apk/debug/app-debug.apk
```
