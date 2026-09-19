"""Tutorial onboarding: admin CMS, versioning, progress and analytics."""
import uuid

from src.app import mongo
from src.app.models.user_model import UserModel


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


def _step(order, title="Hello"):
    return {
        "id": f"step-{order}",
        "order": order,
        "title": {"en": title, "pt_br": title},
        "body": {"en": "Body", "pt_br": "Corpo"},
        "tip": {"en": "Tip"},
        "icon": "school",
        "brain_expression": "happy",
        "target_key": "menu" if order == 2 else "",
        "tooltip_placement": "bottom",
    }


def test_admin_tutorial_crud_publish_and_progress(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_tut_{suffix}@example.com", roles=["user", "admin"]
    )
    user_headers, user_id = _auth_user(client, f"learner_{suffix}@example.com")

    created = client.post(
        "/admin/tutorials",
        headers=admin_headers,
        json={
            "key": f"onboarding-{suffix}",
            "name": "Welcome tour",
            "description": "Quick tour",
            "audience": {"type": "specific_users", "user_ids": [user_id]},
            "steps": [_step(1, "Welcome"), _step(2, "Menu")],
        },
    )
    assert created.status_code == 201, created.get_json()
    tutorial = created.get_json()
    tutorial_id = tutorial["_id"]
    assert tutorial["status"] == "draft"
    assert tutorial["version"] == 1

    patched = client.patch(
        f"/admin/tutorials/{tutorial_id}",
        headers=admin_headers,
        json={"description": "Updated description"},
    )
    assert patched.status_code == 200
    assert patched.get_json()["description"]["en"] == "Updated description"

    published = client.post(
        f"/admin/tutorials/{tutorial_id}/publish", headers=admin_headers
    )
    assert published.status_code == 200
    assert published.get_json()["status"] == "active"

    me = client.get("/tutorials/me", headers=user_headers)
    assert me.status_code == 200
    payload = me.get_json()["tutorial"]
    assert payload["_id"] == tutorial_id
    assert payload["name"] == "Welcome tour"
    assert len(payload["steps"]) == 2

    viewed = client.post(
        f"/tutorials/{tutorial_id}/events",
        headers=user_headers,
        json={"type": "view", "step_index": 0},
    )
    assert viewed.status_code == 200

    skipped = client.post(
        f"/tutorials/{tutorial_id}/skip",
        headers=user_headers,
        json={"step_index": 0, "duration_ms": 1200},
    )
    assert skipped.status_code == 200
    assert skipped.get_json()["progress"]["skipped"] is True

    me_after = client.get("/tutorials/me", headers=user_headers)
    assert me_after.get_json()["tutorial"] is None

    duplicated = client.post(
        f"/admin/tutorials/{tutorial_id}/duplicate",
        headers=admin_headers,
        json={"new_version": True},
    )
    assert duplicated.status_code == 201
    v2 = duplicated.get_json()
    assert v2["version"] == 2
    assert v2["status"] == "draft"

    published_v2 = client.post(
        f"/admin/tutorials/{v2['_id']}/publish", headers=admin_headers
    )
    assert published_v2.status_code == 200
    assert published_v2.get_json()["status"] == "active"

    old = client.get(f"/admin/tutorials/{tutorial_id}", headers=admin_headers)
    assert old.get_json()["status"] == "archived"

    me_v2 = client.get("/tutorials/me", headers=user_headers)
    assert me_v2.status_code == 200
    assert me_v2.get_json()["tutorial"]["_id"] == v2["_id"]

    completed = client.post(
        f"/tutorials/{v2['_id']}/complete",
        headers=user_headers,
        json={"duration_ms": 4000},
    )
    assert completed.status_code == 200
    assert completed.get_json()["progress"]["completed"] is True
    assert client.get("/tutorials/me", headers=user_headers).get_json()["tutorial"] is None

    replayed = client.post(f"/tutorials/{v2['_id']}/replay", headers=user_headers)
    assert replayed.status_code == 200
    assert replayed.get_json()["tutorial"]["_id"] == v2["_id"]

    analytics = client.get(
        f"/admin/tutorials/{v2['_id']}/analytics", headers=admin_headers
    )
    assert analytics.status_code == 200
    stats = analytics.get_json()
    assert stats["users_impacted"] >= 1
    assert "completion_rate" in stats
    assert "step_dropoff" in stats

    listed = client.get("/admin/tutorials", headers=admin_headers)
    assert listed.status_code == 200
    keys = [item["_id"] for item in listed.get_json()["tutorials"]]
    assert v2["_id"] in keys

    history = client.get("/tutorials/me/history", headers=user_headers)
    assert history.status_code == 200
    assert len(history.get_json()["history"]) >= 1

    profile = client.get(f"/admin/users/{user_id}/profile", headers=admin_headers)
    assert profile.status_code == 200
    assert "tutorials" in profile.get_json()
    assert profile.get_json()["tutorials"]["history"]


