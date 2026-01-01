from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.db.session import init_db, close_db
from app.api.routes import health, sources, feed, auth, signals, briefings, feedback

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    setup_logging(debug=settings.DEBUG)
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        # Continue anyway - DB might need manual setup

    yield

    # Shutdown
    await close_db()
    logger.info("Application shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(sources.router, prefix="/api/v1", tags=["Sources"])
app.include_router(feed.router, prefix="/api/v1", tags=["Feed"])
app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
app.include_router(signals.router, prefix="/api/v1", tags=["Signals"])
app.include_router(briefings.router, prefix="/api/v1", tags=["Briefings"])
app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
