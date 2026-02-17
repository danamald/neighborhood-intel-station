# Neighborhood Intel Station (NIS)

A real-time neighborhood monitoring dashboard combining weather data, satellite tracking, aircraft surveillance, mesh networking, and NOAA satellite imagery — all displayed on a cyberpunk-themed web dashboard and a Waveshare 7.3" 6-color e-Paper display.

![Dashboard](https://img.shields.io/badge/Status-Operational-brightgreen) ![License](https://img.shields.io/badge/License-MIT-blue)

## Features

- **🛰 NOAA Satellite Reception** — Automated capture and decode of NOAA 15/18/19 APT imagery via RTL-SDR
- **🌤 Weather Station** — Live data from Ambient Weather WS-2902 (temp, humidity, wind, pressure, UV, solar radiation)
- **✈ Airspace Tracking** — Real-time aircraft monitoring via OpenSky Network API
- **🛸 ISS Tracker** — Live ISS position, distance, crew info, and overhead alerts
- **📡 Meshtastic Mesh** — LoRa mesh network status (Heltec V4)
- **🖥 e-Paper Display** — Push weather, dashboard, satellite images, or photo slideshow to Waveshare 7.3" 6-color display
- **📸 Random Slideshow** — Cycle through personal photos on the e-Paper every 3 minutes

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Windows PC     │────>│  Pi 5 SDR Node   │     │  Pi Zero 2W     │
│  192.168.1.45   │     │  192.168.1.192   │     │  192.168.1.220  │
│                 │     │                  │     │                 │
│  Backend :5000  │     │  RTL-SDR Blog V4 │     │  Waveshare 7.3" │
│  Dashboard HTML │     │  noaa_capture.py  │     │  e-Paper 6-color│
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │                                                ▲
        │            SCP + SSH                           │
        └────────────────────────────────────────────────┘
```

## Hardware

| Component | Details |
|-----------|---------|
| SDR | RTL-SDR Blog V4 (R828D tuner) |
| Antenna | V-Dipole 137MHz / Discone (wideband) |
| SDR Computer | Raspberry Pi 5 (8GB) + NVMe |
| Display | Waveshare 7.3" ACeP 6-Color e-Paper |
| Display Computer | Raspberry Pi Zero 2W |
| Weather | Ambient Weather WS-2902 |
| Mesh Radio | Heltec LoRa V3 "Danimal" |
| Cyberdeck | Raspberry Pi 5 + UPS HAT E |

## Files

| File | Description |
|------|-------------|
| `index.html` | Dashboard web interface (GitHub Pages site) |
| `intel_station_backend.py` | Python backend server — APIs, image generation, e-Paper push |
| `noaa_capture.py` | NOAA satellite auto-capture with debug logging |
| `NIS_Launch.bat` | Windows one-click launcher |
| `README.md` | This file |

## Quick Start

### 1. Install dependencies
```bash
pip install Pillow
```

### 2. Launch
Double-click `NIS_Launch.bat` or run:
```bash
python intel_station_backend.py
```
Then open the dashboard HTML in your browser.

### 3. SDR Node Setup (Pi 5)
```bash
sudo pip3 install ephem requests --break-system-packages
sudo apt install rtl-sdr sox
# Install noaa-apt from https://noaa-apt.mbernardi.com.ar/
python3 noaa_capture.py --schedule
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Full system status |
| GET | `/api/iss` | ISS position, crew, passes |
| GET | `/api/aircraft` | Nearby aircraft |
| GET | `/api/sdr` | SDR node status and log |
| POST | `/api/push/dashboard` | Push dashboard image to e-Paper |
| POST | `/api/push/weather` | Push weather image to e-Paper |
| POST | `/api/push/satellite` | Push latest satellite image to e-Paper |
| POST | `/api/push/random` | Toggle random photo slideshow |

## NOAA Capture System

The `noaa_capture.py` script runs as a systemd service on the SDR Pi:

- Predicts satellite passes using TLE orbital data
- Automatically wakes 2 minutes before each pass
- Captures signal via `rtl_fm`
- Decodes APT images using `noaa-apt`
- Debug logging with tags: `[SCHEDULER]`, `[PRE-CHECK]`, `[WAIT]`, `[CAPTURE]`, `[VALIDATE]`, `[PROCESS]`, `[EPAPER]`

## Live Dashboard

[https://danamald.github.io/neighborhood-intel-station/](https://danamald.github.io/neighborhood-intel-station/)

> Note: GitHub Pages version shows weather, ISS, and airspace via public APIs. E-Paper push and SDR features require the local backend.

## License

MIT
