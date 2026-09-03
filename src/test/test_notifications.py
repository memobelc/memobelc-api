"""Testes das rotas de notificações."""
import json
import pytest


def test_notifications_list_requires_auth(client):
    response = client.get("/notifications/list")
    assert response.status_code == 401


def test_notifications_list(client, auth_headers):
    response = client.get("/notifications/list", headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert "notifications" in data


def test_notifications_unread_count_requires_auth(client):
    response = client.get("/notifications/unread_count")
    assert response.status_code == 401


def test_notifications_unread_count(client, auth_headers):
    response = client.get("/notifications/unread_count", headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert "unread_count" in data


def test_notifications_mark_as_read_requires_auth(client):
    response = client.post(
        "/notifications/mark_as_read",
        data=json.dumps({"notification_id": "507f1f77bcf86cd799439011"}),
        content_type="application/json",
    )
    assert response.status_code == 401


def test_notifications_mark_as_read(client, auth_headers):
    response = client.post(
        "/notifications/mark_as_read",
        data=json.dumps({"mark_all": True}),
        headers=auth_headers,
    )
    assert response.status_code in (200, 400)


def test_notification_settings_requires_auth(client):
    response = client.get("/notifications/settings")
    assert response.status_code == 401


def test_notification_settings_defaults(client, auth_headers):
    response = client.get("/notifications/settings", headers=auth_headers)
    assert response.status_code == 200
    data = response.get_json()
    assert "services" in data
    assert data["services"]["daily_study"]["enabled"] is True
    assert data["services"]["daily_study"]["email"] is False
    assert data["services"]["affiliate_sales"]["enabled"] is True
    assert data["services"]["affiliate_sales"]["email"] is True


def test_notification_settings_update_email(client, auth_headers):
    response = client.patch(
        "/notifications/settings",
        data=json.dumps({"services": {"support": {"email": True}}}),
        content_type="application/json",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["services"]["support"]["email"] is True
    assert data["services"]["support"]["enabled"] is True


def test_notification_settings_rejects_unknown_service(client, auth_headers):
    response = client.patch(
        "/notifications/settings",
        data=json.dumps({"services": {"unknown_service": {"email": True}}}),
        content_type="application/json",
        headers=auth_headers,
    )
    assert response.status_code == 400
