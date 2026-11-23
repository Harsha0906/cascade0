"""
CascadeZero — verified actors (who is calling) and factory memberships (what they may do).

Credentials, checked in this order; the first one present decides, and an invalid one is a 401
(there is no fall-through to a weaker credential):

  Authorization: Bearer <Supabase access token>   a user; verified server-side with
                                                  `auth.get_user(token)` (cached 60 s by token hash);
                                                  memberships from `factory_members`
  X-API-Key: <CASCADE_API_KEY>                    the machine actor (automation): approver of
                                                  CASCADE_API_KEY_FACTORY; only machine endpoints
  X-Dev-User: <email>                             AUTH_MODE=dev only (offline storage, never in
                                                  production): a user seeded in the mirror

Anything else is 401. A user without a membership in the requested factory gets 404 (no
existence leak); a member without the needed role gets 403.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Optional

from fastapi import Depends, Header, HTTPException, status

from app import db
from app.config import settings

logger = logging.getLogger("cascadezero.auth")

ROLES = ("owner", "approver", "viewer")
ANY_ROLE = ROLES
WRITE_ROLES = ("owner", "approver")
OWNER_ONLY = ("owner",)

TOKEN_CACHE_SECONDS = 60.0
_TOKEN_CACHE_MAX = 1024

_clock: Callable[[], float] = time.monotonic   # patched in tests
_token_cache: dict[str, tuple[float, str, Optional[str]]] = {}   # sha256(token) -> (expires, user_id, email)
_cache_lock = threading.Lock()


def _unauthorized(detail: str = "Authentication required") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factory not found")


@dataclass(frozen=True)
class Actor:
    kind: Literal["user", "machine"]
    user_id: Optional[str]
    email: Optional[str]
    memberships: Mapping[str, str] = field(default_factory=dict)   # factory_id -> role

    def __post_init__(self) -> None:
        object.__setattr__(self, "memberships", MappingProxyType(dict(self.memberships)))

    def factory_for(self, requested: Optional[str] = None) -> str:
        """The factory this request acts on. A factory the actor is not a member of is a 404."""
        if requested is not None:
            if requested in self.memberships:
                return requested
            raise _not_found()
        if len(self.memberships) == 1:
            return next(iter(self.memberships))
        if settings.DEFAULT_FACTORY_ID in self.memberships:
            return settings.DEFAULT_FACTORY_ID
        raise _not_found()

    def require_role(self, factory_id: str, *roles: str) -> None:
        if self.memberships.get(factory_id) not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Your role in this factory does not allow this action")

    @property
    def approver_name(self) -> str:
        """The verified identity recorded as `approved_by` / `entered_by`."""
        if self.kind != "user" or not self.email:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Approvals need a signed-in user")
        return self.email


# ─── Bearer tokens (Supabase) ────────────────────────────────────────────────

def _auth_client():
    """The service-role Supabase client used to verify access tokens (None offline)."""
    return db._get_supabase()


def clear_token_cache() -> None:
    with _cache_lock:
        _token_cache.clear()


def _verify_token(token: str) -> tuple[str, Optional[str]]:
    """(user_id, email) of a valid access token; 401 otherwise. Valid results are cached for
    TOKEN_CACHE_SECONDS, so a revoked token is accepted for at most that long."""
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = _clock()
    with _cache_lock:
        hit = _token_cache.get(key)
        if hit is not None:
            if hit[0] > now:
                return hit[1], hit[2]
            del _token_cache[key]

    client = _auth_client()
    if client is None:
        raise _unauthorized("Token authentication is not available (Supabase not configured)")
    try:
        response = client.auth.get_user(token)
    except Exception as exc:   # invalid, expired, other project, or Supabase unreachable: fail closed
        logger.info("Access token rejected: %s", type(exc).__name__)
        raise _unauthorized("Invalid or expired token") from None
    user = getattr(response, "user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise _unauthorized("Invalid or expired token")
    email = getattr(user, "email", None)
    with _cache_lock:
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            for k in [k for k, v in _token_cache.items() if v[0] <= now] or list(_token_cache)[:_TOKEN_CACHE_MAX // 2]:
                _token_cache.pop(k, None)
        _token_cache[key] = (now + TOKEN_CACHE_SECONDS, str(user_id), email)
    return str(user_id), email


# ─── The dependency ──────────────────────────────────────────────────────────

def get_actor(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    x_dev_user: Optional[str] = Header(None),
) -> Actor:
    if authorization is not None:
        scheme, _, token = authorization.strip().partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise _unauthorized("Authorization must be 'Bearer <token>'")
        user_id, email = _verify_token(token)
        # Memberships are read on every request, so a removed membership takes effect at once.
        return Actor("user", user_id, email, db.get_memberships(user_id))

    if x_api_key is not None:
        expected = settings.CASCADE_API_KEY
        if not expected or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
            raise _unauthorized("Invalid X-API-Key")
        return Actor("machine", None, None, {settings.api_key_factory: "approver"})

    if x_dev_user is not None and _dev_auth_enabled():
        email = x_dev_user.strip().lower()
        found = db.get_dev_user(email)
        if found is None:
            raise _unauthorized("Unknown dev user")
        user_id, memberships = found
        return Actor("user", user_id, email, memberships)

    raise _unauthorized()


def _dev_auth_enabled() -> bool:
    # Checked per request as well as at startup (defence in depth).
    return settings.AUTH_MODE == "dev" and settings.storage_mode == "offline" and not settings.is_production


def require(*roles: str, machine: bool = False):
    """Dependency: a verified actor holding one of `roles` in the factory it acts on.

    The machine actor (X-API-Key) is refused unless `machine=True` (ingest/simulate endpoints)."""
    def dependency(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.kind == "machine" and not machine:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="The API key is for automation endpoints only; sign in")
        actor.require_role(actor.factory_for(), *roles)
        return actor
    return dependency


read_access = require(*ANY_ROLE)
write_access = require(*WRITE_ROLES)
machine_write_access = require(*WRITE_ROLES, machine=True)
owner_access = require(*OWNER_ONLY)
