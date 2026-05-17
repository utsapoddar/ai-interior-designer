import asyncio
import io
import inspect
import json
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from chat.routes.catalog import load_seed_catalog
from llm import orchestrator
from llm.image_gen import generate_room_images
from llm.verify import verify_urls
from solver.layout import build_exclusion_zones, place_furniture, validate_and_repair


PARSED_MESH_DIR = Path("ingest/parsed-mesh")
PLANS_DIR = Path("chat/plans")
MAX_REFERENCE_BYTES = 40 * 1024 * 1024
ACCEPTED_REFERENCE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class PlanResponse(BaseModel):
    plan_id: str
    status: str
    scan_id: str
    items: list[dict]
    rationale: str
    exclusion_zones: list[dict] = Field(default_factory=list)
    repair_log: list[dict] = Field(default_factory=list)


router = APIRouter(prefix="/plans", tags=["plans"])
ProgressEmitter = Callable[..., None]


@router.post("", response_model=PlanResponse)
async def create_plan(
    scan_id: str = Form(...),
    prompt: str = Form(...),
    references: list[UploadFile] = File(default=[]),
) -> PlanResponse:
    _assert_parsed_mesh_exists(scan_id)
    reference_images = await _read_reference_images(references)
    plan = await asyncio.to_thread(_build_plan, scan_id, prompt, reference_images, _noop_emit)
    _schedule_plan_images(plan.model_dump(), _load_parsed_mesh(scan_id))
    return plan


