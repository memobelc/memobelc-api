"""Testes das rotas de autenticação."""
import json
import uuid
import pytest


@pytest.fixture
def new_user():
    return {"name": "Test User", "email": "test@example.com", "password": "password123"}


def test_register_new_user(client, new_user):
    # Usar email único para evitar 409 de testes anteriores na mesma sessão
    unique_user = {**new_user, "email": f"unique_register_{uuid.uuid4().hex[:8]}@example.com"}
    response = client.post(
        "/auth/register",
        data=json.dumps(unique_user),
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert "token" in data or "access_token" in data


def test_register_user_already_exists(client, new_user):
    client.post("/auth/register", data=json.dumps(new_user), content_type="application/json")
    response = client.post(
        "/auth/register",
        data=json.dumps(new_user),
        content_type="application/json",
    )
    assert response.status_code in (400, 409)
    data = response.get_json()
    assert "error" in data or "message" in data


def test_register_missing_fields(client):
    response = client.post(
        "/auth/register",
        data=json.dumps({"email": "a@a.com"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_login_success(client, new_user):
    client.post("/auth/register", data=json.dumps(new_user), content_type="application/json")
    response = client.post(
        "/auth/login",
        data=json.dumps({"email": new_user["email"], "password": new_user["password"]}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    # Usuário pode retornar token (confirmado) ou pending (não confirmado)
    assert "token" in data or "access_token" in data or "pending" in data


def test_login_invalid_credentials(client):
    response = client.post(
        "/auth/login",
        data=json.dumps({"email": "nonexistent@example.com", "password": "wrong"}),
        content_type="application/json",
    )
    assert response.status_code == 401


def test_login_missing_fields(client):
    response = client.post(
        "/auth/login",
        data=json.dumps({"email": "a@a.com"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_forgot_password(client):
    response = client.post(
        "/auth/forgot_password",
        data=json.dumps({"email": "any@example.com"}),
        content_type="application/json",
    )
    assert response.status_code == 200


def test_mail_list(client):
    response = client.post(
        "/auth/mail_list",
        data=json.dumps({"email": "newsletter@example.com", "name": "Test"}),
        content_type="application/json",
    )
    assert response.status_code in (200, 201)


def test_logout_requires_token(client):
    response = client.post("/auth/logout", content_type="application/json")
    assert response.status_code == 401


def test_logout_success(client, auth_headers):
    response = client.post("/auth/logout", headers=auth_headers)
    assert response.status_code == 200
