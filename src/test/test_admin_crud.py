"""Admin CRUD: badges, users, and user study content."""
import json
import uuid

from bson import ObjectId

from src.app import mongo
from src.app.models.user_model import UserModel
from src.app.models.user_progress_model import UserProgressModel


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


def test_admin_badge_update_and_delete(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_badge_{suffix}@example.com", roles=["user", "admin"]
    )
    _, user_id = _auth_user(client, f"earner_{suffix}@example.com")

    created = client.post(
        "/admin/badges",
        headers=admin_headers,
        json={"name": "Star", "description": "Nice"},
    )
    assert created.status_code == 201, created.get_json()
    badge_id = created.get_json()["_id"]

    patched = client.patch(
        f"/admin/badges/{badge_id}",
        headers=admin_headers,
        json={"name": "Super Star", "description": "Better"},
    )
    assert patched.status_code == 200
    assert patched.get_json()["name"] == "Super Star"

    awarded = client.post(
        f"/admin/users/{user_id}/badges",
        headers=admin_headers,
        json={"badge_id": badge_id},
    )
    assert awarded.status_code == 201

    deleted = client.delete(f"/admin/badges/{badge_id}", headers=admin_headers)
    assert deleted.status_code == 200
    listed = client.get("/admin/badges", headers=admin_headers)
    assert all(item["_id"] != badge_id for item in listed.get_json()["badges"])
    with client.application.app_context():
        assert mongo.db.user_badges.count_documents({"badge_id": str(badge_id)}) == 0


def test_admin_update_and_delete_user(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, admin_id = _auth_user(
        client, f"admin_user_{suffix}@example.com", roles=["user", "admin"], name="Admin"
    )
    _, user_id = _auth_user(client, f"target_user_{suffix}@example.com", name="Target")

    self_delete = client.delete(f"/admin/users/{admin_id}", headers=admin_headers)
    assert self_delete.status_code == 400

    patched = client.patch(
        f"/admin/users/{user_id}",
        headers=admin_headers,
        json={"name": "Renamed", "email": f"renamed_{suffix}@example.com"},
    )
    assert patched.status_code == 200, patched.get_json()
    assert patched.get_json()["name"] == "Renamed"
    assert patched.get_json()["email"] == f"renamed_{suffix}@example.com"

    deleted = client.delete(f"/admin/users/{user_id}", headers=admin_headers)
    assert deleted.status_code == 200
    listed = client.get("/admin/users", headers=admin_headers)
    assert all(item["_id"] != user_id for item in listed.get_json()["users"])


def test_admin_delete_personal_collection_removes_content(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_col_{suffix}@example.com", roles=["user", "admin"]
    )
    _, user_id = _auth_user(client, f"owner_{suffix}@example.com")

    created = client.post(
        "/collections/create",
        data=json.dumps({"name": "Pessoal", "user_id": user_id}),
        content_type="application/json",
    )
    assert created.status_code == 200, created.get_json()
    collection_id = created.get_json().get("collection_id")
    deck = client.post(
        "/deck/create",
        data=json.dumps({
            "name": "Deck pessoal",
            "collection_id": collection_id,
            "cards": [{"front": "Q", "back": "A"}],
        }),
        content_type="application/json",
    )
    assert deck.status_code == 200, deck.get_json()
    deck_id = deck.get_json()["deck_id"]

    with client.application.app_context():
        deck_doc = mongo.db.decks.find_one({"_id": ObjectId(deck_id)})
        card_id = str((deck_doc.get("cards") or [None])[0])
        UserProgressModel.create_or_update(user_id, deck_id, card_id)

    removed = client.delete(
        f"/admin/users/{user_id}/collections/{collection_id}",
        headers=admin_headers,
    )
    assert removed.status_code == 200, removed.get_json()
    assert removed.get_json()["mode"] == "content"
    with client.application.app_context():
        assert mongo.db.collections.find_one({"_id": ObjectId(collection_id)}) is None
        assert mongo.db.decks.find_one({"_id": ObjectId(deck_id)}) is None
        assert mongo.db.user_progress.count_documents({
            "$or": [{"user_id": ObjectId(user_id)}, {"user_id": user_id}],
        }) == 0


def test_admin_delete_classroom_collection_only_clears_progress(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_class_{suffix}@example.com", roles=["user", "admin"]
    )
    _, teacher_id = _auth_user(
        client,
        f"teacher_col_{suffix}@example.com",
        roles=["user", "teacher"],
        name="Teacher",
    )
    _, student_id = _auth_user(client, f"student_col_{suffix}@example.com")

    created = client.post(
        "/collections/create",
        data=json.dumps({"name": "Turma", "user_id": student_id}),
        content_type="application/json",
    )
    collection_id = created.get_json().get("collection_id")
    deck = client.post(
        "/deck/create",
        data=json.dumps({
            "name": "Deck turma",
            "collection_id": collection_id,
            "cards": [{"front": "Q2", "back": "A2"}],
        }),
        content_type="application/json",
    )
    deck_id = deck.get_json()["deck_id"]

    with client.application.app_context():
        classroom_id = mongo.db.classrooms.insert_one({
            "name": "Class progress",
            "teacher": ObjectId(teacher_id),
            "collection": ObjectId(collection_id),
            "students": [ObjectId(student_id)],
            "guests": [],
        }).inserted_id
        mongo.db.collections.update_one(
            {"_id": ObjectId(collection_id)},
            {"$set": {"classroom": classroom_id}},
        )
        deck_doc = mongo.db.decks.find_one({"_id": ObjectId(deck_id)})
        card_id = str((deck_doc.get("cards") or [None])[0])
        UserProgressModel.create_or_update(student_id, deck_id, card_id)

    removed = client.delete(
        f"/admin/users/{student_id}/collections/{collection_id}",
        headers=admin_headers,
    )
    assert removed.status_code == 200, removed.get_json()
    assert removed.get_json()["mode"] == "progress"
    with client.application.app_context():
        assert mongo.db.collections.find_one({"_id": ObjectId(collection_id)}) is not None
        assert mongo.db.decks.find_one({"_id": ObjectId(deck_id)}) is not None
        assert mongo.db.user_progress.count_documents({
            "$or": [{"user_id": ObjectId(student_id)}, {"user_id": student_id}],
        }) == 0
        user = mongo.db.users.find_one({"_id": ObjectId(student_id)})
        owned = {str(item) for item in (user.get("collections") or [])}
        assert collection_id not in owned
