# LiDAR Room Designer

## Overview

LiDAR Room Designer is a personal prototype for turning an iPhone RoomPlan scan into a furniture plan for the user's real room, not a generated room that merely resembles it. The product solves the geometry-fidelity gap in common AI interior tools: instead of restyling a flat photo and hallucinating walls, windows, doors, ceiling height, and furniture scale, it treats the LiDAR-derived room mesh as the source of truth and uses a vision-capable LLM plus a placement reasoner to choose furniture and layout against known geometry.

## Locked Decisions

1. **Platform split**: iOS handles RoomPlan capture only; the web app handles upload, chat, preview, and everything else. Rationale: keep the native work limited to the one capability the web cannot provide.
2. **USDZ parsing location**: the backend receives the web-uploaded USDZ and parses it into structured mesh JSON. Rationale: backend parsing keeps logs, schema inspection, and solver iteration in one place.
3. **Placement contract**: the LLM extracts taste, constraints, and candidate furniture; a deterministic Python layout solver computes final coordinates, collisions, and clearances. Rationale: LLM coordinates are advisory, while the solver remains the source of truth for what goes where.
4. **Vision LLM provider**: use NVIDIA NIM via OpenAI-compatible API with `meta/llama-3.2-90b-vision-instruct` as the primary model. Rationale: free NVIDIA build-platform access, vision capability, and an OpenAI-compatible client keep the prototype cheap and simple until NIM proves insufficient.

## User Flow

1. User opens the mobile app and starts a new one-room project.
2. App guides the user through scanning the bedroom with iPhone LiDAR using Apple RoomPlan.
3. User reviews the captured room boundary, ceiling height, doors, windows, and fixed openings.
4. App exports the scan as USDZ for handoff to the web app.
5. User uploads the USDZ in the web app, which sends it to the backend as the project geometry source.
6. Backend parses the USDZ file into normalized mesh JSON: room dimensions, wall segments, windows, doors, outlets if available, and coordinate frame metadata.
7. User opens the chat panel for that scanned room.
8. User attaches visual references such as a Pinterest screenshot, catalog PDF page, furniture photo, or image of an owned item.
9. User describes the goal in natural language, for example: "minimalist, warm wood, low bed, reading nook by the window, budget around $3k."
10. Chat orchestrator packages the parsed mesh JSON, reference-image summaries, budget, style notes, and catalog candidates into one planning request.
11. Claude vision call interprets the user's images and prompt into style constraints, must-have objects, avoided objects, and candidate product preferences.
12. Furniture catalog lookup returns specific furniture candidates with dimensions, approximate prices, asset references, and availability notes.
13. Layout solver places selected furniture in the scanned room coordinate system, checking clearance, scale, door swings, window conflicts, and reachable walking paths.
14. Solver emits structured furniture-placement JSON with item IDs, dimensions, positions, rotations, and rationale.
15. Renderer loads the original parsed room geometry plus furniture assets and displays the proposed furnished room in 3D.
16. User gets a concrete furniture plan: 3D preview, item list, dimensions, budget estimate, and explanation of why each piece fits where it was placed.

## System Architecture

```text
+--------------------+        +------------------------+        +----------------------+
| iOS Capture Client | -----> | Web Frontend           | -----> | Backend              |
| RoomPlan -> USDZ   | USDZ   | upload + chat + preview| USDZ   | parser + orchestrator|
+--------------------+        +-----------+------------+        +----------+-----------+
                                            ^                              |
                                            | placement JSON + mesh        | parsed mesh JSON
                                            |                              v
                               +------------+-------------+        +----------------------+
                               | 3D Preview Renderer      |        | LLM Orchestrator     |
                               | scanned room + items     |        | prompt/ref reasoning |
                               +--------------------------+        +----------+-----------+
                                                                            | style constraints
                                                                            | + catalog candidates
                                                                            v
                               +--------------------------+        +----------------------+
                               | Furniture Catalog        | -----> | Python Layout Solver |
                               | dimensions + assets      |        | collisions/clearance |
                               +--------------------------+        +----------+-----------+
                                                                            |
                                                                            | furniture-placement JSON
                                                                            v
                                                                    Web Frontend
```

The architecture is intentionally small: one user, one room, one active design plan at a time. The iOS client owns capture only, the web frontend owns upload, chat, and preview, and the backend owns USDZ parsing, LLM orchestration, catalog lookup, and deterministic layout solving. RoomPlan owns geometric truth, the backend parser converts it into compact planning data, Claude interprets images and style intent, the catalog provides real furniture dimensions, the Python solver converts intent into checked coordinates, and the renderer shows the result without changing the scanned room shell.

## Data Flow

