from fastapi import APIRouter, Query

from app.cache import cache
from app.clients import traffic as traffic_client
from app.config import settings
from app.models import TrafficEvent

router = APIRouter(prefix="/traffic", tags=["traffic"])


@router.get("", response_model=list[TrafficEvent])
async def get_traffic(
    lat: float = Query(default=settings.default_lat),
    lon: float = Query(default=settings.default_lon),
    radius_miles: float = Query(default=25.0, gt=0, le=200),
):
    key = f"traffic:{lat:.3f}:{lon:.3f}:{radius_miles}"
    return await cache.get_or_set(
        key,
        settings.cache_ttl_traffic,
        lambda: traffic_client.fetch_events(lat, lon, radius_miles),
    )
