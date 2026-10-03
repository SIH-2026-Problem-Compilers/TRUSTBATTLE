from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import settings
from backend.app.db import init_db
from backend.app.api import v1_router
from backend.app.api.ws import ws_router


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="TRUSTBATTLE — AI-Driven Battlefield Information Integrity & Trust Assessment Engine",
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    try:
        init_db()
    except Exception:
        pass

    app.include_router(v1_router)
    app.include_router(ws_router)

    @app.get("/health", tags=["meta"])
    def root_health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()
