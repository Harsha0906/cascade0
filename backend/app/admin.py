"""
CascadeZero — operator CLI for factory memberships.

    python -m app.admin add-member --email E --factory F --role owner|approver|viewer

The user must already exist in Supabase Auth (they sign up on the dashboard first); this looks
them up with the admin API and upserts their row in `factory_members`. Needs the live Supabase
service-role configuration (backend/.env); it does nothing in offline mode.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Optional

from app import db
from app.auth import ROLES
from app.config import settings

_PAGE_SIZE = 200
_MAX_PAGES = 500


class AdminError(RuntimeError):
    """A clear, user-facing CLI error."""


def _client():
    # The admin API needs the service-role key; never fall back to the anon key.
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise AdminError("The admin CLI needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env "
                         "(the anon key cannot look up users)")
    client = db._get_supabase()
    if client is None:
        raise AdminError("Supabase is not configured (offline mode)")
    return client


def _users_page(client, page: int) -> list[Any]:
    result = client.auth.admin.list_users(page=page, per_page=_PAGE_SIZE)
    return list(getattr(result, "users", result) or [])


def find_user(email: str) -> Optional[Any]:
    """The Supabase Auth user with this email (case-insensitive), or None."""
    client = _client()
    wanted = email.strip().lower()
    for page in range(1, _MAX_PAGES + 1):
        users = _users_page(client, page)
        for user in users:
            if (getattr(user, "email", None) or "").lower() == wanted:
                return user
        if len(users) < _PAGE_SIZE:
            return None
    raise AdminError("Too many users to search; narrow the lookup")


def add_member(email: str, factory_id: str, role: str) -> dict[str, Any]:
    email = (email or "").strip().lower()
    factory_id = (factory_id or "").strip()
    if role not in ROLES:
        raise AdminError(f"role must be one of {', '.join(ROLES)}")
    if not email or not factory_id:
        raise AdminError("--email and --factory are required")
    if db.get_factory_row(factory_id) is None:
        raise AdminError(f"Unknown factory {factory_id!r}")
    user = find_user(email)
    if user is None:
        raise AdminError(f"No Supabase user with email {email}: sign up on the dashboard first, then re-run")
    row = {"user_id": str(user.id), "factory_id": factory_id, "role": role, "email": email}
    return db.upsert_row("factory_members", row, key_columns=("user_id", "factory_id"))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.admin", description="CascadeZero membership admin")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add-member", help="give an existing user a role in a factory")
    add.add_argument("--email", required=True)
    add.add_argument("--factory", required=True)
    add.add_argument("--role", required=True, choices=ROLES)
    args = parser.parse_args(argv)
    try:
        if args.command == "add-member":
            add_member(args.email, args.factory, args.role)
            print(f"{args.email.strip().lower()} is now {args.role} of {args.factory.strip()}")
    except (AdminError, db.DatabaseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:   # Supabase Auth errors (e.g. not an admin key), network failures
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
