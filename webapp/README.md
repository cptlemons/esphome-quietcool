# QuietCool Web Controller

A lightweight web app for controlling your QuietCool whole-house fan from any browser on your local network.

> **Note**: Your LilyGO board also hosts an on-device web UI directly at `http://192.168.50.114` (or `http://quietcool-lora32.local`) without needing this container running! This Docker container is an optional dedicated web UI for running on a NAS or server.

## Features
- Clean mobile-friendly dark theme with animated fan blades
- Controls: Fan On/Off, Speeds (Low, Medium, High), Run Timers (Continuous, 1h, 2h, 4h, 8h, 12h)
- Live status: Confirmation state, remaining timer countdown, Wi-Fi signal, remote ID
- Learn mode trigger button for pairing OEM remote
- Fast real-time WebSocket updates directly via ESPHome Native API (`aioesphomeapi`)

## Deploying on your NAS (Docker Compose)

1. Clone or copy this directory to your server (e.g. `~/quietcool-web` on `nardis`):
   ```bash
   git clone https://github.com/cptlemons/esphome-quietcool.git
   cd esphome-quietcool/webapp
   ```

2. Start the container:
   ```bash
   export ESPHOME_HOST=192.168.50.114
   export ESPHOME_API_KEY="<your-api-key-from-secrets.yaml>"
   docker compose up -d --build
   ```

3. Open `http://<nas-ip>:8080` in your browser.
