from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.cache import cache
from app.clients import google as google_client
from app.config import settings
from app.models import RouteResult


router = APIRouter(prefix="/route", tags=["route"])


@router.get("/drive", response_model=RouteResult)
async def drive(
    origin: str = Query(..., description="Address or 'lat,lon'"),
    destination: str = Query(..., description="Address or 'lat,lon'"),
):
    """Driving directions with live traffic via Google Directions."""
    try:
        return await cache.get_or_set(
            f"route:drive:{origin.lower()}->{destination.lower()}",
            settings.cache_ttl_traffic,
            lambda: google_client.fetch_directions(origin, destination, mode="driving"),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/transit", response_model=RouteResult)
async def transit(
    origin: str = Query(..., description="Address or 'lat,lon'"),
    destination: str = Query(..., description="Address or 'lat,lon'"),
    departure_time: Optional[str] = Query(
        default=None,
        description="Epoch seconds or 'now'. Defaults to 'now'. Mutually exclusive with arrival_time.",
    ),
    arrival_time: Optional[str] = Query(
        default=None,
        description="Epoch seconds. Mutually exclusive with departure_time.",
    ),
):
    """SEPTA-aware door-to-door routing via Google Directions (mode=transit)."""
    if departure_time and arrival_time:
        raise HTTPException(
            status_code=400,
            detail="departure_time and arrival_time are mutually exclusive",
        )
    key_time = arrival_time or departure_time or "now"
    try:
        return await cache.get_or_set(
            f"route:transit:{origin.lower()}->{destination.lower()}:{key_time}",
            settings.cache_ttl_traffic,
            lambda: google_client.fetch_directions(
                origin,
                destination,
                mode="transit",
                departure_time=departure_time,
                arrival_time=arrival_time,
            ),
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
