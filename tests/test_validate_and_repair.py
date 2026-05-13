from solver.layout import validate_and_repair


def mesh(features=None, width=4.0, depth=3.0):
    return {
        "up_axis": "Y",
        "dimensions_m": {"width": width, "depth": depth, "height": 2.5},
        "bounding_box_m": {"min": [0, 0, 0], "max": [width, 2.5, depth]},
        "features": features or {"walls": [], "doors": [], "windows": []},
    }


def item(id_, category="decor", wall="any", w=0.5, d=0.5):
    return {
        "id": id_,
        "name": id_.replace("-", " ").title(),
        "category": category,
        "dimensions_m": {"width": w, "depth": d, "height": 0.5},
        "wall_preference": wall,
        "rationale": "test",
    }


def test_empty_proposed_list_returns_empty():
    assert validate_and_repair(mesh(), []) == ([], [])


def test_wall_preference_item_is_anchored_to_wall():
    placed, log = validate_and_repair(mesh(), [item("chair", wall="south", w=0.8, d=0.8)])
    assert len(placed) == 1
    assert placed[0]["position"] == {"x": 2.0, "y": 0.0, "z": 0.4}
    assert placed[0]["rotation_degrees"] == 0
    assert log == [{"id": "chair", "action": "kept", "reason": "kept proposed placement"}]


def test_item_overlapping_window_zone_is_shifted_and_kept():
    features = {"walls": [], "doors": [], "windows": [{"feature_id": "/Windows_South", "center_m": [2.0, 1.0, 0.0], "extent_m": [0.8, 1.0, 0.1]}]}
    placed, log = validate_and_repair(mesh(features), [item("bench", wall="south", w=0.7, d=0.4)])
    assert len(placed) == 1
    assert log[0]["action"] == "shifted_zone"
    assert placed[0]["position"]["z"] > 0.2


def test_item_overlapping_door_zone_drops_if_unresolvable():
    features = {"walls": [], "doors": [{"feature_id": "/Doors_South", "center_m": [2.0, 1.0, 0.0], "extent_m": [3.8, 2.0, 0.1]}], "windows": []}
    placed, log = validate_and_repair(mesh(features), [item("wide-sofa", wall="south", w=3.8, d=1.0)])
    assert placed == []
    assert log[0]["action"] == "dropped"


def test_collision_is_shifted_or_dropped():
    placed, log = validate_and_repair(mesh(width=2.5, depth=2.5), [item("bed", "bed", wall="center", w=1.4, d=1.4), item("table", "surface", wall="center", w=0.5, d=0.5)])
    assert len(placed) >= 1
    assert log[0]["action"] == "kept"
    assert log[1]["action"] in {"shifted_collision", "dropped"}


def test_integration_places_at_least_four_items_with_typed_logs():
    features = {"walls": [], "doors": [{"feature_id": "/Doors_South", "center_m": [0.8, 1.0, 0.0], "extent_m": [0.8, 2.0, 0.1]}], "windows": []}
    proposed = [
        item("bed", "bed", wall="north", w=1.4, d=1.8),
        item("dresser", "storage", wall="east", w=1.0, d=0.4),
        item("chair", "seating", wall="west", w=0.6, d=0.6),
        item("desk", "surface", wall="north", w=0.8, d=0.5),
        item("lamp", "lighting", wall="any", w=0.3, d=0.3),
        item("rug", "textile", wall="center", w=1.0, d=0.8),
    ]
    placed, log = validate_and_repair(mesh(features), proposed)
    assert len(placed) >= 4
    assert {entry["action"] for entry in log} <= {"kept", "snapped", "shifted_zone", "shifted_collision", "dropped"}
