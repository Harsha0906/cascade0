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

import base64
import hashlib
import json
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
_wall_clock: Callable[[], float] = time.time    # converts a token's `exp` onto _clock (patched in tests)
_token_cache: dict[str, tuple[float, str, Optional[str]]] = {}   # sha256(token) -> (expires, user_id, email)
_cache_lock = threading.Lock()


def _unauthorized(detail: str = "Authentication required") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


def _auth_unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail="Authentication service unavailable", headers={"Retry-After": "5"})


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

    def authorize(self, requested: Optional[str], *roles: str) -> str:
        """The factory a request names (or the actor's default) with one of `roles` in it:
        404 for a non-member, 403 for a member without the role. Returns the factory id."""
        factory_id = self.factory_for(requested)
        self.require_role(factory_id, *roles)
        return factory_id

    def authorize_resource(self, factory_id: Optional[str], *roles: str) -> str:
        """Authorise against the factory that OWNS an existing resource (a run, an outcome, a
        line...). A resource without a factory, or of a factory the actor is not a member of,
        is a 404 (fail closed, no existence leak); a member without the role is a 403."""
        if not factory_id or factory_id not in self.memberships:
            raise _not_found()
        self.require_role(factory_id, *roles)
        return factory_id

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


def _is_auth_rejection(exc: Exception) -> bool:
    """True when Supabase Auth judged the token itself (invalid, expired, other project, no such
    user); False for outages, rate limits and anything unrecognised (those are 503, never 401,
    so an outage or a library change cannot look like a mass logout)."""
    try:
        from supabase_auth.errors import AuthApiError, AuthInvalidJwtError, AuthSessionMissingError
    except ImportError:   # pragma: no cover - supabase is a dependency
        return False
    if isinstance(exc, (AuthInvalidJwtError, AuthSessionMissingError)):
        return True
    if isinstance(exc, AuthApiError):
        code = getattr(exc, "status", None)
        return isinstance(code, int) and 400 <= code < 500 and code not in (408, 429)
    return False


def _token_exp(token: str) -> Optional[float]:
    """The `exp` claim (epoch seconds) read from the JWT payload WITHOUT verifying it. Used only
    to shorten a cache entry after Supabase has verified the token; never trusted for auth."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        exp = claims.get("exp") if isinstance(claims, dict) else None
        return float(exp) if isinstance(exp, (int, float)) and not isinstance(exp, bool) else None
    except Exception:
        return None


def _verify_token(token: str) -> tuple[str, Optional[str]]:
    """(user_id, email) of a valid access token. An auth rejection is a 401; an unreachable or
    failing Supabase Auth is a 503 with Retry-After. Only successes are cached, for at most
    TOKEN_CACHE_SECONDS and never past the token's own `exp`, so a revoked token is accepted
    for at most 60 s and an expired one not at all."""
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
    except Exception as exc:
        if _is_auth_rejection(exc):
            logger.info("Access token rejected: %s", type(exc).__name__)
            raise _unauthorized("Invalid or expired token") from None
        # Outage, timeout, 5xx, rate limit or unknown error: fail closed, but not as a logout.
        logger.warning("Supabase Auth unavailable while verifying a token: %s", type(exc).__name__)
        raise _auth_unavailable() from None
    user = getattr(response, "user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise _unauthorized("Invalid or expired token")
    email = getattr(user, "email", None)
    expires = now + TOKEN_CACHE_SECONDS
    exp = _token_exp(token)
    if exp is not None:
        expires = min(expires, now + (exp - _wall_clock()))
    if expires <= now:
        return str(user_id), email   # verified but at (or past) its exp: do not cache
    with _cache_lock:
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            for k in [k for k, v in _token_cache.items() if v[0] <= now] or list(_token_cache)[:_TOKEN_CACHE_MAX // 2]:
                _token_cache.pop(k, None)
        _token_cache[key] = (expires, str(user_id), email)
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


def actor_kind(machine: bool = False):
    """Dependency: a verified actor. The machine actor (X-API-Key) is refused unless
    `machine=True` (automation endpoints). The FACTORY is authorised by each endpoint against the
    resource it touches (`Actor.authorize` / `Actor.authorize_resource`), never here."""
    def dependency(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.kind == "machine" and not machine:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="The API key is for automation endpoints only; sign in")
        return actor
    return dependency


user_actor = actor_kind()
machine_actor = actor_kind(machine=True)


def require(*roles: str, machine: bool = False):
    """Dependency for endpoints that touch NO factory resource (health checks, weather): one of
    `roles` in the actor's own default factory. Anything factory-scoped uses Actor.authorize*."""
    kind = actor_kind(machine)

    def dependency(actor: Actor = Depends(kind)) -> Actor:
        actor.authorize(None, *roles)
        return actor
    return dependency
