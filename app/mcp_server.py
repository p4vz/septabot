"""MCP server exposing Septabot's live transit data as agent tools.

Mounted at /mcp on the FastAPI app (Streamable HTTP transport). An external
agent such as Hermes connects here, auto-discovers these tools, and calls
them to answer Philadelphia commuter questions. The tool bodies reuse the
same cache + client logic the REST endpoints and dashboard use, so there's a
single source of truth for each data source.
"""
from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.bot import context as ctx
from app.cache import cache
from app.clients import septa as septa_client
from app.config import settings


# DNS-rebinding protection (FastMCP's default) validates the Host header against
# an allowlist. That's designed for localhost dev servers reachable from a
# browser; it doesn't fit a server-to-server deployment where the Host varies
# (Railway uses *.railway.internal and *.up.railway.app), and it would 421 every
# request. We disable it here because this endpoint is a server-side tool API
# guarded instead by (a) Railway private networking and/or (b) the optional
# MCP_AUTH_TOKEN bearer check in main.py — not browser-reachable, read-only data.
_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP(
    "septabot",
    instructions=(
        "Live Philadelphia commuting data. Use these tools to answer questions "
        "about SEPTA Regional Rail status, service alerts, bus detours, weather, "
        "highway traffic, and door-to-door routing (driving vs. transit). All data "
        "is real-time and Philadelphia-region only. When a user asks 'should I "
        "drive or take the train?', call both drive_route and transit_route and "
        "compare, and check get_rail_disruptions for the relevant line."
    ),
    stateless_http=True,
    json_response=True,
    # Serve the endpoint at the mount root so mounting at /mcp yields exactly /mcp.
    streamable_http_path="/",
    transport_security=_security,
)


@mcp.tool()
async def get_rail_disruptions(line: str = "") -> dict:
    """Regional Rail disruption rollup: per-line stuck-train counts, the worst
    delay on each line, the inbound/outbound split, and any matched SEPTA
    service alerts. Pass a canonical line name like 'Paoli/Thorndale' or
    'Airport' to focus on one line; leave blank for every line with a problem.
    Best first call for 'how's the X line?' or 'are trains messed up?'."""
    return await ctx._disruption(line or None)


@mcp.tool()
async def get_train_delays(min_late: int = 5) -> list[dict]:
    """Currently delayed Regional Rail trains, most-delayed first. Each entry
    has train number, line, destination, next stop, and minutes late. Use
    min_late to set the threshold in minutes (default 5)."""
    trains = await cache.get_or_set(
        "septa:trains", settings.cache_ttl_trains, septa_client.fetch_trains
    )
    delayed = sorted(
        (t for t in trains if t.late_minutes >= min_late),
        key=lambda t: -t.late_minutes,
    )[:12]
    return [
        {
            "train": t.train_number,
            "line": t.line,
            "destination": t.destination,
            "next_stop": t.next_stop,
            "late_min": t.late_minutes,
        }
        for t in delayed
    ]


@mcp.tool()
async def get_service_alerts(mode: str = "") -> list[dict]:
    """Active SEPTA service alerts with full message text. Optionally filter by
    mode: 'Rail', 'Bus', 'Trolley', or 'Subway'. Returns route, name, mode, and
    the alert/advisory message."""
    alerts = await cache.get_or_set(
        "septa:alerts", settings.cache_ttl_alerts, septa_client.fetch_alerts
    )
    out: list[dict] = []
    for a in alerts:
        if mode and a.mode.lower() != mode.lower():
            continue
        if not (a.current_message or a.advisory_message):
            continue
        out.append(
            {
                "route": a.route_id,
                "name": a.route_name,
                "mode": a.mode,
                "message": a.current_message,
                "advisory": a.advisory_message,
            }
        )
    return out


@mcp.tool()
async def get_bus_detours() -> list[dict]:
    """Active SEPTA bus/trolley detours: route, reason, and where the detour
    runs."""
    return await ctx._detours()


@mcp.tool()
async def get_next_to_arrive(origin: str, destination: str) -> list[dict]:
    """Next Regional Rail trains between two SEPTA stations (direct or via one
    transfer). Pass full station names, e.g. origin='Wayne', destination=
    'Suburban Station'. Returns departure/arrival times, line, and delay."""
    opts = await septa_client.fetch_next_to_arrive(origin, destination, results=5)
    return [o.model_dump(exclude_none=True) for o in opts]


@mcp.tool()
async def get_weather() -> Optional[dict]:
    """Current Philadelphia weather and short forecast from the National Weather
    Service: temperature, conditions, wind, precipitation chance, plus the next
    couple of periods."""
    return await ctx._weather(settings.default_lat, settings.default_lon)


@mcp.tool()
async def get_traffic() -> list[dict]:
    """Active highway traffic incidents near Center City Philadelphia from 511PA
    (crashes, closures, construction): road, direction, type, and headline.
    Empty if no incidents or no 511PA key configured."""
    return await ctx._traffic(settings.default_lat, settings.default_lon)


@mcp.tool()
async def drive_route(origin: str, destination: str) -> Optional[dict]:
    """Driving directions with live traffic via Google Maps. Returns total time
    (including current traffic), distance in miles, and a route summary. Accepts
    addresses or 'lat,lon'. Returns null if no Google key is configured."""
    return await ctx._route("driving", origin, destination)


@mcp.tool()
async def transit_route(origin: str, destination: str) -> Optional[dict]:
    """SEPTA-aware door-to-door transit directions via Google Maps. Returns total
    time, fare, and each transit leg (line, boarding/alighting stops, times).
    Accepts addresses or 'lat,lon'. Returns null if no Google key is configured."""
    return await ctx._route("transit", origin, destination)
