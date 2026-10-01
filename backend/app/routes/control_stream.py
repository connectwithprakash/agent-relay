"""Authenticated live stream for one managed harness session."""
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database import SessionLocal
from ..models import AgentToken, ControlEvent, ControlLease, HarnessSession, Worker
from ..schemas import utf8_size, validate_approval_data
from ..security import digest
from ..control_stream_manager import manager
from .control import _as_utc, _event, _event_response, _expire_stale_workers, _now

router = APIRouter()

MAX_FRAME_TEXT_BYTES = 65536
RESIZE_COLS = (20, 500)
RESIZE_ROWS = (5, 200)


def _is_bounded_int(value, bounds) -> bool:
    return type(value) is int and bounds[0] <= value <= bounds[1]


def _token_from_protocol(websocket: WebSocket) -> Optional[str]:
    for protocol in (websocket.headers.get("sec-websocket-protocol") or "").split(","):
        protocol = protocol.strip()
        if protocol.startswith("token-"):
            return protocol[len("token-"):]
    return None


@router.websocket("/relays/{relay_id}/sessions/{session_id}/stream")
async def control_stream(websocket: WebSocket, relay_id: str, session_id: str, cursor: int = 0):
    db = SessionLocal()
    key = (relay_id, session_id)
    try:
        _expire_stale_workers(db, relay_id)
        db.commit()
        token = _token_from_protocol(websocket)
        agent_token = db.query(AgentToken).filter(AgentToken.token_hash == digest(token or "")).first()
        session = db.query(HarnessSession).filter(
            HarnessSession.id == session_id, HarnessSession.relay_id == relay_id
        ).first()
        if not token or not agent_token or agent_token.relay_id != relay_id or not session:
            await websocket.close(code=4001, reason="Authentication or session failed")
            return
        worker = db.get(Worker, session.worker_id)
        if not worker or worker.revoked_at is not None or worker.status == "revoked":
            await websocket.close(code=4003, reason="Worker is unavailable")
            return
        if agent_token.agent_name == worker.agent_name:
            role = "worker"
        elif agent_token.is_creator:
            role = "controller"
        else:
            await websocket.close(code=4003, reason="Not authorized for this session")
            return

        await manager.connect(key, role, websocket, subprotocol=f"token-{token}")
        lease = db.get(ControlLease, session.id)
        await websocket.send_json({
            "type": "connected", "session_id": session.id, "actor": role,
            "status": session.status, "version": session.version,
            "cursor": cursor,
            "lease": {"held": bool(lease and lease.controller_agent == agent_token.agent_name and lease.expires_at and _as_utc(lease.expires_at) > _now())},
        })
        events = db.query(ControlEvent).filter(
            ControlEvent.session_id == session.id, ControlEvent.sequence > cursor
        ).order_by(ControlEvent.sequence).all()
        db.commit()
        for event in events:
            await websocket.send_json({"type": "event", "event": _event_response(event)})

        while True:
            frame = await websocket.receive_json()
            try:
                if not isinstance(frame, dict) or not isinstance(frame.get("type"), str):
                    await websocket.send_json({"type": "error", "code": "invalid_frame", "message": "Frame must be a JSON object with a string type"})
                    continue
                frame_type = frame["type"]
                if role == "controller" and frame_type in {"input", "resize"}:
                    _expire_stale_workers(db, relay_id)
                    # The stream holds one DB session for its lifetime; rows loaded
                    # at connect are identity-mapped and go stale when leases change
                    # via HTTP. Expire cached state so lease checks see committed
                    # values instead of objects cached before the claim.
                    db.expire_all()
                    worker = db.get(Worker, session.worker_id)
                    if not worker or worker.status != "online" or worker.revoked_at is not None:
                        await websocket.send_json({"type": "error", "code": "worker_unavailable", "message": "Worker is unavailable"})
                        continue
                    lease = db.get(ControlLease, session.id)
                    if not lease or lease.controller_agent != agent_token.agent_name or not lease.expires_at or _as_utc(lease.expires_at) <= _now():
                        await websocket.send_json({"type": "error", "code": "lease_required", "message": "An active control lease is required"})
                        continue
                    if frame_type == "resize":
                        cols, rows = frame.get("cols"), frame.get("rows")
                        if not _is_bounded_int(cols, RESIZE_COLS) or not _is_bounded_int(rows, RESIZE_ROWS):
                            await websocket.send_json({"type": "error", "code": "invalid_resize", "message": "cols must be an integer 20..500 and rows an integer 5..200"})
                            continue
                        event = _event(db, session.id, "resize_requested", {"cols": cols, "rows": rows})
                        db.commit()
                        await manager.send_to_role(key, "worker", {"type": "event", "event": _event_response(event)})
                        continue
                    value = frame.get("input")
                    size = utf8_size(value) if isinstance(value, str) else None
                    if not value or size is None or size > MAX_FRAME_TEXT_BYTES:
                        await websocket.send_json({"type": "error", "code": "invalid_input", "message": "Input must be non-empty UTF-8 text up to 64 KB"})
                        continue
                    event = _event(db, session.id, "input_requested", {"input": value})
                    db.commit()
                    payload = {"type": "event", "event": _event_response(event)}
                    await manager.send_to_role(key, "worker", payload)
                    await manager.send_to_role(key, "controller", payload, exclude=websocket)
                elif role == "worker" and frame_type == "output":
                    value = frame.get("text")
                    size = utf8_size(value) if isinstance(value, str) else None
                    if size is None or size > MAX_FRAME_TEXT_BYTES:
                        await websocket.send_json({"type": "error", "code": "invalid_output", "message": "Output must be UTF-8 text up to 64 KB"})
                        continue
                    event = _event(db, session.id, "output", {"text": value})
                    db.commit()
                    payload = {"type": "event", "event": _event_response(event)}
                    await manager.send_to_role(key, "controller", payload)
                elif role == "worker" and frame_type == "approval":
                    try:
                        data = validate_approval_data({"prompt": frame.get("prompt")})
                    except ValueError:
                        await websocket.send_json({"type": "error", "code": "invalid_approval", "message": "Prompt must be non-empty UTF-8 text up to 4096 bytes"})
                        continue
                    event = _event(db, session.id, "approval_requested", data)
                    db.commit()
                    await manager.send_to_role(key, "controller", {"type": "event", "event": _event_response(event)})
                else:
                    await websocket.send_json({"type": "error", "code": "invalid_frame", "message": "Frame is not allowed for this stream role"})
            finally:
                # Never hold a DB transaction while parked on receive(): HTTP routes
                # share this database and would block behind the stream's lock.
                db.rollback()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(key, websocket)
        db.close()
