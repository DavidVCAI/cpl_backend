from fastapi import APIRouter, HTTPException
import httpx
import logging

from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/token", response_model=dict)
async def get_deepgram_token():
    """
    Get a temporary Deepgram API key for client-side transcription
    This allows the frontend to connect directly to Deepgram WebSocket
    """
    if not settings.DEEPGRAM_API_KEY:
        raise HTTPException(status_code=500, detail="Deepgram API key not configured")

    try:
        # Create a temporary project key (expires after some time)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.deepgram.com/v1/keys",
                headers={
                    "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "comment": "Temporary key for CityPulse Live transcription",
                    "scopes": ["usage:write"],
                    "time_to_live_in_seconds": 3600  # 1 hour
                },
                timeout=10.0
            )

            if response.status_code == 201:
                data = response.json()
                return {
                    "key": data["key"],
                    "expires_in": data.get("time_to_live_in_seconds", 3600)
                }
            else:
                # If temporary key creation fails, return the main key (less secure but works)
                logger.warning(f"Failed to create temporary Deepgram key: {response.status_code}")
                return {
                    "key": settings.DEEPGRAM_API_KEY,
                    "expires_in": 3600
                }

    except Exception as e:
        logger.error(f"Error getting Deepgram token: {e}")
        # Fallback to main key
        return {
            "key": settings.DEEPGRAM_API_KEY,
            "expires_in": 3600
        }
