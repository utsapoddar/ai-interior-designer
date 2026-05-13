from __future__ import annotations


def build_exclusion_zones(parsed_mesh: dict) -> list[dict]:
    dims = parsed_mesh["dimensions_m"]
    room_width = float(dims["width"])
    room_depth = float(dims["depth"])
    bbox_min = parsed_mesh.get("bounding_box_m", {}).get("min", [0, 0, 0])
    up_axis = parsed_mesh.get("up_axis", "Y")
    depth_index = 2 if up_axis == "Y" else 1
    zones: list[dict] = []

    def clamp(bounds: dict) -> dict:
        return {
            "x_min": round(max(0.0, bounds["x_min"]), 3),
            "x_max": round(min(room_width, bounds["x_max"]), 3),
            "z_min": round(max(0.0, bounds["z_min"]), 3),
            "z_max": round(min(room_depth, bounds["z_max"]), 3),
        }

    def nearest_wall(x: float, z: float) -> str:
        distances = {"south": z, "north": room_depth - z, "west": x, "east": room_width - x}
        return min(distances, key=distances.get)

    features = parsed_mesh.get("features") or {}
    for kind, margin in (("door", 0.9), ("window", 0.4)):
        for feature in features.get(f"{kind}s", []):
            center = feature.get("center_m", [0, 0, 0])
            extent = feature.get("extent_m", [0, 0, 0])
            x = float(center[0]) - float(bbox_min[0])
            z = float(center[depth_index]) - float(bbox_min[depth_index])
            half_x = max(0.05, float(extent[0]) / 2)
            half_z = max(0.05, float(extent[2]) / 2)
            bounds = {"x_min": x - half_x, "x_max": x + half_x, "z_min": z - half_z, "z_max": z + half_z}
            wall = nearest_wall(x, z)
            if wall == "south":
                bounds["z_max"] += margin
            elif wall == "north":
                bounds["z_min"] -= margin
            elif wall == "west":
                bounds["x_max"] += margin
            else:
                bounds["x_min"] -= margin
            zones.append({"kind": kind, "feature_id": feature.get("feature_id", ""), "wall": wall, "bounds": clamp(bounds)})
    return zones


