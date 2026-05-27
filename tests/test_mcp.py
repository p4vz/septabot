"""Tests for the MCP server: tool registration + tool-body behavior.

The tool functions are exercised directly (the @mcp.tool() decorator returns
the original coroutine) with upstreams mocked via respx — same pattern as the
REST route tests.
"""
import respx
from httpx import ASGITransport, AsyncClient, Response

from app import mcp_server
from app.config import settings
from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_all_tools_registered():
    tools = await mcp_server.mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "get_rail_disruptions",
        "get_train_delays",
        "get_service_alerts",
        "get_bus_detours",
        "get_vehicle_locations",
        "get_elevator_outages",
        "get_next_to_arrive",
        "get_station_arrivals",
        "get_train_schedule",
        "get_weather",
        "get_traffic",
        "drive_route",
        "transit_route",
    }


async def test_every_tool_has_a_description():
    # Hermes relies on these to decide when to call each tool.
    tools = await mcp_server.mcp.list_tools()
    for t in tools:
        assert t.description and len(t.description) > 20, t.name


@respx.mock
async def test_get_train_delays_tool():
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(
            200,
            json=[
                {"trainno": "532", "line": "Paoli/Thorndale", "dest": "Thorndale",
                 "currentstop": "Strafford", "nextstop": "Devon", "late": 22,
                 "lat": "40.04", "lon": "-75.39", "service": "L", "SOURCE": "S"},
                {"trainno": "9", "line": "Airport", "dest": "PHL",
                 "currentstop": "Eastwick", "nextstop": "PHL", "late": 2,
                 "lat": "39.9", "lon": "-75.2", "service": "L", "SOURCE": "S"},
            ],
        )
    )
    result = await mcp_server.get_train_delays(min_late=5)
    assert len(result) == 1  # only the 22-min-late train clears the threshold
    assert result[0]["train"] == "532"
    assert result[0]["late_min"] == 22


@respx.mock
async def test_drive_route_tool_returns_none_without_key():
    saved = settings.google_maps_api_key
    settings.google_maps_api_key = ""
    try:
        assert await mcp_server.drive_route("Wayne", "Center City") is None
    finally:
        settings.google_maps_api_key = saved


@respx.mock
async def test_drive_route_tool_summarizes_traffic():
    settings.google_maps_api_key = "test-key"
    respx.get("https://maps.googleapis.com/maps/api/directions/json").mock(
        return_value=Response(
            200,
            json={
                "status": "OK",
                "routes": [
                    {
                        "summary": "I-76 E",
                        "warnings": [],
                        "legs": [
                            {
                                "start_address": "Wayne, PA",
                                "end_address": "Center City, Philadelphia, PA",
                                "distance": {"value": 30577},
                                "duration": {"value": 1680},
                                "duration_in_traffic": {"value": 2520},
                                "steps": [],
                            }
                        ],
                    }
                ],
            },
        )
    )
    result = await mcp_server.drive_route("Wayne", "Center City")
    assert result["mode"] == "driving"
    assert result["duration_with_traffic_min"] == 42
    assert result["distance_mi"] == 19.0


async def test_mcp_endpoint_mounted_and_speaks_protocol():
    # Full MCP initialize handshake through the mounted app, proving the mount
    # and the session-manager lifespan are wired up. The lifespan must be
    # entered explicitly because ASGITransport doesn't run it on its own.
    async with app.router.lifespan_context(app):
        async with _client() as c:
            r = await c.post(
                "/mcp/",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["serverInfo"]["name"] == "septabot"


async def test_mcp_auth_gate_rejects_bad_token(monkeypatch):
    monkeypatch.setattr("app.main.settings.mcp_auth_token", "s3cret")
    async with _client() as c:
        r = await c.post(
            "/mcp/",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer wrong",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "t", "version": "1"}}},
        )
    assert r.status_code == 401
