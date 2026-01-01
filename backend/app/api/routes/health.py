from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from redis import asyncio as aioredis

from app.api.deps import get_db, get_redis
from app.core.config import settings
from app.core.metrics import metrics

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
    }


@router.get("/health/ready")
async def readiness_check(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Readiness check - verifies all dependencies are available."""
    checks = {
        "database": False,
        "redis": False,
    }

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        checks["database_error"] = str(e)

    # Check Redis
    try:
        await redis.ping()
        checks["redis"] = True
    except Exception as e:
        checks["redis_error"] = str(e)

    all_healthy = all(v for k, v in checks.items() if isinstance(v, bool))

    return {
        "status": "ready" if all_healthy else "degraded",
        "checks": checks,
    }


@router.get("/health/metrics")
async def get_metrics():
    """Get current application metrics."""
    return await metrics.get_all()
