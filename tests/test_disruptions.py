"""Tests for stuck-train inference: lines, bottlenecks, directions."""
import respx
from httpx import ASGITransport, AsyncClient, Response

from app.inference import _alert_matches_line, build_disruption_report, infer_train_direction
from app.main import app
from app.models import Alert, Train


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _train(num, line, dest, next_stop, late, *, lat="0", lon="0", **kw) -> Train:
    return Train.model_validate(
        {
            "trainno": num,
            "line": line,
            "dest": dest,
            "currentstop": kw.get("current", "A"),
            "nextstop": next_stop,
            "late": late,
            "lat": lat,
            "lon": lon,
            "service": "LOCAL",
            "SOURCE": "S",
        }
    )


def test_direction_inferred_from_destination():
    inbound = _train("1", "Paoli/Thorndale", "Suburban Station", "Bryn Mawr", 20)
    outbound = _train("2", "Paoli/Thorndale", "Thorndale", "Devon", 20)
    cc_alt = _train("3", "Wilmington/Newark", "Jefferson Station", "Temple U", 5)
    blank = _train("4", "X", "", "?", 0)
    assert inbound.direction == "inbound"
    assert outbound.direction == "outbound"
    assert cc_alt.direction == "inbound"
    assert blank.direction == "unknown"


def test_report_groups_bottleneck_by_next_stop_and_direction():
    trains = [
        _train("9501", "Paoli/Thorndale", "Thorndale", "Devon", 25),
        _train("9503", "Paoli/Thorndale", "Thorndale", "Devon", 32),
        _train("9505", "Paoli/Thorndale", "Thorndale", "Devon", 18),
        # Different direction at same next_stop -> separate bottleneck
        _train("9510", "Paoli/Thorndale", "Suburban Station", "Devon", 14),
        # On-time, ignored
        _train("9520", "Paoli/Thorndale", "Thorndale", "Devon", 3),
        # Different line
        _train("4521", "Lansdale/Doylestown", "Doylestown", "Glenside", 22),
    ]
    report = build_disruption_report(trains, alerts=[], threshold_minutes=10)

    assert report.total_trains == 6
    assert report.total_stuck == 5

    # worst line is Paoli/Thorndale (4 stuck)
    paoli = report.lines[0]
    assert paoli.line == "Paoli/Thorndale"
    assert paoli.stuck_count == 4
    assert paoli.max_late_minutes == 32
    assert paoli.outbound_stuck == 3
    assert paoli.inbound_stuck == 1

    # bottleneck order: outbound Devon (3 trains) first, then inbound Devon (1)
    assert paoli.bottlenecks[0].next_stop == "Devon"
    assert paoli.bottlenecks[0].direction == "outbound"
    assert paoli.bottlenecks[0].train_count == 3
    assert paoli.bottlenecks[0].max_late_minutes == 32
    assert paoli.bottlenecks[1].direction == "inbound"
    assert paoli.bottlenecks[1].train_count == 1

    # Lansdale comes after Paoli
    assert report.lines[1].line == "Lansdale/Doylestown"
    assert report.lines[1].stuck_count == 1


def test_report_correlates_matching_alerts():
    trains = [_train("9501", "Paoli/Thorndale", "Thorndale", "Devon", 25)]
    alerts = [
        Alert(
            route_id="PAO",
            route_name="Paoli/Thorndale Line",
            mode="Rail",
            current_message="Single-tracking between Devon and Strafford.",
        ),
        Alert(
            route_id="WAR",
            route_name="Warminster Line",
            mode="Rail",
            current_message="Normal service.",
        ),
        Alert(
            route_id="1",
            route_name="Route 1",
            mode="Bus",
            current_message="Detour.",
        ),
    ]
    report = build_disruption_report(trains, alerts, threshold_minutes=10)
    paoli = report.lines[0]
    assert len(paoli.alerts) == 1
    assert paoli.alerts[0].route_id == "PAO"


def test_report_threshold_filter():
    trains = [
        _train("1", "X", "Thorndale", "Devon", 5),
        _train("2", "X", "Thorndale", "Devon", 12),
    ]
    report_high = build_disruption_report(trains, [], threshold_minutes=10)
    report_low = build_disruption_report(trains, [], threshold_minutes=3)
    assert report_high.total_stuck == 1
    assert report_low.total_stuck == 2


