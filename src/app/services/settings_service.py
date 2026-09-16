"""Centralized system settings with in-memory cache and env fallback."""

import re
import threading
import time
from urllib.parse import urlparse

from src.app.config import Config
from src.app.models.system_setting_model import SystemSettingModel
from src.app.utils.settings_crypto import decrypt_value, encrypt_value, mask_value

MANAGED_KEYS = (
    "GENAI_API_KEY",
    "GENAI_MODEL",
    "ASAAS_API_KEY",
    "ASAAS_API_URL",
    "ASAAS_WEBHOOK_TOKEN",
    "MAIL_SERVER",
    "MAIL_PORT",
    "MAIL_USERNAME",
    "MAIL_PASSWORD",
    "MAIL_DEFAULT_SENDER",
)

SENSITIVE_KEYS = frozenset(
    {
        "GENAI_API_KEY",
        "ASAAS_API_KEY",
        "ASAAS_WEBHOOK_TOKEN",
        "MAIL_PASSWORD",
    }
)

OPTIONAL_KEYS = frozenset(
    {
        "ASAAS_API_KEY",
        "ASAAS_API_URL",
        "ASAAS_WEBHOOK_TOKEN",
    }
)

CACHE_CHECK_INTERVAL = 1.0
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_lock = threading.RLock()
_cache = {}
_cached_revision = None
_last_check = 0.0
_loaded = False


class SettingsValidationError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def can_manage_system_settings(user):
    return bool(user and (user.has_role("admin") or user.has_role("super_admin")))