1. **RoomPlan USDZ export**: The iOS scan produces a USDZ file containing the room shell and detected architectural objects. This file is stored unchanged as the authoritative source for the project.
2. **USDZ to parsed mesh JSON**: The ingest layer extracts a simplified JSON representation for reasoning: units, coordinate frame, room bounding dimensions, ceiling height, wall segments, corners, openings, doors, windows, and any detected fixed features such as outlets if exposed by the scan pipeline.
3. **Parsed mesh JSON to LLM context**: The chat orchestrator trims the parsed mesh into model-friendly context: room size, wall IDs, usable wall lengths, blocked regions, window/door positions, clearance rules, and a short natural-language room summary.
4. **User prompt and reference images to LLM context**: User text, image attachments, and PDF-derived page images are sent to Claude vision for style extraction. The output is not a final room image; it is a structured intent summary.
5. **Catalog data to planning context**: Candidate furniture is represented as JSON records with stable IDs, names, categories, dimensions, price, material/style tags, and optional 3D asset URL.
6. **LLM context to placement request**: The orchestrator combines geometry constraints, style intent, budget, owned-item constraints, and candidate furniture into a placement request.
7. **Placement request to structured furniture-placement JSON**: The layout solver returns specific items with coordinates in room space, rotations, dimensions, clearance assumptions, and conflict-check results.
8. **Placement JSON to renderer**: The renderer loads the original room geometry, then overlays furniture models or simple dimension-accurate proxies at the specified coordinates.
9. **Renderer to user**: The user sees a faithful 3D preview of their scanned room with proposed furniture, plus a shopping and placement plan.

Example placement JSON shape, described not implemented:

```json
{
  "room_id": "single-room-project",
  "unit": "meters",
  "items": [
    {
      "catalog_id": "bed_low_oak_queen_001",
      "category": "bed",
      "position": { "x": 2.1, "y": 0.0, "z": 3.4 },
      "rotation_degrees": 90,
      "dimensions": { "width": 1.6, "depth": 2.1, "height": 0.8 },
      "rationale": "Places the bed on the longest uninterrupted wall and preserves window access."
    }
  ]
}
```

## Tech Choices

| Component | Primary choice | Why primary | Viable alternative | Why not primary |
| --- | --- | --- | --- | --- |
| LiDAR scan | Apple RoomPlan | iOS-native, captures room-scale geometry with walls, windows, doors, and USDZ export; it is the practical source of truth for iPhone LiDAR. | ARKit raw mesh capture | More flexible, but would require rebuilding semantic room detection that RoomPlan already provides. |
| USDZ parsing | Pixar USD Python bindings on the backend | Server-side parsing matches the locked upload flow and keeps geometry logs, schemas, and solver inputs inspectable. | Apple ModelIO on-device | Useful for native inspection, but it would split parsing away from the backend solver loop. |
| Chat backend | Python FastAPI | Simple API surface for upload, parse, chat, catalog lookup, and placement; Python is also convenient for geometry checks and later solver experiments. | Node with Express | Good for web teams, but less convenient for geometry/prototyping libraries. |
| Vision LLM | NVIDIA NIM via OpenAI-compatible API, `meta/llama-3.2-90b-vision-instruct` | Free access via NVIDIA build platform; vision-capable; OpenAI-compatible client. | Claude API with vision (`claude-sonnet-4-6`) | Paid; not needed until NVIDIA NIM proves insufficient. |
| Prompt templates | Markdown templates under `llm/prompts` | Keeps prompt contracts readable while the architecture is still changing. | Hardcoded prompts in backend | Faster at first, but harder to review and tune. |
| Furniture catalog | Static seed catalog | Reliable dimensions and prices for a prototype; avoids depending on unofficial or unstable retailer APIs. | IKEA or Wayfair APIs if accessible | Better real inventory, but API access and terms may block fast prototyping. |
| 3D asset sources | Poly Pizza for simple assets plus dimension-accurate box proxies | Lightweight, web-friendly assets; proxies preserve scale even when exact models are missing. | Sketchfab API or Meshy image-to-3D | Richer visuals, but licensing, API complexity, and generated-model scale issues can distract from layout fidelity. |
| Layout solver | Python constraint-satisfaction solver with greedy candidate generation and collision checks | Concrete enough for a first build: generate plausible placements, then deterministically reject violations for doors, paths, bed access, windows, and item collisions. | LLM-as-solver returning coordinates directly | Fast to prototype, but harder to trust for clearance, collisions, and repeatability. |
| Renderer | Three.js web renderer | Cross-platform preview surface for desktop and mobile browsers; easy to load room geometry, furniture assets, and simple proxies. | RealityKit native renderer | Best iOS feel, but locks the prototype into native app work before validating the planning loop. |
| Frontend shell | Web app first | Fastest way to combine file upload, chat, references, and 3D preview in one interface. | iOS native app | Required for best RoomPlan capture, but heavier for chat and iteration; use iOS only for scan/export initially. |
| Tests | Contract fixtures for JSON formats | Architecture hinges on stable data contracts, not UI polish; fixtures can validate mesh JSON and placement JSON later. | Full end-to-end visual tests | Too much for a docs-only scaffold and early prototype. |

## Directory Structure

