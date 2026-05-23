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


async def test_telegram_webhook_secret_enforced(monkeypatch):
    monkeypatch.setattr("app.routes.telegram.settings.telegram_webhook_secret", "shh")
    async with _client() as c:
        r = await c.post(
            "/telegram/webhook",
            json={"update_id": 4, "message": {"message_id": 4, "chat": {"id": 1}, "text": "/help"}},
        )
    assert r.status_code == 401
