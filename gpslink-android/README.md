# GPSLink (Android app)

Sends the phone's location over UDP (port `5000`) to the server every second. In the car that carries the Raspberry Pi it also sends the location to the Pi, receives the Pi's sign detections and forwards them to the server. **The phone is the only device that talks to the server**; the same APK works with and without a Pi. Pipo, a voice assistant, reads the signs aloud and answers questions.

## Versions

| Version | Date | Where | What changed |
|---|---|---|---|
| v1.2 | 2026-11-23 | build from source (see *Build*); to be published as GitHub release `v1.2.0` | Pi sends its detections to the app, new look, Pipo voice assistant, new icon and live notification |
| v1.1-pi-1s | 2026-11-16 | [`releases/GPSLink-v1.1-pi-1s.apk`](releases/GPSLink-v1.1-pi-1s.apk) (file in the repo, not a GitHub release) | Sends every 1 s, Raspberry Pi buttons |
| v1.1.0 | 2026-09-13 | GitHub release `v1.1.0` (pre-release, debug APK) | Persistent `Device` id in every message |
| v1.0 | 2026-09-12 | GitHub release `v1.0.0` (pre-release, debug APK) | First build: background GPS, UDP to several servers |

- All APKs are *debug* builds (signed with Android Studio's debug key). Installing one requires allowing "install unknown apps".
- **Installing over an older version** only works if both APKs were signed with the same debug key, which in practice means built on the same computer. Otherwise Android refuses ("conflicts with an existing package") and the old app has to be uninstalled first, which creates a **new Device id** (the web page then shows that phone as a new vehicle) and forgets the saved IPs.
- Up to v1.1-pi-1s the APK said `versionName 1.0`; from v1.2 (`versionCode 3`) it matches this table.

## Changes in v1.2

### Pi link (the Pi only talks to the phone)

1. **The app builds and sends the Pi's detections.** The app listens on UDP `5001`. The Pi sends `DET,<id>,<sign>,<conf>,<MPU km/h|NA>,<age_ms>`; the app answers `ACK,<id>` to the Pi (port 5000) and builds the server line itself: its position closest to the detection time, the time, its GPS speed (if the fix is within 3 s), `Usa: GPS|MPU|NA` and `SI`/`EXCEDE` (limit + 3 km/h), with this phone's `Device`. Repeated `DET` with the same id are confirmed again but sent only once. A detection that arrives before the phone's first GPS fix is not confirmed: the Pi keeps it and sends it again once the phone has a position.
2. **GPS speed to the Pi.** The route goes to the Pi as `GPS,lat,lon,kmh,epoch_ms` (the Pi calibrates its MPU with it). The route to the server is unchanged.
3. **Pi heartbeat and discovery.** Every 5 s the Pi sends `EST,<device>,<ACTIVO|PAUSADO>,<signs>`, by broadcast while it hasn't heard the phone. The app uses that IP when no Pi IP is saved, so normally nothing has to be typed. The Raspberry widget shows *Conectada*, *En pausa* or *Sin respuesta* (nothing for 15 s).
4. **Two settings fields** (gear button): "IP del servidor" (default `52.71.39.197`) and "IP de la Raspberry (opcional)", only needed if discovery doesn't work on some network. An old saved `PI_IP;SERVER_IP` is split automatically.
5. **No internet → queue.** If Android reports no validated internet, route points and detections are saved to files and sent when it comes back (detections first, 40 per second), with their original timestamp; the server already ignores repeated points. The Ubicación widget shows "Sin internet" and how many messages wait.
6. Message format to the server unchanged.

### New look

Dark purple background with glass cards (Inter font, OFL, see `FONTS_LICENSE.txt`). A ring shows the GPS speed, next to the last speed limit seen (for 15 min) and how far over it the car is; two widgets show the Raspberry and the route status; a list shows the last signs; a floating bar holds the Pi commands. Without a Pi, the bar and the list are hidden and only the route is shown. A long press on the gear opens the manual send. Tapping the notification opens the app.

### Pipo, voice assistant (P3-S5)

1. **Pipo.** A card under the speed ring shows Pipo (a sphere that changes color: violet asleep, turquoise listening, amber thinking, pink speaking, grey off) and a switch to turn him on/off. Say **«Pipo»** (or tap the card) and a sheet comes up from the bottom while he listens, thinks and answers.
2. **Wake word offline.** Vosk listens only for «Pipo» with the small Spanish model (`vosk-model-small-es-0.42`, ~40 MB), **downloaded automatically the first time** (needs internet once; saved in the app's files). The question itself is transcribed with Android's speech recognizer. If Vosk can't run on a phone, only the wake word is off: tapping Pipo still works.
3. **Answers from the server.** The question goes to `POST http://<server IP>/api/pipo` (Nginx, port 80) with the device id and what the phone knows now (speed, last limit, position, Pi status). The server adds the car's detections from the database and asks Groq (`GROQ_API_KEY` in the server's `.env`). The Groq key is never inside the APK. If the server can't answer (no internet, or `/api/pipo` turned off to save tokens), Pipo answers simple questions on the phone (speed, last limit, Raspberry, last sign) and otherwise says the server's Pipo is off.
4. **Automatic warnings.** Pipo speaks every sign the Pi sends («Límite de 30», «Pare adelante»…), warns when the speed is over the limit (again every 45 s while it stays over) and, 10 s after a PARE, says whether the car stopped (GPS speed below 5 km/h). Only signs seen in the last 10 s are spoken: older ones the Pi kept while the phone was away still go to the server, silently.
5. **Floating bubble.** Outside the app Pipo stays as a bubble over other apps (needs "Display over other apps"): tap it to ask, drag it onto the X to hide it.
6. **Permissions.** Microphone (asked after location). The service declares `location|microphone`; on Android 14+ the mic only works if the service was started with the app on screen (or with the bubble visible), so after Android restarts it in the background Pipo only speaks warnings until the app is opened again.
7. **Plain HTTP** to the server is allowed (`usesCleartextTraffic`), since Nginx serves port 80 without TLS.

### Icon and notification

1. **New icon:** a white "G" drawn as a route that ends in a pink point, on the app's purple background (adaptive icon with a monochrome layer for themed icons). The notification uses the same G.
2. **Notification with the speed.** The title says what is happening (`Enviando · 32 km/h`, `47 km/h en zona de 30`, `Sin señal GPS…`, `Sin internet · N guardados`); below it, the last limit seen and the Raspberry status. Buttons: **Preguntar a Pipo** (if Pipo is on and the mic is allowed) and **Pausar/Reanudar Pi** (only with a Pi).
3. **Android 16+: Live Update.** On Android 16 the notification has a bar from 0 to above the limit, with a mark on the limit (lilac below, red above). From Android 16 QPR2 it is also promoted: the speed shows as a chip on the status bar and the notification stays at the top of the lock screen (`POST_PROMOTED_NOTIFICATIONS`; the user can turn Live Updates off for the app). Older phones show the regular version.
4. **Red alert when over the limit.** A separate notification on its own channel ("Alertas de velocidad", high importance): «Baja la velocidad · Vas a 47 en zona de 30». It pops up with sound at most every 45 s while the car stays over the limit (+3 km/h) and goes away by itself 3 s after slowing down.

### Other fixes

- **Location permission:** FINE and COARSE are asked together. Android 12+ ignores a request for FINE alone, so before this a fresh install never showed the dialog and the permission had to be given by hand. If the user picks "approximate", the app says that precise location is needed.
- **16 KB memory pages:** Vosk `0.3.75` and JNA `5.18.1`, whose 64-bit native libraries are 16 KB aligned, so newer phones and the Android 16+ emulator don't show the "Android App Compatibility" warning.
- **Backup:** Android's backup skips Pipo's voice model and the send queues (the model alone went over the 25 MB backup limit, so nothing was backed up).

## Changes in v1.1-pi-1s

1. **Sends every 1 s.** Before, it requested a single GPS fix every 10 s and, if the GPS never answered (indoors), the app waited forever. Now it listens to the GPS continuously (1 s, no minimum distance) and sends every new fix, even when the phone stands still. If fixes stop arriving, the app and the notification show "Sin señal GPS hace N s".
2. **Pi buttons.** Estado / Pausa / Reanudar / Apagar send `CMD,ESTADO|PAUSA|REANUDA|APAGAR` over UDP to the **first saved IP** (port 5000) and show the Pi's reply (`EST,<device>,<ACTIVO|PAUSADO|APAGANDO>,<signs>`). Apagar (shutdown) asks for confirmation.
3. **The message format did not change:** `Device: <uuid>, Lat: ..., Lon: ..., Timestamp GPS: yyyy-MM-dd HH:mm:ss.SSS -05:00`.

## Changes in v1.1.0

- **Persistent `Device` id.** A UUID is created on the first run and saved; every message starts with `Device: <uuid>`. The 4 EC2 instances that receive the same packet use it to avoid inserting the same point 4 times in the shared RDS database. Uninstalling the app creates a new id.

## v1.0

- First build: a foreground service takes a GPS fix every 10 s, also with the app closed, and sends `Lat: ..., Lon: ..., Timestamp GPS: ...` over UDP port 5000 to every IP saved in the app (separated by `;`).

## Phone setup

- Settings → Apps → GPSLink → Battery → **Unrestricted**; Location → **Allow all the time** and **precise** (the app asks for location, notifications, background location and microphone in that order the first time).
- Server `52.71.39.197`; leave the Raspberry field empty (the app finds the Pi on the same Wi-Fi). Type the Pi's IP (e.g. `172.20.10.3`) only if it isn't found.
- For Pipo's bubble: allow "Display over other apps" when the app offers it.

The Raspberry Pi side is in [`../raspberry/`](../raspberry/).

## Build

Open this folder in Android Studio (it downloads the JDK that Gradle asks for), or:

```bash
./gradlew assembleDebug   # output: app/build/outputs/apk/debug/app-debug.apk
```

AGP 9.3, Gradle 9.5, compileSdk/targetSdk 37, minSdk 24. Vosk and JNA bring native libraries for every CPU type (about 40 MB of the ~55 MB APK; they are stored uncompressed so they load with 16 KB memory pages).
