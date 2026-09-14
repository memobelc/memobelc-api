"""Testes das rotas de curso, atividades e questões."""
import json
import uuid

from src.app import mongo
from src.app.models.user_model import UserModel
from bson import ObjectId


def _auth_user(client, email, password="password123", name="User", teacher=False):
    client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
        content_type="application/json",
    )
    mongo.db.users.update_one(
        {"email": email},
        {
            "$set": {
                "is_confirmed": True,
                "roles": ["user", "teacher"] if teacher else ["user"],
                "role": "teacher" if teacher else "user",
            }
        },
    )
    if teacher:
        user = mongo.db.users.find_one({"email": email})
        UserModel.update_roles(str(user["_id"]), ["user", "teacher"])
    login = client.post(
        "/auth/login",
        json={"email": email, "password": password},
        content_type="application/json",
    )
    data = login.get_json() or {}
    token = data.get("token") or (data.get("pending") or [None, None])[1]
    user_id = data.get("user_id")
    if not user_id:
        user = mongo.db.users.find_one({"email": email})
        user_id = str(user["_id"]) if user else None
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, user_id


def _setup_course(client):
    suffix = uuid.uuid4().hex[:8]
    teacher_headers, teacher_id = _auth_user(
        client, f"teacher_{suffix}@example.com", name="Teacher", teacher=True
    )
    student_headers, student_id = _auth_user(
        client, f"student_{suffix}@example.com", name="Student", teacher=False
    )

    coll = client.post(
        "/collections/create",
        data=json.dumps({"name": f"Coll {suffix}", "user_id": teacher_id}),
        content_type="application/json",
    )
    collection_id = (coll.get_json() or {}).get("collection_id")
    classroom = client.post(
        "/classroom/create",
        data=json.dumps({"collection_id": collection_id}),
        headers=teacher_headers,
    )
    classroom_id = (classroom.get_json() or {}).get("class_id")
    client.post(
        "/classroom/add_user_in_classroom",
        data=json.dumps({
            "classroom_id": classroom_id,
            "email_user": f"student_{suffix}@example.com",
        }),
        headers=teacher_headers,
    )
    course = client.post(
        "/course/create",
        data=json.dumps({
            "name": f"Course {suffix}",
            "description": "desc",
            "classroom_id": classroom_id,
        }),
        headers=teacher_headers,
    )
    course_id = (course.get_json() or {}).get("course_id")
    module = client.post(
        "/course/module/create",
        data=json.dumps({"name": "Module 1", "course_id": course_id}),
        headers=teacher_headers,
    )
    module_id = (module.get_json() or {}).get("module_id")
    assert classroom_id, "classroom should be created"
    assert course_id, "course should be created"
    assert module_id, "module should be created"
    return {
        "teacher_headers": teacher_headers,
        "student_headers": student_headers,
        "teacher_id": teacher_id,
        "student_id": student_id,
        "course_id": course_id,
        "module_id": module_id,
        "classroom_id": classroom_id,
        "collection_id": collection_id,
    }


def test_course_create_requires_auth(client):
    response = client.post(
        "/course/create",
        data=json.dumps({"name": "X", "classroom_id": "507f1f77bcf86cd799439011"}),
        content_type="application/json",
    )
    assert response.status_code == 401


