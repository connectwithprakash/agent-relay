"""
API route modules - each file handles a specific resource domain
"""
from fastapi import APIRouter

from .health import router as health_router
from .relays import router as relays_router
from .messages import router as messages_router
from .webhooks import router as webhooks_router
from .websocket import router as websocket_router
from .spectators import router as spectators_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(relays_router)
api_router.include_router(messages_router)
api_router.include_router(webhooks_router)
api_router.include_router(websocket_router)
api_router.include_router(spectators_router)

__all__ = ["api_router"]
