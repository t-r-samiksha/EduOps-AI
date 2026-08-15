"""Server-side Supabase Admin API access - the REAL mechanism for provisioning a
login-capable teacher account.

Not to be confused with `app/services/auth.py::_get_or_create_user`, which only
lazily materializes the LOCAL `users` row the first time someone with an
ALREADY-EXISTING Supabase Auth account authenticates - it never creates the
Supabase Auth account itself. `scripts/seed_demo_data.py`'s users aren't real
Supabase Auth accounts either (synthetic uuid5 `supabase_id`, can't log in - see
that script's own docstring). The only place a real Supabase Auth account has
ever been created for this project was via ad-hoc one-off scripts run manually
in earlier sessions (e.g. `admin@sam.in`). This module is that same mechanism -
`auth.admin.create_user` - wired into a real, repeatable backend endpoint
instead of a throwaway script.
"""

import os
import uuid

from fastapi import HTTPException, status
from supabase import Client, create_client
from supabase_auth.errors import AuthApiError

def _new_client() -> Client:
    """A FRESH client every call - deliberately not cached/reused across
    requests. Confirmed by direct reproduction: calling
    `client.auth.sign_in_with_password(...)` on a client mutates that
    client's internal auth state to the signed-in user's session - any
    LATER `client.auth.admin.*` call on that SAME instance then fails with
    "User not allowed" (the client is no longer acting as the service role).
    A module-level singleton shared between `create_auth_account` (admin
    operations) and `sign_in_and_get_access_token` (a real sign-in) hit
    exactly this and silently poisoned every admin call for the rest of the
    process's life after the first sign-in. `create_client()` itself is cheap
    (no network call until a method is actually invoked), so there's no real
    cost to never caching this."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def create_auth_account(*, email: str, password: str, full_name: str | None, role: str) -> uuid.UUID:
    """Creates a real, login-capable Supabase Auth account with
    `app_metadata.role = role` - the exact claim
    `app/services/auth.py::get_current_user` reads a caller's role from.

    Raises a clean HTTPException on failure: 409 if the email is already
    registered in Supabase Auth, 502 for any other Supabase-side failure (an
    external dependency problem, not bad client input).
    """
    client = _new_client()
    try:
        resp = client.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "app_metadata": {"role": role},
                "user_metadata": {"full_name": full_name} if full_name else {},
            }
        )
    except AuthApiError as exc:
        message = exc.message or ""
        if exc.status in (400, 409, 422) and "already" in message.lower():
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"A user with email {email} is already registered"
            ) from exc
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Failed to create the {role}'s login account: {message}"
        ) from exc

    if resp.user is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Supabase returned no user after account creation")

    return uuid.UUID(resp.user.id)


def create_teacher_auth_account(*, email: str, password: str, full_name: str | None) -> uuid.UUID:
    return create_auth_account(email=email, password=password, full_name=full_name, role="teacher")


def create_admin_auth_account(*, email: str, password: str, full_name: str | None) -> uuid.UUID:
    return create_auth_account(email=email, password=password, full_name=full_name, role="admin")


def sign_in_and_get_access_token(*, email: str, password: str) -> str:
    """Real Supabase Auth sign-in, server-side - used right after a fresh
    signup so the response can hand back a genuine access_token immediately,
    without a separate client-side login round-trip being the only way to
    get one. Raises a clean HTTPException on failure (should not normally
    happen right after we just created this exact account with this exact
    password, but a transient Supabase-side failure is possible)."""
    client = _new_client()
    try:
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
    except AuthApiError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Account created but sign-in failed: {exc.message}"
        ) from exc

    if resp.session is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Account created but Supabase returned no session")

    return resp.session.access_token
