"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI

from app.api import router
from app.config import settings


def create_app() -> FastAPI:
    logging.basicConfig(level=settings.log_level)
    app = FastAPI(title="Incident Investigator", version="0.1.0")
    app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "env": settings.app_env}

    return app


app = create_app()
