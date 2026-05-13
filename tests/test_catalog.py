from fastapi.testclient import TestClient

from chat.app import app


client = TestClient(app)


def test_catalog_returns_seed_items_with_dimensions() -> None:
    response = client.get("/catalog")

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) > 5
    assert all("dimensions_m" in item for item in items)