def test_tutorial_audience_specific_users(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_aud_{suffix}@example.com", roles=["user", "admin"]
    )
    included_headers, included_id = _auth_user(client, f"in_{suffix}@example.com")
    other_headers, _ = _auth_user(client, f"out_{suffix}@example.com")

    created = client.post(
        "/admin/tutorials",
        headers=admin_headers,
        json={
            "key": f"vip-{suffix}",
            "name": "VIP",
            "audience": {"type": "specific_users", "user_ids": [included_id]},
            "steps": [_step(1, "Only you")],
        },
    )
    tutorial_id = created.get_json()["_id"]
    client.post(f"/admin/tutorials/{tutorial_id}/publish", headers=admin_headers)

    mine = client.get("/tutorials/me", headers=included_headers)
    assert mine.get_json()["tutorial"]["_id"] == tutorial_id
    other = client.get("/tutorials/me", headers=other_headers)
    assert other.get_json()["tutorial"] is None


def test_admin_can_deactivate_tutorial(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_off_{suffix}@example.com", roles=["user", "admin"]
    )
    user_headers, user_id = _auth_user(client, f"learner_off_{suffix}@example.com")

    created = client.post(
        "/admin/tutorials",
        headers=admin_headers,
        json={
            "key": f"off-{suffix}",
            "name": "Turn off",
            "audience": {"type": "specific_users", "user_ids": [user_id]},
            "steps": [_step(1, "Hello")],
        },
    )
    tutorial_id = created.get_json()["_id"]
    client.post(f"/admin/tutorials/{tutorial_id}/publish", headers=admin_headers)
    assert client.get("/tutorials/me", headers=user_headers).get_json()["tutorial"]["_id"] == tutorial_id

    deactivated = client.post(
        f"/admin/tutorials/{tutorial_id}/deactivate", headers=admin_headers
    )
    assert deactivated.status_code == 200
    assert deactivated.get_json()["status"] == "inactive"
    assert client.get("/tutorials/me", headers=user_headers).get_json()["tutorial"] is None


def test_brain_avatar_admin_crud(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_brain_{suffix}@example.com", roles=["user", "admin"]
    )
    listed = client.get("/admin/tutorials/brain-avatars", headers=admin_headers)
    assert listed.status_code == 200
    created = client.post(
        "/admin/tutorials/brain-avatars",
        headers=admin_headers,
        json={"key": f"custom_{suffix}", "name": "Custom Brain", "events": ["tutorial"]},
    )
    assert created.status_code == 201, created.get_json()
    avatar_id = created.get_json()["_id"]
    patched = client.patch(
        f"/admin/tutorials/brain-avatars/{avatar_id}",
        headers=admin_headers,
        json={"name": "Updated Brain", "is_active": True},
    )
    assert patched.status_code == 200
    assert patched.get_json()["name"] == "Updated Brain"


def test_admin_can_save_step_highlight_rect(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_rect_{suffix}@example.com", roles=["user", "admin"]
    )
    created = client.post(
        "/admin/tutorials",
        headers=admin_headers,
        json={
            "key": f"highlight-{suffix}",
            "name": "Highlight tour",
            "steps": [
                {
                    **_step(1, "Menu"),
                    "target_key": "menu",
                    "highlight_rect": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.25},
                }
            ],
        },
    )
    assert created.status_code == 201, created.get_json()
    step = created.get_json()["steps"][0]
    assert step["target_key"] == "menu"
    assert step["highlight_rect"]["x"] == 0.1
    assert step["highlight_rect"]["width"] == 0.3


def test_admin_can_save_section_and_tap_step(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(
        client, f"admin_sec_{suffix}@example.com", roles=["user", "admin"]
    )
    user_headers, user_id = _auth_user(client, f"learner_sec_{suffix}@example.com")

    created = client.post(
        "/admin/tutorials",
        headers=admin_headers,
        json={
            "key": f"books-{suffix}",
            "name": "Books tour",
            "section": "books",
            "audience": {"type": "specific_users", "user_ids": [user_id]},
            "steps": [
                {
                    **_step(1, "Open books"),
                    "target_key": "books_list",
                    "interaction": "tap",
                    "tap_label": {
                        "en": "Tap here to open decks, classrooms, books,...",
                        "pt_br": "Toque aqui para abrir decks, salas, livros,...",
                    },
                }
            ],
        },
    )
    assert created.status_code == 201, created.get_json()
    tutorial = created.get_json()
    tutorial_id = tutorial["_id"]
    assert tutorial["section"] == "books"
    step = tutorial["steps"][0]
    assert step["target_key"] == "books_list"
    assert step["interaction"] == "tap"
    assert "Tap here" in (step.get("tap_label") or {}).get("en", "")

    client.post(f"/admin/tutorials/{tutorial_id}/publish", headers=admin_headers)

    books = client.get("/tutorials/me?section=books", headers=user_headers)
    assert books.status_code == 200
    assert books.get_json()["tutorial"]["_id"] == tutorial_id
    assert books.get_json()["tutorial"]["section"] == "books"
    assert books.get_json()["tutorial"]["steps"][0]["interaction"] == "tap"
    assert "Tap here" in (books.get_json()["tutorial"]["steps"][0].get("tap_label") or "")

    home = client.get("/tutorials/me?section=home", headers=user_headers)
    assert home.get_json()["tutorial"] is None

    default_home = client.get("/tutorials/me", headers=user_headers)
    assert default_home.get_json()["tutorial"] is None
