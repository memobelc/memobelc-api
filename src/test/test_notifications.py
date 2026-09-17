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


def _auth_user(client, email, roles=None, name="User"):
    client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": "password123"},
        content_type="application/json",
    )
    assigned = roles or ["user"]
    if "admin" in assigned:
        primary = "admin"
    elif "teacher" in assigned:
        primary = "teacher"
    else:
        primary = "user"
    from src.app import mongo
    from src.app.models.user_model import UserModel

    with client.application.app_context():
        mongo.db.users.update_one(
            {"email": email},
            {"$set": {"is_confirmed": True, "roles": assigned, "role": primary}},
        )
        user = mongo.db.users.find_one({"email": email})
        UserModel.update_roles(str(user["_id"]), assigned)
        user_id = str(user["_id"])
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "password123"},
        content_type="application/json",
    )
    data = login.get_json() or {}
    token = data.get("token") or (data.get("pending") or [None, None])[1]
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, user_id


def test_admin_groups_requires_admin(client):
    import uuid

    headers, _ = _auth_user(client, f"user_{uuid.uuid4().hex[:8]}@example.com")
    response = client.get("/notifications/admin/groups", headers=headers)
    assert response.status_code in (401, 403)


def test_admin_notification_groups_crud(client):
    import uuid

    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_{suffix}@example.com", roles=["user", "admin"], name="Admin"
    )
    _, member_id = _auth_user(client, f"member_{suffix}@example.com", name="Member")

    created = client.post(
        "/notifications/admin/groups",
        headers=admin_headers,
        json={"name": "Beta", "description": "testers", "user_ids": [member_id]},
    )
    assert created.status_code == 201, created.get_json()
    group = created.get_json()
    assert group["name"] == "Beta"
    assert group["member_count"] == 1
    group_id = group["_id"]

    listed = client.get("/notifications/admin/groups", headers=admin_headers)
    assert listed.status_code == 200
    assert any(item["_id"] == group_id for item in listed.get_json()["groups"])

    patched = client.patch(
        f"/notifications/admin/groups/{group_id}",
        headers=admin_headers,
        json={"name": "Beta 2"},
    )
    assert patched.status_code == 200
    assert patched.get_json()["name"] == "Beta 2"

    deleted = client.delete(f"/notifications/admin/groups/{group_id}", headers=admin_headers)
    assert deleted.status_code == 200
    missing = client.get("/notifications/admin/groups", headers=admin_headers)
    assert all(item["_id"] != group_id for item in missing.get_json()["groups"])


def test_admin_custom_users_and_preview(client):
    import uuid

    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_send_{suffix}@example.com", roles=["user", "admin"]
    )
    _, target_id = _auth_user(client, f"target_{suffix}@example.com")

    preview = client.post(
        "/notifications/admin/preview",
        headers=admin_headers,
        json={"target_type": "users", "user_ids": [target_id]},
    )
    assert preview.status_code == 200
    assert preview.get_json()["count"] == 1

    sent = client.post(
        "/notifications/admin/custom",
        headers=admin_headers,
        json={
            "title": "Hello",
            "body": "World",
            "target_type": "users",
            "user_ids": [target_id],
        },
    )
    assert sent.status_code == 200
    assert sent.get_json()["sent_to"] == 1


def test_admin_custom_roles_and_group(client):
    import uuid
    from bson import ObjectId
    from src.app import mongo

    suffix = uuid.uuid4().hex[:8]
    admin_headers, admin_id = _auth_user(
        client, f"admin_role_{suffix}@example.com", roles=["user", "admin"]
    )
    teacher_headers, teacher_id = _auth_user(
        client,
        f"teacher_{suffix}@example.com",
        roles=["user", "teacher"],
        name="Teacher",
    )
    _, student_id = _auth_user(client, f"student_{suffix}@example.com", name="Student")

    preview_roles = client.post(
        "/notifications/admin/preview",
        headers=admin_headers,
        json={"target_type": "roles", "roles": ["teacher"]},
    )
    assert preview_roles.status_code == 200
    assert preview_roles.get_json()["count"] >= 1

    sent_roles = client.post(
        "/notifications/admin/custom",
        headers=admin_headers,
        json={
            "title": "Teachers",
            "body": "Hello teachers",
            "target_type": "roles",
            "roles": ["teacher"],
        },
    )
    assert sent_roles.status_code == 200
    assert sent_roles.get_json()["sent_to"] >= 1

    group = client.post(
        "/notifications/admin/groups",
        headers=admin_headers,
        json={"name": "Group A", "user_ids": [student_id]},
    ).get_json()
    sent_group = client.post(
        "/notifications/admin/custom",
        headers=admin_headers,
        json={
            "title": "Group hello",
            "body": "Hi group",
            "target_type": "group",
            "group_id": group["_id"],
        },
    )
    assert sent_group.status_code == 200
    assert sent_group.get_json()["sent_to"] == 1

    classroom_id = None
    with client.application.app_context():
        classroom_id = mongo.db.classrooms.insert_one(
            {
                "name": "Class A",
                "teacher": ObjectId(teacher_id),
                "collection": ObjectId(),
                "students": [ObjectId(student_id)],
                "guests": [],
            }
        ).inserted_id

    sent_class = client.post(
        "/notifications/admin/custom",
        headers=admin_headers,
        json={
            "title": "Class hello",
            "body": "Hi class",
            "target_type": "classroom",
            "classroom_id": str(classroom_id),
        },
    )
    assert sent_class.status_code == 200
    assert sent_class.get_json()["sent_to"] == 1

    selected = client.post(
        "/notifications/teacher/custom",
        headers=teacher_headers,
        json={
            "classroom_id": str(classroom_id),
            "title": "Selected",
            "body": "Hi you",
            "student_ids": [student_id],
        },
    )
    assert selected.status_code == 200, selected.get_json()
    assert selected.get_json()["sent_to"] == 1

    other_teacher_headers, _ = _auth_user(
        client,
        f"other_teacher_{suffix}@example.com",
        roles=["user", "teacher"],
        name="Other",
    )
    forbidden = client.post(
        "/notifications/teacher/custom",
        headers=other_teacher_headers,
        json={
            "classroom_id": str(classroom_id),
            "title": "Nope",
            "body": "Nope",
        },
    )
    assert forbidden.status_code == 403

    admin_as_teacher = client.post(
        "/notifications/teacher/custom",
        headers=admin_headers,
        json={
            "classroom_id": str(classroom_id),
            "title": "Admin class",
            "body": "From admin",
        },
    )
    assert admin_as_teacher.status_code == 200
    assert admin_as_teacher.get_json()["sent_to"] == 1

    invalid_student = client.post(
        "/notifications/teacher/custom",
        headers=teacher_headers,
        json={
            "classroom_id": str(classroom_id),
            "title": "Bad",
            "body": "Bad",
            "student_ids": [admin_id],
        },
    )
    assert invalid_student.status_code == 400
