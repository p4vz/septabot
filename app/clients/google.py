"""Google Maps Directions client.

Used for traffic-aware driving ETAs (/route/drive) and SEPTA-aware
multi-leg transit routing (/route/transit). SEPTA's GTFS is published to
Google Transit, so transit mode returns walk + bus + train legs with live
schedules and transfer info.
"""
from __future__ import annotations

import html
import re
from typing import Any, Optional

import httpx

from app.config import settings
from app.models import RouteLeg, RouteResult, RouteStep


DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    """Google returns html_instructions with <b>, <div>, etc. The bot wants plain text."""
    return html.unescape(_TAG_RE.sub(" ", s or "")).strip()


def _get(d: Any, *keys: str, default: Any = None) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur if cur is not None else default


def _parse_step(raw: dict) -> RouteStep:
    transit = raw.get("transit_details") or {}
    line = transit.get("line") or {}
    vehicle = (line.get("vehicle") or {}).get("type")
    return RouteStep(
        mode=raw.get("travel_mode", ""),
        instruction=_strip_html(raw.get("html_instructions", "")),
        distance_meters=_get(raw, "distance", "value", default=0) or 0,
        duration_seconds=_get(raw, "duration", "value", default=0) or 0,
        transit_line=line.get("name"),
        transit_short_name=line.get("short_name"),
        transit_vehicle=vehicle,
        transit_headsign=transit.get("headsign"),
        transit_num_stops=transit.get("num_stops"),
        departure_stop=_get(transit, "departure_stop", "name"),
        arrival_stop=_get(transit, "arrival_stop", "name"),
        departure_time=_get(transit, "departure_time", "text"),
        arrival_time=_get(transit, "arrival_time", "text"),
    )


def _parse_leg(raw: dict) -> RouteLeg:
    steps = [_parse_step(s) for s in raw.get("steps", [])]
    return RouteLeg(
        start_address=raw.get("start_address", ""),
        end_address=raw.get("end_address", ""),
        distance_meters=_get(raw, "distance", "value", default=0) or 0,
        duration_seconds=_get(raw, "duration", "value", default=0) or 0,
        duration_in_traffic_seconds=_get(raw, "duration_in_traffic", "value"),
        departure_time=_get(raw, "departure_time", "text"),
        arrival_time=_get(raw, "arrival_time", "text"),
        steps=steps,
    )


async def fetch_directions(
    origin: str,
    destination: str,
    mode: str = "driving",
    departure_time: Optional[str] = None,
    arrival_time: Optional[str] = None,
) -> RouteResult:
    """Fetch a route from Google Directions.

    `mode` is 'driving' or 'transit'. For driving, `departure_time` defaults
    to 'now' so the response includes duration_in_traffic. For transit, you
    can pass `departure_time` (epoch seconds or 'now') or `arrival_time`
    (epoch seconds) — not both.
    """
    if not settings.google_maps_api_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured")
    if mode not in ("driving", "transit"):
        raise ValueError(f"unsupported mode: {mode}")
    if departure_time and arrival_time:
        raise ValueError("departure_time and arrival_time are mutually exclusive")

    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "key": settings.google_maps_api_key,
    }
    if mode == "driving":
        params["departure_time"] = departure_time or "now"
    elif mode == "transit":
        params["transit_mode"] = "rail|bus|subway"
        if departure_time:
            params["departure_time"] = departure_time
        if arrival_time:
            params["arrival_time"] = arrival_time

    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        r = await client.get(DIRECTIONS_URL, params=params)
        r.raise_for_status()
        data = r.json()

    status = data.get("status")
    if status != "OK":
        msg = data.get("error_message") or status or "unknown"
        raise RuntimeError(f"Google Directions returned {status}: {msg}")

    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError("Google Directions returned no routes")

    route = routes[0]
    legs = [_parse_leg(leg) for leg in route.get("legs", [])]
    total_dist = sum(l.distance_meters for l in legs)
    total_dur = sum(l.duration_seconds for l in legs)
    traffic_durs = [l.duration_in_traffic_seconds for l in legs if l.duration_in_traffic_seconds]
    total_dur_traffic = sum(traffic_durs) if traffic_durs else None

    fare_raw = route.get("fare") or {}
    fare = (
        {"currency": fare_raw["currency"], "value": fare_raw["value"]}
        if fare_raw.get("currency") and fare_raw.get("value") is not None
        else None
    )

    return RouteResult(
        mode=mode,
        summary=route.get("summary", ""),
        warnings=list(route.get("warnings", []) or []),
        legs=legs,
        total_distance_meters=total_dist,
        total_duration_seconds=total_dur,
        total_duration_in_traffic_seconds=total_dur_traffic,
        polyline=_get(route, "overview_polyline", "points"),
        fare=fare,
    )
