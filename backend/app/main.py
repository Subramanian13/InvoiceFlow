from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.extraction import get_extraction_provider


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.state.session_factory = SessionLocal
app.state.provider_factory = get_extraction_provider
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(router)

