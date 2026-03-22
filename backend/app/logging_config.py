"""
Structured logging configuration using loguru.
Supports JSON format for production and text format for development.
Intercepts stdlib logging so uvicorn/sqlalchemy logs go through loguru.
"""
import logging
import sys

from loguru import logger

from .config import settings


class _InterceptHandler(logging.Handler):
    """Route stdlib logging through loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where the logged message originated
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging():
    """Configure application logging based on settings."""
    # Remove default loguru handler
    logger.remove()

    if settings.log_format == "json":
        logger.add(
            sys.stdout,
            level=settings.log_level.upper(),
            serialize=True,
        )
    else:
        logger.add(
            sys.stdout,
            level=settings.log_level.upper(),
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> | <level>{message}</level>",
        )

    # Intercept stdlib logging (uvicorn, sqlalchemy, etc.)
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if settings.db_echo else logging.WARNING
    )
