"""Testes das rotas de curso, atividades e questões."""
import json
import uuid

from src.app import mongo
from src.app.models.user_model import UserModel


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
