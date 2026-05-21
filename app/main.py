from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import commute, septa, telegram, traffic, weather


STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="septabot backend",
    description=(
        "Backend API for a Philadelphia commuter bot. Aggregates SEPTA service alerts, "
        "regional rail train delays, bus detours, NWS weather, and 511PA traffic events. "
        "Includes a static dashboard at / and a Telegram webhook handler at /telegram/webhook."
    ),
    version="0.2.0",
)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


app.include_router(septa.router)
app.include_router(weather.router)
app.include_router(traffic.router)
app.include_router(commute.router)
app.include_router(telegram.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