def test_activity_feedback_mode_and_questions(client):
    ctx = _setup_course(client)

    created = client.post(
        "/course/activity/create",
        data=json.dumps({
            "title": "Quiz 1",
            "description": "desc",
            "module_id": ctx["module_id"],
            "course_id": ctx["course_id"],
            "feedback_mode": "immediate",
        }),
        headers=ctx["teacher_headers"],
    )
    assert created.status_code == 201
    activity_id = created.get_json()["activity_id"]

    detail = client.get(
        f"/course/activity/{activity_id}",
        headers=ctx["teacher_headers"],
    )
    assert detail.status_code == 200
    assert detail.get_json().get("feedback_mode") == "immediate"

    bad = client.post(
        "/course/question/create",
        data=json.dumps({
            "text": "Q?",
            "type": "multiple_choice",
            "activity_id": activity_id,
            "options": ["A"],
            "correct_answer": "A",
        }),
        headers=ctx["teacher_headers"],
    )
    assert bad.status_code == 400

    ok = client.post(
        "/course/question/create",
        data=json.dumps({
            "text": "Capital?",
            "type": "multiple_choice",
            "activity_id": activity_id,
            "options": ["SP", "RJ"],
            "correct_answer": "RJ",
            "points": 2,
        }),
        headers=ctx["teacher_headers"],
    )
    assert ok.status_code == 201
    q1 = ok.get_json()["question_id"]

    blank_bad = client.post(
        "/course/question/create",
        data=json.dumps({
            "text": "Sem lacuna",
            "type": "fill_in_blank",
            "activity_id": activity_id,
            "correct_answer": ["x"],
        }),
        headers=ctx["teacher_headers"],
    )
    assert blank_bad.status_code == 400

    blank_ok = client.post(
        "/course/question/create",
        data=json.dumps({
            "text": "A capital do ___ é ___.",
            "type": "fill_in_blank",
            "activity_id": activity_id,
            "correct_answer": ["Brasil", "Brasilia"],
            "points": 2,
        }),
        headers=ctx["teacher_headers"],
    )
    assert blank_ok.status_code == 201
    q2 = blank_ok.get_json()["question_id"]

    student_view = client.get(
        f"/course/activity/{activity_id}",
        headers=ctx["student_headers"],
    )
    assert student_view.status_code == 200
    questions = student_view.get_json().get("questions") or []
    assert questions
    assert all("correct_answer" not in q for q in questions)

    reorder = client.put(
        f"/course/activity/{activity_id}/questions/reorder",
        data=json.dumps({"question_ids": [q2, q1]}),
        headers=ctx["teacher_headers"],
    )
    assert reorder.status_code == 200
    teacher_view = client.get(
        f"/course/activity/{activity_id}",
        headers=ctx["teacher_headers"],
    )
    ids = [q["_id"] for q in teacher_view.get_json()["questions"]]
    assert ids[:2] == [q2, q1]


def test_after_correction_hides_score_until_approved(client):
    ctx = _setup_course(client)

    created = client.post(
        "/course/activity/create",
        data=json.dumps({
            "title": "Homework",
            "module_id": ctx["module_id"],
            "course_id": ctx["course_id"],
            "feedback_mode": "after_correction",
        }),
        headers=ctx["teacher_headers"],
    )
    activity_id = created.get_json()["activity_id"]
    q = client.post(
        "/course/question/create",
        data=json.dumps({
            "text": "2+2",
            "type": "short_answer",
            "activity_id": activity_id,
            "correct_answer": "4",
            "points": 1,
        }),
        headers=ctx["teacher_headers"],
    )
    question_id = q.get_json()["question_id"]

    submit = client.post(
        f"/course/activity/{activity_id}/submit",
        data=json.dumps({
            "answers": [{"question_id": question_id, "answer": "4"}],
        }),
        headers=ctx["student_headers"],
    )
    assert submit.status_code == 200
    body = submit.get_json()
    assert body.get("feedback_pending") is True
    assert body.get("score") is None

    mine = client.get(
        f"/course/activity/{activity_id}/my_answer",
        headers=ctx["student_headers"],
    )
    assert mine.get_json()["answer"]["score"] is None

    client.post(
        f"/course/activity/{activity_id}/answer/{ctx['student_id']}/approve",
        data=json.dumps({"approved": True}),
        headers=ctx["teacher_headers"],
    )
    mine2 = client.get(
        f"/course/activity/{activity_id}/my_answer",
        headers=ctx["student_headers"],
    )
    assert mine2.get_json()["answer"]["score"] == 100


def test_ranking_orders_by_xp(client):
    ctx = _setup_course(client)

    created = client.post(
        "/course/activity/create",
        data=json.dumps({
            "title": "Quiz XP",
            "module_id": ctx["module_id"],
            "course_id": ctx["course_id"],
            "feedback_mode": "immediate",
        }),
        headers=ctx["teacher_headers"],
    )
    activity_id = created.get_json()["activity_id"]
    q = client.post(
        "/course/question/create",
        data=json.dumps({
            "text": "Ok?",
            "type": "short_answer",
            "activity_id": activity_id,
            "correct_answer": "sim",
            "points": 5,
        }),
        headers=ctx["teacher_headers"],
    )
    question_id = q.get_json()["question_id"]
    client.post(
        f"/course/activity/{activity_id}/submit",
        data=json.dumps({
            "answers": [{"question_id": question_id, "answer": "sim"}],
        }),
        headers=ctx["student_headers"],
    )

    ranking = client.get(
        f"/course/{ctx['course_id']}/ranking",
        headers=ctx["student_headers"],
    )
    assert ranking.status_code == 200
    data = ranking.get_json()
    assert data["ranking"]
    top = data["ranking"][0]
    assert top["_id"] == ctx["student_id"]
    assert top["xp"] == 5
    assert "first_step" in top["badges"]
    assert "perfect" in top["badges"]


