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
    if any(k in t for k in BUS_KEYWORDS):
        tags.add("bus")
    if any(k in t for k in TRAFFIC_KEYWORDS):
        tags.add("traffic")
    if any(k in t for k in ALERT_KEYWORDS):
        tags.add("alerts")
    if any(k in t for k in COMMUTE_KEYWORDS):
        tags.update({"weather", "trains", "alerts", "traffic"})
    if not tags:
        # Default to a lean commute snapshot when intent is unclear.
        tags.update({"weather", "alerts", "trains"})
    return tags
