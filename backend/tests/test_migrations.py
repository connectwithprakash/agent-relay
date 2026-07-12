"""Regression tests for Alembic upgrade compatibility."""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import AgentToken, Relay


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _upgrade(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _downgrade(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_upgrade_handles_current_tables_created_before_revision_011(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'mixed-schema.db'}"
    _upgrade(database_url, "010")
    engine = create_engine(database_url)

    # Historical application startup used create_all independently of Alembic.
    Base.metadata.create_all(engine)

    _upgrade(database_url, "head")

    inspector = inspect(engine)
    assert "pairing_invitations" in inspector.get_table_names()
    assert "version" in {column["name"] for column in inspector.get_columns("relays")}


def test_upgrade_preserves_newest_creator_credential(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'duplicates.db'}"
    _upgrade(database_url, "011")
    engine = create_engine(database_url)
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        session.add(Relay(id="relay-legacy", agent_names=["alice"]))
        session.flush()
        session.add_all(
            [
                AgentToken(
                    token_hash="old-creator-hash",
                    token_prefix="old-creator",
                    relay_id="relay-legacy",
                    agent_name="alice",
                    is_creator=True,
                    created_at=now - timedelta(days=2),
                ),
                AgentToken(
                    token_hash="new-creator-hash",
                    token_prefix="new-creator",
                    relay_id="relay-legacy",
                    agent_name="alice",
                    is_creator=True,
                    created_at=now - timedelta(days=1),
                ),
                AgentToken(
                    token_hash="newest-participant-hash",
                    token_prefix="newest-part",
                    relay_id="relay-legacy",
                    agent_name="alice",
                    is_creator=False,
                    created_at=now,
                ),
            ]
        )
        session.commit()

    _upgrade(database_url, "head")

    with Session(engine) as session:
        tokens = session.scalars(
            select(AgentToken).where(
                AgentToken.relay_id == "relay-legacy",
                AgentToken.agent_name == "alice",
            )
        ).all()

    assert len(tokens) == 1
    assert tokens[0].token_hash == "new-creator-hash"
    assert tokens[0].is_creator is True

    _downgrade(database_url, "011")
    with engine.connect() as connection:
        restored = connection.execute(
            text(
                "SELECT token_hash FROM agent_tokens "
                "WHERE relay_id='relay-legacy' AND agent_name='alice'"
            )
        ).scalars().all()
    assert set(restored) == {
        "old-creator-hash",
        "new-creator-hash",
        "newest-participant-hash",
    }
    assert "agent_token_dedup_backup" not in inspect(engine).get_table_names()


def test_upgrade_hashes_and_removes_legacy_plaintext_tokens(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'plaintext.db'}"
    _upgrade(database_url, "010")
    engine = create_engine(database_url)
    raw_token = "legacy-secret-token"

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE agent_tokens ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "token VARCHAR NOT NULL, "
                "relay_id VARCHAR NOT NULL, "
                "agent_name VARCHAR NOT NULL, "
                "is_creator BOOLEAN NOT NULL DEFAULT 0, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO agent_tokens "
                "(token, relay_id, agent_name, is_creator, created_at) "
                "VALUES (:token, :relay_id, :agent_name, 1, :created_at)"
            ),
            {
                "token": raw_token,
                "relay_id": "legacy-relay",
                "agent_name": "alice",
                "created_at": datetime.now(timezone.utc),
            },
        )

    _upgrade(database_url, "head")

    columns = {column["name"] for column in inspect(engine).get_columns("agent_tokens")}
    assert "token" not in columns
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT token_hash, token_prefix FROM agent_tokens")
        ).one()
    assert row.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
    assert row.token_prefix == raw_token[:12]
