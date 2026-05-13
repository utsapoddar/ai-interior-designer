from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any


PROMPT_PATH = Path("llm/prompts/extract_intent.md")
REPAIR_PROMPT_PATH = Path("llm/prompts/repair_drops.md")
MODEL = "meta/llama-4-maverick-17b-128e-instruct"


def plan_room(
    prompt: str,
    parsed_mesh: dict,
    reference_images: list[bytes] | None = None,
    catalog_inspiration: list[dict] | None = None,
) -> dict:
    """One NIM call. Returns {items: [...], rationale: str}."""
    client = _make_client()
    user_prompt = _render_prompt(prompt, parsed_mesh, catalog_inspiration or [])
    images = reference_images or []
    messages = _messages(user_prompt, images, use_image_parts=bool(images))

    try:
        content = _call_nim(client, messages)
    except Exception as exc:
        if images and _status_code(exc) == 500:
            messages = _messages(user_prompt, images, use_image_parts=False)
            content = _call_nim(client, messages)
        else:
            raise

    parsed = _parse_json(content)
    if parsed is None:
        retry_messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "Return ONLY valid JSON. No prose, no markdown, no code fences."},
        ]
        content = _call_nim(client, retry_messages)
        parsed = _parse_json(content)
        if parsed is None:
            raise ValueError("Could not parse NVIDIA NIM JSON response")

    parsed.setdefault("items", [])
    parsed.setdefault("rationale", "")
    if isinstance(parsed.get("items"), list):
        parsed["items"] = [_normalize_item(item) for item in parsed["items"] if isinstance(item, dict)]
    else:
        parsed["items"] = []
    return parsed


def plan_room_retry(
    original_prompt: str,
    parsed_mesh: dict,
    dropped_slots: list[dict],
) -> list[dict]:
    """One text-only NIM call for replacement proposals that fit dropped slots."""
    if not dropped_slots:
        return []

    client = _make_client()
    user_prompt = _render_repair_prompt(original_prompt, parsed_mesh, dropped_slots)
    messages = _messages(user_prompt, [], use_image_parts=False)

    try:
        content = _call_nim(client, messages)
    except Exception as exc:
        if _status_code(exc) == 429:
            return []
        raise

    parsed = _parse_json(content)
    if parsed is None:
        retry_messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "Return ONLY valid JSON matching the replacements schema."},
        ]
        try:
            content = _call_nim(client, retry_messages)
        except Exception as exc:
            if _status_code(exc) == 429:
                return []
            raise
        parsed = _parse_json(content)
        if parsed is None:
            return []

    replacements = parsed.get("replacements")
    if not isinstance(replacements, list):
        return []

    slots_by_id = {str(slot.get("dropped_id")): slot for slot in dropped_slots}
    normalized: list[dict] = []
    seen_slots: set[str] = set()
    for item in replacements:
        if not isinstance(item, dict):
            continue
        replaces = str(item.get("replaces") or "")
        slot = slots_by_id.get(replaces)
        if not slot or replaces in seen_slots:
            continue
        replacement = _normalize_retry_item(item, slot)
        if replacement:
            normalized.append(replacement)
            seen_slots.add(replaces)
        if len(normalized) == len(dropped_slots):
            break
    return normalized


def _make_client():
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set. Export your NVIDIA NIM API key before calling /plans.")
    from openai import OpenAI

    return OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)


def _call_nim(client, messages: list[dict[str, Any]]) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or "{}"


def _messages(user_prompt: str, reference_images: list[bytes], use_image_parts: bool) -> list[dict[str, Any]]:
    content: str | list[dict[str, Any]] = user_prompt
    if reference_images:
        if use_image_parts:
            content = [{"type": "text", "text": user_prompt}] + [
                {"type": "image_url", "image_url": {"url": data_url}}
                for data_url in _image_data_urls(reference_images)
            ]
        else:
            content = _html_image_prompt(user_prompt, reference_images)
    return [
        {"role": "system", "content": "You are a creative furnishing agent. Return ONLY valid JSON."},
        {"role": "user", "content": content},
    ]


def _html_image_prompt(user_prompt: str, reference_images: list[bytes]) -> str:
    html_images = "\n".join(f'<img src="{data_url}" />' for data_url in _image_data_urls(reference_images))
    return f"{user_prompt}\n\nReference images:\n{html_images}"


def _image_data_urls(reference_images: list[bytes]) -> list[str]:
    return [f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('ascii')}" for image_bytes in reference_images]


def _render_prompt(prompt: str, parsed_mesh: dict, catalog: list[dict]) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{{prompt}}", prompt)
        .replace("{{parsed_mesh_json}}", json.dumps(parsed_mesh, indent=2))
        .replace("{{catalog_json}}", json.dumps(catalog, indent=2))
    )


def _render_repair_prompt(prompt: str, parsed_mesh: dict, dropped_slots: list[dict]) -> str:
    template = REPAIR_PROMPT_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{{prompt}}", prompt)
        .replace("{{parsed_mesh_json}}", json.dumps(parsed_mesh, indent=2))
        .replace("{{dropped_slots_json}}", json.dumps(dropped_slots, indent=2))
    )


def _parse_json(content: str) -> dict | None:
    try:
        parsed = json.loads(content)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_item(item: dict) -> dict:
    normalized = dict(item)
    if not normalized.get("id"):
        normalized["id"] = slugify_name(str(normalized.get("name") or normalized.get("category") or "item"))
    normalized["verified"] = False
    return normalized


def _normalize_retry_item(item: dict, slot: dict) -> dict | None:
    dims = item.get("dimensions_m")
    max_dims = slot.get("max_dimensions_m") or {}
    if not isinstance(dims, dict) or not isinstance(max_dims, dict):
        return None

    parsed_dims: dict[str, float] = {}
    for axis in ("width", "depth", "height"):
        try:
            value = float(dims[axis])
            max_value = float(max_dims[axis])
        except (KeyError, TypeError, ValueError):
            return None
        if value <= 0 or value > max_value:
            return None
        parsed_dims[axis] = value

    normalized = dict(item)
    normalized["dimensions_m"] = parsed_dims
    normalized["replaces"] = str(slot.get("dropped_id"))
    normalized.setdefault("category", slot.get("category", "unknown"))
    normalized["wall_preference"] = str(normalized.get("wall_preference") or slot.get("wall_preference") or "any").lower()
    if not normalized.get("id"):
        normalized["id"] = slugify_name(str(normalized.get("name") or normalized.get("category") or "replacement"))
    normalized["verified"] = False
    return normalized


def _status_code(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if code is not None:
        return int(code)
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return int(code) if code is not None else None


def slugify_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "item"
