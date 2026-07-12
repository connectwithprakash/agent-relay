"""Regression tests for Alembic upgrade compatibility."""
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import AgentToken, Relay

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _upgrade(database_url: str, revision: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_upgrade_012_deduplicates_legacy_agent_tokens(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'relay.db'}"
    _upgrade(database_url, "011")

    engine = create_engine(database_url)
    with Session(engine) as session:
        session.add(Relay(id="relay-legacy", agent_names=["alice"], is_public=False))
        session.add_all(
            [
                AgentToken(
                    token_hash="first-token-hash",
                    token_prefix="first",
                    relay_id="relay-legacy",
                    agent_name="alice",
                    is_creator=True,
                ),
                AgentToken(
                    token_hash="second-token-hash",
                    token_prefix="second",
                    relay_id="relay-legacy",
                    agent_name="alice",
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
    assert tokens[0].token_hash == "first-token-hash"
