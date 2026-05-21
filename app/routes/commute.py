import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query

from app.cache import cache
from app.clients import septa as septa_client
from app.clients import traffic as traffic_client
from app.clients import weather as weather_client
from app.config import settings
from app.models import CommuteSnapshot

router = APIRouter(tags=["commute"])


@router.get("/commute", response_model=CommuteSnapshot)
async def get_commute(
    lat: float = Query(default=settings.default_lat),
    lon: float = Query(default=settings.default_lon),
    line: Optional[str] = Query(default=None, description="Regional Rail line filter for delayed trains"),
    min_late: int = Query(default=5, ge=0, description="Minimum delay (minutes) to include a train"),
    radius_miles: float = Query(default=25.0, gt=0, le=200),
):
    alerts, trains, detours, weather, traffic = await asyncio.gather(
        cache.get_or_set("septa:alerts", settings.cache_ttl_alerts, septa_client.fetch_alerts),
        cache.get_or_set("septa:trains", settings.cache_ttl_trains, septa_client.fetch_trains),
        cache.get_or_set("septa:bus-detours", settings.cache_ttl_alerts, septa_client.fetch_bus_detours),
        cache.get_or_set(
            f"weather:{lat:.3f}:{lon:.3f}:False",
            settings.cache_ttl_weather,
            lambda: weather_client.fetch_forecast(lat, lon),
        ),
        cache.get_or_set(
            f"traffic:{lat:.3f}:{lon:.3f}:{radius_miles}",
            settings.cache_ttl_traffic,
            lambda: traffic_client.fetch_events(lat, lon, radius_miles),
        ),
        return_exceptions=True,
    )

    errors: dict[str, str] = {}

    def take(name: str, value, default):
        if isinstance(value, Exception):
            errors[name] = f"{type(value).__name__}: {value}"
            return default
        return value

    delays = take("trains", trains, [])
    if line:
        delays = [t for t in delays if t.line.lower() == line.lower()]
    delays = [t for t in delays if t.late_minutes >= min_late]

    return CommuteSnapshot(
        timestamp=datetime.now(timezone.utc),
        weather=take("weather", weather, None),
        septa_alerts=take("alerts", alerts, []),
        train_delays=delays,
        bus_detours=take("bus_detours", detours, []),
        traffic_events=take("traffic", traffic, []),
        errors=errors,
    )
