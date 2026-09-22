"""Caller identity for Concrete HTTP endpoints.

Two mechanisms, deliberately separate:

- **Session JWT** (HS256, `SESSION_JWT_SECRET`) — the public chat widget. Minted by
  `chat_init` after a siteKey exchange, sent as the `x-session-token` header or a
  `sessionToken` body field. Never a Firebase Auth identity.
- **Firebase ID token** — a logged-in Concrete user, sent as `Authorization: Bearer`.

Errors carry the HTTP status and message the endpoints already returned, so call
sites can keep their exact wire contract.
"""
import os

DEFAULT_ALGORITHMS = ["HS256"]


class SessionTokenError(Exception):
    """Session token could not be accepted. Carries the response to send."""

    status = 401
    message = "Invalid session token"

    def __init__(self, message: str | None = None, status: int | None = None):
        if message is not None:
            self.message = message
        if status is not None:
            self.status = status
        super().__init__(self.message)


class MissingSessionToken(SessionTokenError):
    status = 401
    message = "Missing x-session-token header"


class MissingSessionSecret(SessionTokenError):
    status = 500
    message = "Server misconfigured: missing SESSION_JWT_SECRET"


class ExpiredSessionToken(SessionTokenError):
    status = 401
    message = "Session token expired"


class InvalidSessionToken(SessionTokenError):
    status = 401
    message = "Invalid session token"


def session_secret() -> str:
    """Read SESSION_JWT_SECRET or raise MissingSessionSecret (HTTP 500)."""
    secret = os.environ.get("SESSION_JWT_SECRET")
    if not secret:
        raise MissingSessionSecret()
    return secret


def verify_session_token(
    token: str | None,
    *,
    secret: str | None = None,
    verify_exp: bool = True,
) -> dict:
    """Decode a widget session JWT, or raise a SessionTokenError.

    `verify_exp=False` is for refresh flows that must read the claims of an
    already-expired token (see chat_init).
    """
    import jwt as pyjwt

    token = (token or "").strip()
    if not token:
        raise MissingSessionToken()

    secret = secret or session_secret()

    try:
        return pyjwt.decode(
            token,
            secret,
            algorithms=DEFAULT_ALGORITHMS,
            options={"verify_exp": verify_exp},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise ExpiredSessionToken() from exc
    except pyjwt.InvalidTokenError as exc:
        raise InvalidSessionToken() from exc


def verify_id_token(token: str) -> dict:
    """Verify a Firebase ID token. Raises whatever firebase_admin raises."""
    from firebase_admin import auth as firebase_auth

    return firebase_auth.verify_id_token(token)


def bearer_token(authorization: str | None) -> str | None:
    """Pull the token out of an `Authorization: Bearer <token>` header."""
    header = (authorization or "").strip()
    if not header.startswith("Bearer "):
        return None
    return header.split(" ", 1)[1].strip() or None


def resolve_uid(
    *,
    session_token: str | None = None,
    authorization: str | None = None,
) -> str | None:
    """Best-effort uid from either mechanism — session JWT first, then ID token.

    Returns None instead of raising: this is for endpoints that treat any
    authentication failure as a flat 401/403 (the client-integration pattern).
    Endpoints that distinguish the failure modes should call
    `verify_session_token` and handle SessionTokenError directly.
    """
    if session_token and session_token.strip():
        try:
            return verify_session_token(session_token).get("uid")
        except SessionTokenError:
            return None
        except Exception:
            return None

    token = bearer_token(authorization)
    if token:
        try:
            return verify_id_token(token).get("uid")
        except Exception:
            return None

    return None
