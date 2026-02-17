#!/usr/bin/env python3
"""
Neighborhood Intel Station - Backend Server
Runs on any machine on the local network.
Provides REST API for:
  - Pushing images to e-Paper display via SSH/SCP
  - SDR node status and satellite capture log
  - ISS position and pass predictions
  - Aircraft tracking via ADS-B Exchange API (until local SDR is ready)
"""

import http.server
import json
import subprocess
import os
import time
import threading
import urllib.request
import math
import tempfile
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("[!] Pillow not installed. Run: pip install Pillow")
    print("    e-Paper image generation will be disabled.")

# ============================================
# CONFIGURATION
# ============================================
CONFIG = {
    'port': 5000,
    'sdr_node': {'host': '192.168.1.192', 'user': 'mem'},
    'epaper_node': {'host': '192.168.1.220', 'user': 'epaper'},
    'location': {'lat': 29.4953, 'lon': -95.1547, 'alt': 15.0},
    'weather': {
        'api_key': 'ea6f024843dd42c39e23c3484016fdafd203909dae1a40e5811aa1db33f2bc7b',
        'app_key': 'dea6391c2ada481389e3d7eec5d3598f2c8da4d8a19c48bda824b8b40c0c9489'
    }
}

# Shared state
state = {
    'sdr_status': 'unknown',
    'sdr_log': [],
    'iss': {'lat': 0, 'lon': 0, 'alt': 0, 'velocity': 0, 'visibility': '', 'timestamp': 0},
    'iss_crew': [],
    'iss_passes': [],
    'aircraft': [],
    'last_update': {}
}


# ============================================
# ISS TRACKING
# ============================================
def update_iss_position():
    """Fetch current ISS position from Open Notify API"""
    try:
        req = urllib.request.Request('http://api.open-notify.org/iss-now.json')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data['message'] == 'success':
                state['iss']['lat'] = float(data['iss_position']['latitude'])
                state['iss']['lon'] = float(data['iss_position']['longitude'])
                state['iss']['timestamp'] = data['timestamp']
                state['last_update']['iss_position'] = time.time()
    except Exception as e:
        print(f"ISS position error: {e}")


def update_iss_crew():
    """Fetch current ISS crew from Open Notify API"""
    try:
        req = urllib.request.Request('http://api.open-notify.org/astros.json')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data['message'] == 'success':
                state['iss_crew'] = [
                    p for p in data['people'] if p['craft'] == 'ISS'
                ]
                state['last_update']['iss_crew'] = time.time()
    except Exception as e:
        print(f"ISS crew error: {e}")


def update_iss_passes():
    """Predict ISS visible passes for our location"""
    try:
        lat = CONFIG['location']['lat']
        lon = CONFIG['location']['lon']
        alt = CONFIG['location']['alt']
        url = f'http://api.open-notify.org/iss-pass.json?lat={lat}&lon={lon}&alt={alt}&n=5'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data['message'] == 'success':
                state['iss_passes'] = data['response']
                state['last_update']['iss_passes'] = time.time()
    except Exception as e:
        print(f"ISS passes error: {e}")


def calculate_iss_distance():
    """Calculate distance from our location to ISS ground track"""
    lat1 = math.radians(CONFIG['location']['lat'])
    lon1 = math.radians(CONFIG['location']['lon'])
    lat2 = math.radians(state['iss']['lat'])
    lon2 = math.radians(state['iss']['lon'])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return 6371 * c  # km


# ============================================
# SDR NODE STATUS
# ============================================
def update_sdr_status():
    """Check SDR node and get capture log"""
    try:
        host = CONFIG['sdr_node']['host']
        user = CONFIG['sdr_node']['user']
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=3', '-o', 'StrictHostKeyChecking=no',
             f'{user}@{host}', 'tail -10 ~/noaa_capture.log 2>/dev/null; echo "---SDR_STATUS---"; ps aux | grep noaa_capture | grep -v grep | wc -l'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            parts = result.stdout.split('---SDR_STATUS---')
            log_lines = parts[0].strip().split('\n') if parts[0].strip() else []
            running = int(parts[1].strip()) if len(parts) > 1 else 0

            state['sdr_log'] = log_lines[-10:]

            # Determine status from log
            if running > 0:
                last_line = log_lines[-1] if log_lines else ''
                if 'Recording' in last_line:
                    state['sdr_status'] = 'recording'
                elif 'Sleeping' in last_line:
                    state['sdr_status'] = 'sleeping'
                elif 'Starting capture' in last_line:
                    state['sdr_status'] = 'armed'
                elif 'Waiting' in last_line:
                    state['sdr_status'] = 'armed'
                else:
                    state['sdr_status'] = 'running'
            else:
                state['sdr_status'] = 'offline'

            state['last_update']['sdr'] = time.time()
    except Exception as e:
        state['sdr_status'] = 'unreachable'
        print(f"SDR status error: {e}")


