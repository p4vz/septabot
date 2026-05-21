from fastapi import APIRouter, Query

from app.cache import cache
from app.clients import weather as weather_client
from app.config import settings
from app.models import WeatherSummary

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("", response_model=WeatherSummary)
async def get_weather(
    lat: float = Query(default=settings.default_lat),
    lon: float = Query(default=settings.default_lon),
    hourly: bool = Query(default=False, description="Use hourly forecast periods"),
):
    key = f"weather:{lat:.3f}:{lon:.3f}:{hourly}"
    return await cache.get_or_set(
        key,
        settings.cache_ttl_weather,
        lambda: weather_client.fetch_forecast(lat, lon, hourly=hourly),
    )
