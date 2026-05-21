from fastapi import FastAPI

from app.routes import commute, septa, traffic, weather


app = FastAPI(
    title="septabot backend",
    description=(
        "Backend API for a Philadelphia commuter bot. Aggregates SEPTA service alerts, "
        "regional rail train delays, bus detours, NWS weather, and 511PA traffic events."
    ),
    version="0.1.0",
)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


app.include_router(septa.router)
app.include_router(weather.router)
app.include_router(traffic.router)
app.include_router(commute.router)
