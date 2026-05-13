from __future__ import annotations

import asyncio
import os
import re
from collections import OrderedDict
from urllib.parse import quote_plus, urlparse

import httpx


_SEARCH_CACHE: OrderedDict[tuple[str, int], list[dict]] = OrderedDict()
_CACHE_LIMIT = 64
_STOPWORDS = {"the", "a", "an", "and", "or", "for", "of", "to", "in", "with", "by", "on", "at"}


async def verify_urls(items: list[dict]) -> list[dict]:
    """Verify or replace product URLs in-place, returning the same list reference."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
        head_tasks = [_head_ok(client, item.get("product_url")) for item in items]
        results = await asyncio.gather(*head_tasks, return_exceptions=True)

    failed_indexes: list[int] = []
    for index, (item, result) in enumerate(zip(items, results, strict=False)):
        if result is True:
            item["verified"] = True
            item["fallback_url"] = None
        else:
            failed_indexes.append(index)

    replacements = await asyncio.gather(
        *[_replacement_url(items[index]) for index in failed_indexes],
        return_exceptions=True,
    )
    for index, replacement in zip(failed_indexes, replacements, strict=False):
        item = items[index]
        if isinstance(replacement, str) and replacement:
            item["product_url"] = replacement
            item["verified"] = True
            item["fallback_url"] = None
        else:
            item["product_url"] = None
            item["verified"] = False
            item["fallback_url"] = _google_search_url(str(item.get("name") or ""))

    return items


async def _head_ok(client: httpx.AsyncClient, url: str | None) -> bool:
    if not url:
        return False
    response = await client.head(url)
    return 200 <= response.status_code < 300


async def _replacement_url(item: dict) -> str | None:
    name = str(item.get("name") or "")
    results = await _tavily_search(name)
    if not results or not _title_mentions_name(str(results[0].get("title") or ""), name):
        return None

    for result in results:
        url = result.get("url")
        if isinstance(url, str) and _looks_like_product_page(url):
            return url

    url = results[0].get("url")
    return url if isinstance(url, str) and url else None


async def _tavily_search(query: str, max_results: int = 3) -> list[dict]:
    key = (query, max_results)
    if key in _SEARCH_CACHE:
        _SEARCH_CACHE.move_to_end(key)
        return _SEARCH_CACHE[key]

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
                json={"query": query, "max_results": max_results, "search_depth": "basic"},
            )
    except Exception:
        return []

    if response.status_code != 200:
        return []

    try:
        results = response.json().get("results", [])
    except Exception:
        results = []
    if not isinstance(results, list):
        results = []

    _SEARCH_CACHE[key] = results
    if len(_SEARCH_CACHE) > _CACHE_LIMIT:
        _SEARCH_CACHE.popitem(last=False)
    return results


def _title_mentions_name(title: str, name: str) -> bool:
    title_words = set(_content_words(title))
    return any(word in title_words for word in _content_words(name))


def _content_words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in _STOPWORDS]


def _looks_like_product_page(url: str) -> bool:
    path = urlparse(url).path.lower()
    segments = [segment for segment in path.split("/") if segment]
    return (
        any(char.isdigit() for char in path)
        or "product" in path
        or "item" in path
        or "p" in segments
    )


def _google_search_url(name: str) -> str:
    return f"https://www.google.com/search?q={quote_plus(name)}"
