"""Canonical SEPTA Regional Rail route codes.

SEPTA's Alerts API uses short codes (e.g. 'PAO' for Paoli/Thorndale) in the
`route_id` field. These codes don't appear in the TrainView feed, which uses
the full line name. This map lets us correlate alerts to lines deterministically
instead of doing fuzzy substring matching that produces false positives
(e.g. "Paoli Pike" matching the Paoli/Thorndale line).
"""
from __future__ import annotations


LINE_BY_ROUTE_ID: dict[str, str] = {
    "AIR": "Airport",
    "CHE": "Chestnut Hill East",
    "CHW": "Chestnut Hill West",
    "CYN": "Cynwyd",
    "FXC": "Fox Chase",
    "LAN": "Lansdale/Doylestown",
    "MED": "Media/Wawa",
    "NOR": "Manayunk/Norristown",
    "PAO": "Paoli/Thorndale",
    "TRE": "Trenton",
    "WAR": "Warminster",
    "WIL": "Wilmington/Newark",
    "WTR": "West Trenton",
}

RAIL_LINE_NAMES: frozenset[str] = frozenset(LINE_BY_ROUTE_ID.values())


def line_from_route_id(route_id: str) -> str | None:
    if not route_id:
        return None
    return LINE_BY_ROUTE_ID.get(route_id.strip().upper())
