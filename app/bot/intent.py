"""Keyword-based intent classification.

Cheap heuristic to decide which data slices to fetch and inject into the
Hermes prompt, so we don't pay for tokens carrying irrelevant context.
"""
from __future__ import annotations


WEATHER_KEYWORDS = (
    "weather", "rain", "snow", "storm", "cold", "hot", "humid", "umbrella",
    "forecast", "temperature", "wind", "sunny", "cloudy",
)

TRAIN_KEYWORDS = (
    "train", "regional rail", " rr ", "rrt", "trolley", "subway",
    "mfl", "market-frankford", "broad street", "bsl", "el ", "line",
)

BUS_KEYWORDS = ("bus", "detour", "route ")

TRAFFIC_KEYWORDS = (
    "traffic", "highway", "schuylkill", "i-95", "i95", "i-76", "i76",
    "676", "blue route", "476", "vine", "roosevelt", "kelly drive",
    "accident", "crash",
)

ALERT_KEYWORDS = ("alert", "outage", "service", "delay", "septa", "disruption", "down")

# Asking about a specific route between A and B — fetch driving + transit
# from Google so Hermes can recommend one.
ROUTE_KEYWORDS = (
    "drive", "driving", "by car", "fastest", "quickest", "best way",
    "how do i get", "how do i go", "get to", "trip from", " from ",
    "directions", "route to", "should i drive", "should i take",
)

# Asking about line-level health — fetch the disruption rollup, which
# correlates stuck trains with active alerts per line.
DISRUPTION_KEYWORDS = (
    "stuck", "stranded", "single track", "bottleneck", "how's the",
    "how is the", "what's up with", "running late", "behind schedule",
)

COMMUTE_KEYWORDS = (
    "commute", "ride", "going to", "get to work", "leave", "trip",
    "how is", "how's", "morning", "evening",
)


def classify(text: str) -> set[str]:
    t = f" {text.lower()} "
    tags: set[str] = set()
    if any(k in t for k in WEATHER_KEYWORDS):
        tags.add("weather")
    if any(k in t for k in TRAIN_KEYWORDS):
        tags.add("trains")
        tags.add("disruption")  # train question → also pull line-level rollup
    if any(k in t for k in BUS_KEYWORDS):
        tags.add("bus")
    if any(k in t for k in TRAFFIC_KEYWORDS):
        tags.add("traffic")
    if any(k in t for k in ALERT_KEYWORDS):
        tags.add("alerts")
        tags.add("disruption")
    if any(k in t for k in DISRUPTION_KEYWORDS):
        tags.add("disruption")
        tags.add("trains")
    if any(k in t for k in ROUTE_KEYWORDS):
        tags.add("route")
        tags.add("traffic")  # routes care about live traffic context
    if any(k in t for k in COMMUTE_KEYWORDS):
        tags.update({"weather", "trains", "alerts", "traffic", "disruption"})
    if not tags:
        # Default to a lean commute snapshot when intent is unclear.
        tags.update({"weather", "alerts", "trains"})
    return tags
