"""Require a service entitlement after authentication."""

from functools import wraps
from flask import jsonify

from src.app.services.entitlement_service import EntitlementService


def require_service_access(service_key):
    def decorator(f):
        @wraps(f)
        def wrapped(current_user, *args, **kwargs):
            allowed, payload = EntitlementService.can_access_service(current_user, service_key)
            if not allowed:
                return jsonify(payload), 403
            return f(current_user, *args, **kwargs)
        return wrapped
    return decorator
