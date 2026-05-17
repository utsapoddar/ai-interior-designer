from pathlib import Path
from collections import defaultdict
import logging
import math
from zipfile import ZipFile, is_zipfile

import numpy as np
from pxr import Gf, Usd, UsdGeom


logger = logging.getLogger(__name__)
_LABELED_PRIM_NAMES = {"walls", "doors", "windows", "object"}
_FEATURE_LABELS = {"walls": "walls", "doors": "doors", "windows": "windows"}


def parse_usdz(path) -> dict:
    source_path = Path(path)
    stage = Usd.Stage.Open(str(source_path))
    if stage is None:
        raise ValueError(f"Could not open USDZ file: {source_path}")

    up_axis = str(UsdGeom.GetStageUpAxis(stage)).upper()
    if up_axis not in {"Y", "Z"}:
        raise ValueError(f"Unsupported USD up-axis {up_axis!r}; expected Y or Z")

    meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    xform_cache = UsdGeom.XformCache()
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    all_points: list[np.ndarray] = []
    triangle_count = 0
    features = {"walls": [], "doors": [], "windows": []}
    existing_furniture: list[dict] = []
    roomplan_walls: list[dict] = []
    roomplan_index = _roomplan_index(source_path)

    for prim in stage.Traverse():
        bounds = _world_bounds(prim, bbox_cache, meters_per_unit)

        if prim.IsA(UsdGeom.Mesh):
            mesh = UsdGeom.Mesh(prim)
            points = mesh.GetPointsAttr().Get()
            if points:
                local_to_world = xform_cache.GetLocalToWorldTransform(prim)
                transformed = np.asarray([
                    _transform_point(local_to_world, point) * meters_per_unit
                    for point in points
                ], dtype=float)
                all_points.append(transformed)
                bounds = (transformed.min(axis=0), transformed.max(axis=0))

            face_counts = mesh.GetFaceVertexCountsAttr().Get() or []
            triangle_count += sum(max(0, int(count) - 2) for count in face_counts)

            roomplan_entry = _roomplan_entry(prim.GetName(), roomplan_index)
            if roomplan_entry:
                try:
                    extracted = _extract_roomplan_prim(prim, bounds, xform_cache, meters_per_unit, up_axis)
                except Exception as exc:  # pragma: no cover - defensive skip for malformed scans
                    logger.warning("Skipping RoomPlan prim %s: %s", prim.GetPath(), exc)
                    extracted = None
                if extracted:
                    kind = roomplan_entry["kind"]
                    extracted["id"] = roomplan_entry["id"]
                    extracted["feature_id"] = roomplan_entry["id"]
                    if kind == "furniture":
                        extracted["category"] = roomplan_entry["category"]
                        existing_furniture.append(extracted)
                    else:
                        extracted["kind"] = kind[:-1]
                        if roomplan_entry.get("wall_id"):
                            extracted["wall_id"] = roomplan_entry["wall_id"]
                        features[kind].append(extracted)
                        if kind == "walls":
                            roomplan_walls.append(extracted)
        elif bounds is not None:
            all_points.append(np.asarray([bounds[0], bounds[1]], dtype=float))

        bucket = _feature_bucket(prim)
        if bucket:
            feature = _extract_feature(prim, bucket, bounds, xform_cache, meters_per_unit, up_axis)
            if feature:
                features[bucket].append(feature)

    if not all_points:
        raise ValueError(f"No mesh points found in USDZ file: {source_path}")

    vertices = np.vstack(all_points)
    bbox_min = vertices.min(axis=0)
    bbox_max = vertices.max(axis=0)
    extents = bbox_max - bbox_min

    up_index = 1 if up_axis == "Y" else 2
    depth_index = 2 if up_axis == "Y" else 1
    parametric = any(features[bucket] for bucket in features) or bool(existing_furniture)

    return {
        "schema_version": "v1",
        "units": "meters",
        "bounding_box_m": {
            "min": bbox_min.tolist(),
            "max": bbox_max.tolist(),
        },
        "dimensions_m": {
            "width": float(extents[0]),
            "depth": float(extents[depth_index]),
            "height": float(extents[up_index]),
        },
        "up_axis": up_axis,
        "floor_z_or_y_m": float(bbox_min[up_index]),
        "ceiling_z_or_y_m": float(bbox_max[up_index]),
        "triangle_count": int(triangle_count),
        "has_labeled_primitives": parametric,
        "parametric": parametric,
        "features": features,
        "outline_m": _build_outline(roomplan_walls),
        "existing_furniture": existing_furniture,
        "source_file_bytes": source_path.stat().st_size,
    }


def _transform_point(matrix: Gf.Matrix4d, point) -> np.ndarray:
    transformed = matrix.Transform(Gf.Vec3d(point[0], point[1], point[2]))
    return np.array([transformed[0], transformed[1], transformed[2]], dtype=float)


