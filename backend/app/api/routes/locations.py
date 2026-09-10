from fastapi import APIRouter, HTTPException

from app.config.states import US_STATES
from app.extraction.netronline_locations import fetch_counties_for_state

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("/states")
async def list_states() -> list[dict[str, str]]:
    return US_STATES


@router.get("/states/{state_code}/counties")
async def list_counties(state_code: str) -> list[dict[str, str]]:
    code = state_code.upper()
    valid = {s["code"] for s in US_STATES}
    if code not in valid:
        raise HTTPException(status_code=404, detail=f"Unknown state: {state_code}")

    counties = fetch_counties_for_state(code)
    if not counties:
        raise HTTPException(
            status_code=502,
            detail=f"Could not load counties for {code} from NETR Online",
        )
    return counties
