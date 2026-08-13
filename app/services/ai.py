"""Anthropic client, mirroring growth-os's src/lib/ai.ts pattern: no SDK, one
function, one endpoint. Ported deliberately rather than reinvented — same
error handling, same "fail loud if the key is missing" behaviour.
"""

import httpx

from app.config import settings

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

# claude-sonnet-5 rejects an explicit temperature outright (verified against
# the live API in growth-os: HTTP 400 "temperature is deprecated for this
# model"). Generation here always wants the model's own judgement on phrasing
# anyway — the citation guardrail below is what actually keeps answers honest,
# not a pinned temperature — so this client never sends one.


def ai_enabled() -> bool:
    return bool(settings.anthropic_api_key)


async def call_claude(prompt: str, max_tokens: int = 2000, model: str = "claude-sonnet-5") -> str:
    if not settings.anthropic_api_key:
        raise RuntimeError("AI mode is off — add ANTHROPIC_API_KEY to .env and restart the server.")

    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "content-type": "application/json",
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if res.status_code != 200:
        body = res.text[:200]
        if res.status_code == 401:
            raise RuntimeError("Anthropic rejected the API key — check ANTHROPIC_API_KEY in .env.")
        if res.status_code == 429:
            raise RuntimeError("Rate limited by the Anthropic API — wait a minute and try again.")
        raise RuntimeError(f"Anthropic API error {res.status_code}: {body}")

    data = res.json()
    text = "\n".join(block["text"] for block in data.get("content", []) if block.get("type") == "text" and block.get("text"))
    if not text.strip():
        raise RuntimeError("The model returned an empty reply — try again.")
    return text
