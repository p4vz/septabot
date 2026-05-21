from fastapi import APIRouter, HTTPException, Request

from app.bot import handler
from app.clients import telegram as telegram_client
from app.config import settings

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/webhook")
async def webhook(request: Request) -> dict:
    if settings.telegram_webhook_secret:
        provided = request.headers.get("x-telegram-bot-api-secret-token", "")
        if provided != settings.telegram_webhook_secret:
            raise HTTPException(status_code=401, detail="bad secret token")
    update = await request.json()
    await handler.handle_update(update)
    return {"ok": True}


@router.post("/set-webhook")
async def set_webhook(url: str) -> dict:
    """Convenience endpoint to register the Telegram webhook.

    Pass the public URL (e.g. https://your.railway.app/telegram/webhook).
    """
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN not configured")
    return await telegram_client.set_webhook(url, settings.telegram_webhook_secret or None)
