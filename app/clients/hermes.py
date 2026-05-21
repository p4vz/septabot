from typing import Optional

import httpx

from app.config import settings


class HermesError(RuntimeError):
    pass


async def chat(
    system: str,
    user: str,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> str:
    if not settings.hermes_base_url:
        raise HermesError("HERMES_BASE_URL is not configured")

    headers = {"Content-Type": "application/json"}
    if settings.hermes_api_key:
        headers["Authorization"] = f"Bearer {settings.hermes_api_key}"

    payload = {
        "model": settings.hermes_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens or settings.hermes_max_tokens,
        "temperature": settings.hermes_temperature if temperature is None else temperature,
        "stream": False,
    }

    url = settings.hermes_base_url.rstrip("/") + "/v1/chat/completions"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            raise HermesError(f"Hermes {r.status_code}: {r.text[:200]}")
        data = r.json()

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise HermesError(f"Unexpected Hermes response: {data!r}") from e