# ============================================
# WEATHER DATA & IMAGE GENERATION
# ============================================
def fetch_weather_data():
    """Fetch current weather from Ambient Weather API"""
    try:
        api_key = CONFIG['weather']['api_key']
        app_key = CONFIG['weather']['app_key']
        url = f'https://rt.ambientweather.net/v1/devices?apiKey={api_key}&applicationKey={app_key}'
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'NIS/1.0')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data and len(data) > 0:
                return data[0].get('lastData', {})
    except Exception as e:
        print(f"Weather fetch error: {e}")
    return None


def generate_weather_image(weather_data=None):
    """Generate an 800x480 weather image for the Waveshare 7.3in 6-color e-Paper"""
    if not HAS_PIL:
        return None

    if weather_data is None:
        weather_data = fetch_weather_data()
    if weather_data is None:
        return None

    # 7.3" e-Paper resolution
    W, H = 800, 480

    # 6-color palette
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    RED = (255, 0, 0)
    GREEN = (0, 255, 0)
    BLUE = (0, 0, 255)
    YELLOW = (255, 255, 0)

    img = Image.new('RGB', (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    # Try to load fonts, fall back to default
    def load_font(size):
        for path in [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'C:/Windows/Fonts/consola.ttf',
            'C:/Windows/Fonts/arial.ttf',
            'C:/Windows/Fonts/consolab.ttf',
        ]:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()

    font_huge = load_font(72)
    font_large = load_font(36)
    font_med = load_font(24)
    font_small = load_font(18)
    font_tiny = load_font(14)

    # Extract weather values with safe defaults
    temp_f = weather_data.get('tempf', '--')
    feels_like = weather_data.get('feelsLike', '--')
    humidity = weather_data.get('humidity', '--')
    humidity_out = weather_data.get('humidityin', humidity)
    wind_mph = weather_data.get('windspeedmph', 0)
    wind_gust = weather_data.get('windgustmph', 0)
    wind_dir = weather_data.get('winddir', 0)
    pressure_in = weather_data.get('baromrelin', '--')
    pressure_abs = weather_data.get('baromabsin', '--')
    rain_daily = weather_data.get('dailyrainin', 0)
    rain_rate = weather_data.get('hourlyrainin', 0)
    uv = weather_data.get('uv', 0)
    solar_rad = weather_data.get('solarradiation', 0)
    temp_inside = weather_data.get('tempinf', '--')
    humidity_in = weather_data.get('humidityin', '--')
    dew_point = weather_data.get('dewPoint', '--')

    # Wind direction to compass
    directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    wind_compass = directions[int((wind_dir + 11.25) / 22.5) % 16] if isinstance(wind_dir, (int, float)) else '--'

    # Timestamp
    date_str = weather_data.get('date', '')
    if date_str:
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            cst = dt - timedelta(hours=6)
            time_str = cst.strftime('%I:%M %p CST')
            date_display = cst.strftime('%a %b %d, %Y')
        except Exception:
            time_str = datetime.now().strftime('%I:%M %p')
            date_display = datetime.now().strftime('%a %b %d, %Y')
    else:
        time_str = datetime.now().strftime('%I:%M %p')
        date_display = datetime.now().strftime('%a %b %d, %Y')

    # ---- HEADER BAR ----
    draw.rectangle([0, 0, W, 52], fill=BLACK)
    draw.text((12, 8), "NEIGHBORHOOD INTEL STATION", font=font_med, fill=WHITE)
    draw.text((W - 12, 8), time_str, font=font_med, fill=YELLOW, anchor='ra')

    # Date below header
    draw.text((12, 56), date_display, font=font_small, fill=BLACK)
    draw.text((W - 12, 56), "WS-2902 WEATHER", font=font_small, fill=BLUE, anchor='ra')

    # ---- MAIN TEMP (big, left side) ----
    temp_str = f"{temp_f}" if isinstance(temp_f, (int, float)) else str(temp_f)
    draw.text((30, 85), temp_str, font=font_huge, fill=BLACK)
    # Degree symbol and F
    bbox = draw.textbbox((30, 85), temp_str, font=font_huge)
    draw.text((bbox[2] + 4, 88), "°F", font=font_large, fill=BLACK)

    # Feels like
    feels_str = f"Feels like {feels_like}°F" if isinstance(feels_like, (int, float)) else "Feels like --"
    draw.text((34, 165), feels_str, font=font_small, fill=RED if isinstance(feels_like, (int, float)) and feels_like > 90 else BLACK)

    # ---- HUMIDITY & DEW POINT (right of temp) ----
    col2_x = 320
    draw.text((col2_x, 95), f"Humidity", font=font_small, fill=BLUE)
    draw.text((col2_x, 118), f"{humidity}%", font=font_large, fill=BLACK)

    draw.text((col2_x, 158), f"Dew Point: {dew_point}°F", font=font_small, fill=BLACK)

    # ---- DIVIDER LINE ----
    draw.line([(12, 192), (W - 12, 192)], fill=BLACK, width=2)

    # ---- WIND SECTION ----
    y_wind = 200
    draw.text((20, y_wind), "WIND", font=font_med, fill=BLUE)
    draw.text((20, y_wind + 30), f"{wind_mph} mph {wind_compass}", font=font_large, fill=BLACK)
    draw.text((20, y_wind + 70), f"Gusts: {wind_gust} mph", font=font_small, fill=RED if isinstance(wind_gust, (int, float)) and wind_gust > 20 else BLACK)

    # ---- PRESSURE SECTION ----
    col2_x = 300
    draw.text((col2_x, y_wind), "PRESSURE", font=font_med, fill=BLUE)
    press_str = f"{pressure_in} inHg" if isinstance(pressure_in, (int, float)) else str(pressure_in)
    draw.text((col2_x, y_wind + 30), press_str, font=font_large, fill=BLACK)

    # Pressure trend indicator
    if isinstance(pressure_in, (int, float)):
        if pressure_in > 30.1:
            trend = "HIGH"
            trend_color = GREEN
        elif pressure_in < 29.8:
            trend = "LOW"
            trend_color = RED
        else:
            trend = "NORMAL"
            trend_color = BLACK
        draw.text((col2_x, y_wind + 70), trend, font=font_small, fill=trend_color)

    # ---- RAIN SECTION ----
    col3_x = 570
    draw.text((col3_x, y_wind), "RAIN", font=font_med, fill=BLUE)
    draw.text((col3_x, y_wind + 30), f"{rain_daily}\"", font=font_large, fill=BLACK)
    rate_color = RED if isinstance(rain_rate, (int, float)) and rain_rate > 0 else BLACK
    draw.text((col3_x, y_wind + 70), f"Rate: {rain_rate}\"/hr", font=font_small, fill=rate_color)

    # ---- DIVIDER LINE ----
    draw.line([(12, 305), (W - 12, 305)], fill=BLACK, width=2)

    # ---- BOTTOM ROW: UV / Solar / Indoor ----
    y_bot = 315
    # UV Index
    draw.text((20, y_bot), "UV INDEX", font=font_med, fill=BLUE)
    uv_val = uv if isinstance(uv, (int, float)) else 0
    if uv_val >= 8:
        uv_color = RED
        uv_label = "Very High"
    elif uv_val >= 6:
        uv_color = RED
        uv_label = "High"
    elif uv_val >= 3:
        uv_color = YELLOW
        uv_label = "Moderate"
    else:
        uv_color = GREEN
        uv_label = "Low"
    draw.text((20, y_bot + 28), f"{uv}", font=font_large, fill=uv_color)
    draw.text((80, y_bot + 35), uv_label, font=font_small, fill=uv_color)

    # Solar Radiation
    draw.text((250, y_bot), "SOLAR", font=font_med, fill=BLUE)
    draw.text((250, y_bot + 28), f"{solar_rad}", font=font_large, fill=BLACK)
    draw.text((250, y_bot + 68), "W/m²", font=font_small, fill=BLACK)

    # Indoor conditions
    draw.text((450, y_bot), "INDOOR", font=font_med, fill=BLUE)
    draw.text((450, y_bot + 28), f"{temp_inside}°F", font=font_large, fill=BLACK)
    draw.text((450, y_bot + 68), f"Humidity: {humidity_in}%", font=font_small, fill=BLACK)

    # ---- FOOTER BAR ----
    draw.rectangle([0, H - 38, W, H], fill=BLACK)
    draw.text((12, H - 32), "NIS WEATHER", font=font_small, fill=GREEN)
    draw.text((W - 12, H - 32), "LEAGUE CITY, TX", font=font_small, fill=WHITE, anchor='ra')

    # ---- UV BAR GRAPH ----
    bar_x = 20
    bar_y = y_bot + 72
    bar_w = 180
    bar_h = 12
    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=BLACK)
    fill_w = min(int((uv_val / 11) * bar_w), bar_w)
    if fill_w > 0:
        draw.rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], fill=uv_color)

    # Save to temp file
    tmp_path = os.path.join(tempfile.gettempdir(), 'nis_weather.png')
    img.save(tmp_path, 'PNG')
    print(f"[+] Weather image generated: {tmp_path}")
    return tmp_path


