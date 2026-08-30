"""FastAPI entrypoint for the Agentic Conversion & Merchant Growth Engine.

Step 1 scope: app factory + lifespan wiring Postgres/Redis + /health.
Routers (webhook, chat, dashboard) are attached in step 7.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.agents.sweep import start_sweep_task
from app.db.postgres import close_db, init_db
from app.db.redis_client import close_redis, init_redis
from app.db.schema import ensure_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("growth_engine")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db(settings.database_url)
    await ensure_schema()
    await init_redis(settings.redis_url)
    sweep_task = start_sweep_task()
    logger.info("Startup complete -- %s", settings.app_name)
    yield
    sweep_task.cancel()
    await close_redis()
    await close_db()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Agentic Conversion & Merchant Growth Engine",
        description=(
            "Multi-agent cart-recovery orchestration: LangGraph + Gemini + "
            "policy-aware RAG, with Razorpay sandbox webhooks."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    # API routers (step 7)
    from app.api import chat, dashboard, webhooks

    app.include_router(webhooks.router)
    app.include_router(chat.router)
    app.include_router(dashboard.router)
    return app


app = create_app()