class SettingsService:
    @staticmethod
    def bootstrap():
        SystemSettingModel.ensure_indexes()
        SettingsService.seed_from_env()
        SettingsService.reload(force=True)

    @staticmethod
    def reset_cache():
        global _cache, _cached_revision, _last_check, _loaded
        with _lock:
            _cache = {}
            _cached_revision = None
            _last_check = 0.0
            _loaded = False

    @staticmethod
    def seed_from_env(updated_by="system"):
        inserted = False
        for key in MANAGED_KEYS:
            existing = SystemSettingModel.get_by_key(key)
            if existing:
                continue
            raw = SettingsService._env_fallback(key)
            stored = encrypt_value(raw) if key in SENSITIVE_KEYS else ("" if raw is None else str(raw))
            SystemSettingModel.upsert(key, stored, updated_by=updated_by)
            inserted = True
        if inserted:
            SystemSettingModel.bump_revision()

    @staticmethod
    def get(key, default=None):
        SettingsService._ensure_fresh()
        with _lock:
            if key in _cache:
                value = _cache.get(key)
                return default if value in (None, "") and default is not None else value
        fallback = SettingsService._env_fallback(key)
        if fallback in (None, "") and default is not None:
            return default
        return fallback

    @staticmethod
    def mail_sender():
        return SettingsService.get("MAIL_DEFAULT_SENDER") or SettingsService.get("MAIL_USERNAME")

    @staticmethod
    def list_settings():
        SettingsService._ensure_fresh()
        docs = {item["key"]: item for item in SystemSettingModel.list_by_keys(MANAGED_KEYS)}
        items = []
        for key in MANAGED_KEYS:
            doc = docs.get(key) or {}
            items.append(
                {
                    "key": key,
                    "value": SettingsService.get(key) or "",
                    "is_sensitive": key in SENSITIVE_KEYS,
                    "updated_at": doc.get("updated_at"),
                    "updated_by": doc.get("updated_by"),
                }
            )
        return items

    @staticmethod
    def update(payload, updated_by):
        incoming = SettingsService._normalize_payload(payload)
        if not incoming:
            raise SettingsValidationError("No settings provided")

        SettingsService._ensure_fresh()
        current = {key: SettingsService.get(key) or "" for key in MANAGED_KEYS}
        merged = dict(current)
        changed = []

        for key, value in incoming.items():
            if key not in MANAGED_KEYS:
                continue
            if key in SENSITIVE_KEYS and (value is None or str(value).strip() == ""):
                continue
            normalized = "" if value is None else str(value).strip()
            SettingsService._validate_field(key, normalized)
            if normalized != (current.get(key) or ""):
                changed.append((key, current.get(key) or "", normalized))
            merged[key] = normalized

        for key, normalized in merged.items():
            if key in incoming or key in {item[0] for item in changed}:
                SettingsService._validate_field(key, normalized)

        if not changed:
            return SettingsService.list_settings()

        for key, old_value, new_value in changed:
            stored = encrypt_value(new_value) if key in SENSITIVE_KEYS else new_value
            SystemSettingModel.upsert(key, stored, updated_by=updated_by)
            history_old = mask_value(old_value) if key in SENSITIVE_KEYS else old_value
            history_new = mask_value(new_value) if key in SENSITIVE_KEYS else new_value
            SystemSettingModel.insert_history(key, history_old, history_new, updated_by)

        SystemSettingModel.bump_revision()
        SettingsService.reload(force=True)
        return SettingsService.list_settings()

    @staticmethod
    def list_history(skip=0, limit=50, key=None):
        if key and key not in MANAGED_KEYS:
            raise SettingsValidationError("Unknown setting key")
        return SystemSettingModel.list_history(skip=skip, limit=limit, key=key)

    @staticmethod
    def reload(force=False):
        global _cache, _cached_revision, _last_check, _loaded
        with _lock:
            docs = {item["key"]: item for item in SystemSettingModel.list_by_keys(MANAGED_KEYS)}
            next_cache = {}
            for key in MANAGED_KEYS:
                doc = docs.get(key)
                if doc and doc.get("value") not in (None,):
                    raw = doc.get("value")
                    next_cache[key] = decrypt_value(raw) if key in SENSITIVE_KEYS else ("" if raw is None else str(raw))
                else:
                    fallback = SettingsService._env_fallback(key)
                    next_cache[key] = "" if fallback is None else str(fallback)
            _cache = next_cache
            _cached_revision = SystemSettingModel.get_revision()
            _last_check = time.monotonic()
            _loaded = True
            SettingsService.apply_runtime(dict(_cache))
            return dict(_cache)

    @staticmethod
    def apply_runtime(values=None):
        data = values if values is not None else dict(_cache)
        for key in MANAGED_KEYS:
            value = data.get(key)
            if key == "MAIL_PORT":
                value = SettingsService._coerce_mail_port(value)
            setattr(Config, key, value)
            try:
                from flask import current_app

                current_app.config[key] = value
            except RuntimeError:
                pass

        api_key = data.get("GENAI_API_KEY")
        if api_key:
            try:
                import google.generativeai as genai

                genai.configure(api_key=api_key)
            except Exception:
                pass

    @staticmethod
    def _ensure_fresh():
        global _last_check, _cached_revision, _loaded
        with _lock:
            now = time.monotonic()
            if not _loaded:
                SettingsService.reload(force=True)
                return
            if now - _last_check < CACHE_CHECK_INTERVAL:
                return
            _last_check = now
            revision = SystemSettingModel.get_revision()
            if revision != _cached_revision:
                SettingsService.reload(force=True)

    @staticmethod
    def _env_fallback(key):
        return getattr(Config, key, None)

    @staticmethod
    def _normalize_payload(payload):
        if payload is None:
            return {}
        if isinstance(payload, dict) and isinstance(payload.get("settings"), dict):
            return payload.get("settings") or {}
        if isinstance(payload, dict):
            return {key: value for key, value in payload.items() if key in MANAGED_KEYS}
        return {}

    @staticmethod
    def _coerce_mail_port(value):
        if value in (None, ""):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _validate_field(key, value):
        if key in OPTIONAL_KEYS:
            if value == "":
                return
        elif key in SENSITIVE_KEYS:
            if value == "":
                return
        elif value == "":
            raise SettingsValidationError(f"{key} cannot be empty")

        if key == "MAIL_PORT" and value != "":
            try:
                port = int(value)
            except (TypeError, ValueError):
                raise SettingsValidationError("MAIL_PORT must be an integer")
            if port < 1 or port > 65535:
                raise SettingsValidationError("MAIL_PORT must be between 1 and 65535")

        if key == "MAIL_DEFAULT_SENDER" and value and not EMAIL_RE.match(value):
            raise SettingsValidationError("MAIL_DEFAULT_SENDER must be a valid email")

        if key == "ASAAS_API_URL" and value:
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise SettingsValidationError("ASAAS_API_URL must be a valid http(s) URL")
