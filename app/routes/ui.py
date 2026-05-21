"""HTMX fragment endpoints for the dashboard."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.cache import cache
from app.clients import septa as septa_client
from app.clients import traffic as traffic_client
from app.clients import weather as weather_client
from app.config import settings

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

router = APIRouter(prefix="/ui", tags=["ui"])


@router.get("/all")
async def all_cards(request: Request):
    return TEMPLATES.TemplateResponse(request, "_cards.html")


@router.get("/weather")
async def weather_card(request: Request, lat: float | None = None, lon: float | None = None):
    lat = lat if lat is not None else settings.default_lat
    lon = lon if lon is not None else settings.default_lon
    ctx: dict = {"weather": None, "error": None}
    try:
        ctx["weather"] = await cache.get_or_set(
            f"weather:{lat:.3f}:{lon:.3f}:False",
            settings.cache_ttl_weather,
            lambda: weather_client.fetch_forecast(lat, lon),
        )
    except Exception as e:
        ctx["error"] = f"weather unavailable ({type(e).__name__})"
    return TEMPLATES.TemplateResponse(request, "_weather.html", ctx)


@router.get("/alerts")
async def alerts_card(request: Request):
    ctx: dict = {"alerts": [], "error": None}
    try:
        ctx["alerts"] = await cache.get_or_set(
            "septa:alerts", settings.cache_ttl_alerts, septa_client.fetch_alerts
        )
    except Exception as e:
        ctx["error"] = f"alerts unavailable ({type(e).__name__})"
    return TEMPLATES.TemplateResponse(request, "_alerts.html", ctx)


@router.get("/trains")
async def trains_card(request: Request, min_late: int = 5):
    ctx: dict = {"trains": [], "error": None}
    try:
        trains = await cache.get_or_set(
            "septa:trains", settings.cache_ttl_trains, septa_client.fetch_trains
        )
        ctx["trains"] = sorted(
            (t for t in trains if t.late_minutes >= min_late),
            key=lambda t: t.late_minutes,
            reverse=True,
        )[:15]
    except Exception as e:
        ctx["error"] = f"trains unavailable ({type(e).__name__})"
    return TEMPLATES.TemplateResponse(request, "_trains.html", ctx)


@router.get("/detours")
async def detours_card(request: Request):
    ctx: dict = {"detours": [], "error": None}
    try:
        ctx["detours"] = await cache.get_or_set(
            "septa:bus-detours", settings.cache_ttl_alerts, septa_client.fetch_bus_detours
        )
    except Exception as e:
        ctx["error"] = f"detours unavailable ({type(e).__name__})"
    return TEMPLATES.TemplateResponse(request, "_detours.html", ctx)


@router.get("/traffic")
async def traffic_card(request: Request, lat: float | None = None, lon: float | None = None):
    lat = lat if lat is not None else settings.default_lat
    lon = lon if lon is not None else settings.default_lon
    ctx: dict = {"traffic": [], "error": None}
    try:
        ctx["traffic"] = await cache.get_or_set(
            f"traffic:{lat:.3f}:{lon:.3f}:25.0",
            settings.cache_ttl_traffic,
            lambda: traffic_client.fetch_events(lat, lon, 25.0),
        )
    except Exception as e:
        ctx["error"] = f"traffic unavailable ({type(e).__name__})"
    return TEMPLATES.TemplateResponse(request, "_traffic.html", ctx)
