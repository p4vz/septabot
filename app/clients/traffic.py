import math
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.config import settings
from app.models import TrafficEvent


PA511_EVENTS_URL = "https://www.511pa.com/api/v2/get/event"


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613
    p = math.pi / 180
    a = (
        0.5
        - math.cos((lat2 - lat1) * p) / 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def _maybe_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _maybe_dt(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        ts = v / 1000 if v > 10**10 else v
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(v, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
            try:
                return datetime.strptime(v, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


async def fetch_events(
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_miles: float = 25.0,
) -> list[TrafficEvent]:
    if not settings.pa511_api_key:
        return []

    params = {"key": settings.pa511_api_key, "format": "json"}
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        r = await client.get(PA511_EVENTS_URL, params=params)
        r.raise_for_status()
        data = r.json()

    events: list[TrafficEvent] = []
    for raw in data or []:
        e_lat = _maybe_float(raw.get("Latitude") or raw.get("latitude"))
        e_lon = _maybe_float(raw.get("Longitude") or raw.get("longitude"))
        if lat is not None and lon is not None and e_lat is not None and e_lon is not None:
            if _haversine_miles(lat, lon, e_lat, e_lon) > radius_miles:
                continue
        events.append(
            TrafficEvent(
                id=str(raw.get("ID") or raw.get("id") or ""),
                type=str(raw.get("EventType") or raw.get("type") or ""),
                severity=str(raw.get("Severity") or "unknown"),
                headline=str(raw.get("EventDescription") or raw.get("Description") or ""),
                description=str(raw.get("Comments") or raw.get("FullDescription") or ""),
                roadway=str(raw.get("RoadwayName") or raw.get("Roadway") or ""),
                direction=str(raw.get("DirectionOfTravel") or raw.get("Direction") or ""),
                lat=e_lat,
                lon=e_lon,
                start_time=_maybe_dt(raw.get("StartDate") or raw.get("Start")),
                last_updated=_maybe_dt(raw.get("LastUpdate") or raw.get("Updated")),
            )
        )
    return events
