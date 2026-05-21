"""Build a compact, token-efficient context object for Hermes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.cache import cache
from app.clients import septa as septa_client
from app.clients import traffic as traffic_client
from app.clients import weather as weather_client
from app.config import settings


MAX_ALERTS = 6
MAX_TRAINS = 8
MAX_DETOURS = 5
MAX_TRAFFIC = 6


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


async def build(
    tags: set[str],
    lat: float | None = None,
    lon: float | None = None,
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

    results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    ctx: dict[str, Any] = {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    for k, v in zip(jobs.keys(), results):
        if isinstance(v, Exception):
            continue
        if v in (None, [], {}):
            continue
        ctx[k] = v
    return ctx
