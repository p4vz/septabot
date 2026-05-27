"""Tests for the newer SEPTA endpoints: live vehicles (TransitView) and
elevator/escalator outages — REST routes, client parsing, and MCP tools."""
import respx
from httpx import ASGITransport, AsyncClient, Response

from app import mcp_server
from app.clients import septa as septa_client
from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_TRANSITVIEW = {
    "bus": [
        {
            "lat": "40.045227", "lng": "-75.125603", "label": "3354",
            "VehicleID": "3354", "route_id": "K", "Direction": "EastBound",
            "destination": "Arrott Transportation Center", "Offset": "19",
            "heading": 100, "late": 19, "next_stop_id": "31349",
            "next_stop_name": "Godfrey Av & 2nd St", "next_stop_sequence": 63,
            "estimated_seat_availability": "FEW_SEATS_AVAILABLE",
        },
        {
            "lat": "40.01", "lng": "-75.10", "label": "3360",
            "VehicleID": "3360", "route_id": "K", "Direction": "WestBound",
            "destination": "69th Street", "late": 0,
            "next_stop_name": "Bridge & Pratt", "next_stop_id": "200",
            "estimated_seat_availability": "MANY_SEATS_AVAILABLE",
        },
    ]
}

_ELEVATOR = {
    "meta": {"elevators_out": 2, "updated": "2026-05-27 13:00:00"},
    "results": [
        {
            "line": "Market Frankford Line", "station": "69th Street Transportation Center",
            "elevator": "Street to Mezzanine",
            "message": "<p>Elevator out of service until further notice.</p>",
            "alternate_url": "https://www.septa.org/",
        },
        {
            "line": "Broad Street Line", "station": "Walnut-Locust",
            "elevator": "Mezzanine to Platform", "message": "Out for repairs.",
            "alternate_url": "",
        },
    ],
}


@respx.mock
async def test_fetch_vehicles_parses_transitview():
    respx.get("https://www3.septa.org/api/TransitView/index.php").mock(
        return_value=Response(200, json=_TRANSITVIEW)
    )
    vehicles = await septa_client.fetch_vehicles("K")
    assert len(vehicles) == 2
    v = vehicles[0]
    assert v.vehicle_id == "3354"
    assert v.route_id == "K"
    assert v.lat == 40.045227
    assert v.lon == -75.125603  # mapped from "lng"
    assert v.late_minutes == 19
    assert v.next_stop == "Godfrey Av & 2nd St"
    assert v.seat_availability == "FEW_SEATS_AVAILABLE"


@respx.mock
async def test_vehicles_endpoint_filters_min_late():
    respx.get("https://www3.septa.org/api/TransitView/index.php").mock(
        return_value=Response(200, json=_TRANSITVIEW)
    )
    async with _client() as c:
        r = await c.get("/septa/vehicles", params={"route": "K", "min_late": 5})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["vehicle_id"] == "3354"


@respx.mock
async def test_fetch_elevator_outages_strips_html():
    respx.get("https://www3.septa.org/api/elevator/index.php").mock(
        return_value=Response(200, json=_ELEVATOR)
    )
    outages = await septa_client.fetch_elevator_outages()
    assert len(outages) == 2
    assert outages[0].station == "69th Street Transportation Center"
    assert outages[0].message == "Elevator out of service until further notice."
    assert outages[0].elevator == "Street to Mezzanine"


@respx.mock
async def test_elevator_endpoint_filters_by_station():
    respx.get("https://www3.septa.org/api/elevator/index.php").mock(
        return_value=Response(200, json=_ELEVATOR)
    )
    async with _client() as c:
        r = await c.get("/septa/elevator-outages", params={"station": "walnut"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["station"] == "Walnut-Locust"


@respx.mock
async def test_mcp_vehicle_locations_tool():
    respx.get("https://www3.septa.org/api/TransitView/index.php").mock(
        return_value=Response(200, json=_TRANSITVIEW)
    )
    result = await mcp_server.get_vehicle_locations("K")
    assert len(result) == 2
    assert result[0]["route"] == "K"
    assert result[0]["next_stop"] == "Godfrey Av & 2nd St"
    assert result[0]["late_min"] == 19


@respx.mock
async def test_mcp_elevator_outages_tool():
    respx.get("https://www3.septa.org/api/elevator/index.php").mock(
        return_value=Response(200, json=_ELEVATOR)
    )
    result = await mcp_server.get_elevator_outages()
    assert len(result) == 2
    assert {o["station"] for o in result} == {
        "69th Street Transportation Center",
        "Walnut-Locust",
    }


async def test_new_mcp_tools_registered():
    tools = {t.name for t in await mcp_server.mcp.list_tools()}
    assert "get_vehicle_locations" in tools
    assert "get_elevator_outages" in tools
