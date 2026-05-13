from pathlib import Path
import math

import numpy as np
from pxr import Gf, Usd, UsdGeom


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
    parametric = any(features[bucket] for bucket in features)

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
