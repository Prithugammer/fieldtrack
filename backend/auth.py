"""Authentication: login, current user, and the @role_required decorator."""

import hmac
import logging
from functools import wraps

from flask import Blueprint, current_app, g, jsonify
from flask_jwt_extended import create_access_token, get_jwt, verify_jwt_in_request

from extensions import db
from models import STAFF_ROLES, User
from security import client_address
from validation import ApiError, get_json, require_str

log = logging.getLogger("fieldtrack.auth")

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def session_claims(user):
    """The extra claims put into a login token (also used by tests that mint tokens)."""
    return {"user_id": user.user_id, "role": user.role, "pwv": user.session_stamp()}


def role_required(*roles):
    """Allow the decorated route only for logged-in users whose role is in `roles`.

    Usage:
        @role_required("Dispatcher", "Admin")
        def create_job(): ...

    Steps: (1) require a valid JWT (401 if missing/expired), (2) load the account named in the
    token and make sure it is still active (403 if an admin deactivated it after login),
    (3) compare the account's CURRENT role with the allowed roles (403 if not allowed). The role
    is read from the database, not trusted from the token, so a demotion applies immediately
    instead of lasting until the token expires. The logged-in User is then available as
    g.current_user.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            user_id = claims.get("user_id")
            user = db.session.get(User, user_id) if isinstance(user_id, int) else None
            if user is None or not user.is_active:
                raise ApiError("Your account is no longer active.", status=403)
            if not hmac.compare_digest(str(claims.get("pwv", "")), user.session_stamp()):
                # The password was changed (or the token predates this check): sign in again.
                raise ApiError("Your session has ended. Please log in again.", status=401)
            if user.role not in roles:
                raise ApiError(
                    f"Your role ({user.role}) cannot do this. Allowed: {', '.join(roles)}.",
                    status=403,
                )
            g.current_user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


@auth_bp.post("/login")
def login():
    """Log in with email + password and receive a JWT.

    The token's claims carry user_id and role so every later request can be authorised
    without another password check. Workers and deactivated users are refused.
    """
    data = get_json()
    email = require_str(data.get("email"), "email", "Email", max_len=120).lower()
    password = require_str(data.get("password"), "password", "Password", max_len=128)

    # Throttle BEFORE touching the password so a blocked client costs no bcrypt work.
    limiter = current_app.extensions.get("login_limiter")
    client = client_address()
    if limiter:
        wait = limiter.retry_after(email, client)
        if wait:
            log.warning("Login throttled for client %s (retry in %ss)", client, wait)
            raise ApiError(
                f"Too many failed sign-in attempts. Try again in {wait} seconds.",
                status=429,
                headers={"Retry-After": str(wait)},
            )

    user = User.query.filter_by(email=email).first()
    # Same message AND (approximately) the same time for "no such user", "no password on record" and
    # "wrong password", so attackers can't probe which emails exist (see User.burn_password_check).
    if user is not None and user.password_hash:
        password_ok = user.check_password(password)
    else:
        password_ok = User.burn_password_check(password)
    if not password_ok:
        if limiter:
            limiter.record_failure(email, client)
        raise ApiError("Invalid email or password.", "password", status=401)
    if limiter:
        limiter.reset_account(email)
    if not user.is_active:
        raise ApiError("This account has been deactivated. Contact an administrator.", status=403)
    if user.role not in STAFF_ROLES:
        raise ApiError("Workers do not have access to the admin portal.", status=403)

    token = create_access_token(
        identity=str(user.user_id),
        additional_claims=session_claims(user),
    )
    return jsonify({"token": token, "user": user.to_dict()})


@auth_bp.get("/me")
@role_required(*STAFF_ROLES)
def me():
    """Return the user the current JWT belongs to (used to restore a session on page load)."""
    return jsonify({"user": g.current_user.to_dict()})
