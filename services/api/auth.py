"""
Simple API key authentication for Phase 1.
Validates X-API-Key header against the configured key.
"""

from fastapi import Header, HTTPException, status

from shared.config import get_settings

settings = get_settings()


async def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    """FastAPI dependency: validates API key from request header."""
    if x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return x_api_key