```text
room-designer/
├── README.md
├── ingest/
│   ├── .gitkeep              # Placeholder for scan ingestion boundary docs or future glue.
│   ├── usdz/
│   │   └── .gitkeep          # Future home for USDZ handling notes and sample-scan placeholders.
│   └── parsed-mesh/
│       └── .gitkeep          # Future home for parsed mesh JSON schema and fixtures.
├── chat/
│   └── .gitkeep              # Future chat orchestrator boundary: uploads, prompts, and planning requests.
├── llm/
│   ├── .gitkeep              # Future LLM integration notes and model contract docs.
│   └── prompts/
│       └── .gitkeep          # Future prompt templates for style extraction and placement planning.
├── catalog/
│   ├── .gitkeep              # Future furniture catalog contracts and item-dimension rules.
│   └── seed/
│       └── .gitkeep          # Future static seed catalog records for prototype furniture.
├── renderer/
│   └── .gitkeep              # Future 3D preview renderer surface and scene contract docs.
├── frontend/
│   └── .gitkeep              # Future web or app shell for scan upload, chat, and preview.
├── docs/
│   └── .gitkeep              # Supporting architecture notes and decision records if needed.
└── tests/
    └── .gitkeep              # Future contract tests for mesh JSON and placement JSON.
```

The scaffold intentionally avoids implementation files. The first real implementation should add only the smallest pieces needed to prove the loop: import one RoomPlan USDZ, parse one room into JSON, place a few furniture proxies, and render them in the scanned coordinate frame.

## AR (v2)

AR is a v2 capability, not part of the v1 loop. The v1 pipeline remains unchanged: RoomPlan capture, backend parsing, Python solver, placement JSON, and web box-proxy preview.

AR is a presentation layer, not a correctness layer. The geometry-fidelity guarantee is already delivered by the LiDAR scan, parsed room geometry, and deterministic solver; AR only changes where the checked placement is shown.

The same placement JSON, in meters and in the RoomPlan coordinate frame, can render natively in RealityKit on iOS instead of Three.js on the web. The existing iOS capture client would gain a second screen: an AR preview that overlays the solver's furniture placement on top of the real room.

V2 unlocks three user-facing capabilities:

1. **Live in-room preview at true scale** using the scanned room coordinate system.
2. **Drag-to-adjust furniture in AR**, with updated positions flowing back to the solver as user constraints.
3. **Optional ARKit capture of owned furniture pieces** for items the user already has.

Explicit non-goals for v2: photorealistic rendering, multi-room navigation, and shared sessions.

## Open Questions

1. **How strict should geometry fidelity be?** The prototype should never move walls, windows, or doors. It can simplify meshes into wall/opening primitives for reasoning, but the renderer should keep the scanned room shell visually anchored.
2. **How much catalog realism is needed?** A static catalog is enough to validate layout fidelity. Real retailer integrations should wait until the prototype proves users trust the generated furniture plan.
3. **How should owned furniture be handled?** A user photo can inform style, but exact placement needs dimensions. The app may need a manual dimension entry step for owned items.
4. **How are PDFs processed?** Catalog PDFs should be converted into selected page images or text snippets before the vision call. Full PDF ingestion can wait.
5. **How are scale and units enforced?** The system should normalize everything to meters and preserve original scan scale metadata. Any catalog item without dimensions should be rejected or represented only as inspiration.
6. **What preview quality is acceptable?** Early previews can use dimension-accurate box proxies with labels. Photorealistic models should come later because the differentiator is geometry accuracy, not rendering beauty.
7. **How are bad scans handled?** The architecture needs a future validation step for missing walls, broken openings, or inconsistent ceiling height before the model is allowed to plan.
8. **What is the budget behavior?** The prototype should treat budget as a soft constraint unless catalog prices are reliable. If prices are stale or approximate, the plan should say so.
9. **Should the system optimize one plan or offer alternatives?** Recommended default: generate one best plan plus rationale. Multiple alternatives can wait until the core one-room loop works.
10. **How are safety and clearance rules defined?** Minimum walking clearances, door swing zones, bed access, and window access should be explicit constants before solver implementation.
11. **What counts as success for the first build?** A good first milestone is one scanned bedroom, one seed catalog, one prompt, one placement JSON, and one faithful 3D preview with no wall hallucination.

## First Implementation Milestone

Smallest end-to-end loop: one scanned bedroom, one seed catalog, one prompt, one placement JSON, and one box-proxy preview in the scanned coordinate frame.

Priority order:

1. **Sample bedroom USDZ** exported from the iOS RoomPlan capture client.
2. **Web USDZ upload path** that sends the scan to the backend as the project geometry source.
3. **Backend USDZ parser** that converts the scan into one normalized mesh JSON fixture.
4. **Seed furniture catalog** with a few dimensioned bedroom items: bed, nightstand, dresser, desk, chair, and lamp.
5. **LLM orchestration prompt** that extracts style, constraints, and a candidate furniture shortlist from one user prompt.
6. **Python layout solver** that emits placement JSON with coordinates, rotations, dimensions, and clearance/collision results.
7. **Web box-proxy preview** that renders the scanned room shell with dimension-accurate furniture boxes and labels.
