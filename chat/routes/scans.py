import json
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ingest.parser import parse_usdz


INGEST_DIR = Path("ingest")
USDZ_DIR = INGEST_DIR / "usdz"
PARSED_MESH_DIR = INGEST_DIR / "parsed-mesh"


class ScanUploadResponse(BaseModel):
    scan_id: str
    dimensions_m: dict[str, float]
    has_labeled_primitives: bool


router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=ScanUploadResponse)
async def create_scan(file: UploadFile = File(...)) -> ScanUploadResponse:
    scan_id = uuid.uuid4().hex[:12]
    usdz_path = USDZ_DIR / f"{scan_id}.usdz"
    parsed_path = PARSED_MESH_DIR / f"{scan_id}.json"

    USDZ_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_MESH_DIR.mkdir(parents=True, exist_ok=True)

    usdz_path.write_bytes(await file.read())

    try:
        parsed = parse_usdz(usdz_path)
    except Exception as exc:
        usdz_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parsed_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    return ScanUploadResponse(
        scan_id=scan_id,
        dimensions_m=parsed["dimensions_m"],
        has_labeled_primitives=parsed["has_labeled_primitives"],
    )


@router.get("/{scan_id}/mesh")
def get_scan_mesh(scan_id: str) -> JSONResponse:
    parsed_path = PARSED_MESH_DIR / f"{scan_id}.json"
    if not parsed_path.exists():
        raise HTTPException(status_code=404, detail="Parsed mesh not found")

    return JSONResponse(json.loads(parsed_path.read_text(encoding="utf-8")))


@router.get("/{scan_id}/usdz")
def get_scan_usdz(scan_id: str) -> FileResponse:
    usdz_path = USDZ_DIR / f"{scan_id}.usdz"
    if not usdz_path.exists():
        raise HTTPException(status_code=404, detail="USDZ scan not found")

    return FileResponse(usdz_path, media_type="model/vnd.usdz+zip")
