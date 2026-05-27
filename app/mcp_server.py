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
from app.bot import entities, intent
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
        "Live Philadelphia commuting data for SEPTA, weather, traffic, and "
        "routing.\n\n"
        "PREFERRED: For almost any commuter question, call `commute_briefing` "
        "with the user's raw question. It figures out what's relevant and "
        "returns ONLY that data (e.g. a rail question gets train + disruption "
        "data, not weather or driving routes), keeping the response small and "
        "focused. Answer from what it returns.\n\n"
        "The other tools are for drilling in when you need one specific thing "
        "(a single train's schedule, a station board, one bus route's "
        "vehicles, elevator outages). All data is real-time and "
        "Philadelphia-region only."
    ),
    stateless_http=True,
    json_response=True,
    # Serve the endpoint at the mount root so mounting at /mcp yields exactly /mcp.
    streamable_http_path="/",
    transport_security=_security,
)


@mcp.tool()
async def commute_briefing(query: str) -> dict:
    """Smart, single-call briefing. Pass the user's raw question and get back
    ONLY the data relevant to it — nothing extra. This should be your first
    call for general commute questions.

    It classifies the question and fetches just the matching slices:
      - weather words ('rain', 'umbrella') -> weather only
      - a rail line / 'delays' / 'stuck' -> delayed trains + per-line disruption
        rollup (with the relevant line pre-filtered)
      - 'bus' / 'detour' -> bus detours
      - 'traffic' / a highway name -> 511PA incidents
      - 'drive', 'fastest', or 'from X to Y' -> driving AND transit routes for
        that trip (extracted from the text), plus live traffic
    Multiple intents combine (e.g. a 'should I drive or take the train from
    Wayne to Center City' question returns drive, transit, and disruption).

    The returned object includes an `_included` list naming which data sections
    are present and a `_route` echo of any origin/destination parsed from the
    question. If a section the user asked about is missing, the underlying feed
    was empty or unavailable — say so rather than inventing data."""
    tags = intent.classify(query)
    route = entities.extract_route(query, default_origin=settings.default_origin)
    line = entities.extract_line(query)
    if route and "route" not in tags:
        tags.add("route")
        tags.add("traffic")

    data = await ctx.build(
        tags,
        route_origin=route[0] if route else None,
        route_destination=route[1] if route else None,
        line=line,
    )
    data["_included"] = sorted(k for k in data if not k.startswith("_") and k != "as_of")
    if route:
        data["_route"] = {"origin": route[0], "destination": route[1]}
    if line:
        data["_line"] = line
    return data


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
async def get_vehicle_locations(route: str, min_late: int = 0) -> list[dict]:
    """Live positions of every bus/trolley on a route (SEPTA TransitView). Pass
    the public route like '33', 'K', or '101'. Each vehicle has its direction,
    destination, next stop, minutes late, and seat availability. Use for 'where
    is the 33 bus?' or 'is the K trolley running late?'. min_late filters to
    vehicles at least N minutes behind."""
    vehicles = await cache.get_or_set(
        f"septa:vehicles:{route.lower()}",
        settings.cache_ttl_trains,
        lambda: septa_client.fetch_vehicles(route),
    )
    return [
        {
            "vehicle": v.vehicle_id,
            "route": v.route_id,
            "direction": v.direction,
            "destination": v.destination,
            "next_stop": v.next_stop,
            "late_min": v.late_minutes,
            "seats": v.seat_availability,
            "lat": v.lat,
            "lon": v.lon,
        }
        for v in vehicles
        if v.late_minutes >= min_late
    ]


@mcp.tool()
async def get_elevator_outages(station: str = "") -> list[dict]:
    """Out-of-service SEPTA elevators/escalators (accessibility). Optionally
    filter by station name substring. Each entry has line, station, the elevator
    location, and the outage message. Use for wheelchair/stroller/accessibility
    questions like 'is the elevator at 69th St working?'."""
    outages = await cache.get_or_set(
        "septa:elevator-outages",
        settings.cache_ttl_alerts,
        septa_client.fetch_elevator_outages,
    )
    s = station.lower()
    return [
        {
            "line": o.line,
            "station": o.station,
            "elevator": o.elevator,
            "message": o.message,
        }
        for o in outages
        if not s or s in o.station.lower()
    ]


@mcp.tool()
async def get_next_to_arrive(origin: str, destination: str) -> list[dict]:
    """Next Regional Rail trains between two SEPTA stations (direct or via one
    transfer). Pass full station names, e.g. origin='Wayne', destination=
    'Suburban Station'. Returns departure/arrival times, line, and delay."""
    opts = await septa_client.fetch_next_to_arrive(origin, destination, results=5)
    return [o.model_dump(exclude_none=True) for o in opts]


@mcp.tool()
async def get_station_arrivals(station: str, results: int = 10) -> dict:
    """The 'Big Board' for a SEPTA Regional Rail station: inbound and outbound
    trains due soon, each with line, destination, status (on time / N min late),
    and scheduled time. Pass a full station name like 'Suburban Station' or
    '30th Street Station'. Use for 'what's leaving Suburban Station soon?'."""
    arr = await cache.get_or_set(
        f"septa:arrivals:{station.lower()}:{results}",
        settings.cache_ttl_trains,
        lambda: septa_client.fetch_arrivals(station, results),
    )
    return arr.model_dump(exclude_none=True)


@mcp.tool()
async def get_train_schedule(train_number: str) -> list[dict]:
    """The full stop list for a specific train run with scheduled, estimated,
    and actual times. Pass the train number (e.g. '532'). Use to answer 'what
    stops does train 532 make and when?' or to check a train's progress."""
    stops = await cache.get_or_set(
        f"septa:schedule:{train_number}",
        settings.cache_ttl_trains,
        lambda: septa_client.fetch_train_schedule(train_number),
    )
    return [s.model_dump(exclude_none=True) for s in stops]


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
