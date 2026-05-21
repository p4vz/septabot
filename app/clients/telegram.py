from typing import Optional

import httpx

from app.config import settings


TELEGRAM_API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


def _require_token() -> str:
    if not settings.telegram_bot_token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not configured")
    return settings.telegram_bot_token


async def send_message(chat_id: int, text: str, parse_mode: Optional[str] = "Markdown") -> None:
    token = _require_token()
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        r = await client.post(f"{TELEGRAM_API}/bot{token}/sendMessage", json=payload)
        if r.status_code >= 400 and parse_mode:
            # Markdown can break on user content; retry plain.
            payload.pop("parse_mode", None)
            r = await client.post(f"{TELEGRAM_API}/bot{token}/sendMessage", json=payload)
        if r.status_code >= 400:
            raise TelegramError(f"Telegram {r.status_code}: {r.text[:200]}")


async def set_webhook(url: str, secret_token: Optional[str] = None) -> dict:
    token = _require_token()
    payload: dict = {"url": url, "allowed_updates": ["message", "edited_message"]}
    if secret_token:
        payload["secret_token"] = secret_token
    async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
        r = await client.post(f"{TELEGRAM_API}/bot{token}/setWebhook", json=payload)
        r.raise_for_status()
        return r.json()