@router.post("/stream")
async def create_plan_stream(
    scan_id: str = Form(...),
    prompt: str = Form(...),
    references: list[UploadFile] = File(default=[]),
) -> StreamingResponse:
    _assert_parsed_mesh_exists(scan_id)
    reference_images = await _read_reference_images(references)
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def enqueue(event: str, data: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    def emit(stage: str, **data: object) -> None:
        enqueue("progress", {"stage": stage, **data})

    def run_pipeline() -> None:
        try:
            plan = _build_plan(scan_id, prompt, reference_images, emit)
            parsed_mesh = _load_parsed_mesh(scan_id)
            loop.call_soon_threadsafe(_schedule_plan_images, plan.model_dump(), parsed_mesh)
            enqueue("done", {"plan_id": plan.plan_id})
        except Exception as exc:
            enqueue("error", {"message": _error_message(exc)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    task = asyncio.create_task(asyncio.to_thread(run_pipeline))

    async def event_stream():
        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield _format_sse(event, data)
        await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_plan(
    scan_id: str,
    prompt: str,
    reference_images: list[bytes],
    emit: ProgressEmitter | None = None,
) -> PlanResponse:
    emit = emit or _noop_emit
    parsed_path = PARSED_MESH_DIR / f"{scan_id}.json"
    if not parsed_path.exists():
        raise HTTPException(status_code=404, detail="Parsed mesh not found")

    parsed_mesh = _load_parsed_mesh(scan_id)
    catalog = load_seed_catalog()
    exclusion_zones = build_exclusion_zones(parsed_mesh)

    emit("llm_proposing", label="Asking the AI to pick furniture")
    plan = orchestrator.plan_room(prompt, parsed_mesh, reference_images=reference_images, catalog_inspiration=catalog)
    proposed_items = plan.get("items") or []
    emit("solver_placing", label="Fitting items in your room")
    if not proposed_items:
        placements = place_furniture(parsed_mesh, catalog)
        repair_log: list[dict] = []
        rationale = "LLM returned no items; used seed catalog fallback."
    else:
        placements, repair_log = validate_and_repair(parsed_mesh, proposed_items)
        repair_log = _annotate_repair_log(repair_log, proposed_items)
        rationale = plan.get("rationale", "")

        dropped = [entry for entry in repair_log if entry.get("action") == "dropped"]
        if dropped:
            emit(
                "retrying",
                label=f"Retrying {len(dropped)} {_pluralize('item', len(dropped))} that didn't fit",
                count=len(dropped),
            )
            replacements, retry_log = _retry_for_drops(
                prompt, parsed_mesh, proposed_items, placements, dropped
            )
            if replacements:
                survivor_ids = {_item_id(item) for item in placements}
                extra_placements, extra_log = validate_and_repair(
                    parsed_mesh,
                    _merge_placed_with_proposals(placements, replacements),
                )
                if survivor_ids.issubset({_item_id(item) for item in extra_placements}):
                    placements = extra_placements
                    replacement_ids = {_item_id(item) for item in replacements}
                    extra_log = [
                        entry for entry in _annotate_repair_log(extra_log, replacements)
                        if entry.get("id") in replacement_ids
                    ]
                    repair_log.extend(extra_log)
                    repair_log.extend(_substitution_logs(replacements, dropped, placements))
            repair_log.extend(retry_log)

    emit("verifying_urls", label="Verifying product links")
    _run_verify_urls(placements)

    plan_id = uuid.uuid4().hex[:12]
    payload = {
        "plan_id": plan_id,
        "scan_id": scan_id,
        "items": placements,
        "rationale": rationale,
        "exclusion_zones": exclusion_zones,
        "repair_log": repair_log,
        "status": "ok",
    }
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    (PLANS_DIR / f"{plan_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return PlanResponse(**payload)


def _load_parsed_mesh(scan_id: str) -> dict:
    return json.loads((PARSED_MESH_DIR / f"{scan_id}.json").read_text(encoding="utf-8"))


def _schedule_plan_images(plan: dict, parsed_mesh: dict) -> None:
    task = asyncio.create_task(_write_plan_images(plan, parsed_mesh))
    task.add_done_callback(_log_background_exception)


def _log_background_exception(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print(f"Plan image generation failed: {exc}")


async def _write_plan_images(plan: dict, parsed_mesh: dict) -> None:
    plan_id = str(plan["plan_id"])
    image_dir = PLANS_DIR / plan_id
    image_dir.mkdir(parents=True, exist_ok=True)
    images: list[dict] = []
    metadata_path = image_dir / "images.json"

    async for image_bytes in generate_room_images(plan, parsed_mesh, count=3):
        index = len(images)
        filename = f"img_{index}.png"
        (image_dir / filename).write_bytes(bytes(image_bytes))
        images.append({"index": index, "filename": filename, "prompt": getattr(image_bytes, "prompt", "")})
        metadata_path.write_text(json.dumps(images, indent=2), encoding="utf-8")


def _read_plan_image_metadata(plan_id: str) -> list[dict]:
    metadata_path = PLANS_DIR / plan_id / "images.json"
    if not metadata_path.exists():
        return []
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _assert_parsed_mesh_exists(scan_id: str) -> None:
    if not (PARSED_MESH_DIR / f"{scan_id}.json").exists():
        raise HTTPException(status_code=404, detail="Parsed mesh not found")


def _noop_emit(*args: object, **kwargs: object) -> None:
    return None


def _format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc) or "Plan generation failed"


def _run_verify_urls(placements: list[dict]) -> None:
    result = verify_urls(placements)
    if inspect.isawaitable(result):
        asyncio.run(result)


def _pluralize(word: str, count: int) -> str:
    if count == 1:
        return word
    return f"{word}s"


def _retry_for_drops(
    prompt: str,
    parsed_mesh: dict,
    original_items: list[dict],
    surviving_placements: list[dict],
    dropped_entries: list[dict],
) -> tuple[list[dict], list[dict]]:
    dropped_slots = _dropped_slots(parsed_mesh, original_items, surviving_placements, dropped_entries)
    if not dropped_slots:
        return [], []

    replacements = orchestrator.plan_room_retry(prompt, parsed_mesh, dropped_slots)
    slot_ids = {slot["dropped_id"] for slot in dropped_slots}
    usable = [
        replacement for replacement in replacements
        if isinstance(replacement, dict) and str(replacement.get("replaces") or "") in slot_ids
    ]
    return usable[: len(dropped_slots)], []


def _dropped_slots(
    parsed_mesh: dict,
    original_items: list[dict],
    surviving_placements: list[dict],
    dropped_entries: list[dict],
) -> list[dict]:
    originals_by_id = {_item_id(item): item for item in original_items}
    slots: list[dict] = []
    for entry in dropped_entries:
        dropped_id = str(entry.get("id") or "")
        original = originals_by_id.get(dropped_id)
        if not original:
            continue
        wall = str(original.get("wall_preference") or "any").lower()
        slots.append(
            {
                "dropped_id": dropped_id,
                "category": original.get("category", "unknown"),
                "wall_preference": wall,
                "max_dimensions_m": _max_dimensions_for_retry(parsed_mesh, wall, surviving_placements),
                "original_name": original.get("name") or dropped_id,
                "original_rationale": original.get("rationale", ""),
            }
        )
    return slots


def _max_dimensions_for_retry(parsed_mesh: dict, wall: str, surviving_placements: list[dict]) -> dict:
    dims = parsed_mesh.get("dimensions_m") or {}
    room_width = float(dims.get("width", 3.0))
    room_depth = float(dims.get("depth", 3.0))
    ceiling_height = float(dims.get("height", 2.4))

    if wall in {"south", "north"}:
        wall_length = room_width
    elif wall in {"east", "west"}:
        wall_length = room_depth
    else:
        return {
            "width": round(min(0.6 * room_width, 1.5), 3),
            "depth": round(min(0.6 * room_depth, 1.5), 3),
            "height": round(ceiling_height, 3),
        }

    used_length = 0.0
    for placement in surviving_placements:
        if _nearest_wall_for_placement(placement, room_width, room_depth) != wall:
            continue
        width, depth = _rotated_size(placement)
        used_length += width if wall in {"south", "north"} else depth
        used_length += 0.2

    fallback_width = min(0.6 * wall_length, 1.5)
    remaining_width = max(0.25, wall_length - used_length)
    return {
        "width": round(max(0.25, min(remaining_width, fallback_width)), 3),
        "depth": 0.6,
        "height": round(ceiling_height, 3),
    }


def _merge_placed_with_proposals(placements: list[dict], replacements: list[dict]) -> list[dict]:
    return [dict(item) for item in placements] + [dict(item) for item in replacements]


def _substitution_logs(replacements: list[dict], dropped_entries: list[dict], placements: list[dict]) -> list[dict]:
    placed_ids = {_item_id(item) for item in placements}
    drops_by_id = {str(entry.get("id") or ""): entry for entry in dropped_entries}
    logs: list[dict] = []
    for replacement in replacements:
        replacement_id = _item_id(replacement)
        dropped_id = str(replacement.get("replaces") or "")
        if replacement_id not in placed_ids or dropped_id not in drops_by_id:
            continue
        drop_reason = drops_by_id[dropped_id].get("reason", "dropped")
        logs.append(
            {
                "id": replacement_id,
                "name": replacement.get("name") or replacement_id,
                "category": replacement.get("category", "unknown"),
                "wall_preference": replacement.get("wall_preference"),
                "action": "substituted",
                "reason": f"replaces {dropped_id}: {drop_reason}",
                "replaces": dropped_id,
            }
        )
    return logs


def _annotate_repair_log(repair_log: list[dict], items: list[dict]) -> list[dict]:
    items_by_id = {_item_id(item): item for item in items}
    annotated: list[dict] = []
    for entry in repair_log:
        item = items_by_id.get(str(entry.get("id") or ""))
        if not item:
            annotated.append(entry)
            continue
        enriched = dict(entry)
        enriched.setdefault("name", item.get("name") or enriched.get("id"))
        enriched.setdefault("category", item.get("category", "unknown"))
        enriched.setdefault("wall_preference", item.get("wall_preference"))
        annotated.append(enriched)
    return annotated


def _item_id(item: dict) -> str:
    return str(item.get("id") or item.get("catalog_id") or item.get("name") or "item")


def _rotated_size(item: dict) -> tuple[float, float]:
    dims = item.get("dimensions_m") or item.get("dimensions") or {}
    width = float(dims.get("width", 0.5))
    depth = float(dims.get("depth", 0.5))
    rotation = int(float(item.get("rotation_degrees", 0)))
    if rotation % 180 == 90:
        return depth, width
    return width, depth


def _nearest_wall_for_placement(item: dict, room_width: float, room_depth: float) -> str:
    pos = item.get("position") or {}
    x = float(pos.get("x", room_width / 2))
    z = float(pos.get("z", room_depth / 2))
    distances = {"south": z, "north": room_depth - z, "west": x, "east": room_width - x}
    return min(distances, key=distances.get)


async def _read_reference_images(references: list[UploadFile]) -> list[bytes]:
    processed: list[bytes] = []
    total_bytes = 0
    for upload in references:
        if upload.content_type not in ACCEPTED_REFERENCE_TYPES:
            raise HTTPException(status_code=415, detail="Reference images must be JPEG, PNG, or WebP")
        raw = await upload.read()
        total_bytes += len(raw)
        if total_bytes > MAX_REFERENCE_BYTES:
            raise HTTPException(status_code=413, detail="Reference images exceed 40MB combined")
        processed.append(_resize_and_encode_jpeg(raw))
    return processed


def _resize_and_encode_jpeg(raw: bytes) -> bytes:
    try:
        from PIL import Image
    except ModuleNotFoundError:
        return raw

    try:
        image = Image.open(io.BytesIO(raw))
        image.thumbnail((1024, 1024))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid reference image") from exc


@router.get("/{plan_id}/images")
def get_plan_images(plan_id: str) -> JSONResponse:
    images = []
    for item in _read_plan_image_metadata(plan_id):
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        images.append(
            {
                "index": index,
                "url": f"/plans/{plan_id}/images/{index}",
                "prompt": str(item.get("prompt") or ""),
            }
        )
    return JSONResponse({"images": images})


@router.get("/{plan_id}/images/{index}")
def get_plan_image(plan_id: str, index: int) -> FileResponse:
    image_path = PLANS_DIR / plan_id / f"img_{index}.png"
    if index < 0 or not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(
        image_path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/{plan_id}")
def get_plan(plan_id: str) -> JSONResponse:
    plan_path = PLANS_DIR / f"{plan_id}.json"
    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found")
    return JSONResponse(json.loads(plan_path.read_text(encoding="utf-8")))
