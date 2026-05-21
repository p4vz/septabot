import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response

from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health():
    async with _client() as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@respx.mock
async def test_septa_alerts_filtered_by_mode():
    respx.get("https://www3.septa.org/api/Alerts/index.php").mock(
        return_value=Response(
            200,
            json=[
                {
                    "route_id": "MFL",
                    "route_name": "Market-Frankford Line",
                    "mode": "Rail",
                    "current_message": "Service operating with delays.",
                    "advisory_message": "",
                    "last_updated": "2026-05-21 09:00:00",
                },
                {
                    "route_id": "1",
                    "route_name": "Route 1",
                    "mode": "Bus",
                    "current_message": "On detour.",
                    "advisory_message": "",
                    "last_updated": "2026-05-21 09:00:00",
                },
            ],
        )
    )

    async with _client() as c:
        r = await c.get("/septa/alerts", params={"mode": "rail"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["route_id"] == "MFL"


@respx.mock
async def test_septa_trains_min_late():
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(
            200,
            json=[
                {
                    "trainno": "9501",
                    "line": "Paoli/Thorndale",
                    "dest": "Thorndale",
                    "currentstop": "Suburban",
                    "nextstop": "30th Street",
                    "late": 2,
                    "lat": "39.95",
                    "lon": "-75.17",
                    "service": "LOCAL",
                    "SOURCE": "Suburban",
                },
                {
                    "trainno": "9503",
                    "line": "Paoli/Thorndale",
                    "dest": "Thorndale",
                    "currentstop": "Suburban",
                    "nextstop": "30th Street",
                    "late": 12,
                    "lat": "39.95",
                    "lon": "-75.17",
                    "service": "LOCAL",
                    "SOURCE": "Suburban",
                },
            ],
        )
    )

    async with _client() as c:
        r = await c.get("/septa/trains", params={"min_late": 10})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["train_number"] == "9503"
    assert data[0]["late_minutes"] == 12


@respx.mock
async def test_weather_endpoint():
    respx.get("https://api.weather.gov/points/39.9526,-75.1652").mock(
        return_value=Response(
            200,
            json={
                "properties": {
                    "forecast": "https://api.weather.gov/gridpoints/PHI/50,75/forecast",
                    "forecastHourly": "https://api.weather.gov/gridpoints/PHI/50,75/forecast/hourly",
                    "cwa": "PHI",
                    "relativeLocation": {
                        "properties": {"city": "Philadelphia", "state": "PA"}
                    },
                }
            },
        )
    )
    respx.get("https://api.weather.gov/gridpoints/PHI/50,75/forecast").mock(
        return_value=Response(
            200,
            json={
                "properties": {
                    "periods": [
                        {
                            "name": "This Afternoon",
                            "startTime": "2026-05-21T13:00:00-04:00",
                            "endTime": "2026-05-21T18:00:00-04:00",
                            "temperature": 78,
                            "temperatureUnit": "F",
                            "windSpeed": "10 mph",
                            "windDirection": "SW",
                            "shortForecast": "Partly Sunny",
                            "detailedForecast": "Partly sunny, with a high near 78.",
                            "probabilityOfPrecipitation": {"value": 20},
                        }
                    ]
                }
            },
        )
    )

    async with _client() as c:
        r = await c.get("/weather")
    assert r.status_code == 200
    data = r.json()
    assert data["location"]["city"] == "Philadelphia"
    assert data["current"]["temperature"] == 78
    assert data["current"]["precipitation_probability"] == 20


async def test_traffic_empty_without_key():
    # No PA511_API_KEY in test env => client short-circuits to empty list.
    async with _client() as c:
        r = await c.get("/traffic")
    assert r.status_code == 200
    assert r.json() == []


@respx.mock
async def test_commute_aggregates():
    respx.get("https://www3.septa.org/api/Alerts/index.php").mock(
        return_value=Response(200, json=[])
    )
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(
            200,
            json=[
                {
                    "trainno": "1",
                    "line": "Paoli/Thorndale",
                    "dest": "X",
                    "currentstop": "A",
                    "nextstop": "B",
                    "late": 8,
                    "lat": "0",
                    "lon": "0",
                    "service": "L",
                    "SOURCE": "S",
                }
            ],
        )
    )
    respx.get("https://www3.septa.org/api/BusDetours/index.php").mock(
        return_value=Response(200, json=[])
    )
    respx.get("https://api.weather.gov/points/39.9526,-75.1652").mock(
        return_value=Response(
            200,
            json={
                "properties": {
                    "forecast": "https://api.weather.gov/x/forecast",
                    "forecastHourly": "https://api.weather.gov/x/hourly",
                    "cwa": "PHI",
                    "relativeLocation": {
                        "properties": {"city": "Philadelphia", "state": "PA"}
                    },
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
                            "name": "Tonight",
                            "startTime": "2026-05-21T18:00:00-04:00",
                            "endTime": "2026-05-22T06:00:00-04:00",
                            "temperature": 60,
                            "temperatureUnit": "F",
                            "windSpeed": "5 mph",
                            "windDirection": "N",
                            "shortForecast": "Clear",
                            "detailedForecast": "Clear.",
                            "probabilityOfPrecipitation": {"value": None},
                        }
                    ]
                }
            },
        )
    )

    async with _client() as c:
        r = await c.get("/commute", params={"min_late": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["weather"]["current"]["temperature"] == 60
    assert len(data["train_delays"]) == 1
    assert data["train_delays"][0]["late_minutes"] == 8
    assert data["traffic_events"] == []
    assert data["errors"] == {}
