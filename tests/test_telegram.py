from unittest.mock import AsyncMock, patch

import respx
from httpx import ASGITransport, AsyncClient, Response

from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_dashboard_served_at_root():
    async with _client() as c:
        r = await c.get("/")
    assert r.status_code == 200
    assert "<title>septabot" in r.text
    # HTMX is wired up and the cards declare their refresh endpoints.
    assert "htmx.org" in r.text
    assert 'hx-get="/ui/weather"' in r.text


async def test_static_style():
    async with _client() as c:
        css = await c.get("/static/style.css")
    assert css.status_code == 200


@respx.mock
async def test_telegram_webhook_help_no_hermes_call():
    sent: list[dict] = []

    async def fake_send(chat_id, text, parse_mode="Markdown"):
        sent.append({"chat_id": chat_id, "text": text})

    with patch("app.bot.handler.telegram.send_message", new=AsyncMock(side_effect=fake_send)):
        async with _client() as c:
            r = await c.post(
                "/telegram/webhook",
                json={
                    "update_id": 1,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 42, "type": "private"},
                        "text": "/help",
                    },
                },
            )
    assert r.status_code == 200
    assert sent and sent[0]["chat_id"] == 42
    assert "septabot" in sent[0]["text"]


@respx.mock
async def test_telegram_status_command_uses_backend_no_hermes():
    respx.get("https://www3.septa.org/api/Alerts/get_alert_data.php").mock(
        return_value=Response(
            200,
            json=[
                {
                    "route_id": "MFL",
                    "route_name": "Market-Frankford Line",
                    "mode": "Rail",
                    "current_message": "Single tracking near 30th.",
                    "advisory_message": "",
                    "last_updated": "2026-05-21 09:00:00",
                }
            ],
        )
    )
    respx.get("https://www3.septa.org/api/TrainView/index.php").mock(return_value=Response(200, json=[]))
    respx.get("https://www3.septa.org/api/BusDetours/index.php").mock(return_value=Response(200, json=[]))
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
                            "temperature": 72,
                            "temperatureUnit": "F",
                            "windSpeed": "8 mph",
                            "windDirection": "W",
                            "shortForecast": "Partly Sunny",
                            "detailedForecast": "",
                            "probabilityOfPrecipitation": {"value": 10},
                        }
                    ]
                }
            },
        )
    )

    sent: list[dict] = []

    async def fake_send(chat_id, text, parse_mode="Markdown"):
        sent.append({"chat_id": chat_id, "text": text})

    hermes_mock = AsyncMock()
    with (
        patch("app.bot.handler.telegram.send_message", new=AsyncMock(side_effect=fake_send)),
        patch("app.bot.handler.hermes.chat", new=hermes_mock),
    ):
        async with _client() as c:
            r = await c.post(
                "/telegram/webhook",
                json={
                    "update_id": 2,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 7, "type": "private"},
                        "text": "/status",
                    },
                },
            )

    assert r.status_code == 200
    assert hermes_mock.await_count == 0
    body = sent[0]["text"]
    assert "MFL" in body
    assert "72" in body


@respx.mock
async def test_telegram_freeform_calls_hermes_with_filtered_context():
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
                            "temperature": 65,
                            "temperatureUnit": "F",
                            "windSpeed": "12 mph",
                            "windDirection": "E",
                            "shortForecast": "Showers Likely",
                            "detailedForecast": "",
                            "probabilityOfPrecipitation": {"value": 70},
                        }
                    ]
                }
            },
        )
    )

    sent: list[dict] = []

    async def fake_send(chat_id, text, parse_mode="Markdown"):
        sent.append({"chat_id": chat_id, "text": text})

    async def fake_chat(system, user, **kwargs):
        # Verify that the prompt only carries weather context (no trains/alerts/traffic).
        assert '"weather"' in user
        assert '"trains"' not in user
        assert '"traffic"' not in user
        return "Yes, 70% chance of showers — bring an umbrella."

    with (
        patch("app.bot.handler.telegram.send_message", new=AsyncMock(side_effect=fake_send)),
        patch("app.bot.handler.hermes.chat", new=AsyncMock(side_effect=fake_chat)),
    ):
        async with _client() as c:
            r = await c.post(
                "/telegram/webhook",
                json={
                    "update_id": 3,
                    "message": {
                        "message_id": 3,
                        "chat": {"id": 9, "type": "private"},
                        "text": "will it rain this afternoon?",
                    },
                },
            )

    assert r.status_code == 200
    assert sent[0]["text"].startswith("Yes")


@respx.mock
async def test_telegram_freeform_drive_vs_train_pulls_routes_and_disruption():
    """A "from X to Y" question should populate both `drive` and `transit`
    sub-objects in the Hermes prompt, plus a disruption rollup so the bot
    can warn about active issues."""
    from app.config import settings as app_settings
    app_settings.google_maps_api_key = "test-key"

    respx.get("https://www3.septa.org/api/Alerts/get_alert_data.php").mock(
        return_value=Response(
            200,
            json=[
                {
                    "route_id": "PAO",
                    "route_name": "Paoli/Thorndale",
                    "mode": "Rail",
                    "current_message": "Single-tracking near Strafford.",
                    "advisory_message": "",
                    "last_updated": "2026-05-23 17:00:00",
                }
            ],
        )
    )
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

    sent: list[dict] = []
    captured_prompt = {}

    async def fake_send(chat_id, text, parse_mode="Markdown"):
        sent.append({"chat_id": chat_id, "text": text})

    async def fake_chat(system, user, **kwargs):
        captured_prompt["system"] = system
        captured_prompt["user"] = user
        return "Drive: 42 min with traffic. Train: also good. Paoli line has 1 stuck train near Strafford."

    with (
        patch("app.bot.handler.telegram.send_message", new=AsyncMock(side_effect=fake_send)),
        patch("app.bot.handler.hermes.chat", new=AsyncMock(side_effect=fake_chat)),
    ):
        async with _client() as c:
            r = await c.post(
                "/telegram/webhook",
                json={
                    "update_id": 99,
                    "message": {
                        "message_id": 99,
                        "chat": {"id": 11, "type": "private"},
                        "text": "should I drive or take the train from Wayne to Center City?",
                    },
                },
            )

    assert r.status_code == 200
    body = captured_prompt["user"]
    assert '"drive"' in body, "expected drive route in Hermes prompt"
    assert '"transit"' in body, "expected transit route in Hermes prompt"
    assert '"disruption"' in body, "expected disruption rollup in Hermes prompt"
    assert "duration_with_traffic_min" in body
    assert "Paoli/Thorndale" in body
    assert sent[0]["text"].startswith("Drive:")


async def test_telegram_webhook_secret_enforced(monkeypatch):
    monkeypatch.setattr("app.routes.telegram.settings.telegram_webhook_secret", "shh")
    async with _client() as c:
        r = await c.post(
            "/telegram/webhook",
            json={"update_id": 4, "message": {"message_id": 4, "chat": {"id": 1}, "text": "/help"}},
        )
    assert r.status_code == 401
