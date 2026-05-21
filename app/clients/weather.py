from datetime import datetime
from typing import Optional

import httpx

from app.config import settings
from app.models import WeatherPeriod, WeatherSummary


NWS_BASE = "https://api.weather.gov"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.http_timeout,
        headers={
            "User-Agent": settings.nws_user_agent,
            "Accept": "application/geo+json",
        },
    )


def _parse_period(p: dict) -> WeatherPeriod:
    pop = (p.get("probabilityOfPrecipitation") or {}).get("value")
    return WeatherPeriod(
        name=p["name"],
        start_time=datetime.fromisoformat(p["startTime"]),
        end_time=datetime.fromisoformat(p["endTime"]),
        temperature=p["temperature"],
        temperature_unit=p["temperatureUnit"],
        wind=f"{p.get('windSpeed', '')} {p.get('windDirection', '')}".strip(),
        short_forecast=p.get("shortForecast", ""),
        detailed_forecast=p.get("detailedForecast", ""),
        precipitation_probability=pop,
    )


async def fetch_forecast(lat: float, lon: float, hourly: bool = False) -> WeatherSummary:
    async with _client() as client:
        point = await client.get(f"{NWS_BASE}/points/{lat:.4f},{lon:.4f}")
        point.raise_for_status()
        props = point.json()["properties"]
        forecast_url = props["forecastHourly"] if hourly else props["forecast"]
        fc = await client.get(forecast_url)
        fc.raise_for_status()
        periods = fc.json()["properties"]["periods"]

    parsed = [_parse_period(p) for p in periods[:6]]
    rel: Optional[dict] = (props.get("relativeLocation") or {}).get("properties")
    return WeatherSummary(
        location={
            "lat": lat,
            "lon": lon,
            "city": (rel or {}).get("city"),
            "state": (rel or {}).get("state"),
            "office": props.get("cwa"),
        },
        current=parsed[0] if parsed else None,
        upcoming=parsed[1:],
    )
