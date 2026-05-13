import asyncio
import io
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from chat.app import app


client = TestClient(app)
PARAMETRIC_USDZ = Path("tests/fixtures/parametric_bedroom.usdz")

def _tiny_png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (180, 120, 60)).save(buf, format="PNG")
    return buf.getvalue()


TINY_PNG = _tiny_png()


def test_create_plan_accepts_multipart_reference_image(monkeypatch) -> None:
    scan_id = "multipart-parametric-scan"
    Path("ingest/parsed-mesh").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PARAMETRIC_USDZ, Path("ingest/usdz") / f"{scan_id}.usdz")
    from ingest.parser import parse_usdz

    parsed = parse_usdz(PARAMETRIC_USDZ)
    (Path("ingest/parsed-mesh") / f"{scan_id}.json").write_text(
        json.dumps(parsed), encoding="utf-8"
    )

    def fake_plan_room(
        prompt: str,
        parsed_mesh: dict,
        reference_images: list[bytes] | None = None,
        catalog_inspiration: list[dict] | None = None,
    ) -> dict:
        assert prompt == "use the reference image style"
        assert isinstance(reference_images, list)
        assert len(reference_images) == 1
        assert isinstance(reference_images[0], bytes)
        assert len(reference_images[0]) > 0
        return {
            "items": [
                {
                    "id": "queen-bed",
                    "name": "Queen Bed",
                    "category": "bed",
                    "dimensions_m": {"width": 1.0, "depth": 1.2, "height": 0.8},
                    "wall_preference": "north",
                    "product_url": "https://example.com/queen-bed",
                    "approx_price_usd": 800,
                    "verified": False,
                    "rationale": "Reference image style applied.",
                }
            ],
            "rationale": "Reference image style applied.",
        }

    async def fake_verify_urls(items: list[dict]) -> list[dict]:
        await asyncio.sleep(0)
        return items

    monkeypatch.setattr("llm.orchestrator.plan_room", fake_plan_room)
    monkeypatch.setattr("llm.orchestrator.plan_room_retry", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr("chat.routes.plans.verify_urls", fake_verify_urls)
    response = client.post(
        "/plans",
        data={"scan_id": scan_id, "prompt": "use the reference image style"},
        files={"references": ("reference.png", TINY_PNG, "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scan_id"] == scan_id
    assert body["items"]
    assert "exclusion_zones" in body
