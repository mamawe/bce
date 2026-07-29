"""Feishu tenant access token management with auto-refresh."""
import time
import logging
import httpx
from .config import LARK_APP_ID, LARK_APP_SECRET, LARK_BASE_URL

logger = logging.getLogger(__name__)

_token_cache: dict = {"token": "", "expires_at": 0}


async def get_tenant_access_token() -> str:
    """Get a valid tenant_access_token, refreshing if needed."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{LARK_BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET},
        )
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Failed to get tenant_access_token: {data}")

    token = data["tenant_access_token"]
    expire = data.get("expire", 7200)
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + min(expire - 200, 6000)
    logger.info("Feishu tenant_access_token refreshed, expires in %ds", expire)
    return token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
