"""Credential and invitation helpers. Raw secrets never persist in the database."""
import hashlib
import secrets
def generate_secret() -> str: return secrets.token_urlsafe(32)
def digest(secret: str) -> str: return hashlib.sha256(secret.encode("utf-8")).hexdigest()
def prefix(secret: str) -> str: return secret[:12]
