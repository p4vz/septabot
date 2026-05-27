from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.cache import cache
from app.clients import septa as septa_client
from app.config import settings
from app.data.stations import nearest_stations, search_stations
from app.inference import build_disruption_report
from app.models import (
    Alert,
    BusDetour,
    DisruptionReport,
    ElevatorOutage,
    NextToArriveOption,
    Station,
    StationArrivals,
    Train,
    TrainScheduleStop,
    Vehicle,
)

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


@router.get("/vehicles", response_model=list[Vehicle])
async def get_vehicles(
    route: str = Query(..., description="Route number/letter, e.g. '33', 'K', '101'"),
    min_late: int = Query(default=0, ge=0, description="Only vehicles at least N minutes late"),
):
    """Live bus/trolley positions for a route from TransitView: location, next
    stop, minutes late, and seat availability."""
    vehicles = await cache.get_or_set(
        f"septa:vehicles:{route.lower()}",
        settings.cache_ttl_trains,
        lambda: septa_client.fetch_vehicles(route),
    )
    if min_late > 0:
        vehicles = [v for v in vehicles if v.late_minutes >= min_late]
    return vehicles


@router.get("/elevator-outages", response_model=list[ElevatorOutage])
async def get_elevator_outages(
    station: Optional[str] = Query(default=None, description="Substring match on station name"),
):
    """Out-of-service elevators/escalators across the SEPTA system."""
    outages = await cache.get_or_set(
        "septa:elevator-outages", settings.cache_ttl_alerts, septa_client.fetch_elevator_outages
    )
    if station:
        s = station.lower()
        outages = [o for o in outages if s in o.station.lower()]
    return outages


@router.get("/arrivals", response_model=StationArrivals)
async def get_arrivals(
    station: str = Query(..., description="Station name, e.g. 'Suburban Station'"),
    results: int = Query(default=10, ge=1, le=20),
):
    return await cache.get_or_set(
        f"septa:arrivals:{station.lower()}:{results}",
        settings.cache_ttl_trains,
        lambda: septa_client.fetch_arrivals(station, results),
    )


@router.get("/next-to-arrive", response_model=list[NextToArriveOption])
async def get_next_to_arrive(
    origin: str = Query(..., description="Origin station, e.g. 'Wayne'"),
    destination: str = Query(..., description="Destination station, e.g. 'Suburban Station'"),
    results: int = Query(default=5, ge=1, le=20),
):
    return await cache.get_or_set(
        f"septa:nta:{origin.lower()}->{destination.lower()}:{results}",
        settings.cache_ttl_trains,
        lambda: septa_client.fetch_next_to_arrive(origin, destination, results),
    )


@router.get("/schedule", response_model=list[TrainScheduleStop])
async def get_train_schedule(
    train: str = Query(..., description="Train number, e.g. '532'"),
):
    """Full stop list for a specific train run with scheduled, estimated, and
    actual times (RRSchedules)."""
    return await cache.get_or_set(
        f"septa:schedule:{train}",
        settings.cache_ttl_trains,
        lambda: septa_client.fetch_train_schedule(train),
    )


@router.get("/disruptions", response_model=DisruptionReport)
async def get_disruptions(
    min_late: int = Query(default=10, ge=1, le=180, description="Threshold for 'stuck' in minutes"),
    line: Optional[str] = Query(default=None, description="Filter to a single line"),
    direction: Optional[str] = Query(
        default=None, description="Filter to 'inbound' or 'outbound'"
    ),
):
    """Rollup of stuck trains by line, bottleneck (next-stop + direction), and
    matching service alerts. This is the endpoint Hermes should call to decide
    whether to recommend or warn against a route."""
    trains = await cache.get_or_set(
        "septa:trains", settings.cache_ttl_trains, septa_client.fetch_trains
    )
    alerts = await cache.get_or_set(
        "septa:alerts", settings.cache_ttl_alerts, septa_client.fetch_alerts
    )

    report = build_disruption_report(trains, alerts, threshold_minutes=min_late)

    if line:
        line_l = line.lower()
        report.lines = [ld for ld in report.lines if ld.line.lower() == line_l]
    if direction in ("inbound", "outbound"):
        for ld in report.lines:
            ld.bottlenecks = [b for b in ld.bottlenecks if b.direction == direction]
        report.lines = [ld for ld in report.lines if ld.bottlenecks]

    return report


@router.get("/stations", response_model=list[Station])
async def get_stations(
    search: Optional[str] = Query(default=None, description="Substring match on station name"),
    lat: Optional[float] = Query(default=None, description="Latitude for nearest-station lookup"),
    lon: Optional[float] = Query(default=None, description="Longitude for nearest-station lookup"),
    limit: int = Query(default=3, ge=1, le=20),
):
    if (lat is None) != (lon is None):
        raise HTTPException(status_code=400, detail="lat and lon must be provided together")
    if lat is not None and lon is not None:
        return nearest_stations(lat, lon, limit)
    if search:
        return search_stations(search)
    return search_stations("")
