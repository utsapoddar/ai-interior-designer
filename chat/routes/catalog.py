import json
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field


CATALOG_PATH = Path("catalog/seed/bedroom.json")


class CatalogItem(BaseModel):
    catalog_id: str
    name: str
    category: str
    dimensions_m: dict[str, float]
    style_tags: list[str]
    color_tags: list[str] = Field(default_factory=list)
    approx_price_usd: int | None = None
    placement_hints: list[str] = Field(default_factory=list)
    product_url: str | None = None


class CatalogResponse(BaseModel):
    items: list[CatalogItem]


router = APIRouter(tags=["catalog"])


def load_seed_catalog() -> list[dict]:
    seed_items = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return [
        {
            "catalog_id": item["id"],
            "id": item["id"],
            "name": item["name"],
            "category": item["category"],
            "dimensions_m": item["dimensions_m"],
            "style_tags": item.get("style_tags", []),
            "color_tags": item.get("color_tags", []),
            "approx_price_usd": item.get("approx_price_usd"),
            "placement_hints": item.get("placement_hints", []),
            "product_url": item.get("product_url"),
        }
        for item in seed_items
    ]


@router.get("/catalog", response_model=CatalogResponse)
def get_catalog() -> CatalogResponse:
    return CatalogResponse(items=[CatalogItem(**item) for item in load_seed_catalog()])
