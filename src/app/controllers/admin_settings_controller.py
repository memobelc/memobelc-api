"""Admin endpoints for dynamic system settings."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.services.settings_service import (
    SettingsService,
    SettingsValidationError,
    can_manage_system_settings,
)


def _require_settings_admin(current_user):
    if not can_manage_system_settings(current_user):
        return jsonify({"error": "Unauthorized"}), 403
    return None


class AdminSettingsController:
    @staticmethod
    @token_required
    def list_settings(current_user, token):
        forbidden = _require_settings_admin(current_user)
        if forbidden:
            return forbidden
        return jsonify({"settings": SettingsService.list_settings()}), 200

    @staticmethod
    @token_required
    def update_settings(current_user, token):
        forbidden = _require_settings_admin(current_user)
        if forbidden:
            return forbidden
        payload = request.get_json(silent=True) or {}
        try:
            settings = SettingsService.update(payload, updated_by=current_user.email)
        except SettingsValidationError as exc:
            return jsonify({"error": exc.message}), exc.status_code
        return jsonify({"settings": settings}), 200

    @staticmethod
    @token_required
    def list_history(current_user, token):
        forbidden = _require_settings_admin(current_user)
        if forbidden:
            return forbidden
        skip = request.args.get("skip", 0)
        limit = request.args.get("limit", 50)
        key = request.args.get("key")
        try:
            history, total = SettingsService.list_history(
                skip=int(skip or 0),
                limit=int(limit or 50),
                key=key,
            )
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid pagination"}), 400
        except SettingsValidationError as exc:
            return jsonify({"error": exc.message}), exc.status_code
        return jsonify({"history": history, "total": total}), 200


admin_settings_blueprint = Blueprint("admin_settings_blueprint", __name__)
admin_settings_blueprint.route("/", methods=["GET"], strict_slashes=False)(
    AdminSettingsController.list_settings
)
admin_settings_blueprint.route("/", methods=["PATCH"], strict_slashes=False)(
    AdminSettingsController.update_settings
)
admin_settings_blueprint.route("/history", methods=["GET"])(AdminSettingsController.list_history)
