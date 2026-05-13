# Bedroom Seed Catalog Schema

Top-level JSON value: array of item objects.

## Fields

| Field | Type | Required | Notes |
|---|---:|---:|---|
| `id` | string | yes | Unique slug, lowercase kebab-case. |
| `name` | string | yes | Human-readable item name. |
| `category` | string | yes | One of `bed`, `storage`, `seating`, `lighting`, `surface`, `decor`, `textile`. |
| `dimensions_m` | object | yes | Dimensions in meters. Must include numeric `width`, `depth`, `height`; each value should be greater than 0 and less than 5. |
| `style_tags` | string[] | yes | Style descriptors from the allowed list below. |
| `color_tags` | string[] | yes | Color/material descriptors from the allowed list below. |
| `approx_price_usd` | integer | yes | Ballpark retail price in USD. |
| `placement_hints` | string[] | yes | Placement descriptors from the allowed list below. |

## Allowed values

### `category`

`bed`, `storage`, `seating`, `lighting`, `surface`, `decor`, `textile`

### `style_tags`

`minimalist`, `modern`, `scandinavian`, `warm-wood`, `industrial`, `transitional`, `bohemian`, `natural`

### `color_tags`

`natural-oak`, `off-white`, `matte-black`, `walnut`, `brass`, `dark-metal`, `white`, `charcoal`, `cream`, `light-wood`, `gray`, `natural-fiber`, `tan`

### `placement_hints`

`against-wall`, `needs-clearance-sides`, `anchor-piece`, `corner-friendly`, `needs-clearance-side`, `beside-bed`, `reachable-from-bed`, `needs-clearance-front`, `near-closet`, `small-room-friendly`, `near-window`, `needs-chair-clearance`, `at-desk`, `needs-clearance-back`, `movable`, `reading-corner`, `beside-chair`, `near-outlet`, `on-nightstand`, `on-dresser`, `under-bed-front`, `center-room`, `low-clearance`, `under-bed`, `anchor-to-wall`, `avoid-direct-glare`

## Example item

```json
{
  "id": "queen-platform-bed",
  "name": "Queen Platform Bed",
  "category": "bed",
  "dimensions_m": {
    "width": 1.6,
    "depth": 2.12,
    "height": 0.9
  },
  "style_tags": ["minimalist", "scandinavian"],
  "color_tags": ["natural-oak", "off-white"],
  "approx_price_usd": 650,
  "placement_hints": ["against-wall", "needs-clearance-sides", "anchor-piece"]
}
```
