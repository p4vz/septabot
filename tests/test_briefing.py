"""Tests for the commute_briefing MCP skill — the smart single-call tool that
returns only the data relevant to a natural-language question."""
import respx
from httpx import Response

from app import mcp_server
from app.config import settings


def _weather_mocks():
    respx.get("https://api.weather.gov/points/39.9526,-75.1652").mock(
        return_value=Response(
            200,
            json={
                "properties": {
                    "forecast": "https://api.weather.gov/x/forecast",
                    "forecastHourly": "https://api.weather.gov/x/hourly",
                    "cwa": "PHI",
                    "relativeLocation": {"properties": {"city": "Philadelphia", "state": "PA"}},
                }
            },
        )
    )
    respx.get("https://api.weather.gov/x/forecast").mock(
        return_value=Response(
            200,
            json={
                "properties": {
                    "periods": [
                        {
                            "name": "This Afternoon",
                            "startTime": "2026-05-27T13:00:00-04:00",
                            "endTime": "2026-05-27T18:00:00-04:00",
                            "temperature": 64,
                            "temperatureUnit": "F",
                            "windSpeed": "8 mph",
                            "windDirection": "W",
                            "shortForecast": "Patchy Fog",
                            "detailedForecast": "",
                            "probabilityOfPrecipitation": {"value": 90},
                        }
                    ]
                }
            },
        )
    )


async def test_briefing_registered_and_described():
    tools = {t.name: t for t in await mcp_server.mcp.list_tools()}
    assert "commute_briefing" in tools
    assert "only the data relevant" in tools["commute_briefing"].description.lower()


@respx.mock
async def test_briefing_weather_only_omits_transit():
    _weather_mocks()
    result = await mcp_server.commute_briefing("will I need an umbrella this afternoon?")
    assert "weather" in result
    assert result["_included"] == ["weather"]
    # No transit/route/traffic noise for a pure weather question.
    for k in ("trains", "disruption", "drive", "transit", "traffic", "alerts"):
        assert k not in result


@respx.mock
async def test_briefing_rail_question_includes_disruption_not_weather():
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(
            200,
            json=[
                {"trainno": "532", "line": "Paoli/Thorndale", "dest": "Thorndale",
                 "currentstop": "Strafford", "nextstop": "Devon", "late": 22,
                 "lat": "40.04", "lon": "-75.39", "service": "L", "SOURCE": "S"},
            ],
        )
    )
    respx.get("https://www3.septa.org/api/Alerts/get_alert_data.php").mock(
        return_value=Response(
            200,
            json=[
                {"route_id": "PAO", "route_name": "Paoli/Thorndale", "mode": "Rail",
                 "current_message": "Single-tracking near Strafford.",
                 "advisory_message": "", "last_updated": "2026-05-27 17:00:00"},
            ],
        )
    )
    result = await mcp_server.commute_briefing("how's the Paoli/Thorndale line right now?")
    assert "disruption" in result
    assert result.get("_line") == "Paoli/Thorndale"
    # The line filter was applied: only the Paoli line appears in the rollup.
    lines = [ln["line"] for ln in result["disruption"]["lines"]]
    assert lines == ["Paoli/Thorndale"]
    assert "weather" not in result


@respx.mock
async def test_briefing_drive_vs_train_includes_both_routes():
    settings.google_maps_api_key = "test-key"
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(200, json=[])
    )
    respx.get("https://www3.septa.org/api/Alerts/get_alert_data.php").mock(
        return_value=Response(200, json=[])
    )
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
    result = await mcp_server.commute_briefing(
        "should I drive or take the train from Wayne to Center City?"
    )
    assert "drive" in result and "transit" in result
    assert result["_route"] == {"origin": "Wayne", "destination": "Center City"}
    assert "drive" in result["_included"]