def place_furniture(parsed_mesh: dict, shortlist: list[dict]) -> list[dict]:
    dims = parsed_mesh["dimensions_m"]
    room_width = float(dims["width"])
    room_depth = float(dims["depth"])
    center_x = room_width / 2
    center_z = room_depth / 2
    clear_half_width = 0.35
    exclusion_zones = build_exclusion_zones(parsed_mesh)

    def item_id(item: dict) -> str:
        return str(item.get("id") or item.get("catalog_id"))

    def dims_for(item: dict) -> dict:
        return item["dimensions_m"]

    def rotated_size(item: dict, rotation: int) -> tuple[float, float]:
        d = dims_for(item)
        width = float(d["width"])
        depth = float(d["depth"])
        if rotation in {90, 270}:
            return depth, width
        return width, depth

    def footprint(item: dict, x: float, z: float, rotation: int) -> tuple[float, float, float, float]:
        width, depth = rotated_size(item, rotation)
        return (x - width / 2, x + width / 2, z - depth / 2, z + depth / 2)

    def overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
        return a[0] < b[1] and a[1] > b[0] and a[2] < b[3] and a[3] > b[2]

    def overlap_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
        if not overlaps(a, b):
            return 0.0
        return (min(a[1], b[1]) - max(a[0], b[0])) * (min(a[3], b[3]) - max(a[2], b[2]))

    def zone_fp(zone: dict) -> tuple[float, float, float, float]:
        b = zone["bounds"]
        return (float(b["x_min"]), float(b["x_max"]), float(b["z_min"]), float(b["z_max"]))

    def in_room(fp: tuple[float, float, float, float]) -> bool:
        return fp[0] >= 0 and fp[1] <= room_width and fp[2] >= 0 and fp[3] <= room_depth

    def keeps_center_clear(fp: tuple[float, float, float, float]) -> bool:
        return not (fp[0] < center_x + clear_half_width and fp[1] > center_x - clear_half_width and fp[2] < center_z + clear_half_width and fp[3] > center_z - clear_half_width)

    def avoided_text() -> str:
        if not exclusion_zones:
            return ""
        zone = exclusion_zones[0]
        label = "door swing" if zone["kind"] == "door" else "window clearance"
        return f"; avoids {zone['wall']}-wall {label}"

    def wall_position(item: dict, wall: str) -> tuple[float, float, int, float]:
        width, depth = rotated_size(item, 0 if wall in {"south", "north"} else 90)
        if wall == "south":
            return center_x, depth / 2, 0, room_width
        if wall == "north":
            return center_x, room_depth - depth / 2, 180, room_width
        if wall == "west":
            return width / 2, center_z, 90, room_depth
        return room_width - width / 2, center_z, 270, room_depth

    def run_layout(bed_wall: str) -> tuple[tuple[int, float, float], list[dict]]:
        placed: list[dict] = []
        footprints: list[tuple[float, float, float, float]] = []
        rejected_overlap = 0.0
        opposite_wall = {"south": "north", "north": "south", "west": "east", "east": "west"}[bed_wall]

        def can_place(item: dict, x: float, z: float, rotation: int, allow_center: bool = False) -> tuple[bool, tuple[float, float, float, float], float]:
            fp = footprint(item, x, z, rotation)
            zone_overlap = sum(overlap_area(fp, zone_fp(zone)) for zone in exclusion_zones)
            if not in_room(fp) or (not allow_center and not keeps_center_clear(fp)) or any(overlaps(fp, existing) for existing in footprints) or zone_overlap > 0:
                return False, fp, zone_overlap
            return True, fp, 0.0

        def add(item: dict, x: float, z: float, rotation: int, rationale: str, allow_center: bool = False) -> bool:
            nonlocal rejected_overlap
            ok, fp, zone_overlap = can_place(item, x, z, rotation, allow_center)
            if not ok:
                rejected_overlap += zone_overlap
                return False
            d = dims_for(item)
            placed.append({
                "catalog_id": item_id(item),
                "category": item.get("category", "unknown"),
                "position": {"x": round(x, 3), "y": 0.0, "z": round(z, 3)},
                "rotation_degrees": rotation,
                "dimensions": {"width": float(d["width"]), "depth": float(d["depth"]), "height": float(d["height"])},
                "rationale": rationale + avoided_text() + ".",
            })
            footprints.append(fp)
            return True

        bed = next((item for item in shortlist if item.get("category") == "bed"), None)
        bed_fp = None
        if bed:
            x, z, rotation, wall_len = wall_position(bed, bed_wall)
            if add(bed, x, z, rotation, f"Placed bed on longest wall ({bed_wall}, {wall_len:.1f}m)", allow_center=True):
                bed_fp = footprints[-1]

        nightstands = [item for item in shortlist if "nightstand" in item_id(item).lower() or "nightstand" in str(item.get("name", "")).lower()]
        if bed and bed_fp:
            for side, item in zip((-1, 1), nightstands[:2]):
                width, depth = rotated_size(item, 0 if bed_wall in {"south", "north"} else 90)
                if bed_wall in {"south", "north"}:
                    x = (bed_fp[0] - width / 2) if side < 0 else (bed_fp[1] + width / 2)
                    z = bed_fp[2] + depth / 2 if bed_wall == "south" else bed_fp[3] - depth / 2
                    rotation = 0 if bed_wall == "south" else 180
                else:
                    x = bed_fp[0] + width / 2 if bed_wall == "west" else bed_fp[1] - width / 2
                    z = (bed_fp[2] - depth / 2) if side < 0 else (bed_fp[3] + depth / 2)
                    rotation = 90 if bed_wall == "west" else 270
                add(item, x, z, rotation, f"Placed nightstand beside bed on the {bed_wall} wall", allow_center=True)

        dresser = next((item for item in shortlist if "dresser" in item_id(item).lower() or "dresser" in str(item.get("name", "")).lower()), None)
        if dresser:
            for wall in [opposite_wall, "south", "north", "west", "east"]:
                x, z, rotation, wall_len = wall_position(dresser, wall)
                if add(dresser, x, z, rotation, f"Placed dresser centered on opposite wall ({wall}, {wall_len:.1f}m)"):
                    break

        desk = next((item for item in shortlist if "desk" in item_id(item).lower() or item.get("category") == "desk"), None)
        if desk:
            short_wall = "west" if bed_wall in {"south", "north"} else "south"
            x, z, rotation, wall_len = wall_position(desk, short_wall)
            add(desk, x, z, rotation, f"Placed desk against short wall ({short_wall}, {wall_len:.1f}m)")

        used = {item["catalog_id"] for item in placed}
        walls = ["south", "west", "north", "east"]
        for item in shortlist:
            if item_id(item) in used:
                continue
            for wall in walls:
                x, z, rotation, wall_len = wall_position(item, wall)
                if add(item, x, z, rotation, f"Placed on open wall segment ({wall}, {wall_len:.1f}m) with clearance margin"):
                    used.add(item_id(item))
                    break

        used_area = sum((fp[1] - fp[0]) * (fp[3] - fp[2]) for fp in footprints)
        wasted_floor_area = room_width * room_depth - used_area
        return (len(placed), -rejected_overlap, -wasted_floor_area), placed

    wall_lengths = [(room_width, "south"), (room_width, "north"), (room_depth, "west"), (room_depth, "east")]
    candidate_walls = []
    for _, wall in sorted(wall_lengths, reverse=True):
        if wall not in candidate_walls:
            candidate_walls.append(wall)
        if len(candidate_walls) == 4:
            break
    return max((run_layout(wall) for wall in candidate_walls[:4]), key=lambda result: result[0])[1]

