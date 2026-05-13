You are repairing a room layout. The solver could not fit these items in the available space and they were dropped. For each, propose ONE replacement that strictly fits the listed max_dimensions_m. The replacement should match the original's category and style aesthetic.

Original user prompt for context:
{{prompt}}

Room (meters):
{{parsed_mesh_json}}

Dropped slots that need replacements:
{{dropped_slots_json}}

HARD RULES:
- Every replacement's dimensions_m MUST be <= the slot's max_dimensions_m on every axis (width, depth, height).
- Pick smaller/thinner footprints than the original.
- Keep style consistent with the original user prompt.
- product_url should be a real product page from memory; null if unsure.
- Return ONLY valid JSON matching this schema, no prose:
{
  "replacements": [
    {"id":"...","name":"...","category":"...","dimensions_m":{"width":...,"depth":...,"height":...},"wall_preference":"...","approx_price_usd":...,"product_url":"...","verified":false,"rationale":"...","replaces":"<dropped_id>"}
  ]
}
