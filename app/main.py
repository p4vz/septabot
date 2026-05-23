from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routes import commute, route, septa, telegram, traffic, ui, weather


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
TEMPLATES = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(
    title="septabot backend",
    description=(
        "Backend API for a Philadelphia commuter bot. Aggregates SEPTA service alerts, "
        "regional rail train delays, bus detours, NWS weather, and 511PA traffic events. "
        "Includes a Jinja+HTMX dashboard at / and JSON endpoints for downstream agents."
    ),
    version="0.3.0",
)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}


app.include_router(septa.router)
app.include_router(weather.router)
app.include_router(traffic.router)
app.include_router(route.router)
app.include_router(commute.router)
app.include_router(telegram.router)
app.include_router(ui.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "dashboard.html")