_CATEGORY_PRIORITY = {
    "bed": 0,
    "storage": 1,
    "seating": 2,
    "surface": 3,
    "desk": 3,
    "lighting": 4,
    "textile": 5,
    "decor": 6,
    "unknown": 7,
}

_WALL_ORDER = ["south", "west", "north", "east"]


def _item_id(item: dict) -> str:
    return str(item.get("id") or item.get("catalog_id") or item.get("name") or "item")


def _dims_for(item: dict) -> dict:
    return item.get("dimensions_m") or item.get("dimensions") or {"width": 0.5, "depth": 0.5, "height": 0.5}


def rotated_size(item: dict, rotation: int | float) -> tuple[float, float]:
    dims = _dims_for(item)
    width = float(dims.get("width", 0.5))
    depth = float(dims.get("depth", 0.5))
    if int(rotation) % 180 == 90:
        return depth, width
    return width, depth


def footprint(item: dict, x: float, z: float, rotation: int | float) -> tuple[float, float, float, float]:
    width, depth = rotated_size(item, rotation)
    return (x - width / 2, x + width / 2, z - depth / 2, z + depth / 2)


def overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[1] and a[1] > b[0] and a[2] < b[3] and a[3] > b[2]


def overlap_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    if not overlaps(a, b):
        return 0.0
    return (min(a[1], b[1]) - max(a[0], b[0])) * (min(a[3], b[3]) - max(a[2], b[2]))


def in_room(fp: tuple[float, float, float, float], room_width: float, room_depth: float) -> bool:
    return fp[0] >= 0 and fp[1] <= room_width and fp[2] >= 0 and fp[3] <= room_depth


def _zone_fp(zone: dict) -> tuple[float, float, float, float]:
    b = zone["bounds"]
    return (float(b["x_min"]), float(b["x_max"]), float(b["z_min"]), float(b["z_max"]))


def _nearest_wall(x: float, z: float, room_width: float, room_depth: float) -> str:
    distances = {"south": z, "north": room_depth - z, "west": x, "east": room_width - x}
    return min(distances, key=distances.get)


def _room_adjustment(fp: tuple[float, float, float, float], room_width: float, room_depth: float) -> tuple[float, float]:
    dx = 0.0
    dz = 0.0
    if fp[0] < 0:
        dx = -fp[0]
    elif fp[1] > room_width:
        dx = room_width - fp[1]
    if fp[2] < 0:
        dz = -fp[2]
    elif fp[3] > room_depth:
        dz = room_depth - fp[3]
    return dx, dz


def _placement(item: dict, x: float, z: float, rotation: int | float, note: str | None = None) -> dict:
    dims = _dims_for(item)
    rationale = str(item.get("rationale", ""))
    if note:
        rationale = f"{rationale} ({note})" if rationale else f"({note})"
    placed = dict(item)
    placed.setdefault("id", _item_id(item))
    placed.setdefault("catalog_id", placed["id"])
    placed["position"] = {"x": round(x, 3), "y": float(item.get("position", {}).get("y", 0.0)), "z": round(z, 3)}
    placed["rotation_degrees"] = int(rotation)
    placed["dimensions_m"] = {"width": float(dims.get("width", 0.5)), "depth": float(dims.get("depth", 0.5)), "height": float(dims.get("height", 0.5))}
    placed["dimensions"] = dict(placed["dimensions_m"])
    placed["rationale"] = rationale
    return placed


