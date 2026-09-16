"""Shared draft / published / scheduled helpers for decks and cards."""

from datetime import datetime, timezone

VALID_STATUSES = ('draft', 'published', 'scheduled')
DEFAULT_STATUS = 'published'


def normalize_status(status):
    if status in VALID_STATUSES:
        return status
    return DEFAULT_STATUS


def parse_scheduled_at(value):
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def isoformat_dt(value):
    if not value:
        return None
    dt = parse_scheduled_at(value)
    if dt:
        return dt.isoformat()
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def is_released(status=None, scheduled_at=None, now=None):
    status = normalize_status(status)
    if status == 'draft':
        return False
    if status == 'scheduled':
        dt = parse_scheduled_at(scheduled_at)
        if not dt:
            return False
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return dt <= now
    return True


def validate_status_payload(status, scheduled_at):
    normalized = normalize_status(status)
    parsed = parse_scheduled_at(scheduled_at)
    if normalized == 'scheduled' and not parsed:
        raise ValueError('scheduled_at is required when status is scheduled')
    if normalized != 'scheduled':
        parsed = None
    return normalized, parsed
