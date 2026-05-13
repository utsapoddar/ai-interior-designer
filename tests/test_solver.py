from solver.layout import place_furniture


def _footprint(item: dict) -> tuple[float, float, float, float]:
    width = item["dimensions"]["width"]
    depth = item["dimensions"]["depth"]
    if item["rotation_degrees"] in {90, 270}:
        width, depth = depth, width
    x = item["position"]["x"]
    z = item["position"]["z"]
    return (x - width / 2, x + width / 2, z - depth / 2, z + depth / 2)


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[1] and a[1] > b[0] and a[2] < b[3] and a[3] > b[2]


def test_places_bed_nightstands_and_dresser_without_overlap() -> None:
    parsed_mesh = {
        "up_axis": "Y",
        "dimensions_m": {"width": 4.0, "depth": 3.0, "height": 2.5},
        "bounding_box_m": {"min": [0, 0, 0], "max": [4, 2.5, 3]},
    }
    shortlist = [
        {"id": "bed", "category": "bed", "dimensions_m": {"width": 1.6, "depth": 2.0, "height": 0.8}},
        {"id": "nightstand-left", "category": "storage", "dimensions_m": {"width": 0.4, "depth": 0.4, "height": 0.5}, "placement_hints": ["beside-bed"]},
        {"id": "nightstand-right", "category": "storage", "dimensions_m": {"width": 0.4, "depth": 0.4, "height": 0.5}, "placement_hints": ["beside-bed"]},
        {"id": "dresser", "category": "storage", "dimensions_m": {"width": 1.2, "depth": 0.45, "height": 0.8}, "name": "Dresser"},
    ]

    placements = place_furniture(parsed_mesh, shortlist)

    assert len(placements) == 4
    footprints = [_footprint(item) for item in placements]
    for index, footprint in enumerate(footprints):
        for other in footprints[index + 1:]:
            assert not _overlaps(footprint, other)

    bed = next(item for item in placements if item["catalog_id"] == "bed")
    assert bed["position"]["z"] == 1.0
    assert bed["rationale"].startswith("Placed bed on longest wall")

    dresser = next(item for item in placements if item["catalog_id"] == "dresser")
    assert dresser["position"]["z"] == 3.0 - 0.45 / 2
    assert "opposite wall" in dresser["rationale"]


def test_places_furniture_for_z_up_mesh() -> None:
    parsed_mesh = {
        "up_axis": "Z",
        "dimensions_m": {"width": 4.0, "depth": 3.0, "height": 2.5},
        "bounding_box_m": {"min": [0, 0, 0], "max": [4, 3, 2.5]},
    }
    shortlist = [
        {"id": "bed", "category": "bed", "dimensions_m": {"width": 1.6, "depth": 2.0, "height": 0.8}},
    ]
    placements = place_furniture(parsed_mesh, shortlist)
    assert len(placements) == 1
    assert placements[0]["catalog_id"] == "bed"


def test_solver_avoids_door_swing() -> None:
    parsed_mesh = {
        "up_axis": "Y",
        "dimensions_m": {"width": 4.0, "depth": 3.0, "height": 2.5},
        "bounding_box_m": {"min": [0, 0, 0], "max": [4, 2.5, 3]},
        "parametric": True,
        "features": {
            "walls": [],
            "doors": [{"feature_id": "/Doors_South", "center_m": [2.0, 1.0, 0.0], "extent_m": [0.8, 2.0, 0.1], "rotation_y_degrees": 0.0}],
            "windows": [],
        },
    }
    shortlist = [
        {"id": "bed", "category": "bed", "dimensions_m": {"width": 1.6, "depth": 2.0, "height": 0.8}},
        {"id": "nightstand", "category": "storage", "dimensions_m": {"width": 0.4, "depth": 0.4, "height": 0.5}},
    ]

    placements = place_furniture(parsed_mesh, shortlist)

    bed = next(item for item in placements if item["catalog_id"] == "bed")
    door_swing = (1.6, 2.4, 0.0, 0.95)
    assert not _overlaps(_footprint(bed), door_swing)


def test_solver_falls_back_when_no_features() -> None:
    parsed_mesh = {
        "up_axis": "Y",
        "parametric": False,
        "dimensions_m": {"width": 4.0, "depth": 3.0, "height": 2.5},
        "bounding_box_m": {"min": [0, 0, 0], "max": [4, 2.5, 3]},
    }
    shortlist = [
        {"id": "bed", "category": "bed", "dimensions_m": {"width": 1.6, "depth": 2.0, "height": 0.8}},
    ]

    placements = place_furniture(parsed_mesh, shortlist)

    assert len(placements) == 1
    assert placements[0]["catalog_id"] == "bed"


def test_place_furniture_used_when_llm_proposes_nothing(monkeypatch) -> None:
    from chat.routes import plans

    parsed_mesh = {
        "up_axis": "Y",
        "dimensions_m": {"width": 4.0, "depth": 3.0, "height": 2.5},
        "bounding_box_m": {"min": [0, 0, 0], "max": [4, 2.5, 3]},
    }
    catalog = [{"id": "bed", "catalog_id": "bed", "category": "bed", "dimensions_m": {"width": 1.6, "depth": 2.0, "height": 0.8}}]

    assert plans.place_furniture(parsed_mesh, catalog)[0]["catalog_id"] == "bed"