def _new_anchor_state() -> dict:
    return {"offsets": {wall: 0.0 for wall in _WALL_ORDER}, "footprints": []}


def _wall_candidates(preference: str) -> list[str]:
    if preference == "any":
        return list(_WALL_ORDER)
    if preference in _WALL_ORDER:
        index = _WALL_ORDER.index(preference)
        return _WALL_ORDER[index:] + _WALL_ORDER[:index]
    return list(_WALL_ORDER)


def _anchor_candidate(parsed_mesh: dict, item: dict, wall: str, offset: float) -> tuple[float, float, int, float, float]:
    dims = parsed_mesh["dimensions_m"]
    room_width = float(dims["width"])
    room_depth = float(dims["depth"])
    if wall == "south":
        rotation = 0
        width, depth = rotated_size(item, rotation)
        return room_width / 2 - offset, depth / 2, rotation, room_width, width
    if wall == "north":
        rotation = 180
        width, depth = rotated_size(item, rotation)
        return room_width / 2 - offset, room_depth - depth / 2, rotation, room_width, width
    if wall == "west":
        rotation = 90
        width, depth = rotated_size(item, rotation)
        return width / 2, room_depth / 2 - offset, rotation, room_depth, depth
    rotation = 270
    width, depth = rotated_size(item, rotation)
    return room_width - width / 2, room_depth / 2 - offset, rotation, room_depth, depth


def _anchor_to_wall(parsed_mesh: dict, item: dict, occupied: dict) -> tuple[float, float, int]:
    preference = str(item.get("wall_preference") or "any").lower()
    if preference == "center":
        dims = parsed_mesh["dimensions_m"]
        x = float(dims["width"]) / 2
        z = float(dims["depth"]) / 2
        rotation = 0
        occupied.setdefault("footprints", []).append(footprint(item, x, z, rotation))
        return round(x, 3), round(z, 3), rotation

    offsets = occupied.setdefault("offsets", {wall: 0.0 for wall in _WALL_ORDER})
    footprints = occupied.setdefault("footprints", [])
    fallback: tuple[str, float, float, int, float] | None = None
    for wall in _wall_candidates(preference):
        offset = float(offsets.get(wall, 0.0))
        x, z, rotation, wall_length, along_size = _anchor_candidate(parsed_mesh, item, wall, offset)
        if offset > 0 and offset + along_size / 2 > wall_length / 2:
            offset = 0.0
            x, z, rotation, wall_length, along_size = _anchor_candidate(parsed_mesh, item, wall, offset)
        fp = footprint(item, x, z, rotation)
        if fallback is None:
            fallback = (wall, x, z, rotation, along_size)
        if preference != "any" or not any(overlaps(fp, existing) for existing in footprints):
            offsets[wall] = offset + along_size + 0.2
            footprints.append(fp)
            return round(x, 3), round(z, 3), rotation

    wall, x, z, rotation, along_size = fallback or ("south", 0.0, 0.0, 0, 0.0)
    offsets[wall] = float(offsets.get(wall, 0.0)) + along_size + 0.2
    footprints.append(footprint(item, x, z, rotation))
    return round(x, 3), round(z, 3), rotation


def _anchor_items(parsed_mesh: dict, items: list[dict]) -> list[dict]:
    occupied = _new_anchor_state()
    anchored: list[dict] = []
    for item in items:
        if item.get("position") and item.get("rotation_degrees") is not None:
            anchored.append(item)
            pos = item.get("position") or {}
            occupied["footprints"].append(footprint(item, float(pos.get("x", 0.0)), float(pos.get("z", 0.0)), int(float(item.get("rotation_degrees", 0)))))
            continue
        x, z, rotation = _anchor_to_wall(parsed_mesh, item, occupied)
        anchored_item = dict(item)
        anchored_item["position"] = {"x": x, "y": 0.0, "z": z}
        anchored_item["rotation_degrees"] = rotation
        anchored.append(anchored_item)
    return anchored


