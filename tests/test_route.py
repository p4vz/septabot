"""Tests for Google-backed /route/drive and /route/transit endpoints."""
import respx
from httpx import ASGITransport, AsyncClient, Response

from app.config import settings
from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_drive_returns_502_without_key():
    saved = settings.google_maps_api_key
    settings.google_maps_api_key = ""
    try:
        async with _client() as c:
            r = await c.get("/route/drive", params={"origin": "A", "destination": "B"})
        assert r.status_code == 502
        assert "GOOGLE_MAPS_API_KEY" in r.json()["detail"]
    finally:
        settings.google_maps_api_key = saved


@respx.mock
async def test_drive_parses_duration_in_traffic():
    settings.google_maps_api_key = "test-key"
    respx.get("https://maps.googleapis.com/maps/api/directions/json").mock(
        return_value=Response(
            200,
            json={
                "status": "OK",
                "routes": [
                    {
                        "summary": "I-95 S",
                        "warnings": [],
                        "legs": [
                            {
                                "start_address": "Wayne, PA",
                                "end_address": "Philadelphia, PA",
                                "distance": {"text": "19 mi", "value": 30577},
                                "duration": {"text": "28 mins", "value": 1680},
                                "duration_in_traffic": {"text": "42 mins", "value": 2520},
                                "steps": [
                                    {
                                        "travel_mode": "DRIVING",
                                        "html_instructions": "Head <b>south</b> on US-30",
                                        "distance": {"value": 800},
                                        "duration": {"value": 90},
                                    }
                                ],
                            }
                        ],
                        "overview_polyline": {"points": "abc123"},
                    }
                ],
            },
        )
    )

    async with _client() as c:
        r = await c.get(
            "/route/drive", params={"origin": "Wayne PA", "destination": "Philadelphia PA"}
        )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "driving"
    assert data["total_duration_seconds"] == 1680
    assert data["total_duration_in_traffic_seconds"] == 2520
    assert data["legs"][0]["steps"][0]["instruction"] == "Head  south  on US-30"
    assert data["polyline"] == "abc123"


@respx.mock
async def test_transit_parses_septa_legs():
    settings.google_maps_api_key = "test-key"
    respx.get("https://maps.googleapis.com/maps/api/directions/json").mock(
        return_value=Response(
            200,
            json={
                "status": "OK",
                "routes": [
                    {
                        "summary": "Paoli/Thorndale Line",
                        "warnings": [],
                        "legs": [
                            {
                                "start_address": "Wayne Station, Wayne, PA",
                                "end_address": "1500 Market St, Philadelphia, PA",
                                "distance": {"value": 27800},
                                "duration": {"value": 2400},
                                "departure_time": {"text": "5:13 PM"},
                                "arrival_time": {"text": "5:53 PM"},
                                "steps": [
                                    {
                                        "travel_mode": "WALKING",
                                        "html_instructions": "Walk to Wayne Station",
                                        "distance": {"value": 220},
                                        "duration": {"value": 180},
                                    },
                                    {
                                        "travel_mode": "TRANSIT",
                                        "html_instructions": "Take the Paoli/Thorndale train",
                                        "distance": {"value": 27200},
                                        "duration": {"value": 1800},
                                        "transit_details": {
                                            "headsign": "Suburban Station",
                                            "num_stops": 9,
                                            "departure_stop": {"name": "Wayne"},
                                            "arrival_stop": {"name": "Suburban Station"},
                                            "departure_time": {"text": "5:13 PM"},
                                            "arrival_time": {"text": "5:42 PM"},
                                            "line": {
                                                "name": "Paoli/Thorndale",
                                                "short_name": "PAO",
                                                "vehicle": {"type": "HEAVY_RAIL"},
                                            },
                                        },
                                    },
                                    {
                                        "travel_mode": "WALKING",
                                        "html_instructions": "Walk to 1500 Market",
                                        "distance": {"value": 380},
                                        "duration": {"value": 420},
                                    },
                                ],
                            }
                        ],
                        "fare": {"currency": "USD", "value": 6.5},
                    }
                ],
            },
        )
    )

    async with _client() as c:
        r = await c.get(
            "/route/transit",
            params={"origin": "Wayne Station", "destination": "1500 Market St Philadelphia"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "transit"
    assert data["summary"] == "Paoli/Thorndale Line"
    assert data["fare"] == {"currency": "USD", "value": 6.5}
    steps = data["legs"][0]["steps"]
    assert len(steps) == 3
    transit_step = steps[1]
    assert transit_step["mode"] == "TRANSIT"
    assert transit_step["transit_line"] == "Paoli/Thorndale"
    assert transit_step["transit_short_name"] == "PAO"
    assert transit_step["transit_vehicle"] == "HEAVY_RAIL"
    assert transit_step["departure_stop"] == "Wayne"
    assert transit_step["arrival_stop"] == "Suburban Station"
    assert transit_step["transit_num_stops"] == 9


@respx.mock
async def test_transit_rejects_both_departure_and_arrival():
    settings.google_maps_api_key = "test-key"
    async with _client() as c:
        r = await c.get(
            "/route/transit",
            params={
                "origin": "A",
                "destination": "B",
                "departure_time": "now",
                "arrival_time": "1234567890",
            },
        )
    assert r.status_code == 400


@respx.mock
async def test_drive_propagates_google_error_status_as_502():
    settings.google_maps_api_key = "test-key"
    respx.get("https://maps.googleapis.com/maps/api/directions/json").mock(
        return_value=Response(
            200,
            json={"status": "ZERO_RESULTS", "routes": [], "error_message": "no route"},
        )
    )
    async with _client() as c:
        r = await c.get("/route/drive", params={"origin": "X", "destination": "Y"})
    assert r.status_code == 502
    assert "ZERO_RESULTS" in r.json()["detail"]
