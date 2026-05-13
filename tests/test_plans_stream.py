import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from chat.app import app


client = TestClient(app)


def _write_parsed_mesh(scan_id: str) -> None:
    parsed_path = Path("ingest/parsed-mesh") / f"{scan_id}.json"
    parsed_path.parent.mkdir(parents=True, exist_ok=True)
    parsed_path.write_text(
        json.dumps(
            {
                "up_axis": "Y",
                "dimensions_m": {"width": 4.0, "depth": 3.0, "height": 2.5},
                "bounding_box_m": {"min": [0, 0, 0], "max": [4, 2.5, 3]},
            }
        ),
        encoding="utf-8",
    )


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for raw in body.strip().split("\n\n"):
        lines = raw.splitlines()
        event = next(line.removeprefix("event:").strip() for line in lines if line.startswith("event:"))
        data = next(line.removeprefix("data:").strip() for line in lines if line.startswith("data:"))
        events.append((event, json.loads(data)))
    return events


def test_stream_emits_progress_events_in_order(monkeypatch) -> None:
    scan_id = "stream-plan-scan"
    _write_parsed_mesh(scan_id)

    def fake_plan_room(prompt: str, parsed_mesh: dict, reference_images: list[bytes] | None = None, catalog_inspiration: list[dict] | None = None) -> dict:
        return {
            "items": [
                {
                    "id": "oak-platform-bed",
                    "name": "Oak Platform Bed",
                    "category": "bed",
                    "dimensions_m": {"width": 1.6, "depth": 2.0, "height": 0.8},
                    "wall_preference": "south",
                    "approx_price_usd": 899,
                    "product_url": "https://example.com/oak-platform-bed",
                    "verified": False,
                    "rationale": "Warm minimalist anchor.",
                }
            ],
            "rationale": "Warm minimalist bedroom with practical storage.",
        }

    async def fake_verify_urls(items: list[dict]) -> list[dict]:
        await asyncio.sleep(0)
        return items

    monkeypatch.setattr("llm.orchestrator.plan_room", fake_plan_room)
    monkeypatch.setattr("llm.orchestrator.plan_room_retry", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr("chat.routes.plans.verify_urls", fake_verify_urls)

    with client.stream(
        "POST",
        "/plans/stream",
        data={"scan_id": scan_id, "prompt": "warm minimalist bedroom"},
    ) as response:
        assert response.status_code == 200
        body = response.read().decode()

    events = _parse_sse(body)
    assert [event for event, _ in events] == ["progress", "progress", "progress", "done"]
    assert [data.get("stage") for event, data in events if event == "progress"] == [
        "llm_proposing",
        "solver_placing",
        "verifying_urls",
    ]
    done = events[-1][1]
    assert done["plan_id"]
    assert (Path("chat/plans") / f"{done['plan_id']}.json").exists()


def test_stream_emits_error_event_when_plan_room_raises(monkeypatch) -> None:
    scan_id = "stream-error-scan"
    _write_parsed_mesh(scan_id)

    def fake_plan_room(*args, **kwargs) -> dict:
        raise RuntimeError("NIM rate limit exceeded, please retry in a minute")

    monkeypatch.setattr("llm.orchestrator.plan_room", fake_plan_room)

    with client.stream(
        "POST",
        "/plans/stream",
        data={"scan_id": scan_id, "prompt": "warm minimalist bedroom"},
    ) as response:
        assert response.status_code == 200
        body = response.read().decode()

    events = _parse_sse(body)
    assert events[-1] == (
        "error",
        {"message": "NIM rate limit exceeded, please retry in a minute"},
    )
