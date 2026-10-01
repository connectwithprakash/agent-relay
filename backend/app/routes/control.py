"""Authenticated worker and managed-session control endpoints."""
from datetime import datetime, timedelta, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_agent
from ..config import settings
from ..database import get_db
from ..control_stream_manager import manager
from ..models import ControlEvent, ControlLease, HarnessSession, Worker
from ..schemas import EventRequest, InputRequest, LeaseRequest, RegisterWorkerRequest, StartSessionRequest

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _event(db: Session, session_id: str, kind: str, data: dict | None = None) -> ControlEvent:
    last_sequence = db.query(func.max(ControlEvent.sequence)).filter(
        ControlEvent.session_id == session_id
    ).scalar() or 0
    event = ControlEvent(
        session_id=session_id,
        sequence=last_sequence + 1,
        kind=kind,
        data=data or {},
    )
    db.add(event)
    db.flush()
    return event


def _event_response(event: ControlEvent) -> dict:
    return {
        "sequence": event.sequence,
        "kind": event.kind,
        "data": event.data,
        "created_at": event.created_at.isoformat(),
    }


def _worker_response(worker: Worker) -> dict:
    return {
        "worker_id": worker.id,
        "name": worker.name,
        "agent_name": worker.agent_name,
        "profiles": worker.profiles or [],
        "status": worker.status,
        "last_seen": worker.last_seen.isoformat() if worker.last_seen else None,
    }


def _expire_stale_workers(db: Session, relay_id: str | None = None) -> None:
    """Derive worker availability from the server's persisted heartbeat time."""
    cutoff = _now() - timedelta(seconds=settings.worker_stale_seconds)
    query = db.query(Worker).filter(
        Worker.status == "online",
        Worker.revoked_at.is_(None),
        Worker.last_seen < cutoff,
    )
    if relay_id is not None:
        query = query.filter(Worker.relay_id == relay_id)
    stale_workers = query.all()
    for worker in stale_workers:
        worker.status = "offline"
        sessions = db.query(HarnessSession).filter(
            HarnessSession.worker_id == worker.id,
            HarnessSession.status.in_(("starting", "ready", "controlled")),
        ).all()
        for session in sessions:
            lease = db.get(ControlLease, session.id)
            if lease:
                lease.controller_agent = None
                lease.expires_at = None
                lease.released_at = _now()
            session.status = "detached"
            session.version += 1
            session.updated_at = _now()
            _event(db, session.id, "worker_offline")
    if stale_workers:
        db.commit()


def _session_response(session: HarnessSession, lease: ControlLease | None = None) -> dict:
    return {
        "session_id": session.id,
        "worker_id": session.worker_id,
        "profile": session.profile,
        "status": session.status,
        "version": session.version,
        "controller_agent": lease.controller_agent if lease else None,
        "lease_expires_at": lease.expires_at.isoformat() if lease and lease.expires_at else None,
    }


