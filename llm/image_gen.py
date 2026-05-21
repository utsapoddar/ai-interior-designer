from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx

from llm.orchestrator import MODEL

LOGGER = logging.getLogger(__name__)
FLUX_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell"


class PromptedImage(bytes):
    """PNG bytes plus the text prompt used to create them."""

    prompt: str

    def __new__(cls, value: bytes, prompt: str = ""):
        obj = bytes.__new__(cls, value)
        obj.prompt = prompt
        return obj


async def generate_room_images(plan: dict, parsed_mesh: dict, count: int = 3) -> AsyncIterator[bytes]:
    """Generates `count` distinct room images as PNG bytes.

    Step 1: ask Llama-4-Maverick to produce `count` distinct image prompts based on plan + room.
    Step 2: for each prompt, POST to FLUX.1-schnell, decode base64 PNG bytes, yield.
    Failures on individual images are logged + skipped, not raised.
    """
    try:
        prompts = await _generate_prompts(plan, parsed_mesh, count)
    except Exception:
        LOGGER.exception("Failed to generate FLUX prompts")
        return

    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        LOGGER.warning("Skipping room image generation: NVIDIA_API_KEY is not set")
        return

    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=120) as client:
        for index, prompt in enumerate(prompts[:count]):
            try:
                # Probed 2026-05-21: FLUX.1-schnell accepts this body and returns JSON
                # shaped like {"artifacts": [{"base64": "...", "finishReason": "...", "seed": ...}]}.
                body = {
                    "prompt": prompt,
                    "width": 1024,
                    "height": 1024,
                    "seed": random.randint(0, 2**31 - 1),
                    "steps": 4,
                }
                response = await client.post(FLUX_URL, headers=headers, json=body)
                response.raise_for_status()
                yield PromptedImage(_decode_image_response(response.json()), prompt=prompt)
            except Exception:
                LOGGER.exception("Failed to generate room image %s", index)
                continue


async def _generate_prompts(plan: dict, parsed_mesh: dict, count: int) -> list[str]:
    content = await asyncio.to_thread(_call_prompt_writer, plan, parsed_mesh, count)
    parsed = _parse_json(content)
    raw_prompts = parsed.get("prompts") if parsed else None
    if not isinstance(raw_prompts, list):
        return _fallback_prompts(plan, parsed_mesh, count)
    prompts = [str(prompt).strip()[:200] for prompt in raw_prompts if str(prompt).strip()]
    return (prompts + _fallback_prompts(plan, parsed_mesh, count))[:count]


def _call_prompt_writer(plan: dict, parsed_mesh: dict, count: int) -> str:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set")
    from openai import OpenAI

    client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON."},
            {"role": "user", "content": _prompt_writer_input(plan, parsed_mesh, count)},
        ],
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or "{}"


def _prompt_writer_input(plan: dict, parsed_mesh: dict, count: int) -> str:
    dims = parsed_mesh.get("dimensions_m") or {}
    dimensions = f"{dims.get('width', '?')}m W x {dims.get('depth', '?')}m D x {dims.get('height', '?')}m H"
    items = [_item_name(item) for item in plan.get("items") or []]
    rationale = str(plan.get("rationale") or "photorealistic room design")
    return (
        f"Create {count} distinct FLUX image prompts as JSON: {{\"prompts\":[...]}}. "
        "Each prompt must describe the same room from a different angle, time of day, or composition. "
        "Mood-board only; no need for exact placements. Cap each prompt at 200 characters. "
        f"Room dimensions: {dimensions}. Style/rationale: {rationale}. Placed items: {', '.join(items) or 'furniture'}."
    )


def _fallback_prompts(plan: dict, parsed_mesh: dict, count: int) -> list[str]:
    dims = parsed_mesh.get("dimensions_m") or {}
    dimensions = f"{dims.get('width', '?')}x{dims.get('depth', '?')}x{dims.get('height', '?')}m"
    style = str(plan.get("rationale") or "warm minimalist bedroom").replace("\n", " ")[:60]
    items = ", ".join(_item_name(item) for item in (plan.get("items") or [])[:5]) or "bedroom furniture"
    angles = ["wide shot, golden hour", "from doorway, bright daytime", "close-up, soft evening light"]
    return [f"Photorealistic {style}; {items}; room {dimensions}; {angle}."[:200] for angle in angles[:count]]


def _item_name(item: dict) -> str:
    return str(item.get("name") or item.get("category") or item.get("catalog_id") or item.get("id") or "item")


def _parse_json(content: str) -> dict | None:
    try:
        parsed = json.loads(content)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _decode_image_response(data: dict[str, Any]) -> bytes:
    encoded = _find_base64_image(data)
    if not encoded:
        raise ValueError("FLUX response did not include a base64 image")
    if encoded.startswith("data:"):
        encoded = encoded.split(",", 1)[1]
    return base64.b64decode(encoded)


def _find_base64_image(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("b64_json", "image", "base64"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        artifacts = data.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                found = _find_base64_image(artifact)
                if found:
                    return found
    if isinstance(data, list):
        for item in data:
            found = _find_base64_image(item)
            if found:
                return found
    return None
