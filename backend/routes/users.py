"""User management: staff accounts and worker records."""

from flask import Blueprint, g, jsonify, request

from auth import role_required
from extensions import db
from models import ROLES, STAFF_ROLES, User
from validation import (
    ApiError,
    get_json,
    get_or_404,
    one_of,
    parse_bool,
    require_str,
    validate_email,
    validate_password,
    validate_phone,
)

users_bp = Blueprint("users", __name__, url_prefix="/api/users")


@users_bp.get("")
@role_required(*STAFF_ROLES)
def list_users():
    """List users, optionally filtered by ?role=Worker and ?active=true|false."""
    query = User.query
    role = one_of(request.args.get("role"), "role", "Role", ROLES, required=False)
    if role:
        query = query.filter(User.role == role)
    active = parse_bool(request.args.get("active"), "active", "Active", required=False)
    if active is not None:
        query = query.filter(User.is_active == active)
    users = query.order_by(User.full_name).all()
    return jsonify({"users": [u.to_dict() for u in users]})


@users_bp.post("")
@role_required("Admin")
def create_user():
    """Create a user. Staff roles need a password (they log in); Workers need a trade."""
    data = get_json()
    full_name = require_str(data.get("full_name"), "full_name", "Full name", 2, 100)
    email = validate_email(data.get("email"))
    phone = validate_phone(data.get("phone"))
    role = one_of(data.get("role"), "role", "Role", ROLES)
    trade = require_str(data.get("trade"), "trade", "Trade", 2, 50, required=(role == "Worker"))
    password = validate_password(data.get("password"), required=(role in STAFF_ROLES))

    if User.query.filter_by(email=email).first():
        raise ApiError(f"A user with email {email} already exists.", "email", status=409)

    user = User(
        full_name=full_name, email=email, phone=phone, role=role, trade=trade, is_active=True
    )
    if password and role in STAFF_ROLES:
        user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"user": user.to_dict()}), 201


def _update_profile(user, data):
    """Name, phone and email (email must stay unique)."""
    if "full_name" in data:
        user.full_name = require_str(data["full_name"], "full_name", "Full name", 2, 100)
    if "phone" in data:
        user.phone = validate_phone(data["phone"])
    if "email" in data:
        email = validate_email(data["email"])
        clash = User.query.filter(User.email == email, User.user_id != user.user_id).first()
        if clash:
            raise ApiError(f"A user with email {email} already exists.", "email", status=409)
        user.email = email


def _update_role(user, data, actor):
    """Change the role; an admin may not demote themselves (they could lock everyone out)."""
    if "role" in data:
        new_role = one_of(data["role"], "role", "Role", ROLES)
        if user.user_id == actor.user_id and new_role != "Admin":
            raise ApiError("You cannot remove your own Admin role.", "role", status=409)
        user.role = new_role


def _update_trade_and_password(user, data):
    if "trade" in data:
        user.trade = require_str(data["trade"], "trade", "Trade", 2, 50, required=False)
    if "password" in data and data["password"]:
        user.set_password(validate_password(data["password"], required=True))


def _update_active(user, data, actor):
    """Activate or deactivate; an admin may not deactivate themselves."""
    if "is_active" in data:
        is_active = parse_bool(data["is_active"], "is_active", "Active")
        if user.user_id == actor.user_id and not is_active:
            raise ApiError("You cannot deactivate your own account.", "is_active", status=409)
        user.is_active = is_active


def _check_account_is_consistent(user):
    """Cross-field rules, checked after every change has been applied."""
    if user.role == "Worker" and not user.trade:
        raise ApiError("Trade is required for workers.", "trade")
    if user.role in STAFF_ROLES and not user.password_hash:
        raise ApiError("Set a password so this staff member can log in.", "password")


@users_bp.patch("/<int:user_id>")
@role_required("Admin")
def update_user(user_id):
    """Update name, phone, role, trade, password or active flag (activate/deactivate)."""
    user = get_or_404(User, user_id, "User")
    data = get_json()
    # Fields are validated in this order, so with several mistakes the first one is reported.
    _update_profile(user, data)
    _update_role(user, data, g.current_user)
    _update_trade_and_password(user, data)
    _update_active(user, data, g.current_user)
    _check_account_is_consistent(user)

    db.session.commit()
    return jsonify({"user": user.to_dict()})