@respx.mock
async def test_disruptions_endpoint_end_to_end():
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(
            200,
            json=[
                {"trainno": "9501", "line": "Paoli/Thorndale", "dest": "Thorndale",
                 "currentstop": "Devon", "nextstop": "Strafford", "late": 25,
                 "lat": "0", "lon": "0", "service": "L", "SOURCE": "S"},
                {"trainno": "9503", "line": "Paoli/Thorndale", "dest": "Thorndale",
                 "currentstop": "Devon", "nextstop": "Strafford", "late": 30,
                 "lat": "0", "lon": "0", "service": "L", "SOURCE": "S"},
                {"trainno": "9510", "line": "Paoli/Thorndale", "dest": "Suburban Station",
                 "currentstop": "Devon", "nextstop": "Strafford", "late": 14,
                 "lat": "0", "lon": "0", "service": "L", "SOURCE": "S"},
            ],
        )
    )
    respx.get("https://www3.septa.org/api/Alerts/index.php").mock(
        return_value=Response(
            200,
            json=[
                {"route_id": "PAO", "route_name": "Paoli/Thorndale",
                 "mode": "Rail",
                 "current_message": "Single-tracking near Strafford.",
                 "advisory_message": "",
                 "last_updated": "2026-05-23 17:00:00"},
            ],
        )
    )

    async with _client() as c:
        r = await c.get("/septa/disruptions", params={"min_late": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["total_stuck"] == 3
    assert data["lines"][0]["line"] == "Paoli/Thorndale"
    assert data["lines"][0]["bottlenecks"][0]["next_stop"] == "Strafford"
    assert data["lines"][0]["bottlenecks"][0]["direction"] == "outbound"
    assert len(data["lines"][0]["alerts"]) == 1


# ---- Direction inference precision (FP/FN fixes) ----


def test_direction_through_routed_inbound_leg():
    """A train south of Center City whose dest is north of CC must still
    cross CC to get there — it is INBOUND on its current leg, not outbound."""
    # Train south of Suburban Station, heading to Trenton (north).
    t = _train("5503", "Trenton", "Trenton", "Cornwells Heights",
               late=15, lat="39.8500", lon="-75.4500")
    assert infer_train_direction(t) == "inbound"


def test_direction_clear_outbound_same_side_as_dest():
    """Train already past Center City, between CC and its destination,
    heading outward — OUTBOUND."""
    # Train between Suburban (CC) and Paoli, heading to Paoli.
    t = _train("9501", "Paoli/Thorndale", "Paoli", "Bryn Mawr",
               late=12, lat="40.0050", lon="-75.2900")
    assert infer_train_direction(t) == "outbound"


def test_direction_destination_in_center_city_always_inbound():
    """If the destination IS a Center City station, direction is inbound
    regardless of train position."""
    t = _train("100", "Paoli/Thorndale", "Suburban Station", "Devon",
               late=20, lat="40.04", lon="-75.49")
    assert infer_train_direction(t) == "inbound"


def test_direction_unknown_with_blank_destination():
    t = _train("999", "X", "", "?", 0)
    assert infer_train_direction(t) == "unknown"


def test_direction_falls_back_to_heuristic_without_position():
    """No usable train coords AND dest not in CC -> assume outbound."""
    t = _train("9501", "Paoli/Thorndale", "Thorndale", "Devon", late=10)
    # lat/lon are "0"/"0" → fallback path → outbound
    assert infer_train_direction(t) == "outbound"


# ---- Alert matching precision (FP/FN fixes) ----


def test_alert_matches_by_route_id_even_without_line_name_in_text():
    """FN fix: alerts that only quote the SEPTA code (e.g. 'PAO') should
    still correlate to the line."""
    alert = Alert(
        route_id="PAO",
        route_name="",
        mode="Rail",
        current_message="Single-tracking through next two hours.",
    )
    assert _alert_matches_line(alert, "Paoli/Thorndale") is True
    assert _alert_matches_line(alert, "Warminster") is False


def test_alert_does_not_match_on_primary_token_substring():
    """FP fix: an alert mentioning 'Paoli Pike' (a road) with no PAO route_id
    must NOT be attached to the Paoli/Thorndale line."""
    alert = Alert(
        route_id="125",
        route_name="Route 125",
        mode="Bus",
        current_message="Detour around Paoli Pike construction zone.",
    )
    assert _alert_matches_line(alert, "Paoli/Thorndale") is False


def test_alert_matches_on_verbatim_line_name_in_message():
    alert = Alert(
        route_id="",
        route_name="",
        mode="Rail",
        current_message="Paoli/Thorndale service operating with 20 min delays.",
    )
    assert _alert_matches_line(alert, "Paoli/Thorndale") is True
    assert _alert_matches_line(alert, "Wilmington/Newark") is False


def test_alert_does_not_match_other_modes():
    alert = Alert(
        route_id="PAO",
        route_name="Paoli/Thorndale Line",
        mode="Trolley",  # wrong mode
        current_message="PAO single tracking.",
    )
    assert _alert_matches_line(alert, "Paoli/Thorndale") is False


@respx.mock
async def test_disruptions_endpoint_direction_filter():
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(
            200,
            json=[
                {"trainno": "1", "line": "Paoli/Thorndale", "dest": "Thorndale",
                 "currentstop": "A", "nextstop": "Devon", "late": 20,
                 "lat": "0", "lon": "0", "service": "L", "SOURCE": "S"},
                {"trainno": "2", "line": "Paoli/Thorndale", "dest": "Suburban Station",
                 "currentstop": "A", "nextstop": "Devon", "late": 25,
                 "lat": "0", "lon": "0", "service": "L", "SOURCE": "S"},
            ],
        )
    )
    respx.get("https://www3.septa.org/api/Alerts/index.php").mock(
        return_value=Response(200, json=[])
    )

    async with _client() as c:
        r = await c.get(
            "/septa/disruptions", params={"min_late": 10, "direction": "inbound"}
        )
    assert r.status_code == 200
    data = r.json()
    assert len(data["lines"]) == 1
    bottlenecks = data["lines"][0]["bottlenecks"]
    assert len(bottlenecks) == 1
    assert bottlenecks[0]["direction"] == "inbound"
    assert bottlenecks[0]["trains"][0]["train_number"] == "2"
