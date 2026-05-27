from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


CENTER_CITY_STATIONS = {
    "30th street station",
    "30th street",
    "suburban station",
    "suburban",
    "jefferson station",
    "jefferson",
    "market east",
    "temple university",
    "temple u",
}


def infer_direction(destination: str) -> str:
    """Inbound = heading toward Center City. Outbound = heading away.

    Regional Rail through-routes via Center City, so this reflects the final
    destination as listed by SEPTA, not necessarily the train's current leg.
    """
    if not destination:
        return "unknown"
    d = destination.strip().lower()
    if d in CENTER_CITY_STATIONS or any(cc in d for cc in CENTER_CITY_STATIONS):
        return "inbound"
    return "outbound"


class Alert(BaseModel):
    route_id: str
    route_name: str
    mode: str
    current_message: str = ""
    advisory_message: str = ""
    last_updated: Optional[datetime] = None


class Train(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    train_number: str = Field(validation_alias="trainno")
    line: str = ""
    destination: str = Field(validation_alias="dest", default="")
    current_stop: str = Field(validation_alias="currentstop", default="")
    next_stop: str = Field(validation_alias="nextstop", default="")
    late_minutes: int = Field(validation_alias="late", default=0)
    lat: float = 0.0
    lon: float = 0.0
    service: str = ""
    source: str = Field(validation_alias="SOURCE", default="")
    direction: str = "unknown"

    @model_validator(mode="after")
    def _infer_direction(self):
        if self.direction == "unknown":
            self.direction = infer_direction(self.destination)
        return self


class BusDetour(BaseModel):
    route_id: str
    route_name: str = ""
    reason: str = ""
    start_location: str = ""
    end_location: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    current_message: str = ""


class Vehicle(BaseModel):
    """A real-time bus or trolley position from the TransitView feed."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    vehicle_id: str = Field(validation_alias="VehicleID", default="")
    label: str = ""
    route_id: str = ""
    direction: str = Field(validation_alias="Direction", default="")
    destination: str = ""
    lat: float = 0.0
    lon: float = Field(validation_alias="lng", default=0.0)
    heading: float = 0.0
    late_minutes: int = Field(validation_alias="late", default=0)
    next_stop: str = Field(validation_alias="next_stop_name", default="")
    next_stop_id: str = Field(validation_alias="next_stop_id", default="")
    seat_availability: str = Field(validation_alias="estimated_seat_availability", default="")


class ElevatorOutage(BaseModel):
    """An out-of-service elevator/escalator at a SEPTA station."""

    line: str = ""
    station: str = ""
    elevator: str = ""
    message: str = ""
    alternate_url: str = ""


class Arrival(BaseModel):
    """A single train arrival/departure at a specific station."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    direction: str = ""
    line: str = ""
    train_id: str = ""
    origin: str = ""
    destination: str = ""
    status: str = ""
    service_type: str = Field(validation_alias="service_type", default="")
    next_station: str = ""
    sched_time: Optional[str] = None
    depart_time: Optional[str] = None
    track: str = ""
    platform: str = ""


class StationArrivals(BaseModel):
    station: str
    northbound: list[Arrival] = Field(default_factory=list)
    southbound: list[Arrival] = Field(default_factory=list)


class NextToArriveOption(BaseModel):
    """Origin → destination train pairing. May be direct or include a transfer."""

    orig_train: str = ""
    orig_line: str = ""
    orig_departure_time: str = ""
    orig_arrival_time: str = ""
    orig_delay: str = ""
    is_direct: bool = True
    connection_station: Optional[str] = None
    term_train: Optional[str] = None
    term_line: Optional[str] = None
    term_departure_time: Optional[str] = None
    term_arrival_time: Optional[str] = None
    term_delay: Optional[str] = None


class Station(BaseModel):
    name: str
    lat: float
    lon: float
    lines: list[str] = Field(default_factory=list)
    distance_miles: Optional[float] = None


class WeatherPeriod(BaseModel):
    name: str
    start_time: datetime
    end_time: datetime
    temperature: int
    temperature_unit: str
    wind: str
    short_forecast: str
    detailed_forecast: str = ""
    precipitation_probability: Optional[int] = None


class WeatherSummary(BaseModel):
    location: dict
    current: Optional[WeatherPeriod] = None
    upcoming: list[WeatherPeriod] = Field(default_factory=list)


class TrafficEvent(BaseModel):
    id: str
    type: str = ""
    severity: str = "unknown"
    headline: str = ""
    description: str = ""
    roadway: str = ""
    direction: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    start_time: Optional[datetime] = None
    last_updated: Optional[datetime] = None


class CommuteSnapshot(BaseModel):
    timestamp: datetime
    weather: Optional[WeatherSummary] = None
    septa_alerts: list[Alert] = Field(default_factory=list)
    train_delays: list[Train] = Field(default_factory=list)
    bus_detours: list[BusDetour] = Field(default_factory=list)
    traffic_events: list[TrafficEvent] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)


class Bottleneck(BaseModel):
    """A cluster of stuck trains sharing the same upcoming station + direction."""

    next_stop: str
    direction: str
    train_count: int
    max_late_minutes: int
    trains: list[Train] = Field(default_factory=list)


class LineDisruption(BaseModel):
    """All stuck trains and matching alerts on a single Regional Rail line."""

    line: str
    stuck_count: int
    max_late_minutes: int
    inbound_stuck: int = 0
    outbound_stuck: int = 0
    bottlenecks: list[Bottleneck] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)


class DisruptionReport(BaseModel):
    timestamp: datetime
    threshold_minutes: int
    total_trains: int
    total_stuck: int
    lines: list[LineDisruption] = Field(default_factory=list)


class RouteStep(BaseModel):
    """A single step within a route leg (walk a block, take a train, etc.)."""

    mode: str = ""  # WALKING, TRANSIT, DRIVING, BICYCLING
    instruction: str = ""
    distance_meters: int = 0
    duration_seconds: int = 0
    # Populated only when mode == TRANSIT
    transit_line: Optional[str] = None
    transit_short_name: Optional[str] = None
    transit_vehicle: Optional[str] = None
    transit_headsign: Optional[str] = None
    transit_num_stops: Optional[int] = None
    departure_stop: Optional[str] = None
    arrival_stop: Optional[str] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None


class RouteLeg(BaseModel):
    start_address: str = ""
    end_address: str = ""
    distance_meters: int = 0
    duration_seconds: int = 0
    duration_in_traffic_seconds: Optional[int] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    steps: list[RouteStep] = Field(default_factory=list)


class RouteResult(BaseModel):
    mode: str  # "driving" or "transit"
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    legs: list[RouteLeg] = Field(default_factory=list)
    total_distance_meters: int = 0
    total_duration_seconds: int = 0
    total_duration_in_traffic_seconds: Optional[int] = None
    polyline: Optional[str] = None
    fare: Optional[dict] = None
