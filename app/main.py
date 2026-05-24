from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.mcp_server import mcp
from app.routes import commute, route, septa, telegram, traffic, ui, weather


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
TEMPLATES = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Build the MCP Streamable-HTTP sub-app once. This also lazily creates the
# session manager, which must be run inside the app lifespan below.
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="septabot backend",
    description=(
        "Backend API for a Philadelphia commuter bot. Aggregates SEPTA service alerts, "
        "regional rail train delays, bus detours, NWS weather, and 511PA traffic events. "
        "Includes a Jinja+HTMX dashboard at /, JSON endpoints, and an MCP server at /mcp "
        "for downstream agents (e.g. Hermes)."
    ),
    version="0.4.0",
    lifespan=lifespan,
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


async def _guard_mcp(request: Request, call_next):
    """Optional shared-secret gate on the MCP endpoint.

    If MCP_AUTH_TOKEN is set, require a matching `Authorization: Bearer <token>`
    header. Left unset (the default), the endpoint is open — fine when Hermes
    reaches Septabot over Railway's private network, which isn't publicly
    routable. Set the token if you expose /mcp on the public URL.
    """
    if settings.mcp_auth_token:
        provided = request.headers.get("authorization", "")
        expected = f"Bearer {settings.mcp_auth_token}"
        if provided != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


mcp_app.add_middleware(BaseHTTPMiddleware, dispatch=_guard_mcp)
app.mount("/mcp", mcp_app)


@app.get("/", include_in_schema=False, response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(request, "dashboard.html")
