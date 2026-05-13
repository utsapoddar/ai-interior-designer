import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from chat.app import app


client = TestClient(app)
SAMPLE_USDZ = Path("ingest/usdz/sample_bedroom.usdz")


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_create_scan() -> None:
    response = client.post(
        "/scans",
        files={"file": ("sample_bedroom.usdz", SAMPLE_USDZ.read_bytes(), "model/vnd.usdz+zip")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scan_id"] != "stub"
    assert body["dimensions_m"]["width"] > 0
    assert "has_labeled_primitives" in body


def test_get_scan_mesh() -> None:
    create_response = client.post(
        "/scans",
        files={"file": ("sample_bedroom.usdz", SAMPLE_USDZ.read_bytes(), "model/vnd.usdz+zip")},
    )
    scan_id = create_response.json()["scan_id"]

    response = client.get(f"/scans/{scan_id}/mesh")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "v1"
    assert body["dimensions_m"]["depth"] > 0


def test_create_plan(monkeypatch) -> None:
    scan_id = "test-plan-scan"
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

    def fake_plan_room(prompt: str, parsed_mesh: dict, reference_images: list[bytes] | None = None, catalog_inspiration: list[dict] | None = None) -> dict:
        assert reference_images == []
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
    response = client.post(
        "/plans",
        data={"scan_id": scan_id, "prompt": "warm minimalist bedroom"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["plan_id"]
    assert body["scan_id"] == scan_id
    assert len(body["items"]) > 0
    assert body["repair_log"]
    assert "iterations" not in body
    item = body["items"][0]
    assert item["name"] == "Oak Platform Bed"
    assert item["product_url"] == "https://example.com/oak-platform-bed"
    assert item["approx_price_usd"] == 899
    assert item["position"]["z"] == 1.0
    assert item["rotation_degrees"] == 0
    assert Path("chat/plans", f"{body['plan_id']}.json").exists()

    get_response = client.get(f"/plans/{body['plan_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["plan_id"] == body["plan_id"]


def test_get_catalog() -> None:
    response = client.get("/catalog")
    assert response.status_code == 200
    assert len(response.json()["items"]) > 5
    assert response.json()["items"][0]["dimensions_m"]["width"] > 0
