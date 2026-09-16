"""Admin system settings: persistence, cache, encryption and access control."""
import uuid

from src.app import mongo
from src.app.config import Config
from src.app.models.user_model import UserModel
from src.app.services.settings_service import MANAGED_KEYS, SENSITIVE_KEYS, SettingsService
from src.app.utils.settings_crypto import decrypt_value


def _auth_user(client, email, password="password123", name="User", roles=None):
    client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
        content_type="application/json",
    )
    assigned = roles or ["user"]
    primary = "super_admin" if "super_admin" in assigned else ("admin" if "admin" in assigned else "user")
    mongo.db.users.update_one(
        {"email": email},
        {"$set": {"is_confirmed": True, "roles": assigned, "role": primary}},
    )
    user = mongo.db.users.find_one({"email": email})
    UserModel.update_roles(str(user["_id"]), assigned)
    login = client.post(
        "/auth/login",
        json={"email": email, "password": password},
        content_type="application/json",
    )
    data = login.get_json() or {}
    token = data.get("token") or (data.get("pending") or [None, None])[1]
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, str(user["_id"])


def _reset_settings(app):
    with app.app_context():
        mongo.db.system_settings.delete_many({})
        mongo.db.system_settings_history.delete_many({})
        SettingsService.reset_cache()
        SettingsService.bootstrap()


def test_settings_unauthorized_without_token(client):
    response = client.get("/admin/settings")
    assert response.status_code == 401


def test_settings_forbidden_for_regular_user(client, app):
    _reset_settings(app)
    suffix = uuid.uuid4().hex[:8]
    headers, _ = _auth_user(client, f"user_{suffix}@example.com")
    response = client.get("/admin/settings", headers=headers)
    assert response.status_code == 403


def test_settings_get_and_patch_as_admin(client, app):
    _reset_settings(app)
    suffix = uuid.uuid4().hex[:8]
    headers, _ = _auth_user(client, f"admin_{suffix}@example.com", roles=["user", "admin"])
    listed = client.get("/admin/settings", headers=headers)
    assert listed.status_code == 200
    payload = listed.get_json()
    keys = [item["key"] for item in payload["settings"]]
    assert list(MANAGED_KEYS) == keys
    model_item = next(item for item in payload["settings"] if item["key"] == "GENAI_MODEL")
    previous = model_item["value"]
    updated_value = f"gemini-test-{suffix}"
    patched = client.patch(
        "/admin/settings",
        headers=headers,
        json={"settings": {"GENAI_MODEL": updated_value}},
    )
    assert patched.status_code == 200, patched.get_json()
    updated = next(item for item in patched.get_json()["settings"] if item["key"] == "GENAI_MODEL")
    assert updated["value"] == updated_value
    assert SettingsService.get("GENAI_MODEL") == updated_value
    assert Config.GENAI_MODEL == updated_value
    assert previous != updated_value


def test_settings_patch_as_super_admin(client, app):
    _reset_settings(app)
    suffix = uuid.uuid4().hex[:8]
    headers, _ = _auth_user(
        client,
        f"super_{suffix}@example.com",
        roles=["user", "super_admin"],
    )
    response = client.patch(
        "/admin/settings",
        headers=headers,
        json={"settings": {"GENAI_MODEL": f"super-model-{suffix}"}},
    )
    assert response.status_code == 200, response.get_json()
    assert SettingsService.get("GENAI_MODEL") == f"super-model-{suffix}"


def test_settings_seed_from_env_when_empty(client, app):
    with app.app_context():
        mongo.db.system_settings.delete_many({})
        mongo.db.system_settings_history.delete_many({})
        SettingsService.reset_cache()
        SettingsService.bootstrap()
        for key in MANAGED_KEYS:
            doc = mongo.db.system_settings.find_one({"key": key})
            assert doc is not None
            expected = getattr(Config, key)
            stored = doc.get("value")
            actual = decrypt_value(stored) if key in SENSITIVE_KEYS else stored
            assert str(actual or "") == str(expected or "")


def test_sensitive_value_is_encrypted_in_mongo(client, app):
    _reset_settings(app)
    suffix = uuid.uuid4().hex[:8]
    headers, _ = _auth_user(client, f"admin_enc_{suffix}@example.com", roles=["user", "admin"])
    secret = f"sk-live-{suffix}-secret"
    patched = client.patch(
        "/admin/settings",
        headers=headers,
        json={"settings": {"GENAI_API_KEY": secret}},
    )
    assert patched.status_code == 200, patched.get_json()
    doc = mongo.db.system_settings.find_one({"key": "GENAI_API_KEY"})
    assert doc is not None
    assert doc["value"] != secret
    assert secret not in str(doc["value"])
    assert SettingsService.get("GENAI_API_KEY") == secret
    listed = client.get("/admin/settings", headers=headers)
    item = next(entry for entry in listed.get_json()["settings"] if entry["key"] == "GENAI_API_KEY")
    assert item["value"] == secret
    assert item["is_sensitive"] is True


def test_settings_history_is_masked_for_sensitive_keys(client, app):
    _reset_settings(app)
    suffix = uuid.uuid4().hex[:8]
    email = f"admin_hist_{suffix}@example.com"
    headers, _ = _auth_user(client, email, roles=["user", "admin"])
    old_key = SettingsService.get("GENAI_API_KEY") or ""
    new_key = f"new-secret-{suffix}"
    patched = client.patch(
        "/admin/settings",
        headers=headers,
        json={"settings": {"GENAI_API_KEY": new_key, "GENAI_MODEL": f"hist-model-{suffix}"}},
    )
    assert patched.status_code == 200, patched.get_json()
    history = client.get("/admin/settings/history", headers=headers)
    assert history.status_code == 200
    items = history.get_json()["history"]
    api_key_entries = [item for item in items if item["key"] == "GENAI_API_KEY"]
    assert api_key_entries
    entry = api_key_entries[0]
    assert entry["updated_by"] == email
    assert new_key not in (entry.get("old_value") or "")
    assert new_key not in (entry.get("new_value") or "")
    if old_key:
        assert old_key not in (entry.get("old_value") or "")
    assert entry["new_value"].startswith("****")
    model_entries = [item for item in items if item["key"] == "GENAI_MODEL"]
    assert model_entries
    assert model_entries[0]["new_value"] == f"hist-model-{suffix}"
    assert model_entries[0]["updated_by"] == email


def test_settings_validation_rejects_invalid_port(client, app):
    _reset_settings(app)
    suffix = uuid.uuid4().hex[:8]
    headers, _ = _auth_user(client, f"admin_val_{suffix}@example.com", roles=["user", "admin"])
    response = client.patch(
        "/admin/settings",
        headers=headers,
        json={"settings": {"MAIL_PORT": "99999"}},
    )
    assert response.status_code == 400
    assert "MAIL_PORT" in (response.get_json() or {}).get("error", "")
