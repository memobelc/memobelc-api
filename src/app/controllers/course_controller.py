from datetime import datetime

from flask import Blueprint, jsonify, request
from src.app.middlewares.token_required import token_required
from src.app.services.course_service import CourseService


class CourseController:

    # ── Courses ───────────────────────────────────────────────────────────────

    @staticmethod
    @token_required
    def create_course(current_user, token):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can create courses'}), 403

        data = request.get_json() or {}
        if 'name' not in data or 'classroom_id' not in data:
            return jsonify({'error': 'name and classroom_id are required'}), 400

        result = CourseService.create_course(
            name=data['name'],
            description=data.get('description', ''),
            classroom_id=data['classroom_id'],
            teacher_id=str(current_user._id),
        )
        return jsonify(result), 201

    @staticmethod
    @token_required
    def get_courses_by_classroom(current_user, token, classroom_id):
        result = CourseService.get_courses_by_classroom(classroom_id)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def get_my_courses(current_user, token):
        result = CourseService.get_courses_for_user(str(current_user._id))
        return jsonify(result), 200

    @staticmethod
    def get_public_course(course_id):
        course = CourseService.get_public_course(course_id)
        if not course:
            return jsonify({'error': 'Course not found'}), 404
        return jsonify(course), 200

    @staticmethod
    @token_required
    def get_course_detail(current_user, token, course_id):
        course = CourseService.get_course_detail(
            course_id, user_id=str(current_user._id)
        )
        if not course:
            return jsonify({'error': 'Course not found'}), 404
        return jsonify(course), 200

    @staticmethod
    @token_required
    def update_course(current_user, token, course_id):
        is_teacher = current_user.has_role('teacher')
        is_admin = current_user.has_role('admin')
        if not is_teacher and not is_admin:
            return jsonify({'error': 'Only teachers can update courses'}), 403

        course = CourseService.get_course_detail(course_id)
        if not course:
            return jsonify({'error': 'Course not found'}), 404

        data = request.get_json() or {}
        allowed = ['name', 'description']
        commerce_keys = ['checkout_enabled', 'price']
        is_owner = str(course.get('teacher_id')) == str(current_user._id)
        if is_owner or is_admin:
            allowed = allowed + commerce_keys

        update_data = {k: v for k, v in data.items() if k in allowed}
        if 'checkout_enabled' in update_data:
            update_data['checkout_enabled'] = bool(update_data['checkout_enabled'])
        if 'price' in update_data:
            raw_price = update_data['price']
            if raw_price is None or raw_price == '':
                update_data['price'] = None
            else:
                try:
                    price = float(raw_price)
                except (TypeError, ValueError):
                    return jsonify({'error': 'Invalid price'}), 400
                if price < 0:
                    return jsonify({'error': 'Invalid price'}), 400
                update_data['price'] = price

        result = CourseService.update_course(course_id, update_data)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def delete_course(current_user, token, course_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can delete courses'}), 403

        CourseService.delete_course(course_id)
        return jsonify({'message': 'Course deleted'}), 200

    # ── Modules ───────────────────────────────────────────────────────────────

    @staticmethod
    @token_required
    def create_module(current_user, token):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can create modules'}), 403

        data = request.get_json() or {}
        if 'name' not in data or 'course_id' not in data:
            return jsonify({'error': 'name and course_id are required'}), 400

        scheduled_at = None
        if data.get('scheduled_at'):
            try:
                scheduled_at = datetime.fromisoformat(data['scheduled_at'])
            except (ValueError, TypeError):
                pass

        result = CourseService.create_module(
            name=data['name'],
            course_id=data['course_id'],
            scheduled_at=scheduled_at,
        )
        return jsonify(result), 201

    @staticmethod
    @token_required
    def update_module(current_user, token, module_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can update modules'}), 403

        data = request.get_json() or {}
        update_data = {k: v for k, v in data.items() if k in ['name', 'scheduled_at']}
        result = CourseService.update_module(module_id, update_data)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def delete_module(current_user, token, module_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can delete modules'}), 403

        CourseService.delete_module(module_id)
        return jsonify({'message': 'Module deleted'}), 200

    @staticmethod
    @token_required
    def reorder_modules(current_user, token, course_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can reorder modules'}), 403

        data = request.get_json() or {}
        if 'module_ids' not in data:
            return jsonify({'error': 'module_ids is required'}), 400

        CourseService.reorder_modules(course_id, data['module_ids'])
        return jsonify({'message': 'Modules reordered'}), 200

    # ── Lessons ───────────────────────────────────────────────────────────────

    @staticmethod
    @token_required
    def create_lesson(current_user, token):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can create lessons'}), 403

        data = request.get_json() or {}
        if 'title' not in data or 'module_id' not in data or 'course_id' not in data:
            return jsonify({'error': 'title, module_id and course_id are required'}), 400

        scheduled_at = None
        if data.get('scheduled_at'):
            try:
                scheduled_at = datetime.fromisoformat(data['scheduled_at'])
            except (ValueError, TypeError):
                pass

        result = CourseService.create_lesson(
            title=data['title'],
            video_url=data.get('video_url', ''),
            video_type=data.get('video_type', 'youtube'),
            description=data.get('description', ''),
            module_id=data['module_id'],
            course_id=data['course_id'],
            visible=data.get('visible', True),
            scheduled_at=scheduled_at,
        )
        return jsonify(result), 201

    @staticmethod
    @token_required
    def get_lesson(current_user, token, lesson_id):
        lesson = CourseService.get_lesson_for_user(
            lesson_id, user_id=str(current_user._id)
        )
        if not lesson:
            return jsonify({'error': 'Lesson not found'}), 404
        return jsonify(lesson), 200

    @staticmethod
    @token_required
    def update_lesson(current_user, token, lesson_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can update lessons'}), 403

        data = request.get_json() or {}
        allowed = ['title', 'video_url', 'video_type', 'description', 'visible', 'scheduled_at']
        update_data = {k: v for k, v in data.items() if k in allowed}
        result = CourseService.update_lesson(lesson_id, update_data)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def delete_lesson(current_user, token, lesson_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can delete lessons'}), 403

        CourseService.delete_lesson(lesson_id)
        return jsonify({'message': 'Lesson deleted'}), 200

    @staticmethod
    @token_required
    def reorder_lessons(current_user, token, module_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can reorder lessons'}), 403

        data = request.get_json() or {}
        if 'lesson_ids' not in data:
            return jsonify({'error': 'lesson_ids is required'}), 400

        CourseService.reorder_lessons(module_id, data['lesson_ids'])
        return jsonify({'message': 'Lessons reordered'}), 200

    # ── Activities ────────────────────────────────────────────────────────────

    @staticmethod
    @token_required
    def create_activity(current_user, token):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can create activities'}), 403

        data = request.get_json() or {}
        if 'title' not in data or 'module_id' not in data or 'course_id' not in data:
            return jsonify({'error': 'title, module_id and course_id are required'}), 400

        scheduled_at = None
        if data.get('scheduled_at'):
            try:
                scheduled_at = datetime.fromisoformat(data['scheduled_at'])
            except (ValueError, TypeError):
                pass

        result = CourseService.create_activity(
            title=data['title'],
            description=data.get('description', ''),
            module_id=data['module_id'],
            course_id=data['course_id'],
            visible=data.get('visible', True),
            scheduled_at=scheduled_at,
            feedback_mode=data.get('feedback_mode', 'immediate'),
        )
        return jsonify(result), 201

    @staticmethod
    @token_required
    def get_activity(current_user, token, activity_id):
        activity = CourseService.get_activity_detail(
            activity_id, user_id=str(current_user._id)
        )
        if not activity:
            return jsonify({'error': 'Activity not found'}), 404
        return jsonify(activity), 200

    @staticmethod
    @token_required
    def update_activity(current_user, token, activity_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can update activities'}), 403

        data = request.get_json() or {}
        allowed = ['title', 'description', 'visible', 'scheduled_at', 'feedback_mode']
        update_data = {k: v for k, v in data.items() if k in allowed}
        result = CourseService.update_activity(activity_id, update_data)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def delete_activity(current_user, token, activity_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can delete activities'}), 403

        CourseService.delete_activity(activity_id)
        return jsonify({'message': 'Activity deleted'}), 200

    @staticmethod
    @token_required
    def reorder_activities(current_user, token, module_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can reorder activities'}), 403

        data = request.get_json() or {}
        if 'activity_ids' not in data:
            return jsonify({'error': 'activity_ids is required'}), 400

        CourseService.reorder_activities(module_id, data['activity_ids'])
        return jsonify({'message': 'Activities reordered'}), 200

    # ── Questions ─────────────────────────────────────────────────────────────

    @staticmethod
    @token_required
    def create_question(current_user, token):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can create questions'}), 403

        data = request.get_json() or {}
        if 'text' not in data or 'type' not in data or 'activity_id' not in data:
            return jsonify({'error': 'text, type and activity_id are required'}), 400

        try:
            result = CourseService.create_question(
                text=data['text'],
                q_type=data['type'],
                options=data.get('options', []),
                correct_answer=data.get('correct_answer'),
                show_answer=data.get('show_answer'),
                points=data.get('points', 1),
                activity_id=data['activity_id'],
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        return jsonify(result), 201

    @staticmethod
    @token_required
    def update_question(current_user, token, question_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can update questions'}), 403

        data = request.get_json() or {}
        allowed = ['text', 'type', 'options', 'correct_answer', 'show_answer', 'points']
        update_data = {k: v for k, v in data.items() if k in allowed}
        try:
            result = CourseService.update_question(question_id, update_data)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        return jsonify(result), 200

    @staticmethod
    @token_required
    def delete_question(current_user, token, question_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can delete questions'}), 403

        CourseService.delete_question(question_id)
        return jsonify({'message': 'Question deleted'}), 200

    @staticmethod
    @token_required
    def reorder_questions(current_user, token, activity_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can reorder questions'}), 403

        data = request.get_json() or {}
        if 'question_ids' not in data:
            return jsonify({'error': 'question_ids is required'}), 400

        CourseService.reorder_questions(activity_id, data['question_ids'])
        return jsonify({'message': 'Questions reordered'}), 200

    # ── Lesson Views ─────────────────────────────────────────────────────────

    @staticmethod
    @token_required
    def mark_lesson_viewed(current_user, token, lesson_id):
        CourseService.mark_lesson_viewed(lesson_id, str(current_user._id))
        return jsonify({'viewed': True}), 200

    @staticmethod
    @token_required
    def get_students_progress(current_user, token, course_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can view student progress'}), 403
        result = CourseService.get_students_progress(course_id)
        return jsonify(result), 200

    # ── Teacher answer management ─────────────────────────────────────────────

    @staticmethod
    @token_required
    def get_student_answer_for_teacher(current_user, token, activity_id, student_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can view student answers'}), 403
        result = CourseService.get_student_answer_for_teacher(activity_id, student_id)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def set_student_approved(current_user, token, activity_id, student_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can approve answers'}), 403
        data = request.get_json() or {}
        approved = bool(data.get('approved', True))
        result = CourseService.set_student_approved(activity_id, student_id, approved)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def approve_all_answers(current_user, token, activity_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can approve answers'}), 403
        result = CourseService.approve_all_answers(activity_id)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def reset_student_answer(current_user, token, activity_id, student_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can reset answers'}), 403
        CourseService.reset_student_answer(activity_id, student_id)
        return jsonify({'reset': True}), 200

    # ── Student Answers ───────────────────────────────────────────────────────

    @staticmethod
    @token_required
    def submit_answers(current_user, token, activity_id):
        data = request.get_json() or {}
        if 'answers' not in data:
            return jsonify({'error': 'answers is required'}), 400

        try:
            result = CourseService.submit_answers(
                student_id=str(current_user._id),
                activity_id=activity_id,
                answers=data['answers'],
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        return jsonify(result), 200

    @staticmethod
    @token_required
    def get_my_answer(current_user, token, activity_id):
        result = CourseService.get_my_answer(
            student_id=str(current_user._id),
            activity_id=activity_id,
        )
        return jsonify({'answer': result}), 200

    @staticmethod
    @token_required
    def get_course_ranking(current_user, token, course_id):
        result = CourseService.get_course_ranking(
            course_id, user_id=str(current_user._id)
        )
        if not result:
            return jsonify({'error': 'Course not found'}), 404
        return jsonify(result), 200

    # ── Ratings ──────────────────────────────────────────────────────────────

    @staticmethod
    @token_required
    def rate_lesson(current_user, token, lesson_id):
        data = request.get_json() or {}
        stars = CourseService.parse_stars(data.get('stars'))
        if stars is None:
            return jsonify({'error': 'stars must be an integer from 1 to 5'}), 400
        rating, error = CourseService.rate_lesson(
            lesson_id, str(current_user._id), stars
        )
        if error:
            status = 403 if 'Teachers' in error else 404
            return jsonify({'error': error}), status
        return jsonify(rating), 200

    @staticmethod
    @token_required
    def rate_module(current_user, token, module_id):
        data = request.get_json() or {}
        stars = CourseService.parse_stars(data.get('stars'))
        if stars is None:
            return jsonify({'error': 'stars must be an integer from 1 to 5'}), 400
        rating, error = CourseService.rate_module(
            module_id, str(current_user._id), stars
        )
        if error:
            status = 403 if 'Teachers' in error else 404
            return jsonify({'error': error}), status
        return jsonify(rating), 200

    @staticmethod
    @token_required
    def dismiss_module_rating(current_user, token, module_id):
        rating, error = CourseService.dismiss_module_rating(
            module_id, str(current_user._id)
        )
        if error:
            status = 403 if 'Teachers' in error else 404
            return jsonify({'error': error}), status
        return jsonify(rating), 200

    @staticmethod
    @token_required
    def get_course_ratings(current_user, token, course_id):
        if not current_user.has_role('teacher'):
            return jsonify({'error': 'Only teachers can view ratings'}), 403
        result = CourseService.get_course_ratings(course_id)
        if not result:
            return jsonify({'error': 'Course not found'}), 404
        return jsonify(result), 200


course_blueprint = Blueprint('course_blueprint', __name__)

# Courses
course_blueprint.route('/create', methods=['POST'])(CourseController.create_course)
course_blueprint.route('/mine', methods=['GET'])(CourseController.get_my_courses)
course_blueprint.route('/by_classroom/<classroom_id>', methods=['GET'])(CourseController.get_courses_by_classroom)
course_blueprint.route('/public/<course_id>', methods=['GET'])(CourseController.get_public_course)
course_blueprint.route('/<course_id>', methods=['GET'])(CourseController.get_course_detail)
course_blueprint.route('/<course_id>', methods=['PUT'])(CourseController.update_course)
course_blueprint.route('/<course_id>', methods=['DELETE'])(CourseController.delete_course)

# Modules
course_blueprint.route('/module/create', methods=['POST'])(CourseController.create_module)
course_blueprint.route('/module/<module_id>', methods=['PUT'])(CourseController.update_module)
course_blueprint.route('/module/<module_id>', methods=['DELETE'])(CourseController.delete_module)
course_blueprint.route('/<course_id>/modules/reorder', methods=['PUT'])(CourseController.reorder_modules)

# Lessons
course_blueprint.route('/lesson/create', methods=['POST'])(CourseController.create_lesson)
course_blueprint.route('/lesson/<lesson_id>', methods=['GET'])(CourseController.get_lesson)
course_blueprint.route('/lesson/<lesson_id>', methods=['PUT'])(CourseController.update_lesson)
course_blueprint.route('/lesson/<lesson_id>', methods=['DELETE'])(CourseController.delete_lesson)
course_blueprint.route('/module/<module_id>/lessons/reorder', methods=['PUT'])(CourseController.reorder_lessons)

# Activities
course_blueprint.route('/activity/create', methods=['POST'])(CourseController.create_activity)
course_blueprint.route('/activity/<activity_id>', methods=['GET'])(CourseController.get_activity)
course_blueprint.route('/activity/<activity_id>', methods=['PUT'])(CourseController.update_activity)
course_blueprint.route('/activity/<activity_id>', methods=['DELETE'])(CourseController.delete_activity)
course_blueprint.route('/module/<module_id>/activities/reorder', methods=['PUT'])(CourseController.reorder_activities)

# Questions
course_blueprint.route('/question/create', methods=['POST'])(CourseController.create_question)
course_blueprint.route('/question/<question_id>', methods=['PUT'])(CourseController.update_question)
course_blueprint.route('/question/<question_id>', methods=['DELETE'])(CourseController.delete_question)
course_blueprint.route('/activity/<activity_id>/questions/reorder', methods=['PUT'])(CourseController.reorder_questions)

# Teacher answer management
course_blueprint.route('/activity/<activity_id>/answer/<student_id>', methods=['GET'])(CourseController.get_student_answer_for_teacher)
course_blueprint.route('/activity/<activity_id>/answer/<student_id>/approve', methods=['POST'])(CourseController.set_student_approved)
course_blueprint.route('/activity/<activity_id>/approve_all', methods=['POST'])(CourseController.approve_all_answers)
course_blueprint.route('/activity/<activity_id>/answer/<student_id>/reset', methods=['DELETE'])(CourseController.reset_student_answer)

# Student Answers
course_blueprint.route('/activity/<activity_id>/submit', methods=['POST'])(CourseController.submit_answers)
course_blueprint.route('/activity/<activity_id>/my_answer', methods=['GET'])(CourseController.get_my_answer)

# Lesson Views & Student Progress
course_blueprint.route('/lesson/<lesson_id>/viewed', methods=['POST'])(CourseController.mark_lesson_viewed)
course_blueprint.route('/<course_id>/students_progress', methods=['GET'])(CourseController.get_students_progress)
course_blueprint.route('/<course_id>/ranking', methods=['GET'])(CourseController.get_course_ranking)

# Ratings
course_blueprint.route('/lesson/<lesson_id>/rating', methods=['PUT'])(CourseController.rate_lesson)
course_blueprint.route('/module/<module_id>/rating', methods=['PUT'])(CourseController.rate_module)
course_blueprint.route('/module/<module_id>/rating/dismiss', methods=['POST'])(CourseController.dismiss_module_rating)
course_blueprint.route('/<course_id>/ratings', methods=['GET'])(CourseController.get_course_ratings)
