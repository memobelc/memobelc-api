"""User preferences for in-app and email notifications."""

from datetime import datetime, timezone

from src.app import mongo


SERVICE_KEYS = (
    "daily_study",
    "classroom_added",
    "new_cards",
    "teacher_custom",
    "admin_custom",
    "support",
    "affiliate",
    "affiliate_sales",
)

DEFAULT_PREF = {"enabled": True, "email": False}
SERVICE_DEFAULTS = {
    "affiliate_sales": {"enabled": True, "email": True},
}


class UserSettingsModel:
    @staticmethod
    def default_pref(key=None):
        return dict(SERVICE_DEFAULTS.get(key, DEFAULT_PREF))

    @staticmethod
    def default_services():
        return {key: UserSettingsModel.default_pref(key) for key in SERVICE_KEYS}

    @staticmethod
    def _normalize_pref(pref, key=None):
        base = UserSettingsModel.default_pref(key)
        if not isinstance(pref, dict):
            return base
        enabled = bool(pref.get("enabled", base["enabled"]))
        email = bool(pref.get("email", base["email"])) and enabled
        return {"enabled": enabled, "email": email}

    @staticmethod
    def serialize(user_id, doc=None):
        stored = (doc or {}).get("services") or {}
        services = UserSettingsModel.default_services()
        for key, pref in stored.items():
            if key in services:
                services[key] = UserSettingsModel._normalize_pref(pref, key)
        updated_at = (doc or {}).get("updated_at")
        return {
            "user_id": str(user_id),
            "services": services,
            "updated_at": updated_at.isoformat() if updated_at else None,
        }

    @staticmethod
    def get_settings(user_id):
        doc = mongo.db.user_notification_settings.find_one({"user_id": str(user_id)})
        return UserSettingsModel.serialize(user_id, doc)

    @staticmethod
    def update_settings(user_id, settings):
        payload = settings or {}
        incoming = payload.get("services", payload)
        if not isinstance(incoming, dict):
            raise ValueError("services must be an object")

        unknown = [key for key in incoming.keys() if key not in SERVICE_KEYS]
        if unknown:
            raise ValueError(f"Unknown notification services: {', '.join(unknown)}")

        current = UserSettingsModel.get_settings(user_id)
        merged = current["services"]
        for key, pref in incoming.items():
            merged[key] = UserSettingsModel._normalize_pref(
                {**merged.get(key, UserSettingsModel.default_pref(key)), **(pref if isinstance(pref, dict) else {})},
                key,
            )

        now = datetime.now(timezone.utc)
        mongo.db.user_notification_settings.update_one(
            {"user_id": str(user_id)},
            {"$set": {"services": merged, "updated_at": now}},
            upsert=True,
        )
        return UserSettingsModel.get_settings(user_id)
