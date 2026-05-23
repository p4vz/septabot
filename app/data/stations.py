"""Curated SEPTA Regional Rail station list with approximate coordinates.

Coordinates are accurate to within ~200m, which is enough for nearest-station
selection from a user's lat/lon without a maps API. To add more stations,
pull SEPTA's GTFS `stops.txt` (location_type=1) and append entries below.
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from app.models import Station


STATIONS: list[Station] = [
    # Center City
    Station(name="30th Street Station", lat=39.9566, lon=-75.1820, lines=["all"]),
    Station(name="Suburban Station", lat=39.9540, lon=-75.1670, lines=["all"]),
    Station(name="Jefferson Station", lat=39.9529, lon=-75.1583, lines=["all"]),
    Station(name="Temple University", lat=39.9810, lon=-75.1494, lines=["all"]),
    Station(name="University City", lat=39.9472, lon=-75.1898, lines=["all"]),
    Station(name="North Broad", lat=39.9836, lon=-75.1614, lines=["all"]),
    # Major suburban hubs / line termini
    Station(name="Wilmington", lat=39.7385, lon=-75.5510, lines=["Wilmington/Newark"]),
    Station(name="Trenton", lat=40.2196, lon=-74.7563, lines=["Trenton"]),
    Station(name="West Trenton", lat=40.2592, lon=-74.8156, lines=["West Trenton"]),
    Station(name="Paoli", lat=40.0436, lon=-75.4895, lines=["Paoli/Thorndale"]),
    Station(name="Wayne", lat=40.0432, lon=-75.3886, lines=["Paoli/Thorndale"]),
    Station(name="Bryn Mawr", lat=40.0207, lon=-75.3147, lines=["Paoli/Thorndale"]),
    Station(name="Ardmore", lat=40.0034, lon=-75.2897, lines=["Paoli/Thorndale"]),
    Station(name="Norristown Transportation Center", lat=40.1210, lon=-75.3406,
            lines=["Manayunk/Norristown"]),
    Station(name="Doylestown", lat=40.3097, lon=-75.1290, lines=["Lansdale/Doylestown"]),
    Station(name="Lansdale", lat=40.2410, lon=-75.2845, lines=["Lansdale/Doylestown"]),
    Station(name="Glenside", lat=40.1006, lon=-75.1525, lines=["Lansdale/Doylestown", "Warminster", "West Trenton"]),
    Station(name="Warminster", lat=40.2071, lon=-75.0995, lines=["Warminster"]),
    Station(name="Chestnut Hill East", lat=40.0728, lon=-75.2061, lines=["Chestnut Hill East"]),
    Station(name="Chestnut Hill West", lat=40.0742, lon=-75.2105, lines=["Chestnut Hill West"]),
    Station(name="Fox Chase", lat=40.0779, lon=-75.0826, lines=["Fox Chase"]),
]


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613  # earth radius in miles
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


def search_stations(query: str) -> list[Station]:
    q = query.strip().lower()
    if not q:
        return list(STATIONS)
    return [s for s in STATIONS if q in s.name.lower()]


def nearest_stations(lat: float, lon: float, limit: int = 3) -> list[Station]:
    ranked = [
        s.model_copy(update={"distance_miles": round(_haversine_miles(lat, lon, s.lat, s.lon), 2)})
        for s in STATIONS
    ]
    ranked.sort(key=lambda s: s.distance_miles or 0)
    return ranked[: max(1, limit)]