def _get_session(db: Session, relay_id: str, session_id: str) -> HarnessSession:
    session = db.query(HarnessSession).filter(
        HarnessSession.id == session_id,
        HarnessSession.relay_id == relay_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Harness session not found")
    return session


def _get_active_worker(db: Session, relay_id: str, worker_id: str) -> Worker:
    _expire_stale_workers(db, relay_id)
    worker = db.query(Worker).filter(Worker.id == worker_id, Worker.relay_id == relay_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker.revoked_at is not None or worker.status == "revoked":
        raise HTTPException(status_code=409, detail="Worker is revoked")
    if worker.status != "online":
        raise HTTPException(status_code=409, detail="Worker is offline")
    return worker


def _require_session_worker(db: Session, session: HarnessSession, agent_name: str) -> Worker:
    worker = db.query(Worker).filter(
        Worker.id == session.worker_id,
        Worker.relay_id == session.relay_id,
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker.revoked_at is not None or worker.status == "revoked":
        raise HTTPException(status_code=403, detail="Worker is revoked")
    if worker.agent_name != agent_name:
        raise HTTPException(status_code=403, detail="Only the session worker may perform this action")
    return worker


def _require_creator(agent_info: dict) -> None:
    if not agent_info["is_creator"]:
        raise HTTPException(status_code=403, detail="Only the relay creator may perform this action")


@router.post("/relays/{relay_id}/workers", status_code=status.HTTP_201_CREATED)
async def register_worker(
    relay_id: str,
    req: RegisterWorkerRequest,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    _expire_stale_workers(db, relay_id)
    existing = db.query(Worker).filter(
        Worker.relay_id == relay_id,
        Worker.agent_name == agent_info["agent_name"],
    ).first()
    if existing:
        existing.name = req.name
        existing.profiles = req.profiles
        existing.status = "online"
        existing.last_seen = _now()
        existing.revoked_at = None
        worker = existing
    else:
        worker = Worker(
            id=f"worker-{uuid.uuid4().hex}",
            relay_id=relay_id,
            agent_name=agent_info["agent_name"],
            name=req.name,
            profiles=req.profiles,
        )
        db.add(worker)
    db.commit()
    db.refresh(worker)
    return _worker_response(worker)


@router.get("/relays/{relay_id}/workers")
async def list_workers(
    relay_id: str,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    _expire_stale_workers(db, relay_id)
    workers = db.query(Worker).filter(Worker.relay_id == relay_id).order_by(Worker.created_at).all()
    return {"workers": [_worker_response(worker) for worker in workers]}


@router.post("/relays/{relay_id}/workers/{worker_id}/heartbeat")
async def heartbeat_worker(
    relay_id: str,
    worker_id: str,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    _expire_stale_workers(db, relay_id)
    worker = db.query(Worker).filter(Worker.id == worker_id, Worker.relay_id == relay_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    if worker.revoked_at is not None or worker.status == "revoked":
        raise HTTPException(status_code=409, detail="Worker is revoked")
    if worker.agent_name != agent_info["agent_name"]:
        raise HTTPException(status_code=403, detail="Only the worker may heartbeat")
    worker.last_seen = _now()
    worker.status = "online"
    db.commit()
    db.refresh(worker)
    return _worker_response(worker)


@router.post("/relays/{relay_id}/sessions", status_code=status.HTTP_201_CREATED)
async def start_session(
    relay_id: str,
    req: StartSessionRequest,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    _require_creator(agent_info)
    if req.idempotency_key:
        existing = db.query(HarnessSession).filter(
            HarnessSession.relay_id == relay_id,
            HarnessSession.controller_agent == agent_info["agent_name"],
            HarnessSession.idempotency_key == req.idempotency_key,
        ).first()
        if existing:
            return _session_response(existing, db.get(ControlLease, existing.id))
    worker = _get_active_worker(db, relay_id, req.worker_id)
    if req.profile not in (worker.profiles or []):
        raise HTTPException(status_code=400, detail="Session profile is not allowed by this worker")
    session = HarnessSession(
        id=f"session-{uuid.uuid4().hex}",
        relay_id=relay_id,
        worker_id=worker.id,
        controller_agent=agent_info["agent_name"],
        profile=req.profile,
        idempotency_key=req.idempotency_key,
    )
    db.add(session)
    db.flush()
    _event(db, session.id, "session_requested", {"profile": req.profile})
    db.commit()
    db.refresh(session)
    return _session_response(session)


@router.get("/relays/{relay_id}/sessions")
async def list_sessions(
    relay_id: str,
    worker_id: str | None = None,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    _expire_stale_workers(db, relay_id)
    query = db.query(HarnessSession).filter(HarnessSession.relay_id == relay_id)
    if worker_id:
        worker = _get_active_worker(db, relay_id, worker_id)
        if worker.agent_name != agent_info["agent_name"]:
            raise HTTPException(status_code=403, detail="Only the worker may list its sessions")
        query = query.filter(HarnessSession.worker_id == worker_id)
    elif not agent_info["is_creator"]:
        raise HTTPException(status_code=403, detail="Only the relay creator may list all sessions")
    sessions = query.order_by(HarnessSession.created_at).all()
    return {
        "sessions": [
            {
                **_session_response(session, db.get(ControlLease, session.id)),
                "worker_status": db.get(Worker, session.worker_id).status,
            }
            for session in sessions
        ]
    }


@router.post("/relays/{relay_id}/sessions/{session_id}/ready")
async def mark_session_ready(
    relay_id: str,
    session_id: str,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    session = _get_session(db, relay_id, session_id)
    _require_session_worker(db, session, agent_info["agent_name"])
    if session.status != "starting":
        raise HTTPException(status_code=409, detail="Session is not starting")
    session.status = "ready"
    session.version += 1
    session.updated_at = _now()
    _event(db, session.id, "session_ready")
    db.commit()
    db.refresh(session)
    return _session_response(session)


@router.post("/relays/{relay_id}/sessions/{session_id}/claim")
async def claim_control_lease(
    relay_id: str,
    session_id: str,
    req: LeaseRequest,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    _require_creator(agent_info)
    session = _get_session(db, relay_id, session_id)
    _get_active_worker(db, relay_id, session.worker_id)
    if session.version != req.expected_version:
        raise HTTPException(status_code=409, detail="Session state changed; refresh and retry")
    if session.status not in {"ready", "controlled"}:
        raise HTTPException(status_code=409, detail="Session is not available for control")
    lease = db.get(ControlLease, session.id)
    now = _now()
    if lease and lease.controller_agent and lease.expires_at and _as_utc(lease.expires_at) > now:
        raise HTTPException(status_code=409, detail="Session already has an active control lease")
    if not lease:
        lease = ControlLease(session_id=session.id)
        db.add(lease)
    lease.controller_agent = agent_info["agent_name"]
    lease.expires_at = now + timedelta(seconds=req.lease_seconds)
    lease.released_at = None
    session.status = "controlled"
    session.version += 1
    session.updated_at = now
    _event(db, session.id, "lease_claimed", {"controller_agent": agent_info["agent_name"]})
    db.commit()
    db.refresh(session)
    db.refresh(lease)
    return _session_response(session, lease)


@router.post("/relays/{relay_id}/sessions/{session_id}/input", status_code=status.HTTP_202_ACCEPTED)
async def send_input(
    relay_id: str,
    session_id: str,
    req: InputRequest,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    session = _get_session(db, relay_id, session_id)
    _get_active_worker(db, relay_id, session.worker_id)
    if req.expected_version is not None and req.expected_version != session.version:
        raise HTTPException(status_code=409, detail="Session state changed; refresh and retry")
    lease = db.get(ControlLease, session.id)
    if (
        not lease
        or lease.controller_agent != agent_info["agent_name"]
        or not lease.expires_at
        or _as_utc(lease.expires_at) <= _now()
    ):
        raise HTTPException(status_code=409, detail="An active control lease is required for input")
    event = _event(db, session.id, "input_requested", {"input": req.input})
    db.commit()
    db.refresh(event)
    await manager.send_to_role(
        (relay_id, session_id), "controller", {"type": "event", "event": _event_response(event)}
    )
    return {"event": _event_response(event), "version": session.version}


@router.post("/relays/{relay_id}/sessions/{session_id}/events", status_code=status.HTTP_202_ACCEPTED)
async def append_worker_event(
    relay_id: str,
    session_id: str,
    req: EventRequest,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    session = _get_session(db, relay_id, session_id)
    worker = _require_session_worker(db, session, agent_info["agent_name"])
    if req.kind == "session_adopted":
        _expire_stale_workers(db, relay_id)
        # One conditional UPDATE so concurrent adoptions cannot both succeed.
        adopted = db.query(HarnessSession).filter(
            HarnessSession.id == session.id,
            HarnessSession.status == "detached",
            HarnessSession.worker_id.in_(
                db.query(Worker.id).filter(Worker.id == worker.id, Worker.status == "online", Worker.revoked_at.is_(None))
            ),
        ).update(
            {"status": "ready", "version": HarnessSession.version + 1, "updated_at": _now()},
            synchronize_session=False,
        )
        if adopted != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Only a detached session of an online worker can be adopted")
        db.refresh(session)
    if req.kind in {"session_exited", "session_failed"}:
        session.status = "failed"
        session.version += 1
        session.updated_at = _now()
        lease = db.get(ControlLease, session.id)
        if lease:
            lease.controller_agent = None
            lease.expires_at = None
            lease.released_at = _now()
    event = _event(db, session.id, req.kind, req.data)
    db.commit()
    db.refresh(event)
    response = {"event": _event_response(event), "version": session.version}
    if req.kind in {"output", "approval_requested", "session_adopted"}:
        await manager.send_to_role(
            (relay_id, session_id),
            "controller",
            {"type": "event", "event": response["event"]},
        )
    return response


@router.get("/relays/{relay_id}/sessions/{session_id}/events")
async def get_events(
    relay_id: str,
    session_id: str,
    after_sequence: int = 0,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    _get_session(db, relay_id, session_id)
    events = db.query(ControlEvent).filter(
        ControlEvent.session_id == session_id,
        ControlEvent.sequence > after_sequence,
    ).order_by(ControlEvent.sequence).all()
    return {"events": [_event_response(event) for event in events]}


@router.post("/relays/{relay_id}/sessions/{session_id}/release")
async def release_control_lease(
    relay_id: str,
    session_id: str,
    expected_version: int | None = None,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    session = _get_session(db, relay_id, session_id)
    if expected_version is not None and session.version != expected_version:
        raise HTTPException(status_code=409, detail="Session state changed; refresh and retry")
    lease = db.get(ControlLease, session.id)
    if not lease or lease.controller_agent != agent_info["agent_name"]:
        raise HTTPException(status_code=409, detail="You do not hold this session's control lease")
    lease.controller_agent = None
    lease.expires_at = None
    lease.released_at = _now()
    session.status = "ready"
    session.version += 1
    session.updated_at = _now()
    _event(db, session.id, "lease_released")
    db.commit()
    db.refresh(session)
    return _session_response(session, lease)


@router.post("/relays/{relay_id}/workers/{worker_id}/revoke")
async def revoke_worker(
    relay_id: str,
    worker_id: str,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    _require_creator(agent_info)
    worker = _get_active_worker(db, relay_id, worker_id)
    worker.status = "revoked"
    worker.revoked_at = _now()
    db.commit()
    db.refresh(worker)
    return _worker_response(worker)
