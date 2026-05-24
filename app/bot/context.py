"""Build a compact, token-efficient context object for Hermes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from app.cache import cache
from app.clients import google as google_client
from app.clients import septa as septa_client
from app.clients import traffic as traffic_client
from app.clients import weather as weather_client
from app.config import settings
from app.inference import build_disruption_report


MAX_ALERTS = 6
MAX_TRAINS = 8
MAX_DETOURS = 5
MAX_TRAFFIC = 6
MAX_ROUTE_STEPS = 4
MAX_DISRUPTION_LINES = 5


def _trim(s: str, n: int = 140) -> str:
    s = (s or "").strip().replace("\r", " ").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


async def _alerts() -> list[dict[str, Any]]:
    try:
        alerts = await cache.get_or_set(
            "septa:alerts", settings.cache_ttl_alerts, septa_client.fetch_alerts
        )
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for a in alerts:
        if not a.current_message:
            continue
        out.append(
            {
                "route": a.route_id,
                "mode": a.mode,
                "msg": _trim(a.current_message),
            }
        )
        if len(out) >= MAX_ALERTS:
            break
    return out


async def _trains() -> list[dict[str, Any]]:
    try:
        trains = await cache.get_or_set(
            "septa:trains", settings.cache_ttl_trains, septa_client.fetch_trains
        )
    except Exception:
        return []
    delayed = sorted(
        (t for t in trains if t.late_minutes >= 5),
        key=lambda t: t.late_minutes,
        reverse=True,
    )[:MAX_TRAINS]
    return [
        {
            "no": t.train_number,
            "line": t.line,
            "dest": t.destination,
            "next": t.next_stop,
            "late_min": t.late_minutes,
        }
        for t in delayed
    ]


async def _detours() -> list[dict[str, Any]]:
    try:
        detours = await cache.get_or_set(
            "septa:bus-detours", settings.cache_ttl_alerts, septa_client.fetch_bus_detours
        )
    except Exception:
        return []
    return [
        {
            "route": d.route_id,
            "reason": _trim(d.reason, 80),
            "where": _trim(f"{d.start_location} -> {d.end_location}", 120),
        }
        for d in detours[:MAX_DETOURS]
    ]


async def _weather(lat: float, lon: float) -> dict[str, Any] | None:
    try:
        w = await cache.get_or_set(
            f"weather:{lat:.3f}:{lon:.3f}:False",
            settings.cache_ttl_weather,
            lambda: weather_client.fetch_forecast(lat, lon),
        )
    except Exception:
        return None
    if not w.current:
        return None
    return {
        "now": {
            "when": w.current.name,
            "temp": f"{w.current.temperature}{w.current.temperature_unit}",
            "wind": w.current.wind,
            "summary": _trim(w.current.short_forecast, 60),
            "pop": w.current.precipitation_probability,
        },
        "next": [
            {
                "when": p.name,
                "temp": f"{p.temperature}{p.temperature_unit}",
                "summary": _trim(p.short_forecast, 60),
                "pop": p.precipitation_probability,
            }
            for p in w.upcoming[:2]
        ],
    }


async def _traffic(lat: float, lon: float) -> list[dict[str, Any]]:
    try:
        events = await cache.get_or_set(
            f"traffic:{lat:.3f}:{lon:.3f}:25.0",
            settings.cache_ttl_traffic,
            lambda: traffic_client.fetch_events(lat, lon, 25.0),
        )
    except Exception:
        return []
    return [
        {
            "road": e.roadway,
            "dir": e.direction,
            "type": e.type,
            "headline": _trim(e.headline, 120),
        }
        for e in events[:MAX_TRAFFIC]
    ]


async def _disruption(line: Optional[str]) -> dict[str, Any]:
    """Line-by-line stuck-train rollup with matched alerts.

    If `line` is given, the response is filtered to that line only — useful
    for "how's the Paoli line?" questions where Hermes needs a focused view.
    """
    try:
        trains = await cache.get_or_set(
            "septa:trains", settings.cache_ttl_trains, septa_client.fetch_trains
        )
        alerts = await cache.get_or_set(
            "septa:alerts", settings.cache_ttl_alerts, septa_client.fetch_alerts
        )
    except Exception:
        return {}
    report = build_disruption_report(trains, alerts, threshold_minutes=10)
    lines = list(report.lines)
    if line:
        lines = [ln for ln in lines if ln.line.lower() == line.lower()]
    return {
        "total_trains": report.total_trains,
        "total_stuck": report.total_stuck,
        "lines": [
            {
                "line": ln.line,
                "stuck": ln.stuck_count,
                "max_late_min": ln.max_late_minutes,
                "inbound_stuck": ln.inbound_stuck,
                "outbound_stuck": ln.outbound_stuck,
                "alerts": [_trim(a.current_message, 120) for a in ln.alerts[:2] if a.current_message],
            }
            for ln in lines[:MAX_DISRUPTION_LINES]
        ],
    }


async def _route(mode: str, origin: str, destination: str) -> Optional[dict[str, Any]]:
    """Driving or transit route summary via Google Directions.

    Trimmed to the bits Hermes actually needs to recommend: total time
    (with traffic for driving, scheduled for transit), distance, fare,
    and the transit legs (so the bot can say "Paoli train to Suburban").
    """
    if not settings.google_maps_api_key:
        return None
    cache_key = f"route:{mode}:{origin.lower()}->{destination.lower()}"
    try:
        result = await cache.get_or_set(
            cache_key,
            settings.cache_ttl_traffic,
            lambda: google_client.fetch_directions(origin, destination, mode=mode),
        )
    except Exception:
        return None

    transit_steps: list[dict[str, Any]] = []
    for leg in result.legs:
        for step in leg.steps:
            if step.mode != "TRANSIT":
                continue
            transit_steps.append(
                {
                    "line": step.transit_short_name or step.transit_line,
                    "vehicle": step.transit_vehicle,
                    "from": step.departure_stop,
                    "to": step.arrival_stop,
                    "dep": step.departure_time,
                    "arr": step.arrival_time,
                    "stops": step.transit_num_stops,
                }
            )
            if len(transit_steps) >= MAX_ROUTE_STEPS:
                break

    return {
        "mode": mode,
        "origin": result.legs[0].start_address if result.legs else origin,
        "destination": result.legs[-1].end_address if result.legs else destination,
        "summary": result.summary,
        "duration_min": result.total_duration_seconds // 60,
        "duration_with_traffic_min": (
            result.total_duration_in_traffic_seconds // 60
            if result.total_duration_in_traffic_seconds
            else None
        ),
        "distance_mi": round(result.total_distance_meters / 1609.34, 1),
        "fare": result.fare,
        "transit_steps": transit_steps or None,
    }


async def build(
    tags: set[str],
    lat: float | None = None,
    lon: float | None = None,
    route_origin: str | None = None,
    route_destination: str | None = None,
    line: str | None = None,
) -> dict[str, Any]:
    lat = lat if lat is not None else settings.default_lat
    lon = lon if lon is not None else settings.default_lon

    jobs: dict[str, Any] = {}
    if "weather" in tags:
        jobs["weather"] = _weather(lat, lon)
    if "alerts" in tags:
        jobs["alerts"] = _alerts()
    if "trains" in tags:
        jobs["trains"] = _trains()
    if "bus" in tags:
        jobs["bus_detours"] = _detours()
    if "traffic" in tags:
        jobs["traffic"] = _traffic(lat, lon)
    if "disruption" in tags:
        jobs["disruption"] = _disruption(line)
    if "route" in tags and route_origin and route_destination:
        jobs["drive"] = _route("driving", route_origin, route_destination)
        jobs["transit"] = _route("transit", route_origin, route_destination)

    results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    ctx: dict[str, Any] = {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    for k, v in zip(jobs.keys(), results):
        if isinstance(v, Exception):
            continue
        if v in (None, [], {}):
            continue
        ctx[k] = v
    return ctx
