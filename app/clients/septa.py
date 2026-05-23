from datetime import datetime
from typing import Any, Optional

import httpx

from app.config import settings
from app.models import (
    Alert,
    Arrival,
    BusDetour,
    NextToArriveOption,
    StationArrivals,
    Train,
)


SEPTA_BASE = "https://www3.septa.org/api"


async def _get_json(path: str, params: Optional[dict] = None) -> Any:
    headers = {"User-Agent": settings.nws_user_agent, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=settings.http_timeout, headers=headers) as client:
        r = await client.get(f"{SEPTA_BASE}{path}", params=params)
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
    """Fetch SEPTA service alerts.

    SEPTA exposes two alerts endpoints. /Alerts/index.php returns a thin
    summary (route + flags) where the message-body fields are usually
    empty. /Alerts/get_alert_data.php?req1=all_alerts returns the verbose
    bodies that show up in the SEPTA mobile app. We use the verbose one
    and fall back to the thin one only if it errors, so we always have
    *something* to display.

    Field names vary between modes (rail vs. bus vs. detour-only items),
    so we look for any of: current_message, advisory_message,
    description, descriptiontext, message, detour_message.
    """
    raw_items: list[dict] = []
    try:
        verbose = await _get_json(
            "/Alerts/get_alert_data.php", params={"req1": "all_alerts"}
        )
        raw_items = _flatten_alert_payload(verbose)
    except (httpx.HTTPError, ValueError):
        # Only fall back if the verbose endpoint genuinely failed — an empty
        # response from it is a valid "no active alerts" answer.
        thin = await _get_json("/Alerts/index.php")
        raw_items = list(thin or [])

    alerts: list[Alert] = []
    for raw in raw_items:
        current = _first_nonempty(
            raw, "current_message", "description", "descriptiontext", "message"
        )
        advisory = _first_nonempty(raw, "advisory_message", "advisory")
        detour = _first_nonempty(raw, "detour_message", "detour")
        # If the advisory slot is empty but a detour body exists, surface it
        # there so the dashboard's "advisory" line renders the detour text.
        if not advisory and detour:
            advisory = detour
        alerts.append(
            Alert(
                route_id=str(raw.get("route_id") or raw.get("routeid") or ""),
                route_name=str(raw.get("route_name") or raw.get("routename") or ""),
                mode=str(raw.get("mode") or raw.get("route_type") or ""),
                current_message=current,
                advisory_message=advisory,
                last_updated=_parse_dt(raw.get("last_updated") or raw.get("ts")),
            )
        )
    return alerts


def _first_nonempty(raw: dict, *keys: str) -> str:
    """Return the first non-empty string value among `keys`, HTML-stripped."""
    for key in keys:
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            return _strip_html(val).strip()
    return ""


_HTML_TAG_RE = __import__("re").compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    import html as _html
    return _html.unescape(_HTML_TAG_RE.sub(" ", s))


def _flatten_alert_payload(payload: Any) -> list[dict]:
    """Normalise SEPTA's get_alert_data.php shape to a flat list of dicts.

    The endpoint has historically returned either a top-level list or a
    dict keyed by route_id whose values are alert objects (or lists of
    them). Accept both.
    """
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        out: list[dict] = []
        for key, val in payload.items():
            if isinstance(val, dict):
                val.setdefault("route_id", key)
                out.append(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        item.setdefault("route_id", key)
                        out.append(item)
        return out
    return []


async def fetch_trains() -> list[Train]:
    data = await _get_json("/TrainView/index.php")
    return [Train.model_validate(raw) for raw in (data or [])]


def _arrival(raw: dict) -> Arrival:
    return Arrival(
        direction=str(raw.get("direction", "")),
        line=str(raw.get("line", "")),
        train_id=str(raw.get("train_id", "")),
        origin=str(raw.get("origin", "")),
        destination=str(raw.get("destination", "")),
        status=str(raw.get("status", "")),
        service_type=str(raw.get("service_type", "")),
        next_station=str(raw.get("next_station") or ""),
        sched_time=raw.get("sched_time"),
        depart_time=raw.get("depart_time"),
        track=str(raw.get("track") or raw.get("platform") or ""),
        platform=str(raw.get("platform") or ""),
    )


async def fetch_arrivals(station: str, results: int = 10) -> StationArrivals:
    """Next arrivals at a Regional Rail station.

    SEPTA returns `{ "<station>": [ { "Northbound": [...], "Southbound": [...] } ] }`.
    """
    data = await _get_json(
        "/Arrivals/index.php",
        params={"station": station, "results": max(1, min(20, results))},
    )
    if not isinstance(data, dict) or not data:
        return StationArrivals(station=station)
    key = next(iter(data.keys()))
    blocks = data[key] if isinstance(data[key], list) else [data[key]]
    nb: list[Arrival] = []
    sb: list[Arrival] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for raw in block.get("Northbound", []) or []:
            nb.append(_arrival(raw))
        for raw in block.get("Southbound", []) or []:
            sb.append(_arrival(raw))
    return StationArrivals(station=key, northbound=nb, southbound=sb)


async def fetch_next_to_arrive(
    origin: str, destination: str, results: int = 5
) -> list[NextToArriveOption]:
    """Next trains between two stations (direct or via transfer)."""
    data = await _get_json(
        "/NextToArrive/index.php",
        params={"req1": origin, "req2": destination, "req3": max(1, min(20, results))},
    )
    out: list[NextToArriveOption] = []
    for raw in data or []:
        if not isinstance(raw, dict):
            continue
        is_direct_raw = str(raw.get("isdirect", "true")).lower()
        out.append(
            NextToArriveOption(
                orig_train=str(raw.get("orig_train", "")),
                orig_line=str(raw.get("orig_line", "")),
                orig_departure_time=str(raw.get("orig_departure_time", "")),
                orig_arrival_time=str(raw.get("orig_arrival_time", "")),
                orig_delay=str(raw.get("orig_delay", "")),
                is_direct=is_direct_raw in ("true", "1", "yes"),
                connection_station=raw.get("Connection") or raw.get("connection"),
                term_train=raw.get("term_train"),
                term_line=raw.get("term_line"),
                term_departure_time=raw.get("term_departure_time"),
                term_arrival_time=raw.get("term_arrival_time"),
                term_delay=raw.get("term_delay"),
            )
        )
    return out


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
