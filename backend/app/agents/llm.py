"""Thin wrappers around the Google Gemini (AI Studio) SDK.

All imports of `google.genai` are lazy so that modules depending on this file
can be imported (and pure-logic parts unit-tested) without the SDK or an API
key present. Every helper degrades gracefully: `embed_text` returns None and
`agenerate_json` raises a clear error when no key is configured.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


def _key_is_configured() -> bool:
    key = get_settings().gemini_api_key
    return bool(key) and not key.startswith("paste-your")


@lru_cache
def get_client():
    """Cached google.genai.Client. Raises if the key is missing."""
    if not _key_is_configured():
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Add it to your .env "
            "(see .env.example)."
        )
    from google import genai  # lazy import

    return genai.Client(api_key=get_settings().gemini_api_key)


def embed_text(text: str) -> Optional[list[float]]:
    """Synchronous embedding. Returns None when unavailable (never raises)."""
    try:
        client = get_client()
    except (RuntimeError, ImportError) as exc:
        logger.warning("Embedding unavailable: %s", exc)
        return None
    try:
        from google.genai import types

        resp = client.models.embed_content(
            model=get_settings().gemini_embedding_model,
            contents=[text],
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        return list(resp.embeddings[0].values)
    except Exception as exc:  # noqa: BLE001 -- degrade, don't crash the graph
        logger.warning("Embedding call failed: %s", exc)
        return None


def vector_literal(vec: Optional[list[float]]) -> Optional[str]:
    """pgvector text literal for parameterised SQL (`%s::vector`)."""
    if vec is None:
        return None
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


def _extract_json(raw: str) -> dict[str, Any]:
    """Parse JSON out of an LLM response, tolerating code fences/prose."""
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    else:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)
    return json.loads(raw)


async def agenerate_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    """Generate a JSON object from Gemini (async). Raises on failure -- the
    calling node decides how to handle it."""
    import asyncio

    client = get_client()
    settings = get_settings()

    def _call() -> str:
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=f"{system_prompt}\n\n{user_prompt}",
            config={
                "response_mime_type": "application/json",
                "temperature": 0.4,
            },
        )
        return resp.text

    raw = await asyncio.to_thread(_call)
    return _extract_json(raw)
