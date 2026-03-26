"""Weather sync — local weather conditions for energy/mood correlation.

Fetches current weather from OpenWeatherMap (free tier) and writes
to rag-sources/weather/ as a markdown file with YAML frontmatter.

Barometric pressure, temperature, humidity, and cloud cover correlate
with ADHD energy and autism sensory sensitivity. This data feeds the
briefing agent and behavioral profiler.

No API key required for the free endpoint. Uses the operator's location
from the profile or a configured default.

Run: uv run python -m agents.weather_sync
Timer: hourly via systemd
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

RAG_DIR = Path.home() / "documents" / "rag-sources" / "weather"
CACHE_DIR = Path.home() / ".cache" / "weather-sync"

# OpenWeatherMap free tier — no API key needed for this endpoint
# Default coordinates (configurable via env vars)
DEFAULT_LAT = "44.98"
DEFAULT_LON = "-93.27"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_weather(lat: str = DEFAULT_LAT, lon: str = DEFAULT_LON) -> dict | None:
    """Fetch current weather from Open-Meteo (free, no API key)."""
    params = (
        f"?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        f"surface_pressure,cloud_cover,wind_speed_10m,weather_code"
        f"&temperature_unit=fahrenheit"
        f"&wind_speed_unit=mph"
        f"&timezone=auto"
    )
    url = WEATHER_URL + params

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hapax-council/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        log.error("Weather fetch failed: %s", e)
        return None


def _weather_code_to_description(code: int) -> str:
    """Convert WMO weather code to human-readable description."""
    codes = {
        0: "clear sky",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "fog",
        48: "rime fog",
        51: "light drizzle",
        53: "moderate drizzle",
        55: "dense drizzle",
        61: "slight rain",
        63: "moderate rain",
        65: "heavy rain",
        71: "slight snow",
        73: "moderate snow",
        75: "heavy snow",
        80: "slight rain showers",
        81: "moderate rain showers",
        82: "violent rain showers",
        95: "thunderstorm",
        96: "thunderstorm with slight hail",
        99: "thunderstorm with heavy hail",
    }
    return codes.get(code, f"code {code}")


def write_weather_doc(data: dict) -> Path | None:
    """Write weather data as a RAG-ingestible markdown document."""
    current = data.get("current", {})
    if not current:
        return None

    RAG_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d")
    hour_str = now.strftime("%H")

    temp = current.get("temperature_2m", "?")
    feels_like = current.get("apparent_temperature", "?")
    humidity = current.get("relative_humidity_2m", "?")
    pressure = current.get("surface_pressure", "?")
    clouds = current.get("cloud_cover", "?")
    wind = current.get("wind_speed_10m", "?")
    weather_code = current.get("weather_code", 0)
    description = _weather_code_to_description(weather_code)

    filename = f"weather-{date_str}-{hour_str}.md"
    path = RAG_DIR / filename

    frontmatter = {
        "source": "weather",
        "source_service": "weather",
        "source_platform": "open-meteo",
        "content_type": "weather_observation",
        "timestamp": now.isoformat(),
        "modality_tags": ["environmental", "temporal"],
        "temperature_f": temp,
        "feels_like_f": feels_like,
        "humidity_pct": humidity,
        "pressure_hpa": pressure,
        "cloud_cover_pct": clouds,
        "wind_mph": wind,
        "weather_code": weather_code,
        "description": description,
    }

    import yaml

    content = f"""---
{yaml.dump(frontmatter, default_flow_style=False).strip()}
---
# Weather — {date_str} {hour_str}:00

**Conditions:** {description}
**Temperature:** {temp}°F (feels like {feels_like}°F)
**Humidity:** {humidity}%
**Pressure:** {pressure} hPa
**Cloud cover:** {clouds}%
**Wind:** {wind} mph
"""

    path.write_text(content)
    log.info("Wrote weather doc: %s", path)
    return path


def sync() -> bool:
    """Fetch weather and write to rag-sources."""
    data = fetch_weather()
    if data is None:
        return False
    path = write_weather_doc(data)
    if path is not None:
        # Sensor protocol — write state + impingement
        import time

        from shared.sensor_protocol import emit_sensor_impingement, write_sensor_state

        current = data.get("current", {})
        write_sensor_state(
            "weather",
            {
                "temperature_f": current.get("temperature_2m"),
                "humidity_pct": current.get("relative_humidity_2m"),
                "pressure_hpa": current.get("surface_pressure"),
                "last_sync": time.time(),
            },
        )
        emit_sensor_impingement("weather", "temporal", ["weather_sync"])
    return path is not None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sync():
        print("Weather synced.")
    else:
        print("Weather sync failed.")