def _create_lesson(client, ctx, title="Lesson 1"):
    created = client.post(
        "/course/lesson/create",
        data=json.dumps({
            "title": title,
            "module_id": ctx["module_id"],
            "course_id": ctx["course_id"],
            "video_url": "https://youtu.be/abcdefghijk",
        }),
        headers=ctx["teacher_headers"],
    )
    assert created.status_code == 201
    return created.get_json()["lesson_id"]


def test_student_can_rate_lesson_and_update(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)

    bad = client.put(
        f"/course/lesson/{lesson_id}/rating",
        data=json.dumps({"stars": 0}),
        headers=ctx["student_headers"],
    )
    assert bad.status_code == 400

    first = client.put(
        f"/course/lesson/{lesson_id}/rating",
        data=json.dumps({"stars": 4}),
        headers=ctx["student_headers"],
    )
    assert first.status_code == 200
    assert first.get_json()["stars"] == 4

    updated = client.put(
        f"/course/lesson/{lesson_id}/rating",
        data=json.dumps({"stars": 2}),
        headers=ctx["student_headers"],
    )
    assert updated.status_code == 200
    assert updated.get_json()["stars"] == 2

    lesson = client.get(
        f"/course/lesson/{lesson_id}",
        headers=ctx["student_headers"],
    )
    assert lesson.status_code == 200
    assert lesson.get_json()["my_rating"] == 2


def test_unrated_viewed_lesson_counts_as_five(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)

    client.post(
        f"/course/lesson/{lesson_id}/viewed",
        data=json.dumps({}),
        headers=ctx["student_headers"],
    )

    forbidden = client.get(
        f"/course/{ctx['course_id']}/ratings",
        headers=ctx["student_headers"],
    )
    assert forbidden.status_code == 403

    ratings = client.get(
        f"/course/{ctx['course_id']}/ratings",
        headers=ctx["teacher_headers"],
    )
    assert ratings.status_code == 200
    data = ratings.get_json()
    lesson = data["modules"][0]["lessons"][0]
    assert lesson["avg"] == 5
    assert lesson["explicit_count"] == 0
    assert lesson["implicit_count"] == 1


def test_module_rating_has_weight_three(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)

    client.post(
        f"/course/lesson/{lesson_id}/viewed",
        data=json.dumps({}),
        headers=ctx["student_headers"],
    )
    client.put(
        f"/course/lesson/{lesson_id}/rating",
        data=json.dumps({"stars": 1}),
        headers=ctx["student_headers"],
    )
    client.put(
        f"/course/module/{ctx['module_id']}/rating",
        data=json.dumps({"stars": 5}),
        headers=ctx["student_headers"],
    )

    ratings = client.get(
        f"/course/{ctx['course_id']}/ratings",
        headers=ctx["teacher_headers"],
    )
    data = ratings.get_json()
    assert data["course"]["weight_module"] == 3
    assert data["course"]["avg"] == 4.0
    assert data["modules"][0]["avg"] == 5
    assert data["modules"][0]["lessons"][0]["avg"] == 1


def test_module_rating_prompt_and_dismiss(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)

    before = client.get(
        f"/course/{ctx['course_id']}",
        headers=ctx["student_headers"],
    )
    assert before.status_code == 200
    module = before.get_json()["modules"][0]
    assert module["rating_prompt"] is False
    assert module["can_rate"] is False
    assert module["my_rating"] is None

    client.post(
        f"/course/lesson/{lesson_id}/viewed",
        data=json.dumps({}),
        headers=ctx["student_headers"],
    )
    ready = client.get(
        f"/course/{ctx['course_id']}",
        headers=ctx["student_headers"],
    )
    module = ready.get_json()["modules"][0]
    assert module["can_rate"] is True
    assert module["rating_prompt"] is True

    dismissed = client.post(
        f"/course/module/{ctx['module_id']}/rating/dismiss",
        data=json.dumps({}),
        headers=ctx["student_headers"],
    )
    assert dismissed.status_code == 200
    after_dismiss = client.get(
        f"/course/{ctx['course_id']}",
        headers=ctx["student_headers"],
    )
    module = after_dismiss.get_json()["modules"][0]
    assert module["rating_prompt"] is False
    assert module["can_rate"] is True
    assert module["my_rating"] is None

    rated = client.put(
        f"/course/module/{ctx['module_id']}/rating",
        data=json.dumps({"stars": 3}),
        headers=ctx["student_headers"],
    )
    assert rated.status_code == 200
    after_rate = client.get(
        f"/course/{ctx['course_id']}",
        headers=ctx["student_headers"],
    )
    module = after_rate.get_json()["modules"][0]
    assert module["my_rating"] == 3
    assert module["rating_prompt"] is False


