"""
Agent Relay - FastAPI Application
Clean architecture with services and repositories
"""
from contextlib import asynccontextmanager

from loguru import logger

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .logging_config import setup_logging
from .middleware import RequestLoggingMiddleware
from .database import init_db
from .rate_limit import limiter
from .routes import api_router
from .services.webhook_service import (
    close_webhook_dispatcher,
    start_webhook_dispatcher,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown"""
    setup_logging()
    if settings.environment == "development":
        init_db()
        logger.info("Database tables created (development mode)")
    await start_webhook_dispatcher()
    logger.info("Agent Relay {} started ({})", settings.app_version, settings.environment)
    try:
        yield
    finally:
        await close_webhook_dispatcher()
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


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Default 422 body, minus echoed input when it cannot be encoded as UTF-8.

    Lone surrogates in a rejected body would otherwise crash the response
    serializer and turn a validation error into a 500.
    """
    errors = jsonable_encoder(exc.errors())
    try:
        return JSONResponse(status_code=422, content={"detail": errors})
    except UnicodeEncodeError:
        errors = [{key: value for key, value in error.items() if key not in {"input", "ctx"}} for error in errors]
        return JSONResponse(status_code=422, content={"detail": errors})

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
