from pydantic import BaseModel
from fastapi import APIRouter


class HealthResponse(BaseModel):
    ok: bool


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True)
