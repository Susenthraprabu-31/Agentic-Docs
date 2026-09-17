from fastapi import APIRouter

from app.config.settings import get_settings

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/openai")
async def openai_config_status() -> dict:
    """Return whether OPENAI_API_KEY is configured — never exposes the key."""
    settings = get_settings()
    return {"configured": bool(settings.openai_api_key)}