def test_teacher_cannot_rate_own_course(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)
    response = client.put(
        f"/course/lesson/{lesson_id}/rating",
        data=json.dumps({"stars": 5}),
        headers=ctx["teacher_headers"],
    )
    assert response.status_code == 403


def _create_classroom_deck(client, ctx, name="Vocab", status="published", cards=None):
    payload = {
        "name": name,
        "collection_id": ctx["collection_id"],
        "status": status,
    }
    if cards is not None:
        payload["cards"] = cards
    created = client.post(
        "/deck/create",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert created.status_code == 200
    return created.get_json()["deck_id"]


def test_lesson_deck_link_create_and_unlock(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)

    created = client.post(
        f"/course/lesson/{lesson_id}/decks",
        data=json.dumps({
            "name": "Lesson deck",
            "status": "published",
            "cards": [{"front": "hi", "back": "oi"}],
        }),
        headers=ctx["teacher_headers"],
    )
    assert created.status_code == 201
    deck_id = created.get_json()["deck_id"]

    student_collections = client.get(
        "/collections/get_by_user",
        headers=ctx["student_headers"],
    )
    assert student_collections.status_code == 200
    decks = []
    for collection in student_collections.get_json().get("collections") or []:
        decks.extend(collection.get("decks") or [])
    assert all(str(deck.get("_id")) != str(deck_id) for deck in decks)

    blocked = client.post(
        f"/course/lesson/{lesson_id}/decks/{deck_id}/unlock",
        headers=ctx["student_headers"],
    )
    assert blocked.status_code == 403

    viewed = client.post(
        f"/course/lesson/{lesson_id}/viewed",
        headers=ctx["student_headers"],
    )
    assert viewed.status_code == 200

    unlocked = client.post(
        f"/course/lesson/{lesson_id}/decks/{deck_id}/unlock",
        headers=ctx["student_headers"],
    )
    assert unlocked.status_code == 200
    assert unlocked.get_json().get("unlocked") is True

    after = client.get(
        "/collections/get_by_user",
        headers=ctx["student_headers"],
    )
    visible_ids = []
    for collection in after.get_json().get("collections") or []:
        visible_ids.extend(str(deck.get("_id")) for deck in (collection.get("decks") or []))
    assert str(deck_id) in visible_ids

    progress = list(mongo.db.user_progress.find({
        "user_id": ObjectId(ctx["student_id"]),
        "deck_id": ObjectId(deck_id),
    }))
    assert len(progress) >= 1


def test_unlinked_draft_hidden_and_published_visible(client):
    ctx = _setup_course(client)
    draft_id = _create_classroom_deck(client, ctx, name="Draft deck", status="draft")
    live_id = _create_classroom_deck(client, ctx, name="Live deck", status="published")

    student_collections = client.get(
        "/collections/get_by_user",
        headers=ctx["student_headers"],
    )
    visible_ids = []
    for collection in student_collections.get_json().get("collections") or []:
        visible_ids.extend(str(deck.get("_id")) for deck in (collection.get("decks") or []))
    assert str(draft_id) not in visible_ids
    assert str(live_id) in visible_ids

    teacher_collections = client.get(
        "/collections/get_by_user",
        headers=ctx["teacher_headers"],
    )
    teacher_ids = []
    for collection in teacher_collections.get_json().get("collections") or []:
        teacher_ids.extend(str(deck.get("_id")) for deck in (collection.get("decks") or []))
    assert str(draft_id) in teacher_ids


def test_unlink_returns_deck_to_content(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)
    deck_id = _create_classroom_deck(client, ctx, name="Shared", status="published")

    linked = client.post(
        f"/course/lesson/{lesson_id}/decks",
        data=json.dumps({"deck_id": deck_id}),
        headers=ctx["teacher_headers"],
    )
    assert linked.status_code == 201

    hidden = client.get("/collections/get_by_user", headers=ctx["student_headers"])
    hidden_ids = []
    for collection in hidden.get_json().get("collections") or []:
        hidden_ids.extend(str(deck.get("_id")) for deck in (collection.get("decks") or []))
    assert str(deck_id) not in hidden_ids

    unlinked = client.delete(
        f"/course/lesson/{lesson_id}/decks/{deck_id}",
        headers=ctx["teacher_headers"],
    )
    assert unlinked.status_code == 200

    visible = client.get("/collections/get_by_user", headers=ctx["student_headers"])
    visible_ids = []
    for collection in visible.get_json().get("collections") or []:
        visible_ids.extend(str(deck.get("_id")) for deck in (collection.get("decks") or []))
    assert str(deck_id) in visible_ids


def test_lesson_deck_card_subset_and_card_status(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)
    deck_id = _create_classroom_deck(
        client,
        ctx,
        name="Subset",
        status="published",
        cards=[{"front": "a", "back": "1"}, {"front": "b", "back": "2"}],
    )
    cards = client.get(f"/card/get_cards_by_deck/{deck_id}").get_json()["cards"]
    first_id = cards[0]["_id"]
    second_id = cards[1]["_id"]

    client.put(
        f"/card/{second_id}",
        data=json.dumps({
            "front": "b",
            "back": "2",
            "status": "draft",
        }),
        content_type="application/json",
    )

    linked = client.post(
        f"/course/lesson/{lesson_id}/decks",
        data=json.dumps({"deck_id": deck_id, "card_ids": [first_id]}),
        headers=ctx["teacher_headers"],
    )
    assert linked.status_code == 201
    assert linked.get_json()["whole_deck"] is False

    client.post(f"/course/lesson/{lesson_id}/viewed", headers=ctx["student_headers"])
    client.post(
        f"/course/lesson/{lesson_id}/decks/{deck_id}/unlock",
        headers=ctx["student_headers"],
    )
    student_cards = client.get(
        f"/card/get_cards_by_deck/{deck_id}",
        query_string={"user_id": ctx["student_id"]},
        headers=ctx["student_headers"],
    ).get_json()["cards"]
    student_card_ids = {card["_id"] for card in student_cards}
    assert first_id in student_card_ids
    assert second_id not in student_card_ids


def test_enrollment_skips_progress_for_lesson_linked_deck(client):
    suffix = uuid.uuid4().hex[:8]
    teacher_headers, teacher_id = _auth_user(
        client, f"teacher2_{suffix}@example.com", name="Teacher", teacher=True
    )
    student_headers, student_id = _auth_user(
        client, f"student2_{suffix}@example.com", name="Student", teacher=False
    )
    coll = client.post(
        "/collections/create",
        data=json.dumps({"name": f"Coll {suffix}", "user_id": teacher_id}),
        content_type="application/json",
    )
    collection_id = (coll.get_json() or {}).get("collection_id")
    classroom = client.post(
        "/classroom/create",
        data=json.dumps({"collection_id": collection_id}),
        headers=teacher_headers,
    )
    classroom_id = (classroom.get_json() or {}).get("class_id")
    course = client.post(
        "/course/create",
        data=json.dumps({
            "name": f"Course {suffix}",
            "classroom_id": classroom_id,
        }),
        headers=teacher_headers,
    )
    course_id = (course.get_json() or {}).get("course_id")
    module = client.post(
        "/course/module/create",
        data=json.dumps({"name": "Module 1", "course_id": course_id}),
        headers=teacher_headers,
    )
    module_id = (module.get_json() or {}).get("module_id")
    lesson = client.post(
        "/course/lesson/create",
        data=json.dumps({
            "title": "Lesson",
            "module_id": module_id,
            "course_id": course_id,
        }),
        headers=teacher_headers,
    )
    lesson_id = lesson.get_json()["lesson_id"]
    created = client.post(
        f"/course/lesson/{lesson_id}/decks",
        data=json.dumps({
            "name": "Gated",
            "cards": [{"front": "x", "back": "y"}],
        }),
        headers=teacher_headers,
    )
    deck_id = created.get_json()["deck_id"]
    client.post(
        "/classroom/add_user_in_classroom",
        data=json.dumps({
            "classroom_id": classroom_id,
            "email_user": f"student2_{suffix}@example.com",
        }),
        headers=teacher_headers,
    )
    progress = list(mongo.db.user_progress.find({
        "user_id": ObjectId(student_id),
        "deck_id": ObjectId(deck_id),
    }))
    assert progress == []


def _create_second_classroom(client, teacher_headers, teacher_id, suffix):
    coll = client.post(
        "/collections/create",
        data=json.dumps({"name": f"Coll2 {suffix}", "user_id": teacher_id}),
        content_type="application/json",
    )
    collection_id = (coll.get_json() or {}).get("collection_id")
    classroom = client.post(
        "/classroom/create",
        data=json.dumps({"collection_id": collection_id}),
        headers=teacher_headers,
    )
    classroom_id = (classroom.get_json() or {}).get("class_id")
    course = client.post(
        "/course/create",
        data=json.dumps({
            "name": f"Target Course {suffix}",
            "classroom_id": classroom_id,
        }),
        headers=teacher_headers,
    )
    course_id = (course.get_json() or {}).get("course_id")
    module = client.post(
        "/course/module/create",
        data=json.dumps({"name": "Target Module", "course_id": course_id}),
        headers=teacher_headers,
    )
    module_id = (module.get_json() or {}).get("module_id")
    return {
        "classroom_id": classroom_id,
        "course_id": course_id,
        "module_id": module_id,
        "collection_id": collection_id,
    }


def test_reorder_courses(client):
    ctx = _setup_course(client)
    second = client.post(
        "/course/create",
        data=json.dumps({
            "name": "Course B",
            "classroom_id": ctx["classroom_id"],
        }),
        headers=ctx["teacher_headers"],
    )
    course_b_id = second.get_json()["course_id"]

    listed = client.get(
        f"/course/by_classroom/{ctx['classroom_id']}",
        headers=ctx["teacher_headers"],
    )
    assert listed.status_code == 200
    course_ids = [c["_id"] for c in listed.get_json()["courses"]]
    assert course_ids == [ctx["course_id"], course_b_id]

    reordered = client.put(
        f"/course/by_classroom/{ctx['classroom_id']}/reorder",
        data=json.dumps({"course_ids": [course_b_id, ctx["course_id"]]}),
        headers=ctx["teacher_headers"],
    )
    assert reordered.status_code == 200

    after = client.get(
        f"/course/by_classroom/{ctx['classroom_id']}",
        headers=ctx["teacher_headers"],
    )
    after_ids = [c["_id"] for c in after.get_json()["courses"]]
    assert after_ids == [course_b_id, ctx["course_id"]]


def test_duplicate_lesson_without_decks(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx, title="Original Lesson")
    target = _create_second_classroom(
        client, ctx["teacher_headers"], ctx["teacher_id"], uuid.uuid4().hex[:8]
    )

    dup = client.post(
        f"/course/lesson/{lesson_id}/duplicate",
        data=json.dumps({
            "target_module_id": target["module_id"],
            "target_course_id": target["course_id"],
            "include_decks": False,
            "title": "Copied Lesson",
        }),
        headers=ctx["teacher_headers"],
    )
    assert dup.status_code == 201
    new_lesson_id = dup.get_json()["id"]

    detail = client.get(
        f"/course/{target['course_id']}",
        headers=ctx["teacher_headers"],
    )
    assert detail.status_code == 200
    modules = detail.get_json().get("modules") or []
    lessons = modules[0].get("lessons") or []
    assert any(l["_id"] == new_lesson_id and l["title"] == "Copied Lesson" for l in lessons)
    assert all(not (l.get("decks") or []) for l in lessons)


def test_duplicate_lesson_with_deck(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx, title="Deck Lesson")
    deck_id = _create_classroom_deck(
        client,
        ctx,
        name="Vocab Deck",
        status="published",
        cards=[{"front": "hello", "back": "oi"}],
    )
    linked = client.post(
        f"/course/lesson/{lesson_id}/decks",
        data=json.dumps({"deck_id": deck_id}),
        headers=ctx["teacher_headers"],
    )
    assert linked.status_code == 201

    target = _create_second_classroom(
        client, ctx["teacher_headers"], ctx["teacher_id"], uuid.uuid4().hex[:8]
    )

    dup = client.post(
        f"/course/lesson/{lesson_id}/duplicate",
        data=json.dumps({
            "target_module_id": target["module_id"],
            "target_course_id": target["course_id"],
            "include_decks": True,
        }),
        headers=ctx["teacher_headers"],
    )
    assert dup.status_code == 201
    new_lesson_id = dup.get_json()["id"]

    detail = client.get(
        f"/course/{target['course_id']}",
        headers=ctx["teacher_headers"],
    )
    modules = detail.get_json().get("modules") or []
    copied = next(l for l in modules[0]["lessons"] if l["_id"] == new_lesson_id)
    assert copied.get("decks")
    new_deck_id = copied["decks"][0]["deck_id"]
    assert str(new_deck_id) != str(deck_id)


def test_duplicate_module_includes_activity_and_questions(client):
    ctx = _setup_course(client)
    activity = client.post(
        "/course/activity/create",
        data=json.dumps({
            "title": "Quiz",
            "module_id": ctx["module_id"],
            "course_id": ctx["course_id"],
            "feedback_mode": "immediate",
        }),
        headers=ctx["teacher_headers"],
    )
    activity_id = activity.get_json()["activity_id"]
    client.post(
        "/course/question/create",
        data=json.dumps({
            "text": "2+2?",
            "type": "multiple_choice",
            "activity_id": activity_id,
            "options": ["3", "4"],
            "correct_answer": "4",
        }),
        headers=ctx["teacher_headers"],
    )

    target = _create_second_classroom(
        client, ctx["teacher_headers"], ctx["teacher_id"], uuid.uuid4().hex[:8]
    )

    dup = client.post(
        f"/course/module/{ctx['module_id']}/duplicate",
        data=json.dumps({
            "target_course_id": target["course_id"],
            "include_decks": False,
            "name": "Copied Module",
        }),
        headers=ctx["teacher_headers"],
    )
    assert dup.status_code == 201
    new_module_id = dup.get_json()["id"]

    detail = client.get(
        f"/course/{target['course_id']}",
        headers=ctx["teacher_headers"],
    )
    modules = detail.get_json().get("modules") or []
    copied = next(m for m in modules if m["_id"] == new_module_id)
    assert copied["name"] == "Copied Module"
    assert copied.get("activities")
    copied_activity_id = copied["activities"][0]["_id"]
    activity_detail = client.get(
        f"/course/activity/{copied_activity_id}",
        headers=ctx["teacher_headers"],
    )
    questions = activity_detail.get_json().get("questions") or []
    assert len(questions) == 1
    assert questions[0]["text"] == "2+2?"


def test_duplicate_course_includes_modules(client):
    ctx = _setup_course(client)
    _create_lesson(client, ctx, title="L1")
    target = _create_second_classroom(
        client, ctx["teacher_headers"], ctx["teacher_id"], uuid.uuid4().hex[:8]
    )

    dup = client.post(
        f"/course/{ctx['course_id']}/duplicate",
        data=json.dumps({
            "target_classroom_id": target["classroom_id"],
            "include_decks": False,
            "name": "Copied Course",
        }),
        headers=ctx["teacher_headers"],
    )
    assert dup.status_code == 201
    new_course_id = dup.get_json()["id"]

    detail = client.get(
        f"/course/{new_course_id}",
        headers=ctx["teacher_headers"],
    )
    assert detail.status_code == 200
    data = detail.get_json()
    assert data["name"] == "Copied Course"
    assert data.get("modules")
    assert data["modules"][0].get("lessons")


def test_lesson_content_html_save_and_sanitize(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx)

    updated = client.put(
        f"/course/lesson/{lesson_id}",
        data=json.dumps({
            "content_html": (
                '<p><strong>Hello</strong></p>'
                '<img src="https://example.com/a.png" alt="pic" />'
                '<script>alert(1)</script>'
            ),
        }),
        headers=ctx["teacher_headers"],
    )
    assert updated.status_code == 200
    body = updated.get_json()
    assert "<strong>Hello</strong>" in body["content_html"]
    assert "example.com/a.png" in body["content_html"]
    assert "<script>" not in body["content_html"]

    detail = client.get(
        f"/course/lesson/{lesson_id}",
        headers=ctx["teacher_headers"],
    )
    assert detail.status_code == 200
    assert "<strong>Hello</strong>" in detail.get_json()["content_html"]


def test_lesson_content_html_duplicate(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx, title="Rich Lesson")
    client.put(
        f"/course/lesson/{lesson_id}",
        data=json.dumps({"content_html": "<p>Rich body</p>"}),
        headers=ctx["teacher_headers"],
    )
    target = _create_second_classroom(
        client, ctx["teacher_headers"], ctx["teacher_id"], uuid.uuid4().hex[:8]
    )
    dup = client.post(
        f"/course/lesson/{lesson_id}/duplicate",
        data=json.dumps({
            "target_module_id": target["module_id"],
            "target_course_id": target["course_id"],
            "include_decks": False,
        }),
        headers=ctx["teacher_headers"],
    )
    assert dup.status_code == 201
    new_lesson_id = dup.get_json()["id"]
    detail = client.get(
        f"/course/lesson/{new_lesson_id}",
        headers=ctx["teacher_headers"],
    )
    assert "Rich body" in detail.get_json()["content_html"]


def test_lesson_format_text_video_both(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx, title="Format Lesson")

    text_only = client.put(
        f"/course/lesson/{lesson_id}",
        data=json.dumps({"lesson_format": "text", "content_html": "<p>Text body</p>"}),
        headers=ctx["teacher_headers"],
    )
    assert text_only.status_code == 200
    body = text_only.get_json()
    assert body["lesson_format"] == "text"
    assert body["content_html"]
    assert not body.get("video_url")

    video_only = client.put(
        f"/course/lesson/{lesson_id}",
        data=json.dumps({
            "lesson_format": "video",
            "video_url": "https://youtube.com/watch?v=abc",
            "video_type": "youtube",
        }),
        headers=ctx["teacher_headers"],
    )
    assert video_only.status_code == 200
    body = video_only.get_json()
    assert body["lesson_format"] == "video"
    assert body["video_url"]
    assert not body.get("content_html")

    both = client.put(
        f"/course/lesson/{lesson_id}",
        data=json.dumps({
            "lesson_format": "both",
            "content_html": "<p>Both text</p>",
            "video_url": "https://youtube.com/watch?v=xyz",
        }),
        headers=ctx["teacher_headers"],
    )
    assert both.status_code == 200
    body = both.get_json()
    assert body["lesson_format"] == "both"
    assert body["content_html"]
    assert body["video_url"]


def test_lesson_annotation_visibility(client):
    ctx = _setup_course(client)
    lesson_id = _create_lesson(client, ctx, title="Annot Lesson")

    student_ann = client.post(
        f"/course/lesson/{lesson_id}/annotations",
        data=json.dumps({
            "start_offset": 0,
            "end_offset": 4,
            "quote": "test",
            "highlight_color": "#FEF08A",
            "comment": "private",
        }),
        headers=ctx["student_headers"],
    )
    assert student_ann.status_code == 201
    student_id = student_ann.get_json()["_id"]

    teacher_ann = client.post(
        f"/course/lesson/{lesson_id}/annotations",
        data=json.dumps({
            "start_offset": 5,
            "end_offset": 9,
            "quote": "note",
            "comment": "public teacher note",
        }),
        headers=ctx["teacher_headers"],
    )
    assert teacher_ann.status_code == 201

    listed = client.get(
        f"/course/lesson/{lesson_id}/annotations",
        headers=ctx["student_headers"],
    )
    assert listed.status_code == 200
    items = listed.get_json()
    ids = [i["_id"] for i in items]
    assert student_id in ids
    assert any(i.get("is_public") for i in items)
    assert all(i.get("is_public") or i.get("is_mine") for i in items)


def test_lesson_neighbors_continue_and_completed(client):
    ctx = _setup_course(client)
    first = _create_lesson(client, ctx, "Lesson A")
    second = _create_lesson(client, ctx, "Lesson B")

    detail = client.get(
        f"/course/lesson/{first}",
        headers=ctx["student_headers"],
    )
    assert detail.status_code == 200
    body = detail.get_json()
    assert body["completed"] is False
    assert body["prev_lesson"] is None
    assert body["next_lesson"]["_id"] == second

    client.post(
        f"/course/lesson/{first}/viewed",
        data=json.dumps({}),
        headers=ctx["student_headers"],
    )
    done = client.put(
        f"/course/lesson/{first}/completed",
        data=json.dumps({"completed": True}),
        headers=ctx["student_headers"],
    )
    assert done.status_code == 200
    assert done.get_json()["completed"] is True

    cont = client.get(
        f"/course/by_classroom/{ctx['classroom_id']}/continue",
        headers=ctx["student_headers"],
    )
    assert cont.status_code == 200
    payload = cont.get_json()
    assert payload["last_viewed"][0]["_id"] == first
    assert payload["next_lesson"]["_id"] == second