def validate_and_repair(parsed_mesh: dict, proposed_items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (placed_items, repair_log) in parsed_mesh coordinates."""
    if not proposed_items:
        return [], []

    dims = parsed_mesh["dimensions_m"]
    room_width = float(dims["width"])
    room_depth = float(dims["depth"])
    exclusion_zones = build_exclusion_zones(parsed_mesh)
    zone_fps = [(zone, _zone_fp(zone)) for zone in exclusion_zones]
    placed: list[dict] = []
    placed_fps: list[tuple[float, float, float, float]] = []
    repair_log: list[dict] = []

    def collides(fp: tuple[float, float, float, float]) -> bool:
        return any(overlaps(fp, existing) for existing in placed_fps)

    def zone_hit(fp: tuple[float, float, float, float]) -> dict | None:
        hits = [(overlap_area(fp, zfp), zone) for zone, zfp in zone_fps if overlaps(fp, zfp)]
        if not hits:
            return None
        return max(hits, key=lambda pair: pair[0])[1]

    ordered = _anchor_items(
        parsed_mesh,
        sorted(proposed_items, key=lambda item: _CATEGORY_PRIORITY.get(str(item.get("category", "unknown")), 7)),
    )
    for item in ordered:
        item_id = _item_id(item)
        pos = item.get("position") or {}
        x = float(pos.get("x", room_width / 2))
        z = float(pos.get("z", room_depth / 2))
        rotation = int(float(item.get("rotation_degrees", 0)))
        action = "kept"
        reason = "kept proposed placement"
        note = None

        fp = footprint(item, x, z, rotation)
        if not in_room(fp, room_width, room_depth):
            dx, dz = _room_adjustment(fp, room_width, room_depth)
            if abs(dx) <= 0.5 and abs(dz) <= 0.5:
                x += dx
                z += dz
                action = "snapped"
                reason = "snapped inside room bounds"
                note = "snapped to wall"
                fp = footprint(item, x, z, rotation)
            else:
                repair_log.append({"id": item_id, "action": "dropped", "reason": "outside room bounds beyond snap limit"})
                continue

        hit = zone_hit(fp)
        if hit:
            original_x, original_z = x, z
            wall = hit.get("wall") or _nearest_wall(x, z, room_width, room_depth)
            direction = {"south": (0.0, 1.0), "north": (0.0, -1.0), "west": (1.0, 0.0), "east": (-1.0, 0.0)}[wall]
            resolved = False
            for step in range(1, 8):
                nx = original_x + direction[0] * step * 0.1
                nz = original_z + direction[1] * step * 0.1
                nfp = footprint(item, nx, nz, rotation)
                if in_room(nfp, room_width, room_depth) and not zone_hit(nfp):
                    x, z, fp = nx, nz, nfp
                    action = "shifted_zone"
                    reason = f"shifted away from {hit.get('kind', 'exclusion')} zone"
                    note = reason
                    resolved = True
                    break
            if not resolved:
                repair_log.append({"id": item_id, "action": "dropped", "reason": f"could not clear {hit.get('kind', 'exclusion')} zone"})
                continue

        if collides(fp):
            original_x, original_z = x, z
            wall = _nearest_wall(x, z, room_width, room_depth)
            axis = "x" if wall in {"south", "north"} else "z"
            resolved = False
            for step in range(1, 8):
                for sign in (1, -1):
                    nx = original_x + (sign * step * 0.1 if axis == "x" else 0.0)
                    nz = original_z + (sign * step * 0.1 if axis == "z" else 0.0)
                    nfp = footprint(item, nx, nz, rotation)
                    if in_room(nfp, room_width, room_depth) and not zone_hit(nfp) and not collides(nfp):
                        x, z, fp = nx, nz, nfp
                        action = "shifted_collision"
                        reason = "shifted to avoid another item"
                        note = reason
                        resolved = True
                        break
                if resolved:
                    break
            if not resolved:
                repair_log.append({"id": item_id, "action": "dropped", "reason": "could not avoid item collision"})
                continue

        placed.append(_placement(item, x, z, rotation, note))
        placed_fps.append(fp)
        repair_log.append({"id": item_id, "action": action, "reason": reason})

    return placed, repair_log
