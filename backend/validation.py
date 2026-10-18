"""Server-side input validation helpers.

Every helper raises ApiError on bad input. The app turns ApiError into a JSON response of the
form {"error": "...", "field": "..."} so the React UI can show the message under the right
form field.
"""

import math
import re
from datetime import date, datetime, time, timedelta

from flask import request

from extensions import db

# SQLite stores INTEGER as a signed 64-bit value; anything outside this range makes the driver
# raise OverflowError, so ids and counts are range-checked before they reach SQLAlchemy.
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PHONE_RE = re.compile(r"^[0-9 +()\-.]{7,20}$")


class ApiError(Exception):
    """An error that should be returned to the client as JSON."""

    def __init__(self, message, field=None, status=400, headers=None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.status = status
        self.headers = headers or {}

    def to_dict(self):
        return {"error": self.message, "field": self.field}


def get_json():
    """Return the request body as a dict, or raise 400 if it isn't a JSON object.

    Malformed JSON, a wrong content type, text in a bad encoding and absurdly deep nesting are all
    the client's mistake (400). An over-long body never gets this far: Flask answers 413 as soon as
    the body is read (MAX_CONTENT_LENGTH).
    """
    try:
        data = request.get_json(silent=True)
    except RecursionError:  # the parser ran out of stack on something like "[[[[[[ ... (thousands)"
        raise ApiError("Request body is nested too deeply.") from None
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
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:  # e.g. a lone surrogate such as "\ud800": valid JSON, not valid text
        raise ApiError(f"{label} contains characters that are not allowed.", field) from None
    value = value.strip()
    if len(value) < min_len:
        raise ApiError(f"{label} must be at least {min_len} characters.", field)
    if len(value) > max_len:
        raise ApiError(f"{label} must be at most {max_len} characters.", field)
    return value


MAX_PASSWORD_BYTES = 72  # bcrypt only uses the first 72 bytes and (v5+) rejects longer input


def validate_password(value, required=True):
    """A password of 8-128 characters that bcrypt can hash (at most 72 UTF-8 bytes)."""
    password = require_str(value, "password", "Password", 8, 128, required=required)
    if password is not None and len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ApiError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes long.", "password")
    return password


def parse_int(value, field, label, min_value=None, max_value=None, required=True):
    """Validate a whole number within optional bounds.

    Every result also fits a signed 64-bit integer (SQLite's INTEGER), so an oversized value is
    refused here with a 400 instead of crashing later inside the database driver. Non-finite
    floats (inf, -inf, NaN) are not whole numbers and are refused too.
    """
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    if isinstance(value, bool):
        raise ApiError(f"{label} must be a whole number.", field)
    if isinstance(value, float) and not math.isfinite(value):
        raise ApiError(f"{label} must be a whole number.", field)
    try:
        number = int(value)
        if isinstance(value, float) and value != number:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ApiError(f"{label} must be a whole number.", field)
    if not INT64_MIN <= number <= INT64_MAX:
        raise ApiError(f"{label} is out of range.", field)
    if min_value is not None and number < min_value:
        raise ApiError(f"{label} must be at least {min_value}.", field)
    if max_value is not None and number > max_value:
        raise ApiError(f"{label} must be at most {max_value}.", field)
    return number


def parse_id(value, field, label, required=True):
    """Validate a database id: a whole number from 1 up to the signed 64-bit maximum."""
    return parse_int(value, field, label, min_value=1, required=required)


def parse_float(value, field, label, min_value=None, max_value=None, required=True):
    """Validate a finite decimal number within optional bounds (NaN and infinity are refused)."""
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    if isinstance(value, bool):
        raise ApiError(f"{label} must be a number.", field)
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ApiError(f"{label} must be a number.", field)
    if not math.isfinite(number):
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
        text = value.strip() if isinstance(value, str) else ""
        if not DATE_RE.match(text):  # fromisoformat alone also takes "20261001" and "2026-W40-4"
            raise ValueError
        return date.fromisoformat(text)
    except ValueError:
        raise ApiError(f"{label} must be a date in YYYY-MM-DD format.", field)


def parse_datetime(value, field, label, required=True):
    """Validate an ISO datetime string (YYYY-MM-DDTHH:MM[:SS]). Timezones are not accepted."""
    if _is_blank(value):
        if required:
            raise ApiError(f"{label} is required.", field)
        return None
    try:
        text = str(value).strip()
        if text[-1:] in (
            "Z",
            "z",
        ):  # Python 3.10 cannot parse a trailing Z; 3.11+ can, so normalise
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(f"{label} must be a date and time like 2026-10-01T07:00.", field)
    if parsed.tzinfo is not None:
        # Times are local site time with no zone. Silently dropping "+05:45" or "Z" would store a
        # different moment than the client meant, so a zone is refused instead.
        raise ApiError(
            f"{label} must not include a time zone (use local time like 2026-10-01T07:00).", field
        )
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
    """Fetch a row by primary key or raise a 404 ApiError.

    An id outside the 64-bit range can never exist, so it is a 404 without asking the database
    (Flask's <int:> URL converter accepts any number of digits).
    """
    in_range = isinstance(record_id, int) and 1 <= record_id <= INT64_MAX
    record = db.session.get(model, record_id) if in_range else None
    if record is None:
        raise ApiError(f"{label} #{record_id} was not found.", field, status=404)
    return record


def day_bounds(day):
    """Return (start, end) datetimes covering one calendar day: [00:00, next day 00:00)."""
    start = datetime.combine(day, time.min)
    try:
        return start, start + timedelta(days=1)
    except OverflowError:  # day == date.max: there is no "next day", so the window runs to the end
        return start, datetime.max
