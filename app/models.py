from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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


class BusDetour(BaseModel):
    route_id: str
    route_name: str = ""
    reason: str = ""
    start_location: str = ""
    end_location: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    current_message: str = ""


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
