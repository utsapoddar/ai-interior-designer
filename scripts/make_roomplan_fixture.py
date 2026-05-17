from pathlib import Path
import shutil

from pxr import Gf, Usd, UsdGeom, UsdUtils, Vt

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures"
BUILD_DIR = FIXTURE_DIR / "_roomplan_src"
USDZ_PATH = FIXTURE_DIR / "parametric_roomplan.usdz"

FACE_COUNTS = [4, 4, 4, 4, 4, 4]
FACE_INDICES = [
    0, 1, 2, 3,
    4, 7, 6, 5,
    0, 4, 5, 1,
    1, 5, 6, 2,
    2, 6, 7, 3,
    3, 7, 4, 0,
]


def _box_points(width: float, height: float, depth: float) -> list[tuple[float, float, float]]:
    x = width / 2
    y = height / 2
    z = depth / 2
    return [
        (-x, -y, -z), (x, -y, -z), (x, -y, z), (-x, -y, z),
        (-x, y, -z), (x, y, -z), (x, y, z), (-x, y, z),
    ]


def _write_asset(path: Path, name: str, center: tuple[float, float, float], extent: tuple[float, float, float], yaw: float = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    root = UsdGeom.Xform.Define(stage, f"/{name}")
    stage.SetDefaultPrim(root.GetPrim())
    mesh = UsdGeom.Mesh.Define(stage, f"/{name}/{name}")
    mesh.CreatePointsAttr(Vt.Vec3fArray(_box_points(*extent)))
    mesh.CreateFaceVertexCountsAttr(FACE_COUNTS)
    mesh.CreateFaceVertexIndicesAttr(FACE_INDICES)
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)

    xform = UsdGeom.Xformable(mesh)
    xform.AddTranslateOp().Set(Gf.Vec3d(*center))
    if yaw:
        xform.AddRotateYOp().Set(float(yaw))
    stage.GetRootLayer().Save()


def main() -> None:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    _write_asset(BUILD_DIR / "assets/Mesh/Walls/Wall0/Wall0.usda", "Wall0", (0, 1.25, -1.5), (4.0, 2.5, 0.1), 0)
    _write_asset(BUILD_DIR / "assets/Mesh/Walls/Wall1/Wall1.usda", "Wall1", (2.0, 1.25, 0), (3.0, 2.5, 0.1), 90)
    _write_asset(BUILD_DIR / "assets/Mesh/Walls/Wall2/Wall2.usda", "Wall2", (0, 1.25, 1.5), (4.0, 2.5, 0.1), 180)
    _write_asset(BUILD_DIR / "assets/Mesh/Walls/Wall3/Wall3.usda", "Wall3", (-2.0, 1.25, 0), (3.0, 2.5, 0.1), 90)
    _write_asset(BUILD_DIR / "assets/Mesh/Walls/Wall1/Door1.usda", "Door1", (2.0, 1.0, -0.75), (0.8, 2.0, 0.08), 90)
    _write_asset(BUILD_DIR / "assets/Mesh/Walls/Wall2/Window0.usda", "Window0", (0.8, 1.4, 1.5), (1.0, 0.8, 0.08), 180)
    _write_asset(BUILD_DIR / "assets/Mesh/Bed/Bed0.usda", "Bed0", (-1.0, 0.3, 0.75), (1.0, 0.6, 1.4), 0)
    _write_asset(BUILD_DIR / "assets/Mesh/Floors/Floor0.usda", "Floor0", (0, -0.025, 0), (4.0, 0.05, 3.0), 0)

    root_path = BUILD_DIR / "Project-2605140000.usda"
    root_path.write_text(
        '''#usda 1.0
(
    defaultPrim = "Project2605140000"
    metersPerUnit = 1
    upAxis = "Y"
)

def Xform "Project2605140000"
{
    def Xform "Mesh_grp"
    {
        def Xform "Arch_grp"
        {
            def Xform "Wall_0_grp" (prepend references = @./assets/Mesh/Walls/Wall0/Wall0.usda@) {}
            def Xform "Wall_1_grp" (prepend references = [@./assets/Mesh/Walls/Wall1/Wall1.usda@, @./assets/Mesh/Walls/Wall1/Door1.usda@]) {}
            def Xform "Wall_2_grp" (prepend references = [@./assets/Mesh/Walls/Wall2/Wall2.usda@, @./assets/Mesh/Walls/Wall2/Window0.usda@]) {}
            def Xform "Wall_3_grp" (prepend references = @./assets/Mesh/Walls/Wall3/Wall3.usda@) {}
        }
        def Xform "Floor_grp" (prepend references = @./assets/Mesh/Floors/Floor0.usda@) {}
        def Xform "Object_grp"
        {
            def Xform "Bed_grp" (prepend references = @./assets/Mesh/Bed/Bed0.usda@) {}
        }
    }
}
''',
        encoding="utf-8",
    )

    if USDZ_PATH.exists():
        USDZ_PATH.unlink()
    assert UsdUtils.CreateNewUsdzPackage(str(root_path), str(USDZ_PATH))
    shutil.rmtree(BUILD_DIR)


if __name__ == "__main__":
    main()
