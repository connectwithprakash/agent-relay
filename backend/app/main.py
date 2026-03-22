"""
Agent Relay - FastAPI Application
Clean architecture with services and repositories
"""
from contextlib import asynccontextmanager

from loguru import logger

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .logging_config import setup_logging
from .middleware import RequestLoggingMiddleware
from .database import init_db
from .rate_limit import limiter
from .routes import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    setup_logging()
    if settings.environment == "development":
        init_db()
        logger.info("Database tables created (development mode)")
    logger.info("Agent Relay %s started (%s)", settings.app_version, settings.environment)
    yield
    logger.info("Agent Relay shutting down")


# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Turn-based agent-to-agent communication with WebSocket and webhooks",
    version=settings.app_version,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware - disable credentials when using wildcard origins
allow_credentials = "*" not in settings.cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Include all route modules
app.include_router(api_router)

# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
