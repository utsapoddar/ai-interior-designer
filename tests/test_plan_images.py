import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from chat.app import app


client = TestClient(app)
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png"


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


def _fake_plan_room(*args, **kwargs) -> dict:
    return {
        "items": [
            {
                "id": "oak-platform-bed",
                "name": "Oak Platform Bed",
                "category": "bed",
                "dimensions_m": {"width": 1.6, "depth": 2.0, "height": 0.8},
                "wall_preference": "south",
                "rationale": "Warm minimalist anchor.",
            }
        ],
        "rationale": "Warm minimalist bedroom.",
    }


async def _fake_verify_urls(items: list[dict]) -> list[dict]:
    await asyncio.sleep(0)
    return items


def test_plan_images_endpoints_return_saved_images(monkeypatch) -> None:
    scan_id = "image-endpoints-scan"
    _write_parsed_mesh(scan_id)

    async def fake_generate_room_images(plan: dict, parsed_mesh: dict, count: int = 3):
        for index in range(count):
            yield PNG_BYTES

    monkeypatch.setattr("llm.orchestrator.plan_room", _fake_plan_room)
    monkeypatch.setattr("llm.orchestrator.plan_room_retry", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr("chat.routes.plans.verify_urls", _fake_verify_urls)
    monkeypatch.setattr("chat.routes.plans.generate_room_images", fake_generate_room_images)

    response = client.post("/plans", data={"scan_id": scan_id, "prompt": "warm minimalist bedroom"})
    assert response.status_code == 200
    plan_id = response.json()["plan_id"]

    for _ in range(20):
        images_response = client.get(f"/plans/{plan_id}/images")
        assert images_response.status_code == 200
        images = images_response.json()["images"]
        if len(images) == 3:
            break
        import time
        time.sleep(0.05)
    else:
        raise AssertionError("background image task did not save 3 images")

    assert images == [
        {"index": 0, "url": f"/plans/{plan_id}/images/0", "prompt": ""},
        {"index": 1, "url": f"/plans/{plan_id}/images/1", "prompt": ""},
        {"index": 2, "url": f"/plans/{plan_id}/images/2", "prompt": ""},
    ]

    png_response = client.get(f"/plans/{plan_id}/images/0")
    assert png_response.status_code == 200
    assert png_response.headers["content-type"] == "image/png"
    assert png_response.headers["cache-control"] == "public, max-age=3600"
    assert png_response.content == PNG_BYTES


def test_plan_images_empty_when_directory_missing() -> None:
    response = client.get("/plans/does-not-exist/images")

    assert response.status_code == 200
    assert response.json() == {"images": []}
