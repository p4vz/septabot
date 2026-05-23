"""Inference layer: turn raw SEPTA train + alert feeds into a disruption rollup.

The bot needs to answer: which trains are stuck, on what lines, before which
stations, and in what directions? This module groups stuck trains by line,
then by bottleneck (next stop + direction), and correlates each line with
matching service alerts.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import (
    Alert,
    Bottleneck,
    DisruptionReport,
    LineDisruption,
    Train,
)


def _alert_matches_line(alert: Alert, line: str) -> bool:
    """An alert is relevant to a line if its route_name/text references it.

    SEPTA's alerts API uses `route_id` like 'PAO' (Paoli/Thorndale) for rail
    advisories, so we match on substrings of `route_name` and `current_message`
    rather than equality.
    """
    if (alert.mode or "").lower() not in ("rail", "regional rail", ""):
        return False
    line_l = line.lower()
    if not line_l or line_l == "unknown":
        return False
    haystacks = [
        (alert.route_name or "").lower(),
        (alert.current_message or "").lower(),
        (alert.advisory_message or "").lower(),
    ]
    # match either the full line ("paoli/thorndale") or its primary token ("paoli")
    primary = line_l.split("/")[0].strip()
    return any(line_l in h or (primary and primary in h) for h in haystacks)


def build_disruption_report(
    trains: list[Train], alerts: list[Alert], threshold_minutes: int = 10
) -> DisruptionReport:
    stuck = [t for t in trains if t.late_minutes >= threshold_minutes]

    by_line: dict[str, list[Train]] = {}
    for t in stuck:
        by_line.setdefault(t.line or "Unknown", []).append(t)

    lines_out: list[LineDisruption] = []
    for line_name, line_trains in by_line.items():
        # group by (next_stop, direction) bottleneck
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
        # surface the worst bottlenecks first (most trains, then most late)
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

    # worst lines first
    lines_out.sort(key=lambda ld: (-ld.stuck_count, -ld.max_late_minutes))

    return DisruptionReport(
        timestamp=datetime.now(timezone.utc),
        threshold_minutes=threshold_minutes,
        total_trains=len(trains),
        total_stuck=len(stuck),
        lines=lines_out,
    )
