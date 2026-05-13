from solver.layout import _anchor_to_wall


def mesh(width=4.0, depth=3.0):
    return {
        "up_axis": "Y",
        "dimensions_m": {"width": width, "depth": depth, "height": 2.5},
        "bounding_box_m": {"min": [0, 0, 0], "max": [width, 2.5, depth]},
        "features": {"walls": [], "doors": [], "windows": []},
    }


def item(wall):
    return {
        "id": f"{wall}-item",
        "category": "decor",
        "dimensions_m": {"width": 1.0, "depth": 0.4, "height": 0.5},
        "wall_preference": wall,
    }


def occupied():
    return {"offsets": {"south": 0.0, "west": 0.0, "north": 0.0, "east": 0.0}, "footprints": []}


def test_anchor_south():
    x, z, rotation = _anchor_to_wall(mesh(), item("south"), occupied())
    assert (x, z, rotation) == (2.0, 0.2, 0)


def test_anchor_north():
    x, z, rotation = _anchor_to_wall(mesh(), item("north"), occupied())
    assert (x, z, rotation) == (2.0, 2.8, 180)


def test_anchor_west():
    x, z, rotation = _anchor_to_wall(mesh(), item("west"), occupied())
    assert (x, z, rotation) == (0.2, 1.5, 90)


def test_anchor_east():
    x, z, rotation = _anchor_to_wall(mesh(), item("east"), occupied())
    assert (x, z, rotation) == (3.8, 1.5, 270)


def test_anchor_center():
    x, z, rotation = _anchor_to_wall(mesh(), item("center"), occupied())
    assert (x, z, rotation) == (2.0, 1.5, 0)
