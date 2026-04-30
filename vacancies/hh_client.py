import requests
from django.conf import settings
from django.core.cache import cache


def _oauth_token():
    token = getattr(settings, "HH_API_TOKEN", "").strip()
    if token:
        return token

    cached = cache.get("hh:oauth:token")
    if cached:
        return cached

    client_id = getattr(settings, "HH_API_CLIENT_ID", "").strip()
    client_secret = getattr(settings, "HH_API_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return ""

    try:
        r = requests.post(
            "https://hh.ru/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=15,
            headers={"User-Agent": getattr(settings, "HH_API_USER_AGENT", "job-aggregator-diploma/1.0")},
        )
        r.raise_for_status()
        payload = r.json() if r.content else {}
        token = str(payload.get("access_token") or "").strip()
        if token:
            cache.set("hh:oauth:token", token, timeout=60 * 50)
            return token
    except Exception:
        return ""
    return ""


def hh_openapi_headers():
    headers = {
        "User-Agent": getattr(settings, "HH_API_USER_AGENT", "job-aggregator-diploma/1.0"),
    }
    token = _oauth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    client_id = getattr(settings, "HH_API_CLIENT_ID", "")
    client_secret = getattr(settings, "HH_API_CLIENT_SECRET", "")
    if client_id:
        headers["HH-Client-Id"] = client_id
    if client_secret:
        headers["HH-Client-Secret"] = client_secret
    return headers
