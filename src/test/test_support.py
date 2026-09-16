"""Testes do módulo de suporte (conversa 1:1 usuário↔admin)."""
import uuid

from src.app import mongo
from src.app.models.user_model import UserModel


def _auth_user(client, email, password="password123", name="User", admin=False):
    client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
        content_type="application/json",
    )
    roles = ["user", "admin"] if admin else ["user"]
    mongo.db.users.update_one(
        {"email": email},
        {"$set": {"is_confirmed": True, "roles": roles, "role": "admin" if admin else "user"}},
    )
    user = mongo.db.users.find_one({"email": email})
    UserModel.update_roles(str(user["_id"]), roles)
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


def test_support_conversation_requires_auth(client):
    response = client.get("/support/conversation")
    assert response.status_code == 401


def test_support_empty_conversation(client):
    suffix = uuid.uuid4().hex[:8]
    headers, _ = _auth_user(client, f"user_{suffix}@example.com")
    response = client.get("/support/conversation", headers=headers)
    assert response.status_code == 200
    data = response.get_json()
    assert data["ticket"] is None
    assert data["messages"] == []


def test_support_send_message_creates_ticket(client):
    suffix = uuid.uuid4().hex[:8]
    headers, user_id = _auth_user(client, f"user_{suffix}@example.com", name="Ana")
    empty = client.post("/support/messages", headers=headers, json={"body": "   "})
    assert empty.status_code == 400

    created = client.post("/support/messages", headers=headers, json={"body": "Preciso de ajuda"})
    assert created.status_code == 201
    data = created.get_json()
    assert data["ticket"]["user_id"] == user_id
    assert data["ticket"]["status"] == "open"
    assert data["ticket"]["unread_for_admin"] == 1
    assert data["message"]["body"] == "Preciso de ajuda"
    assert data["message"]["author_role"] == "user"

    conversation = client.get("/support/conversation", headers=headers)
    assert conversation.status_code == 200
    payload = conversation.get_json()
    assert payload["ticket"]["_id"] == data["ticket"]["_id"]
    assert len(payload["messages"]) == 1


def test_support_user_cannot_see_other_ticket(client):
    suffix = uuid.uuid4().hex[:8]
    user_a, _ = _auth_user(client, f"a_{suffix}@example.com")
    user_b, _ = _auth_user(client, f"b_{suffix}@example.com")
    client.post("/support/messages", headers=user_a, json={"body": "Olá do A"})
    other = client.get("/support/conversation", headers=user_b)
    assert other.status_code == 200
    assert other.get_json()["ticket"] is None


def test_support_admin_list_reply_close_reopen(client):
    suffix = uuid.uuid4().hex[:8]
    user_headers, user_id = _auth_user(client, f"user_{suffix}@example.com", name="Carlos")
    admin_headers, _ = _auth_user(client, f"admin_{suffix}@example.com", name="Admin", admin=True)

    forbidden = client.get("/admin/support/tickets", headers=user_headers)
    assert forbidden.status_code == 403

    client.post("/support/messages", headers=user_headers, json={"body": "Não consigo acessar o curso"})

    listed = client.get("/admin/support/tickets", headers=admin_headers)
    assert listed.status_code == 200
    tickets = listed.get_json()["tickets"]
    assert any(item["user_id"] == user_id for item in tickets)
    ticket = next(item for item in tickets if item["user_id"] == user_id)
    ticket_id = ticket["_id"]
    assert ticket["unread_for_admin"] >= 1
    assert ticket["user_name"] == "Carlos"

    empty_reply = client.post(
        f"/admin/support/tickets/{ticket_id}/messages",
        headers=admin_headers,
        json={"body": ""},
    )
    assert empty_reply.status_code == 400

    reply = client.post(
        f"/admin/support/tickets/{ticket_id}/messages",
        headers=admin_headers,
        json={"body": "Já estamos verificando"},
    )
    assert reply.status_code == 201
    assert reply.get_json()["ticket"]["status"] == "in_progress"
    assert reply.get_json()["message"]["author_role"] == "admin"

    messages = client.get(
        f"/admin/support/tickets/{ticket_id}/messages",
        headers=admin_headers,
    )
    assert messages.status_code == 200
    assert len(messages.get_json()["messages"]) == 2

    user_conv = client.get("/support/conversation", headers=user_headers)
    assert user_conv.get_json()["ticket"]["unread_for_user"] >= 1

    marked = client.post("/support/messages/read", headers=user_headers)
    assert marked.status_code == 200
    assert marked.get_json()["ticket"]["unread_for_user"] == 0

    closed = client.patch(
        f"/admin/support/tickets/{ticket_id}/close",
        headers=admin_headers,
    )
    assert closed.status_code == 200
    assert closed.get_json()["ticket"]["status"] == "closed"

    blocked = client.post(
        f"/admin/support/tickets/{ticket_id}/messages",
        headers=admin_headers,
        json={"body": "ainda fechado"},
    )
    assert blocked.status_code == 400

    reopened_by_user = client.post(
        "/support/messages",
        headers=user_headers,
        json={"body": "Ainda preciso de ajuda"},
    )
    assert reopened_by_user.status_code == 201
    assert reopened_by_user.get_json()["ticket"]["status"] == "open"

    client.patch(f"/admin/support/tickets/{ticket_id}/close", headers=admin_headers)
    reopened = client.patch(
        f"/admin/support/tickets/{ticket_id}/reopen",
        headers=admin_headers,
    )
    assert reopened.status_code == 200
    assert reopened.get_json()["ticket"]["status"] == "in_progress"


def test_support_admin_search_and_mark_read(client):
    suffix = uuid.uuid4().hex[:8]
    user_headers, _ = _auth_user(client, f"maria_{suffix}@example.com", name="Maria Silva")
    admin_headers, _ = _auth_user(client, f"admin2_{suffix}@example.com", admin=True)
    client.post("/support/messages", headers=user_headers, json={"body": "Ajuda com pagamento"})

    found = client.get("/admin/support/tickets?q=Maria", headers=admin_headers)
    assert found.status_code == 200
    assert len(found.get_json()["tickets"]) == 1

    missing = client.get("/admin/support/tickets?q=zzzz-not-found", headers=admin_headers)
    assert missing.status_code == 200
    assert missing.get_json()["tickets"] == []

    ticket_id = found.get_json()["tickets"][0]["_id"]
    read = client.post(
        f"/admin/support/tickets/{ticket_id}/messages/read",
        headers=admin_headers,
    )
    assert read.status_code == 200
    assert read.get_json()["ticket"]["unread_for_admin"] == 0