def _world_bounds(prim: Usd.Prim, bbox_cache: UsdGeom.BBoxCache, meters_per_unit: float):
    if not prim.IsA(UsdGeom.Boundable):
        return None
    bbox_range = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
    if bbox_range.IsEmpty():
        return None
    min_pt = bbox_range.GetMin()
    max_pt = bbox_range.GetMax()
    return (
        np.array([min_pt[0], min_pt[1], min_pt[2]], dtype=float) * meters_per_unit,
        np.array([max_pt[0], max_pt[1], max_pt[2]], dtype=float) * meters_per_unit,
    )


def _extract_feature(prim: Usd.Prim, bucket: str, bounds, xform_cache: UsdGeom.XformCache, meters_per_unit: float, up_axis: str):
    if bounds is None:
        return None
    local_to_world = xform_cache.GetLocalToWorldTransform(prim)
    translation = local_to_world.ExtractTranslation()
    bbox_center = (bounds[0] + bounds[1]) / 2
    center = bbox_center if prim.IsA(UsdGeom.Mesh) else np.array([translation[0], translation[1], translation[2]], dtype=float) * meters_per_unit
    if np.allclose(center, np.zeros(3)):
        center = bbox_center
    raw_extent = bounds[1] - bounds[0]
    up_index = 1 if up_axis == "Y" else 2
    depth_index = 2 if up_axis == "Y" else 1
    extent = np.array([raw_extent[0], raw_extent[up_index], raw_extent[depth_index]], dtype=float)
    return {
        "feature_id": str(prim.GetPath()),
        "kind": bucket[:-1],
        "center_m": [float(v) for v in center],
        "extent_m": [float(v) for v in extent],
        "rotation_y_degrees": float(_yaw_degrees(local_to_world)),
    }


def _extract_roomplan_prim(prim: Usd.Prim, bounds, xform_cache: UsdGeom.XformCache, meters_per_unit: float, up_axis: str):
    if bounds is None:
        return None
    local_to_world = xform_cache.GetLocalToWorldTransform(prim)
    center = (bounds[0] + bounds[1]) / 2
    extent = _local_extent(prim, meters_per_unit, up_axis)
    if extent is None:
        extent = bounds[1] - bounds[0]
        if up_axis == "Z":
            extent = np.array([extent[0], extent[2], extent[1]], dtype=float)
    return {
        "center_m": [float(v) for v in center],
        "extent_m": [float(v) for v in extent],
        "rotation_y_degrees": float(_yaw_degrees(local_to_world)),
    }


def _local_extent(prim: Usd.Prim, meters_per_unit: float, up_axis: str):
    if prim.IsA(UsdGeom.Mesh):
        points = UsdGeom.Mesh(prim).GetPointsAttr().Get()
        if points:
            arr = np.asarray([[p[0], p[1], p[2]] for p in points], dtype=float)
            raw = (arr.max(axis=0) - arr.min(axis=0)) * meters_per_unit
            if up_axis == "Y":
                return np.array([raw[0], raw[1], raw[2]], dtype=float)
            return np.array([raw[0], raw[2], raw[1]], dtype=float)

    if prim.IsA(UsdGeom.Boundable):
        extent_attr = UsdGeom.Boundable(prim).GetExtentAttr().Get()
        if extent_attr and len(extent_attr) >= 2:
            raw = (
                np.array([extent_attr[1][0], extent_attr[1][1], extent_attr[1][2]], dtype=float)
                - np.array([extent_attr[0][0], extent_attr[0][1], extent_attr[0][2]], dtype=float)
            ) * meters_per_unit
            if up_axis == "Y":
                return np.array([raw[0], raw[1], raw[2]], dtype=float)
            return np.array([raw[0], raw[2], raw[1]], dtype=float)

    return None


def _yaw_degrees(matrix: Gf.Matrix4d) -> float:
    x_axis = matrix.TransformDir(Gf.Vec3d(1, 0, 0))
    return math.degrees(math.atan2(float(x_axis[2]), float(x_axis[0])))


def _feature_bucket(prim: Usd.Prim) -> str | None:
    path_parts = [part.lower() for part in str(prim.GetPath()).split("/") if part]
    for part in path_parts:
        for label, bucket in _FEATURE_LABELS.items():
            if part == label or part.startswith(f"{label}_"):
                return bucket
    return None


def _is_labeled_primitive(prim: Usd.Prim) -> bool:
    path_parts = [part.lower() for part in str(prim.GetPath()).split("/") if part]
    if any(
        part == label or part.startswith(f"{label}_")
        for part in path_parts
        for label in _LABELED_PRIM_NAMES
    ):
        return True

    for prop in prim.GetProperties():
        name = prop.GetName().lower()
        if "classification" not in name:
            continue
        if not isinstance(prop, Usd.Attribute):
            continue
        value = prop.Get()
        if value:
            return True

    return False


