from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict:
    return {"status": "ok", "service": "house-advantage-api"}


@router.get("/api/v1/health")
def versioned_healthcheck() -> dict:
    return {"status": "ok", "version": "v1"}
