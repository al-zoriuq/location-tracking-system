# Raspberry Pi (in-car traffic sign detector)

A Raspberry Pi Zero 2 W with a camera detects traffic signs and sends them to the server (UDP `5005`). It gets the location from the [GPSLink](../gpslink-android/) app over UDP (`5000`) and answers the app's buttons.

**The full code is not here.** `pipeline_pi.py`, `ocr_limite.py` and the `.eim` models live on the Pi, in `/home/gpslink/`. To copy them to a PC:

```bash
scp gpslink@<PI_IP>:~/pipeline_pi.py gpslink@<PI_IP>:~/ocr_limite.py .
```

This folder holds the scripts that patch and test that pipeline:

| File | Purpose |
|---|---|
| [`INSTRUCCIONES_PI.md`](INSTRUCCIONES_PI.md) | Step-by-step Pi setup (in Spanish) |
| `parche_celular.py` | Adds the `--celular` mode to `pipeline_pi.py` |
| `probar_celular.py` | Simulates the app: a position every 1 s, or one command |
| `detector.service` | systemd service so the detector starts on boot |
| `010-gpslink-shutdown` | sudoers rule for the shutdown button |

## Dual sending

```
GPSLink phone ──UDP 5000 (location every 1 s)───────────────► Server
      │  ▲                                                      ▲
      │  └── EST,... (reply to the buttons)                      │ UDP 5005 (signs only)
      └──UDP 5000 (location + CMD,...)──► Raspberry Pi ──────────┘
```

The route is always sent by the app; the Pi only adds the signs, using the phone's Device (`--device-celular`) so that on the web page they land on that car's route.
