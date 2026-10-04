"""Server-side input validation helpers.

Every helper raises ApiError on bad input. The app turns ApiError into a JSON response of the
form {"error": "...", "field": "..."} so the React UI can show the message under the right
form field.
"""

import re
from datetime import date, datetime, time, timedelta

from flask import request

from extensions import db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9 +()\-.]{7,20}$")


class ApiError(Exception):
    """An error that should be returned to the client as JSON."""

    def __init__(self, message, field=None, status=400):
        super().__init__(message)
        self.message = message
        self.field = field
        self.status = status

    def to_dict(self):
        return {"error": self.message, "field": self.field}


def get_json():
    """Return the request body as a dict, or raise 400 if it isn't a JSON object."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object.")
    return data


def _is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def require_str(value, field, label, min_len=1, max_len=255, required=True):
    """Validate a string: trimmed, within length limits. Returns None if optional and blank."""
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    if not isinstance(value, str):
        raise ApiError(f"{label} must be text.", field)
    value = value.strip()
    if len(value) < min_len:
        raise ApiError(f"{label} must be at least {min_len} characters.", field)
    if len(value) > max_len:
        raise ApiError(f"{label} must be at most {max_len} characters.", field)
    return value


def parse_int(value, field, label, min_value=None, max_value=None, required=True):
    """Validate a whole number within optional bounds."""
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    if isinstance(value, bool):
        raise ApiError(f"{label} must be a whole number.", field)
    try:
        number = int(value)
        if isinstance(value, float) and value != number:
            raise ValueError
    except (TypeError, ValueError):
        raise ApiError(f"{label} must be a whole number.", field)
    if min_value is not None and number < min_value:
        raise ApiError(f"{label} must be at least {min_value}.", field)
    if max_value is not None and number > max_value:
        raise ApiError(f"{label} must be at most {max_value}.", field)
    return number


def parse_float(value, field, label, min_value=None, max_value=None, required=True):
    """Validate a decimal number within optional bounds."""
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    if isinstance(value, bool):
        raise ApiError(f"{label} must be a number.", field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(f"{label} must be a number.", field)
    if number != number:  # NaN
        raise ApiError(f"{label} must be a number.", field)
    if min_value is not None and number < min_value:
        raise ApiError(f"{label} must be between {min_value} and {max_value}.", field)
    if max_value is not None and number > max_value:
        raise ApiError(f"{label} must be between {min_value} and {max_value}.", field)
    return number


def parse_latitude(value, field, label="Latitude", required=True):
    return parse_float(value, field, label, -90.0, 90.0, required)


def parse_longitude(value, field, label="Longitude", required=True):
    return parse_float(value, field, label, -180.0, 180.0, required)


def parse_date(value, field, label, required=True):
    """Validate an ISO date string (YYYY-MM-DD)."""
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ApiError(f"{label} must be a date in YYYY-MM-DD format.", field)


def parse_datetime(value, field, label, required=True):
    """Validate an ISO datetime string (YYYY-MM-DDTHH:MM[:SS]). Timezones are not accepted."""
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        raise ApiError(f"{label} must be a date and time like 2026-10-01T07:00.", field)
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def parse_bool(value, field, label, required=True):
    """Accept true/false as JSON booleans or the strings 'true'/'false'."""
    if value is None or value == "":
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
        return value.lower() in ("true", "1")
    raise ApiError(f"{label} must be true or false.", field)


def one_of(value, field, label, choices, required=True):
    """Validate that a value is one of the allowed choices."""
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    if value not in choices:
        raise ApiError(f"{label} must be one of: {', '.join(choices)}.", field)
    return value


def validate_email(value, field="email"):
    email = require_str(value, field, "Email", 5, 120)
    email = email.lower()
    if not EMAIL_RE.match(email):
        raise ApiError("Enter a valid email address.", field)
    return email


def validate_phone(value, field="phone"):
    phone = require_str(value, field, "Phone", 7, 20, required=False)
    if phone and not PHONE_RE.match(phone):
        raise ApiError("Phone may contain only digits, spaces and + - ( ).", field)
    return phone


def get_or_404(model, record_id, label, field=None):
    """Fetch a row by primary key or raise a 404 ApiError."""
    record = db.session.get(model, record_id)
    if record is None:
        raise ApiError(f"{label} #{record_id} was not found.", field, status=404)
    return record


def day_bounds(day):
    """Return (start, end) datetimes covering one calendar day: [00:00, next day 00:00)."""
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)
