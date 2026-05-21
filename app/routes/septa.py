from typing import Optional

from fastapi import APIRouter, Query

from app.cache import cache
from app.clients import septa as septa_client
from app.config import settings
from app.models import Alert, BusDetour, Train

router = APIRouter(prefix="/septa", tags=["septa"])


@router.get("/alerts", response_model=list[Alert])
async def get_alerts(
    mode: Optional[str] = Query(default=None, description="Filter by mode (e.g. bus, rail, trolley)"),
    route: Optional[str] = Query(default=None, description="Filter by exact route id"),
):
    alerts = await cache.get_or_set(
        "septa:alerts", settings.cache_ttl_alerts, septa_client.fetch_alerts
    )
    if mode:
        m = mode.lower()
        alerts = [a for a in alerts if a.mode.lower() == m]
    if route:
        alerts = [a for a in alerts if a.route_id == route]
    return alerts


@router.get("/trains", response_model=list[Train])
async def get_trains(
    line: Optional[str] = Query(default=None, description="Filter by line name"),
    min_late: int = Query(default=0, ge=0, description="Only return trains at least N minutes late"),
):
    trains = await cache.get_or_set(
        "septa:trains", settings.cache_ttl_trains, septa_client.fetch_trains
    )
    out = trains
    if line:
        out = [t for t in out if t.line.lower() == line.lower()]
    if min_late > 0:
        out = [t for t in out if t.late_minutes >= min_late]
    return out


@router.get("/bus-detours", response_model=list[BusDetour])
async def get_bus_detours(route: Optional[str] = Query(default=None)):
    detours = await cache.get_or_set(
        "septa:bus-detours", settings.cache_ttl_alerts, septa_client.fetch_bus_detours
    )
    if route:
        detours = [d for d in detours if d.route_id == route]
    return detours
