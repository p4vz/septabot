"""Tests for stuck-train inference: lines, bottlenecks, directions."""
import respx
from httpx import ASGITransport, AsyncClient, Response

from app.inference import build_disruption_report
from app.main import app
from app.models import Alert, Train


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _train(num, line, dest, next_stop, late, **kw) -> Train:
    return Train.model_validate(
        {
            "trainno": num,
            "line": line,
            "dest": dest,
            "currentstop": kw.get("current", "A"),
            "nextstop": next_stop,
            "late": late,
            "lat": "0",
            "lon": "0",
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
