# neighborhood-intel-station
RF intelligence dashboard — NOAA satellite imagery, weather station, Meshtastic mesh, RF spectrum
[README.md](https://github.com/user-attachments/files/25353822/README.md)
# 🛰️ Neighborhood Intel Station (NIS)

A real-time intelligence dashboard that combines weather monitoring, satellite reception, aircraft tracking, ISS tracking, mesh networking, and e-Paper display — all running on a local network of Raspberry Pis, ESP32s, and SDR hardware.

**[Live Dashboard →](https://danamald.github.io/neighborhood-intel-station/)**

---

## What It Does

The NIS collects data from multiple sources and displays it on a browser-based dashboard with 7 panels:

- **NOAA Satellite** — Receives NOAA weather satellite passes via RTL-SDR, decodes APT signals, displays captured images with countdown to next pass
- **Weather Station** — Live data from an Ambient Weather WS-2902 (temperature, humidity, wind, pressure, rain, UV, solar radiation)
- **Airspace & ISS** — Real-time aircraft tracking via OpenSky Network with a canvas map of the Houston area, plus ISS position, distance, and crew info
- **Meshtastic** — LoRa mesh network status (Heltec V3 nodes)
- **E-Paper Display** — Push dashboard summaries, weather, or satellite images to a Waveshare 7.3" 6-color e-Paper display with one click
- **System Status** — Network node health for all Pis and services
- **Activity Log** — Live feed of all system events

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Windows PC                         │
│  ┌──────────────────────┐  ┌──────────────────────┐ │
│  │  Dashboard (HTML)     │  │  Backend (Python)     │ │
│  │  - Weather API        │  │  - HTTP API :5000     │ │
│  │  - Airspace map       │  │  - ISS tracking       │ │
│  │  - ISS tracker        │  │  - SDR status via SSH │ │
│  │  - Push buttons       │  │  - e-Paper push       │ │
│  └──────────┬───────────┘  │  - Aircraft data       │ │
│             │               └──────────┬────────────┘ │
└─────────────┼──────────────────────────┼──────────────┘
              │ fetch :5000              │ SSH/SCP
    ┌─────────┴─────────┬───────────────┼────────────┐
    │                   │               │            │
┌───▼───┐         ┌─────▼─────┐   ┌─────▼─────┐  ┌──▼──┐
│ Pi 5  │         │ Pi Zero   │   │ Pi 5      │  │ESP32│
│ SDR   │         │ e-Paper   │   │ Cyberdeck │  │Watch│
│.1.192 │         │ .1.220    │   │ .1.180    │  │     │
└───────┘         └───────────┘   └───────────┘  └─────┘
```

## Hardware

| Device | Role | IP | Details |
|--------|------|-----|---------|
| Windows PC | Dashboard + Backend | 192.168.1.45 | Runs browser dashboard and Python backend |
| Raspberry Pi 5 | SDR Node | 192.168.1.192 | NVMe boot, RTL-SDR Blog V4, V-dipole antenna |
| Raspberry Pi Zero 2W | e-Paper Display | 192.168.1.220 | Waveshare 7.3" 6-color (800×480) |
| Raspberry Pi 5 | Cyberdeck | 192.168.1.180 | UPS HAT E, portable build |
| ESP32-S3 | Round Watch | WiFi → cyberdeck:8888 | Round LCD gauges display |
| Heltec LoRa V3 | Meshtastic | LoRa mesh | Node name: "Danimal" |
| Ambient Weather WS-2902 | Weather Station | Cloud API | Temp, humidity, wind, pressure, rain, UV, solar |

## Files

| File | Description |
|------|-------------|
| `neighborhood-intel-station.html` | Main dashboard — single-file HTML/CSS/JS, runs locally or on GitHub Pages |
| `intel_station_backend.py` | Python backend server (port 5000) — ISS, aircraft, SDR status, e-Paper push |
| `NIS_Launch.bat` | Windows launcher — starts backend + opens dashboard with one double-click |

## Quick Start

### 1. Install Dependencies

```bash
pip install Pillow
```

### 2. Launch

Double-click `NIS_Launch.bat` on the desktop, or manually:

```bash
# Start the backend
python intel_station_backend.py

# Open the dashboard in a browser
# neighborhood-intel-station.html
```

### 3. Use

- The dashboard auto-connects to the backend and starts pulling live data
- Click **Push Dashboard**, **Push Sat Image**, or **Push Weather** to send images to the e-Paper
- Weather data updates every 5 minutes from the Ambient Weather API
- Aircraft and ISS update every few seconds when the backend is running

## Backend API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Full system status (SDR, ISS, aircraft, timestamps) |
| GET | `/api/iss` | ISS position, crew, passes, distance |
| GET | `/api/aircraft` | Nearby aircraft from OpenSky Network |
| GET | `/api/sdr` | SDR node status and capture log |
| POST | `/api/push/dashboard` | Generate dashboard summary image → e-Paper |
| POST | `/api/push/satellite` | Pull latest NOAA image from SDR node → e-Paper |
| POST | `/api/push/weather` | Generate weather image from WS-2902 data → e-Paper |

## E-Paper Display

The Waveshare 7.3" 6-color e-Paper supports black, white, red, green, blue, and yellow. The backend generates 800×480 images using Pillow and pushes them via SCP + SSH.

Three display modes:
- **Dashboard** — System overview with weather, ISS, SDR status, airspace, and node health
- **Weather** — Full weather station readout with temperature, wind, pressure, rain, UV, and indoor conditions
- **Satellite** — Latest NOAA APT satellite image capture

## NOAA Satellite Reception

The Pi 5 SDR node runs `noaa_capture.py` as a systemd service (`noaa-capture.service`) that automatically captures NOAA 15, 18, and 19 passes using an RTL-SDR Blog V4 dongle with a V-dipole antenna tuned to 137 MHz.

## Related Repos

- [noaa-satellite-receiver](https://github.com/danamald/noaa-satellite-receiver) — NOAA APT capture scripts for Raspberry Pi
- [waveshare-epaper-display](https://github.com/danamald/waveshare-epaper-display) — E-Paper display drivers and scripts
- [esp32s3-round-cyberdeck](https://github.com/danamald/esp32s3-round-cyberdeck) — ESP32-S3 round watch gauges for the cyberdeck

## Network Requirements

The dashboard and backend communicate over the local network. The e-Paper push buttons only work when accessed from the same LAN as the backend. The GitHub Pages version of the dashboard will display weather, ISS, and airspace data (via public APIs) but cannot push to local hardware.

## License

MIT

---

*Built in League City, TX with RTL-SDR, Raspberry Pi, LoRa, and too much coffee.*
