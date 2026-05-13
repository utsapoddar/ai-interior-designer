from pathlib import Path
from pxr import Gf, Usd, UsdGeom, UsdUtils

# Builds the tiny parametric RoomPlan-style USDZ fixture used by parser tests.
ROOT = Path(__file__).resolve().parent
usd_path = ROOT / "parametric_bedroom.usdc"
usdz_path = ROOT / "parametric_bedroom.usdz"

stage = Usd.Stage.CreateNew(str(usd_path))
UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
UsdGeom.SetStageMetersPerUnit(stage, 1.0)


def cube(name, translate, scale, yaw=0):
    prim = UsdGeom.Cube.Define(stage, f"/{name}")
    x = UsdGeom.Xformable(prim)
    x.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if yaw:
        x.AddRotateYOp().Set(yaw)
    x.AddScaleOp().Set(Gf.Vec3d(*scale))
    return prim

# Room is 4m x 3m, centered on the USD origin, with walls/door/window named by kind.
cube("Walls_South", (0, 1.25, -1.5), (4.0, 2.5, 0.05))
cube("Walls_North", (0, 1.25, 1.5), (4.0, 2.5, 0.05))
cube("Walls_West", (-2.0, 1.25, 0), (0.05, 2.5, 3.0))
cube("Walls_East", (2.0, 1.25, 0), (0.05, 2.5, 3.0))
cube("Doors_South", (-1.2, 1.0, -1.5), (0.8, 2.0, 0.08))
cube("Windows_North", (1.0, 1.4, 1.5), (1.0, 0.8, 0.08))

stage.GetRootLayer().Save()
assert UsdUtils.CreateNewUsdzPackage(str(usd_path), str(usdz_path))
