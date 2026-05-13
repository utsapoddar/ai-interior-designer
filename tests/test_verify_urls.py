import asyncio
import time

import httpx


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_verify_urls_preserves_200_url(monkeypatch) -> None:
    from llm.verify import verify_urls

    async def fake_head(self, url: str):
        return _Response(200)

    async def fake_tavily(query: str, max_results: int = 3):
        raise AssertionError("Tavily should not be called for a working URL")

    monkeypatch.setattr(httpx.AsyncClient, "head", fake_head)
    monkeypatch.setattr("llm.verify._tavily_search", fake_tavily)

    items = [{"name": "Oak Platform Bed", "product_url": "https://example.com/oak-platform-bed"}]
    result = asyncio.run(verify_urls(items))

    assert result is items
    assert items[0]["verified"] is True
    assert items[0]["product_url"] == "https://example.com/oak-platform-bed"
    assert items[0].get("fallback_url") is None


def test_verify_urls_replaces_404_with_credible_tavily_result(monkeypatch) -> None:
    from llm.verify import verify_urls

    async def fake_head(self, url: str):
        return _Response(404)

    async def fake_tavily(query: str, max_results: int = 3):
        assert query == "Oak Platform Bed"
        return [
            {"title": "Oak Platform Bed - Example Store", "url": "https://store.example.com/product/oak-platform-bed-123"},
        ]

    monkeypatch.setattr(httpx.AsyncClient, "head", fake_head)
    monkeypatch.setattr("llm.verify._tavily_search", fake_tavily)

    items = [{"name": "Oak Platform Bed", "product_url": "https://example.com/dead"}]
    asyncio.run(verify_urls(items))

    assert items[0]["verified"] is True
    assert items[0]["product_url"] == "https://store.example.com/product/oak-platform-bed-123"
    assert items[0].get("fallback_url") is None


def test_verify_urls_drops_url_and_sets_google_fallback_without_credible_result(monkeypatch) -> None:
    from llm.verify import verify_urls

    async def fake_head(self, url: str):
        return _Response(404)

    async def fake_tavily(query: str, max_results: int = 3):
        return [{"title": "Unrelated category page", "url": "https://store.example.com/category/beds"}]

    monkeypatch.setattr(httpx.AsyncClient, "head", fake_head)
    monkeypatch.setattr("llm.verify._tavily_search", fake_tavily)

    items = [{"name": "Oak Platform Bed", "product_url": "https://example.com/dead"}]
    asyncio.run(verify_urls(items))

    assert items[0]["verified"] is False
    assert items[0]["product_url"] is None
    assert items[0]["fallback_url"].startswith("https://www.google.com/search?q=Oak+Platform+Bed")


def test_verify_urls_fires_head_requests_in_parallel(monkeypatch) -> None:
    from llm.verify import verify_urls

    active = 0
    max_active = 0

    async def fake_head(self, url: str):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return _Response(200)

    async def fake_tavily(query: str, max_results: int = 3):
        return []

    monkeypatch.setattr(httpx.AsyncClient, "head", fake_head)
    monkeypatch.setattr("llm.verify._tavily_search", fake_tavily)

    items = [
        {"name": "A", "product_url": "https://example.com/a"},
        {"name": "B", "product_url": "https://example.com/b"},
        {"name": "C", "product_url": "https://example.com/c"},
    ]
    start = time.perf_counter()
    asyncio.run(verify_urls(items))
    elapsed = time.perf_counter() - start

    assert max_active > 1
    assert elapsed < 0.12
    assert all(item["verified"] for item in items)