def _roomplan_index(source_path: Path) -> dict:
    index = {"walls": {}, "doors": {}, "windows": {}, "furniture": {}}
    if not is_zipfile(source_path):
        return index

    with ZipFile(source_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".usda"):
                continue
            parts = name.split("/")
            if len(parts) < 4 or parts[0] != "assets" or parts[1] != "Mesh":
                continue
            category = parts[2]
            item_id = Path(parts[-1]).stem

            if category == "Walls" and len(parts) >= 5:
                wall_id = parts[3]
                if item_id == wall_id:
                    index["walls"][item_id] = {"id": item_id, "kind": "walls"}
                elif item_id.lower().startswith("door"):
                    index["doors"][item_id] = {"id": item_id, "kind": "doors", "wall_id": wall_id}
                elif item_id.lower().startswith("window"):
                    index["windows"][item_id] = {"id": item_id, "kind": "windows", "wall_id": wall_id}
            elif category not in {"Floors", "Walls"}:
                index["furniture"][item_id] = {
                    "id": item_id,
                    "kind": "furniture",
                    "category": category.lower(),
                }
    return index


def _roomplan_entry(prim_name: str, index: dict) -> dict | None:
    for bucket in ("walls", "doors", "windows", "furniture"):
        entry = index[bucket].get(prim_name)
        if entry:
            return entry
    return None


def _build_outline(walls: list[dict]) -> list[dict]:
    endpoints: list[tuple[float, float]] = []
    edges: list[tuple[int, int]] = []
    snapped: dict[tuple[int, int], int] = {}
    coords: list[list[float]] = []
    counts: list[int] = []
    tolerance = 0.15

    def node(point: tuple[float, float]) -> int:
        key = (round(point[0] / tolerance), round(point[1] / tolerance))
        if key not in snapped:
            snapped[key] = len(coords)
            coords.append([point[0], point[1]])
            counts.append(1)
        else:
            idx = snapped[key]
            coords[idx][0] += point[0]
            coords[idx][1] += point[1]
            counts[idx] += 1
        return snapped[key]

    for wall in walls:
        try:
            center = wall["center_m"]
            extent = wall["extent_m"]
            length = float(extent[0])
            angle = math.radians(float(wall.get("rotation_y_degrees", 0.0)))
            dx = math.cos(angle) * length / 2
            dz = math.sin(angle) * length / 2
            a = (float(center[0]) - dx, float(center[2]) - dz)
            b = (float(center[0]) + dx, float(center[2]) + dz)
        except (KeyError, TypeError, ValueError):
            continue
        endpoints.extend([a, b])
        edges.append((node(a), node(b)))

    if not edges:
        return []

    points = [(coords[i][0] / counts[i], coords[i][1] / counts[i]) for i in range(len(coords))]
    graph: dict[int, list[int]] = defaultdict(list)
    for a, b in edges:
        if a != b:
            graph[a].append(b)
            graph[b].append(a)

    candidates: list[list[tuple[float, float]]] = []
    seen: set[int] = set()
    for start in graph:
        if start in seen:
            continue
        component = []
        stack = [start]
        seen.add(start)
        while stack:
            cur = stack.pop()
            component.append(cur)
            for nxt in graph[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)

        if len(component) < 3:
            continue
        if all(len(graph[n]) == 2 for n in component):
            loop = _walk_loop(component[0], graph)
            if loop:
                candidates.append([points[n] for n in loop])
        else:
            candidates.append(_convex_hull([points[n] for n in component]))

    fallback = _convex_hull(endpoints)
    if fallback:
        candidates.append(fallback)
    if not candidates:
        return []

    polygon = max(candidates, key=lambda pts: abs(_polygon_area(pts)))
    if _polygon_area(polygon) < 0:
        polygon = list(reversed(polygon))
    return [{"x": float(x), "z": float(z)} for x, z in polygon]


def _walk_loop(start: int, graph: dict[int, list[int]]) -> list[int] | None:
    loop = [start]
    previous = None
    current = start
    for _ in range(len(graph) + 1):
        choices = [n for n in graph[current] if n != previous]
        if not choices:
            return None
        nxt = choices[0]
        if nxt == start:
            return loop if len(loop) >= 3 else None
        if nxt in loop:
            return None
        loop.append(nxt)
        previous, current = current, nxt
    return None


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def _polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return 0.5 * sum(
        points[i][0] * points[(i + 1) % len(points)][1]
        - points[(i + 1) % len(points)][0] * points[i][1]
        for i in range(len(points))
    )
