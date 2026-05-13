import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from chat.app import app


client = TestClient(app)


def _write_mesh(scan_id: str, width: float = 2.4, depth: float = 2.0) -> None:
    path = Path("ingest/parsed-mesh") / f"{scan_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "up_axis": "Y",
                "dimensions_m": {"width": width, "depth": depth, "height": 2.5},
                "bounding_box_m": {"min": [0, 0, 0], "max": [width, 2.5, depth]},
                "features": {"walls": [], "doors": [], "windows": []},
            }
        ),
        encoding="utf-8",
    )


def _oversized_plan() -> dict:
    return {
        "items": [
            {
                "id": "oversized-dresser",
                "name": "Oversized Dresser",
                "category": "storage",
                "dimensions_m": {"width": 4.0, "depth": 0.7, "height": 1.1},
                "wall_preference": "south",
                "approx_price_usd": 1200,
                "product_url": "https://example.com/oversized-dresser",
                "verified": False,
                "rationale": "Too large for the compact room.",
            }
        ],
        "rationale": "Try to fit a dresser.",
    }


def _patch_plan_and_verify(monkeypatch, retry_result: list[dict]) -> None:
    def fake_plan_room(*args, **kwargs) -> dict:
        return _oversized_plan()

    def fake_plan_room_retry(*args, **kwargs) -> list[dict]:
        return retry_result

    async def fake_verify_urls(items: list[dict]) -> list[dict]:
        await asyncio.sleep(0)
        return items

    monkeypatch.setattr("llm.orchestrator.plan_room", fake_plan_room)
    monkeypatch.setattr("llm.orchestrator.plan_room_retry", fake_plan_room_retry, raising=False)
    monkeypatch.setattr("chat.routes.plans.verify_urls", fake_verify_urls)


def test_repair_retry_substitutes_a_dropped_item(monkeypatch) -> None:
    scan_id = "retry-substitutes-scan"
    _write_mesh(scan_id)
    replacement = {
        "id": "slim-dresser",
        "name": "Slim Dresser",
        "category": "storage",
        "dimensions_m": {"width": 0.8, "depth": 0.35, "height": 1.0},
        "wall_preference": "south",
        "approx_price_usd": 399,
        "product_url": "https://example.com/slim-dresser",
        "verified": False,
        "rationale": "Narrower profile fits the available wall.",
        "replaces": "oversized-dresser",
    }
    _patch_plan_and_verify(monkeypatch, [replacement])

    response = client.post("/plans", data={"scan_id": scan_id, "prompt": "compact bedroom"})

    assert response.status_code == 200
    body = response.json()
    assert {item["catalog_id"] for item in body["items"]} == {"slim-dresser"}
    assert any(entry["id"] == "oversized-dresser" and entry["action"] == "dropped" for entry in body["repair_log"])
    assert any(
        entry["id"] == "slim-dresser"
        and entry["action"] == "substituted"
        and entry["replaces"] == "oversized-dresser"
        for entry in body["repair_log"]
    )


def test_repair_retry_empty_result_keeps_original_drop(monkeypatch) -> None:
    scan_id = "retry-empty-scan"
    _write_mesh(scan_id)
    _patch_plan_and_verify(monkeypatch, [])

    response = client.post("/plans", data={"scan_id": scan_id, "prompt": "compact bedroom"})

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    dropped = [entry for entry in body["repair_log"] if entry["action"] == "dropped"]
    assert [entry["id"] for entry in dropped] == ["oversized-dresser"]
    assert not any(entry["action"] == "substituted" for entry in body["repair_log"])


def test_repair_retry_does_not_loop_when_replacement_also_drops(monkeypatch) -> None:
    scan_id = "retry-replacement-drops-scan"
    _write_mesh(scan_id)
    replacement = {
        "id": "still-too-wide-dresser",
        "name": "Still Too Wide Dresser",
        "category": "storage",
        "dimensions_m": {"width": 4.0, "depth": 0.7, "height": 1.1},
        "wall_preference": "south",
        "approx_price_usd": 999,
        "product_url": "https://example.com/still-too-wide-dresser",
        "verified": False,
        "rationale": "Still too large.",
        "replaces": "oversized-dresser",
    }
    calls = 0

    def fake_plan_room(*args, **kwargs) -> dict:
        return _oversized_plan()

    def fake_plan_room_retry(*args, **kwargs) -> list[dict]:
        nonlocal calls
        calls += 1
        return [replacement]

    async def fake_verify_urls(items: list[dict]) -> list[dict]:
        await asyncio.sleep(0)
        return items

    monkeypatch.setattr("llm.orchestrator.plan_room", fake_plan_room)
    monkeypatch.setattr("llm.orchestrator.plan_room_retry", fake_plan_room_retry, raising=False)
    monkeypatch.setattr("chat.routes.plans.verify_urls", fake_verify_urls)

    response = client.post("/plans", data={"scan_id": scan_id, "prompt": "compact bedroom"})

    assert response.status_code == 200
    body = response.json()
    assert calls == 1
    assert body["items"] == []
    dropped_ids = [entry["id"] for entry in body["repair_log"] if entry["action"] == "dropped"]
    assert dropped_ids == ["oversized-dresser", "still-too-wide-dresser"]
    assert not any(entry["action"] == "substituted" for entry in body["repair_log"])
