import respx
from httpx import ASGITransport, AsyncClient, Response

from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@respx.mock
async def test_weather_card_renders():
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
                            "startTime": "2026-05-21T13:00:00-04:00",
                            "endTime": "2026-05-21T18:00:00-04:00",
                            "temperature": 77,
                            "temperatureUnit": "F",
                            "windSpeed": "9 mph",
                            "windDirection": "W",
                            "shortForecast": "Mostly Sunny",
                            "detailedForecast": "",
                            "probabilityOfPrecipitation": {"value": 5},
                        }
                    ]
                }
            },
        )
    )

    async with _client() as c:
        r = await c.get("/ui/weather")
    assert r.status_code == 200
    assert "Mostly Sunny" in r.text
    assert "77°F" in r.text


@respx.mock
async def test_trains_card_filters_min_late():
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(
            200,
            json=[
                {"trainno": "1", "line": "X", "dest": "Y", "currentstop": "A", "nextstop": "B",
                 "late": 2, "lat": "0", "lon": "0", "service": "L", "SOURCE": "S"},
                {"trainno": "2", "line": "X", "dest": "Y", "currentstop": "A", "nextstop": "B",
                 "late": 11, "lat": "0", "lon": "0", "service": "L", "SOURCE": "S"},
            ],
        )
    )

    async with _client() as c:
        r = await c.get("/ui/trains?min_late=10")
    assert r.status_code == 200
    assert "#2" in r.text
    assert "#1" not in r.text


async def test_card_renders_error_message_on_upstream_failure():
    async with _client() as c:
        r = await c.get("/ui/weather", params={"lat": 0.0, "lon": 0.0})
    # Without respx mocks the outbound request will actually fly, but in CI
    # the sandbox blocks network: either way we should render an error string.
    assert r.status_code == 200
    assert "weather" in r.text.lower()


async def test_ui_all_returns_cards_fragment():
    async with _client() as c:
        r = await c.get("/ui/all")
    assert r.status_code == 200
    assert 'hx-get="/ui/weather"' in r.text
    assert 'hx-get="/ui/alerts"' in r.text
    assert 'hx-get="/ui/disruptions"' in r.text


@respx.mock
async def test_disruptions_card_renders_rollup():
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(
        return_value=Response(
            200,
            json=[
                {"trainno": "9501", "line": "Paoli/Thorndale", "dest": "Thorndale",
                 "currentstop": "Devon", "nextstop": "Strafford", "late": 28,
                 "lat": "40.05", "lon": "-75.40", "service": "L", "SOURCE": "S"},
                {"trainno": "9503", "line": "Paoli/Thorndale", "dest": "Thorndale",
                 "currentstop": "Devon", "nextstop": "Strafford", "late": 22,
                 "lat": "40.05", "lon": "-75.40", "service": "L", "SOURCE": "S"},
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
        r = await c.get("/ui/disruptions")
    assert r.status_code == 200
    assert "Paoli/Thorndale" in r.text
    assert "before" in r.text and "Strafford" in r.text
    assert "Single-tracking near Strafford" in r.text
