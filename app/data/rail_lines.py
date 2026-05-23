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


# Aliases SEPTA staff and riders commonly use in alert text that don't
# verbatim match the canonical "X/Y" line name. Each alias is a multi-word
# phrase to avoid false positives from a bare city name (e.g. "Wilmington"
# could refer to the city; "Wilmington Line" unambiguously refers to the line).
LINE_ALIASES: dict[str, list[str]] = {
    "Paoli/Thorndale": [
        "paoli line", "thorndale line", "paoli/thorndale line",
        "paoli train", "paoli regional rail",
    ],
    "Wilmington/Newark": [
        "wilmington line", "newark line", "wilmington/newark line",
        "wilmington train",
    ],
    "Trenton": ["trenton line"],
    "West Trenton": ["west trenton line"],
    "Lansdale/Doylestown": [
        "lansdale line", "doylestown line", "lansdale/doylestown line",
    ],
    "Media/Wawa": [
        "media line", "wawa line", "media/wawa line",
        # SEPTA renamed this from Media/Elwyn when Wawa extension opened;
        # older alerts may still use the legacy name.
        "media/elwyn",
    ],
    "Manayunk/Norristown": [
        "manayunk line", "norristown line", "manayunk/norristown line",
    ],
    "Chestnut Hill East": ["chestnut hill east line"],
    "Chestnut Hill West": ["chestnut hill west line"],
    "Cynwyd": ["cynwyd line"],
    "Fox Chase": ["fox chase line"],
    "Warminster": ["warminster line"],
    "Airport": ["airport line", "airport regional rail"],
}


def line_from_route_id(route_id: str) -> str | None:
    if not route_id:
        return None
    return LINE_BY_ROUTE_ID.get(route_id.strip().upper())


def aliases_for_line(line: str) -> list[str]:
    return LINE_ALIASES.get(line, [])
