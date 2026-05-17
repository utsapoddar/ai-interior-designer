from pathlib import Path

import pytest

from ingest.parser import parse_usdz


def test_parses_roomplan_usdz_structure() -> None:
    parsed = parse_usdz(Path("tests/fixtures/parametric_roomplan.usdz"))

    assert len(parsed["features"]["walls"]) == 4
    assert len(parsed["features"]["doors"]) == 1
    assert len(parsed["features"]["windows"]) == 1

    wall_ids = {wall["id"] for wall in parsed["features"]["walls"]}
    door = parsed["features"]["doors"][0]
    window = parsed["features"]["windows"][0]
    assert door["wall_id"] in wall_ids
    assert window["wall_id"] in wall_ids

    outline = parsed["outline_m"]
    assert len(outline) == 4
    xs = sorted(round(point["x"], 1) for point in outline)
    zs = sorted(round(point["z"], 1) for point in outline)
    assert xs == pytest.approx([-2.0, -2.0, 2.0, 2.0])
    assert zs == pytest.approx([-1.5, -1.5, 1.5, 1.5])

    assert len(parsed["existing_furniture"]) == 1
    furniture = parsed["existing_furniture"][0]
    assert furniture["category"] == "bed"
    assert furniture["id"] == "Bed0"