def generate_dashboard_image():
    """Generate an 800x480 dashboard summary image for the e-Paper"""
    if not HAS_PIL:
        return None

    W, H = 800, 480
    BLACK = (0, 0, 0); WHITE = (255, 255, 255); RED = (255, 0, 0)
    GREEN = (0, 255, 0); BLUE = (0, 0, 255); YELLOW = (255, 255, 0)

    img = Image.new('RGB', (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    def load_font(size):
        for path in [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            'C:/Windows/Fonts/consola.ttf',
            'C:/Windows/Fonts/arial.ttf',
        ]:
            try: return ImageFont.truetype(path, size)
            except: continue
        return ImageFont.load_default()

    font_huge = load_font(48)
    font_large = load_font(32)
    font_med = load_font(22)
    font_small = load_font(16)
    font_tiny = load_font(13)

    now = datetime.now()
    time_str = now.strftime('%I:%M %p')
    date_str = now.strftime('%a %b %d, %Y')

    # ---- HEADER ----
    draw.rectangle([0, 0, W, 48], fill=BLACK)
    draw.text((12, 7), "NIS DASHBOARD", font=font_med, fill=GREEN)
    draw.text((W - 12, 7), time_str, font=font_med, fill=YELLOW, anchor='ra')

    draw.text((12, 52), date_str, font=font_small, fill=BLACK)
    draw.text((W - 12, 52), "LEAGUE CITY, TX", font=font_small, fill=BLUE, anchor='ra')

    # ---- WEATHER PANEL (top left) ----
    panel_y = 78
    draw.rectangle([10, panel_y, 390, panel_y + 130], outline=BLACK, width=2)
    draw.rectangle([10, panel_y, 390, panel_y + 24], fill=BLUE)
    draw.text((16, panel_y + 2), "WEATHER", font=font_small, fill=WHITE)

    weather = fetch_weather_data()
    if weather:
        temp = weather.get('tempf', '--')
        humid = weather.get('humidity', '--')
        wind = weather.get('windspeedmph', '--')
        wind_dir_val = weather.get('winddir', 0)
        directions = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW']
        wc = directions[int((wind_dir_val + 11.25) / 22.5) % 16] if isinstance(wind_dir_val, (int, float)) else ''
        pressure = weather.get('baromrelin', '--')
        rain = weather.get('dailyrainin', 0)

        draw.text((20, panel_y + 30), f"{temp}°F", font=font_huge, fill=BLACK)
        draw.text((220, panel_y + 32), f"Humidity: {humid}%", font=font_small, fill=BLACK)
        draw.text((220, panel_y + 52), f"Wind: {wind} mph {wc}", font=font_small, fill=BLACK)
        draw.text((220, panel_y + 72), f"Pressure: {pressure} inHg", font=font_small, fill=BLACK)
        draw.text((220, panel_y + 92), f"Rain: {rain}\"", font=font_small, fill=RED if isinstance(rain, (int, float)) and rain > 0 else BLACK)
    else:
        draw.text((20, panel_y + 50), "No data", font=font_large, fill=RED)

    # ---- ISS PANEL (top right) ----
    draw.rectangle([400, panel_y, 790, panel_y + 130], outline=BLACK, width=2)
    draw.rectangle([400, panel_y, 790, panel_y + 24], fill=BLUE)
    draw.text((406, panel_y + 2), "ISS TRACKER", font=font_small, fill=WHITE)

    iss = state['iss']
    dist_km = round(calculate_iss_distance(), 1)
    crew_count = len(state['iss_crew'])
    draw.text((410, panel_y + 30), f"Lat: {iss['lat']:.2f}", font=font_med, fill=BLACK)
    draw.text((410, panel_y + 56), f"Lon: {iss['lon']:.2f}", font=font_med, fill=BLACK)
    draw.text((620, panel_y + 30), f"{dist_km}", font=font_large, fill=BLACK)
    draw.text((620, panel_y + 66), "km away", font=font_tiny, fill=BLACK)
    draw.text((410, panel_y + 90), f"Crew: {crew_count} aboard", font=font_small, fill=BLACK)

    # ---- SDR / SATELLITE PANEL (middle left) ----
    panel_y2 = 218
    draw.rectangle([10, panel_y2, 390, panel_y2 + 110], outline=BLACK, width=2)
    draw.rectangle([10, panel_y2, 390, panel_y2 + 24], fill=BLUE)
    draw.text((16, panel_y2 + 2), "SDR / SATELLITE", font=font_small, fill=WHITE)

    sdr_status = state['sdr_status'].upper()
    if sdr_status in ['RECORDING']:
        sdr_color = RED
    elif sdr_status in ['ARMED', 'RUNNING']:
        sdr_color = GREEN
    else:
        sdr_color = BLACK
    draw.text((20, panel_y2 + 32), f"Status: {sdr_status}", font=font_med, fill=sdr_color)
    draw.text((20, panel_y2 + 60), "RTL-SDR Blog V4", font=font_small, fill=BLACK)
    draw.text((20, panel_y2 + 80), "V-Dipole Antenna", font=font_small, fill=BLACK)

    # Last log entry
    if state['sdr_log']:
        last_log = state['sdr_log'][-1][:45]
        draw.text((20, panel_y2 + 95), last_log, font=font_tiny, fill=BLACK)

    # ---- AIRSPACE PANEL (middle right) ----
    draw.rectangle([400, panel_y2, 790, panel_y2 + 110], outline=BLACK, width=2)
    draw.rectangle([400, panel_y2, 790, panel_y2 + 24], fill=BLUE)
    draw.text((406, panel_y2 + 2), "AIRSPACE", font=font_small, fill=WHITE)

    ac_count = len(state['aircraft'])
    draw.text((410, panel_y2 + 28), f"{ac_count}", font=font_huge, fill=BLACK)
    draw.text((490, panel_y2 + 45), "aircraft tracked", font=font_med, fill=BLACK)

    # Top callsigns
    top_ac = [a for a in state['aircraft'] if a.get('callsign')][:4]
    for i, ac in enumerate(top_ac):
        alt = ac.get('alt_ft', 0)
        draw.text((410, panel_y2 + 78 + i * 14), f"{ac['callsign']} {alt:,}ft", font=font_tiny, fill=BLACK)

    # ---- SYSTEM STATUS PANEL (bottom) ----
    panel_y3 = 338
    draw.rectangle([10, panel_y3, 790, panel_y3 + 95], outline=BLACK, width=2)
    draw.rectangle([10, panel_y3, 790, panel_y3 + 24], fill=BLUE)
    draw.text((16, panel_y3 + 2), "SYSTEM STATUS", font=font_small, fill=WHITE)

    # Node status indicators
    nodes = [
        ("Pi 5 SDR", "192.168.1.192", state['sdr_status'] != 'unreachable'),
        ("Pi Zero e-Paper", "192.168.1.220", True),  # We're pushing to it, so it's up
        ("Pi 5 Cyberdeck", "192.168.1.180", None),  # Unknown
        ("Backend", "192.168.1.45", True),
    ]
    x_pos = 20
    for name, ip, online in nodes:
        color = GREEN if online else (RED if online is False else YELLOW)
        label = "ON" if online else ("OFF" if online is False else "?")
        draw.rectangle([x_pos, panel_y3 + 32, x_pos + 10, panel_y3 + 42], fill=color)
        draw.text((x_pos + 14, panel_y3 + 30), f"{name}", font=font_small, fill=BLACK)
        draw.text((x_pos + 14, panel_y3 + 48), ip, font=font_tiny, fill=BLACK)
        x_pos += 190

    # Meshtastic
    draw.text((20, panel_y3 + 68), "Meshtastic: Danimal (Heltec LoRa V3)", font=font_tiny, fill=BLACK)
    draw.text((400, panel_y3 + 68), f"Last updated: {time_str}", font=font_tiny, fill=BLACK)

    # ---- FOOTER ----
    draw.rectangle([0, H - 32, W, H], fill=BLACK)
    draw.text((12, H - 27), "NEIGHBORHOOD INTEL STATION", font=font_small, fill=GREEN)
    draw.text((W - 12, H - 27), "github.com/danamald", font=font_small, fill=WHITE, anchor='ra')

    tmp_path = os.path.join(tempfile.gettempdir(), 'nis_dashboard.png')
    img.save(tmp_path, 'PNG')
    print(f"[+] Dashboard image generated: {tmp_path}")
    return tmp_path


# ============================================
# E-PAPER PUSH
# ============================================
def push_to_epaper(image_path):
    """SCP an image to the e-Paper node and trigger display"""
    try:
        host = CONFIG['epaper_node']['host']
        user = CONFIG['epaper_node']['user']

        # SCP the image
        result = subprocess.run(
            ['scp', '-o', 'StrictHostKeyChecking=no',
             image_path, f'{user}@{host}:~/incoming/pushed_image.png'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {'success': False, 'error': f'SCP failed: {result.stderr}'}

        # Trigger display
        result = subprocess.run(
            ['ssh', '-o', 'StrictHostKeyChecking=no',
             f'{user}@{host}',
             'sudo python3 ~/display_image.py ~/incoming/pushed_image.png'],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            return {'success': True, 'message': 'Image pushed to e-Paper'}
        else:
            return {'success': False, 'error': f'Display failed: {result.stderr}'}

    except Exception as e:
        return {'success': False, 'error': str(e)}


def push_satellite_image():
    """Get latest satellite image from SDR node and push to e-Paper"""
    try:
        host = CONFIG['sdr_node']['host']
        user = CONFIG['sdr_node']['user']

        # Find latest image
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
             f'{user}@{host}', 'ls -t ~/noaa_reception/images/*.png 2>/dev/null | head -1'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {'success': False, 'error': 'No satellite images found'}

        remote_path = result.stdout.strip()
        local_tmp = '/tmp/sat_image_latest.png'

        # Download from SDR node
        subprocess.run(
            ['scp', '-o', 'StrictHostKeyChecking=no',
             f'{user}@{host}:{remote_path}', local_tmp],
            capture_output=True, timeout=30
        )

        # Push to e-Paper
        return push_to_epaper(local_tmp)

    except Exception as e:
        return {'success': False, 'error': str(e)}


# ============================================
# AIRCRAFT TRACKING (API-based until local SDR)
# ============================================
def update_aircraft():
    """Fetch nearby aircraft from ADS-B Exchange or OpenSky"""
    try:
        lat = CONFIG['location']['lat']
        lon = CONFIG['location']['lon']
        # OpenSky Network API (free, no key required)
        # Bounding box: ~100nm around League City
        lamin = lat - 1.5
        lamax = lat + 1.5
        lomin = lon - 1.5
        lomax = lon + 1.5
        url = f'https://opensky-network.org/api/states/all?lamin={lamin}&lomin={lomin}&lamax={lamax}&lomax={lomax}'
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'NeighborhoodIntelStation/1.0')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            aircraft = []
            if data.get('states'):
                for s in data['states'][:50]:  # Limit to 50
                    if s[5] is not None and s[6] is not None:  # Has position
                        aircraft.append({
                            'icao24': s[0],
                            'callsign': (s[1] or '').strip(),
                            'country': s[2],
                            'lat': s[6],
                            'lon': s[5],
                            'alt_m': s[7] or s[13] or 0,
                            'alt_ft': int((s[7] or s[13] or 0) * 3.281),
                            'velocity_kt': int((s[9] or 0) * 1.944),
                            'heading': s[10] or 0,
                            'vertical_rate': s[11] or 0,
                            'on_ground': s[8],
                            'squawk': s[14]
                        })
            state['aircraft'] = aircraft
            state['last_update']['aircraft'] = time.time()
    except Exception as e:
        print(f"Aircraft error: {e}")


# ============================================
# BACKGROUND UPDATER
# ============================================
def background_updater():
    """Periodically update all data sources"""
    while True:
        try:
            update_iss_position()
            time.sleep(1)
            update_sdr_status()
            time.sleep(1)

            # Less frequent updates
            now = time.time()
            if now - state['last_update'].get('iss_crew', 0) > 600:  # Every 10 min
                update_iss_crew()
            if now - state['last_update'].get('iss_passes', 0) > 300:  # Every 5 min
                update_iss_passes()
            if now - state['last_update'].get('aircraft', 0) > 15:  # Every 15 sec
                update_aircraft()

            time.sleep(3)  # ISS position every ~5 sec total
        except Exception as e:
            print(f"Updater error: {e}")
            time.sleep(10)


# ============================================
# HTTP API SERVER
# ============================================
class APIHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/status':
            self.send_json({
                'sdr_status': state['sdr_status'],
                'sdr_log': state['sdr_log'],
                'iss': state['iss'],
                'iss_crew': state['iss_crew'],
                'iss_passes': state['iss_passes'],
                'iss_distance_km': round(calculate_iss_distance(), 1),
                'aircraft': state['aircraft'],
                'aircraft_count': len(state['aircraft']),
                'last_update': state['last_update'],
                'timestamp': time.time()
            })
        elif self.path == '/api/iss':
            self.send_json({
                'position': state['iss'],
                'crew': state['iss_crew'],
                'passes': state['iss_passes'],
                'distance_km': round(calculate_iss_distance(), 1)
            })
        elif self.path == '/api/aircraft':
            self.send_json({
                'aircraft': state['aircraft'],
                'count': len(state['aircraft']),
                'last_update': state['last_update'].get('aircraft', 0)
            })
        elif self.path == '/api/sdr':
            self.send_json({
                'status': state['sdr_status'],
                'log': state['sdr_log'],
                'last_update': state['last_update'].get('sdr', 0)
            })
        else:
            self.send_error(404, 'Not Found')

    def do_POST(self):
        if self.path == '/api/push/satellite':
            result = push_satellite_image()
            self.send_json(result)
        elif self.path == '/api/push/dashboard':
            img_path = generate_dashboard_image()
            if img_path is None:
                self.send_json({'success': False, 'error': 'Could not generate dashboard image (Pillow missing?)'})
                return
            result = push_to_epaper(img_path)
            self.send_json(result)
        elif self.path == '/api/push/weather':
            weather = fetch_weather_data()
            if weather is None:
                self.send_json({'success': False, 'error': 'Could not fetch weather data'})
                return
            img_path = generate_weather_image(weather)
            if img_path is None:
                self.send_json({'success': False, 'error': 'Could not generate weather image (Pillow missing?)'})
                return
            result = push_to_epaper(img_path)
            self.send_json(result)
        else:
            self.send_error(404, 'Not Found')

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging for cleaner output
        pass


# ============================================
# MAIN
# ============================================
def main():
    print("=" * 60)
    print("  NEIGHBORHOOD INTEL STATION - Backend Server")
    print("=" * 60)
    print(f"  API Port:     {CONFIG['port']}")
    print(f"  SDR Node:     {CONFIG['sdr_node']['user']}@{CONFIG['sdr_node']['host']}")
    print(f"  e-Paper Node: {CONFIG['epaper_node']['user']}@{CONFIG['epaper_node']['host']}")
    print(f"  Location:     {CONFIG['location']['lat']}, {CONFIG['location']['lon']}")
    print("=" * 60)
    print()

    # Start background updater
    updater = threading.Thread(target=background_updater, daemon=True)
    updater.start()
    print("[+] Background updater started")

    # Initial data fetch
    print("[+] Fetching initial data...")
    update_iss_position()
    update_iss_crew()
    print(f"    ISS: {state['iss']['lat']:.2f}, {state['iss']['lon']:.2f}")
    print(f"    ISS Crew: {len(state['iss_crew'])} aboard")

    # Start HTTP server
    server = HTTPServer(('0.0.0.0', CONFIG['port']), APIHandler)
    print(f"[+] API server running on http://0.0.0.0:{CONFIG['port']}")
    print()
    print("Endpoints:")
    print(f"  GET  /api/status    - Full system status")
    print(f"  GET  /api/iss       - ISS position, crew, passes")
    print(f"  GET  /api/aircraft  - Nearby aircraft")
    print(f"  GET  /api/sdr       - SDR node status and log")
    print(f"  POST /api/push/satellite  - Push sat image to e-Paper")
    print(f"  POST /api/push/dashboard  - Push dashboard to e-Paper")
    print(f"  POST /api/push/weather    - Push weather image to e-Paper")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == '__main__':
    main()
