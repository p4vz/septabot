"""Tests for the train-routing endpoints: arrivals, next-to-arrive, stations."""
import respx
from httpx import ASGITransport, AsyncClient, Response

from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@respx.mock
async def test_arrivals_parses_directions():
    respx.get("https://www3.septa.org/api/Arrivals/index.php").mock(
        return_value=Response(
            200,
            json={
                "Suburban Station": [
                    {
                        "Northbound": [
                            {
                                "direction": "N",
                                "line": "Paoli/Thorndale",
                                "train_id": "9210",
                                "origin": "30th Street Station",
                                "destination": "Thorndale",
                                "status": "On time",
                                "service_type": "LOCAL",
                                "next_station": "Suburban Station",
                                "sched_time": "2026-05-23 17:13:00",
                                "depart_time": "2026-05-23 17:13:00",
                                "track": "5",
                                "platform": "5",
                            }
                        ],
                        "Southbound": [
                            {
                                "direction": "S",
                                "line": "Wilmington/Newark",
                                "train_id": "5503",
                                "origin": "Trenton",
                                "destination": "Wilmington",
                                "status": "8 min",
                                "service_type": "LOCAL",
                                "next_station": "Suburban Station",
                                "sched_time": "2026-05-23 17:15:00",
                                "depart_time": "2026-05-23 17:23:00",
                                "track": "3",
                                "platform": "3",
                            }
                        ],
                    }
                ]
            },
        )
    )

    async with _client() as c:
        r = await c.get(
            "/septa/arrivals", params={"station": "Suburban Station", "results": 5}
        )
    assert r.status_code == 200
    data = r.json()
    assert data["station"] == "Suburban Station"
    assert len(data["northbound"]) == 1
    assert data["northbound"][0]["train_id"] == "9210"
    assert data["northbound"][0]["status"] == "On time"
    assert len(data["southbound"]) == 1
    assert data["southbound"][0]["destination"] == "Wilmington"
    assert data["southbound"][0]["track"] == "3"


@respx.mock
async def test_arrivals_empty_response():
    respx.get("https://www3.septa.org/api/Arrivals/index.php").mock(
        return_value=Response(200, json={})
    )
    async with _client() as c:
        r = await c.get("/septa/arrivals", params={"station": "Nowhere"})
    assert r.status_code == 200
    body = r.json()
    assert body["northbound"] == []
    assert body["southbound"] == []


@respx.mock
async def test_next_to_arrive_direct_and_transfer():
    respx.get("https://www3.septa.org/api/NextToArrive/index.php").mock(
        return_value=Response(
            200,
            json=[
                {
                    "orig_train": "9210",
                    "orig_line": "Paoli/Thorndale",
                    "orig_departure_time": "5:13 PM",
                    "orig_arrival_time": "5:42 PM",
                    "orig_delay": "On time",
                    "isdirect": "true",
                },
                {
                    "orig_train": "4521",
                    "orig_line": "Lansdale/Doylestown",
                    "orig_departure_time": "5:20 PM",
                    "orig_arrival_time": "5:55 PM",
                    "orig_delay": "5 min",
                    "isdirect": "false",
                    "Connection": "Jenkintown-Wyncote",
                    "term_train": "812",
                    "term_line": "West Trenton",
                    "term_departure_time": "6:02 PM",
                    "term_arrival_time": "6:25 PM",
                    "term_delay": "On time",
                },
            ],
        )
    )

    async with _client() as c:
        r = await c.get(
            "/septa/next-to-arrive",
            params={"origin": "Wayne", "destination": "Suburban Station", "results": 5},
        )
    assert r.status_code == 200
    options = r.json()
    assert len(options) == 2
    assert options[0]["is_direct"] is True
    assert options[0]["orig_train"] == "9210"
    assert options[1]["is_direct"] is False
    assert options[1]["connection_station"] == "Jenkintown-Wyncote"
    assert options[1]["term_train"] == "812"


async def test_stations_list_default():
    async with _client() as c:
        r = await c.get("/septa/stations")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()]
    assert "30th Street Station" in names
    assert "Suburban Station" in names


async def test_stations_search_substring():
    async with _client() as c:
        r = await c.get("/septa/stations", params={"search": "paoli"})
    assert r.status_code == 200
    names = [s["name"] for s in r.json()]
    assert "Paoli" in names
    # 30th Street shouldn't match a "paoli" query
    assert "30th Street Station" not in names


async def test_stations_nearest_to_center_city():
    # City Hall is closest to Suburban Station.
    async with _client() as c:
        r = await c.get(
            "/septa/stations", params={"lat": 39.9526, "lon": -75.1652, "limit": 1}
        )
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "Suburban Station"
    assert data[0]["distance_miles"] is not None
    assert data[0]["distance_miles"] < 1.0


async def test_stations_nearest_to_wayne_pa():
    async with _client() as c:
        r = await c.get(
            "/septa/stations", params={"lat": 40.0432, "lon": -75.3886, "limit": 1}
        )
    assert r.status_code == 200
    data = r.json()
    assert data[0]["name"] == "Wayne"


async def test_stations_rejects_partial_coords():
    async with _client() as c:
        r = await c.get("/septa/stations", params={"lat": 40.0})
    assert r.status_code == 400
