from datetime import datetime
from typing import Any, Optional

import httpx

from app.config import settings
from app.models import Alert, BusDetour, Train


SEPTA_BASE = "https://www3.septa.org/api"


async def _get_json(path: str) -> Any:
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        r = await client.get(f"{SEPTA_BASE}{path}")
        r.raise_for_status()
        return r.json()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def fetch_alerts() -> list[Alert]:
    data = await _get_json("/Alerts/index.php")
    alerts: list[Alert] = []
    for raw in data or []:
        alerts.append(
            Alert(
                route_id=str(raw.get("route_id", "")),
                route_name=str(raw.get("route_name", "")),
                mode=str(raw.get("mode", "")),
                current_message=(raw.get("current_message") or "").strip(),
                advisory_message=(raw.get("advisory_message") or "").strip(),
                last_updated=_parse_dt(raw.get("last_updated")),
            )
        )
    return alerts


async def fetch_trains() -> list[Train]:
    data = await _get_json("/TrainView/index.php")
    return [Train.model_validate(raw) for raw in (data or [])]


async def fetch_bus_detours() -> list[BusDetour]:
    data = await _get_json("/BusDetours/index.php")
    detours: list[BusDetour] = []
    for block in data or []:
        route_id = str(block.get("route_id", ""))
        route_info = block.get("route_info") or []
        if not isinstance(route_info, list):
            continue
        for d in route_info:
            detours.append(
                BusDetour(
                    route_id=route_id,
                    route_name=str(d.get("route_info") or route_id),
                    reason=str(d.get("reason", "")),
                    start_location=str(d.get("detour_start_location", "")),
                    end_location=str(d.get("detour_end_location", "")),
                    start_date=(d.get("detour_start_date_time") or None),
                    end_date=(d.get("detour_end_date_time") or None),
                    current_message=str(d.get("current_message", "")),
                )
            )
    return detours
