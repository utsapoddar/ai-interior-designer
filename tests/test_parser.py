from pathlib import Path

import pytest
from pxr import Usd, UsdGeom, UsdUtils, Vt

from ingest.parser import parse_usdz


def _write_box_usdz(path: Path) -> None:
    work_dir = path.parent / "usd_src"
    work_dir.mkdir()
    usdc_path = work_dir / "box.usdc"

    stage = Usd.Stage.CreateNew(str(usdc_path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    mesh = UsdGeom.Mesh.Define(stage, "/RoomMesh")
    points = [
        (-2.0, 0.0, -1.5),
        (2.0, 0.0, -1.5),
        (2.0, 0.0, 1.5),
        (-2.0, 0.0, 1.5),
        (-2.0, 2.5, -1.5),
        (2.0, 2.5, -1.5),
        (2.0, 2.5, 1.5),
        (-2.0, 2.5, 1.5),
    ]
    face_vertex_indices = [
        0, 1, 2, 3,  # floor
        4, 7, 6, 5,  # ceiling
        0, 4, 5, 1,
        1, 5, 6, 2,
        2, 6, 7, 3,
        3, 7, 4, 0,
    ]
    mesh.CreatePointsAttr(Vt.Vec3fArray(points))
    mesh.CreateFaceVertexCountsAttr([4, 4, 4, 4, 4, 4])
    mesh.CreateFaceVertexIndicesAttr(face_vertex_indices)
    stage.GetRootLayer().Save()

    assert UsdUtils.CreateNewUsdzPackage(str(usdc_path), str(path))


def test_parse_usdz_extracts_bbox_dimensions_from_raw_mesh(tmp_path: Path) -> None:
    usdz_path = tmp_path / "box.usdz"
    _write_box_usdz(usdz_path)

    parsed = parse_usdz(usdz_path)

    assert parsed["schema_version"] == "v1"
    assert parsed["units"] == "meters"
    assert parsed["up_axis"] == "Y"
    assert parsed["bounding_box_m"] == {
        "min": pytest.approx([-2.0, 0.0, -1.5]),
        "max": pytest.approx([2.0, 2.5, 1.5]),
    }
    assert parsed["dimensions_m"] == {
        "width": pytest.approx(4.0),
        "depth": pytest.approx(3.0),
        "height": pytest.approx(2.5),
    }
    assert parsed["floor_z_or_y_m"] == pytest.approx(0.0)
    assert parsed["ceiling_z_or_y_m"] == pytest.approx(2.5)
    assert parsed["triangle_count"] == 12
    assert parsed["has_labeled_primitives"] is False
    assert parsed["outline_m"] == []
    assert parsed["existing_furniture"] == []
    assert parsed["source_file_bytes"] == usdz_path.stat().st_size


def test_parses_parametric_features() -> None:
    parsed = parse_usdz(Path("tests/fixtures/parametric_bedroom.usdz"))

    assert parsed["parametric"] is True
    assert parsed["has_labeled_primitives"] is True
    assert len(parsed["features"]["walls"]) == 4
    assert len(parsed["features"]["doors"]) == 1
    assert len(parsed["features"]["windows"]) == 1
    assert parsed["outline_m"] == []
    assert parsed["existing_furniture"] == []

    for feature in parsed["features"]["walls"] + parsed["features"]["doors"] + parsed["features"]["windows"]:
        assert set(feature) == {"feature_id", "kind", "center_m", "extent_m", "rotation_y_degrees"}
        assert feature["feature_id"].startswith("/")
        assert len(feature["center_m"]) == 3
        assert len(feature["extent_m"]) == 3
        assert isinstance(feature["rotation_y_degrees"], float)


def test_mesh_only_has_empty_features() -> None:
    sample = Path("tests/fixtures/sample_bedroom.usdz")
    if not sample.exists() or sample.stat().st_size == 0:
        pytest.skip("sample mesh USDZ is not accessible in this sandbox")

    parsed = parse_usdz(sample)

    assert parsed["parametric"] is False
    assert parsed["has_labeled_primitives"] is False
    assert parsed["features"]["doors"] == []
    assert parsed["outline_m"] == []
    assert parsed["existing_furniture"] == []
