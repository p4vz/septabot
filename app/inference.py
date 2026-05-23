"""Inference layer: turn raw SEPTA train + alert feeds into a disruption rollup.

Two interpretation steps live here that the raw feeds don't give us:

1. Direction inference — which trains are heading *into* Center City vs *away*.
   Regional Rail through-routes via Center City, so a train whose final
   destination is, say, Trenton can be currently inbound (still has to pass
   through CC) or outbound (already past CC). We use the train's reported
   lat/lon vs the destination's coordinates to disambiguate.

2. Alert ↔ line correlation — SEPTA's Alerts API uses short route codes
   ('PAO', 'WIL', ...) while TrainView uses full line names. We map both
   ways and require either a code match or a verbatim line-name match,
   not a substring on the line's primary token (which produces false
   positives like "Paoli Pike" matching the Paoli/Thorndale line).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.data.rail_lines import line_from_route_id
from app.data.stations import station_by_name
from app.models import (
    CENTER_CITY_STATIONS,
    Alert,
    Bottleneck,
    DisruptionReport,
    LineDisruption,
    Train,
)


# Suburban Station as the Center City reference point.
CC_LAT = 39.9540
CC_LON = -75.1670


def infer_train_direction(train: Train) -> str:
    """Direction of the train's *current* motion relative to Center City.

    Returns 'inbound', 'outbound', or 'unknown'.

    Strategy, in order:
      1. If the destination is itself a Center City station -> inbound (definitive).
      2. If we have both the train's lat/lon and the destination's coords:
         - Are the train and the destination on opposite sides of Center City?
           Then the train must traverse CC to reach the destination ->
           currently inbound.
         - Same side, train closer to CC than destination ->
           heading toward the destination away from CC -> outbound.
         - Same side, train past destination from CC (rare) -> inbound.
      3. Fallback: destination is outside Center City and we lack coords ->
         outbound.
    """
    dest = (train.destination or "").strip()
    if not dest:
        return "unknown"

    dest_l = dest.lower()
    if dest_l in CENTER_CITY_STATIONS or any(cc in dest_l for cc in CENTER_CITY_STATIONS):
        return "inbound"

    dest_station = station_by_name(dest)
    has_valid_position = abs(train.lat) > 1 and abs(train.lon) > 1
    if dest_station and has_valid_position:
        tx, ty = train.lon - CC_LON, train.lat - CC_LAT
        dx, dy = dest_station.lon - CC_LON, dest_station.lat - CC_LAT
        # Dot product of CC->train and CC->dest. Negative means opposite sides.
        if (tx * dx + ty * dy) < 0:
            return "inbound"
        # Same side of CC; compare squared distances from CC.
        if (tx * tx + ty * ty) < (dx * dx + dy * dy):
            return "outbound"
        return "inbound"

    return "outbound"


def enrich_directions(trains: list[Train]) -> None:
    """Compute and set `direction` on every train using the best available signal."""
    for t in trains:
        t.direction = infer_train_direction(t)


def _alert_matches_line(alert: Alert, line: str) -> bool:
    """True if an alert is talking about a specific Regional Rail line.

    Matching is intentionally strict to avoid false positives:
      - Mode must be rail (or blank, which SEPTA occasionally returns).
      - Either the alert's `route_id` maps to this line via the canonical
        SEPTA code table, OR the full line name appears verbatim somewhere
        in the alert's route_name / current_message / advisory_message.
    """
    if not line or line.lower() == "unknown":
        return False
    if (alert.mode or "").lower() not in ("rail", "regional rail", "regional_rail", ""):
        return False

    rid_line = line_from_route_id(alert.route_id or "")
    if rid_line and rid_line.lower() == line.lower():
        return True

    line_l = line.lower()
    haystacks = (
        (alert.route_name or "").lower(),
        (alert.current_message or "").lower(),
        (alert.advisory_message or "").lower(),
    )
    return any(line_l in h for h in haystacks)


def build_disruption_report(
    trains: list[Train], alerts: list[Alert], threshold_minutes: int = 10
) -> DisruptionReport:
    enrich_directions(trains)

    stuck = [t for t in trains if t.late_minutes >= threshold_minutes]

    by_line: dict[str, list[Train]] = {}
    for t in stuck:
        by_line.setdefault(t.line or "Unknown", []).append(t)

    lines_out: list[LineDisruption] = []
    for line_name, line_trains in by_line.items():
        groups: dict[tuple[str, str], list[Train]] = {}
        for t in line_trains:
            key = (t.next_stop or "?", t.direction)
            groups.setdefault(key, []).append(t)

        bottlenecks = [
            Bottleneck(
                next_stop=k[0],
                direction=k[1],
                train_count=len(v),
                max_late_minutes=max(t.late_minutes for t in v),
                trains=sorted(v, key=lambda x: -x.late_minutes),
            )
            for k, v in groups.items()
        ]
        bottlenecks.sort(key=lambda b: (-b.train_count, -b.max_late_minutes))

        lines_out.append(
            LineDisruption(
                line=line_name,
                stuck_count=len(line_trains),
                max_late_minutes=max(t.late_minutes for t in line_trains),
                inbound_stuck=sum(1 for t in line_trains if t.direction == "inbound"),
                outbound_stuck=sum(1 for t in line_trains if t.direction == "outbound"),
                bottlenecks=bottlenecks,
                alerts=[a for a in alerts if _alert_matches_line(a, line_name)],
            )
        )

    lines_out.sort(key=lambda ld: (-ld.stuck_count, -ld.max_late_minutes))

    return DisruptionReport(
        timestamp=datetime.now(timezone.utc),
        threshold_minutes=threshold_minutes,
        total_trains=len(trains),
        total_stuck=len(stuck),
        lines=lines_out,
    )
