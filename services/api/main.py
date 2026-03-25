"""
API Server — FastAPI application entry point.
All routes imported and registered here.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.config import get_settings
from shared.utils import setup_logging

settings = get_settings()
logger = setup_logging("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API server starting up")
    # Run alembic migrations on startup (Railway-friendly)
    import subprocess
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        logger.info("Database migrations applied successfully")
    else:
        logger.warning(f"Migration output: {result.stderr}")
    yield
    logger.info("API server shutting down")


app = FastAPI(
    title="Multi-Agent Intelligence System",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check (no auth) ────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": "api"}


# ── Register all route modules ────────────────────────────────────────
from services.api.routes.predictions import router as predictions_router
from services.api.routes.agents import router as agents_router
from services.api.routes.dashboard import router as dashboard_router
from services.api.routes.debates import router as debates_router
from services.api.routes.signals import router as signals_router
from services.api.routes.claims import router as claims_router
from services.api.routes.decisions import router as decisions_router
from services.api.routes.events import router as events_router
from services.api.routes.chat import router as chat_router
from services.api.routes.trigger import router as trigger_router
from services.api.routes.newsletter import router as newsletter_router

app.include_router(predictions_router)
app.include_router(agents_router)
app.include_router(dashboard_router)
app.include_router(debates_router)
app.include_router(signals_router)
app.include_router(claims_router)
app.include_router(decisions_router)
app.include_router(events_router)
app.include_router(chat_router)
app.include_router(trigger_router)
app.include_router(newsletter_router)
