"""Shared Firebase/GCP plumbing for Concrete's Python deployments.

Import surface is intentionally small — constants, app init, caller identity,
and Secret Manager. Everything here must stay free of `firebase_functions` so
non-Cloud-Functions consumers (langgraph-agent) can use it too.
"""
from .app import (
    ALLOWED_ORIGINS,
    CORS_METHODS,
    PROJECT_ID,
    RAG_REGION,
    REGION,
    ensure_app,
    project_id,
)
from .secrets import get_secret, upsert_secret
from .tokens import (
    DEFAULT_ALGORITHMS,
    ExpiredSessionToken,
    InvalidSessionToken,
    MissingSessionSecret,
    MissingSessionToken,
    SessionTokenError,
    bearer_token,
    resolve_uid,
    session_secret,
    verify_id_token,
    verify_session_token,
)

__all__ = [
    "ALLOWED_ORIGINS",
    "CORS_METHODS",
    "PROJECT_ID",
    "RAG_REGION",
    "REGION",
    "ensure_app",
    "project_id",
    "get_secret",
    "upsert_secret",
    "DEFAULT_ALGORITHMS",
    "ExpiredSessionToken",
    "InvalidSessionToken",
    "MissingSessionSecret",
    "MissingSessionToken",
    "SessionTokenError",
    "bearer_token",
    "resolve_uid",
    "session_secret",
    "verify_id_token",
    "verify_session_token",
]
