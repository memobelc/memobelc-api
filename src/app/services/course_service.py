from datetime import datetime, timezone
from bson.errors import InvalidId
from src.app.models.course_model import (
    CourseModel, ModuleModel, LessonModel, ActivityModel,
    QuestionModel, StudentAnswerModel, LessonViewModel,
    CourseRatingModel, count_blanks,
)

MODULE_RATING_WEIGHT = 3
UNRATED_STARS = 5


class CourseService:

    # ── Courses ───────────────────────────────────────────────────────────────

    @staticmethod
    def create_course(name, description, classroom_id, teacher_id):
        course = CourseModel(
            name=name,
            description=description,
            classroom_id=classroom_id,
            teacher_id=teacher_id,
        )
        return course.save_to_db()

    @staticmethod
    def get_courses_by_classroom(classroom_id):
        courses = CourseModel.get_by_classroom(classroom_id)
        for course in courses:
            course['has_content'] = CourseModel.has_visible_content(course['_id'])
        return {'courses': courses}

    @staticmethod
    def get_courses_for_user(user_id):
        from src.app.services.classroom_service import ClassroomService

        classrooms_result = ClassroomService.getClassrooms(user_id)
        classrooms = classrooms_result.get('classrooms') or []
        courses = []
        for classroom in classrooms:
            if classroom.get('user_role') != 'student':
                continue
            classroom_id = classroom.get('_id')
            classroom_name = classroom.get('name') or ''
            classroom_courses = CourseModel.get_by_classroom(classroom_id)
            for course in classroom_courses:
                if not CourseModel.has_visible_content(course['_id']):
                    continue
                course['classroom_id'] = classroom_id
                course['classroom_name'] = classroom_name
                course['has_content'] = True
                courses.append(course)
        return {'courses': courses}

    @staticmethod
    def get_course_detail(course_id, user_id=None, is_teacher=False):
        course = CourseModel.get_by_id(course_id)
        if not course:
            return None
        if user_id is not None:
            is_teacher = str(course.get('teacher_id')) == str(user_id)
        # Teachers of this course see all modules; students only see released ones
        modules = ModuleModel.get_by_course(course_id, include_hidden=is_teacher)
        for module in modules:
            # Once a module is visible, content follows its own individual settings.
            # Teachers always see everything inside.
            module['lessons'] = LessonModel.get_by_module(
                module['_id'], include_hidden=is_teacher
            )
            module['activities'] = ActivityModel.get_by_module(
                module['_id'], include_hidden=is_teacher
            )
            for lesson in module.get('lessons') or []:
                lesson['decks'] = CourseService.list_lesson_decks(
                    lesson['_id'], user_id=user_id, is_teacher=is_teacher
                )
        CourseService._attach_student_ratings(course, modules, user_id, is_teacher)
        course['modules'] = modules
        return course

    @staticmethod
    def _attach_student_ratings(course, modules, user_id, is_teacher):
        if not user_id or is_teacher:
            for module in modules:
                module['my_rating'] = None
                module['rating_prompt'] = False
                module['can_rate'] = False
                for lesson in module.get('lessons') or []:
                    lesson['my_rating'] = None
            return

        ratings = CourseRatingModel.get_student_ratings_for_course(
            user_id, course['_id']
        )
        by_key = {
            (r['target_type'], r['target_id']): r
            for r in ratings
            if r
        }
        for module in modules:
            lessons = module.get('lessons') or []
            visible_ids = [lesson['_id'] for lesson in lessons]
            viewed_all = bool(visible_ids) and all(
                LessonViewModel.has_viewed(lid, user_id) for lid in visible_ids
            )
            for lesson in lessons:
                lesson_rating = by_key.get(
                    (CourseRatingModel.TARGET_LESSON, lesson['_id'])
                )
                lesson['my_rating'] = (
                    lesson_rating.get('stars') if lesson_rating else None
                )
            module_rating = by_key.get(
                (CourseRatingModel.TARGET_MODULE, module['_id'])
            )
            my_stars = module_rating.get('stars') if module_rating else None
            dismissed = bool(module_rating and module_rating.get('dismissed'))
            module['my_rating'] = my_stars
            module['can_rate'] = viewed_all
            module['rating_prompt'] = (
                viewed_all and my_stars is None and not dismissed
            )

    @staticmethod
    def get_public_course(course_id):
        course = CourseModel.get_by_id(course_id)
        if not course or not course.get('checkout_enabled'):
            return None
        price = course.get('price')
        return {
            '_id': course['_id'],
            'name': course.get('name'),
            'description': course.get('description') or '',
            'price': float(price) if price is not None else None,
            'checkout_enabled': True,
            'checkout_url': course.get('checkout_url'),
            'classroom_id': course.get('classroom_id'),
        }

    @staticmethod
    def update_course(course_id, update_data):
        CourseModel.update(course_id, update_data)
        return CourseModel.get_by_id(course_id)

    @staticmethod
    def delete_course(course_id):
        modules = ModuleModel.get_by_course(course_id)
        for module in modules:
            CourseService.delete_module(module['_id'])
        CourseModel.delete(course_id)
        return {}

    # ── Modules ───────────────────────────────────────────────────────────────

    @staticmethod
    def create_module(name, course_id, scheduled_at=None):
        module = ModuleModel(name=name, course_id=course_id, scheduled_at=scheduled_at)
        return module.save_to_db()

    @staticmethod
    def update_module(module_id, update_data):
        if 'scheduled_at' in update_data:
            if update_data['scheduled_at']:
                try:
                    update_data['scheduled_at'] = datetime.fromisoformat(
                        update_data['scheduled_at']
                    )
                except (ValueError, TypeError):
                    update_data.pop('scheduled_at', None)
            else:
                update_data['scheduled_at'] = None
        ModuleModel.update(module_id, update_data)
        return ModuleModel.get_by_id(module_id)

    @staticmethod
    def delete_module(module_id):
        lessons = LessonModel.get_by_module(module_id)
        for lesson in lessons:
            LessonModel.delete(lesson['_id'])

        activities = ActivityModel.get_by_module(module_id)
        for activity in activities:
            QuestionModel.delete_by_activity(activity['_id'])
            StudentAnswerModel.delete_by_activity(activity['_id'])
            ActivityModel.delete(activity['_id'])

        ModuleModel.delete(module_id)
        return {}

    @staticmethod
    def reorder_modules(course_id, module_ids):
        ModuleModel.reorder(course_id, module_ids)
        return {}

    @staticmethod
    def reorder_courses(classroom_id, course_ids):
        CourseModel.reorder(classroom_id, course_ids)
        return {}

    # ── Lessons ───────────────────────────────────────────────────────────────

    @staticmethod
    def create_lesson(title, video_url, video_type, description,
                      module_id, course_id, visible, scheduled_at,
                      content_html='', lesson_format='text'):
        from src.app.utils.html_sanitize import sanitize_lesson_html

        if lesson_format not in LessonModel.LESSON_FORMATS:
            lesson_format = 'text'

        try:
            safe_html = sanitize_lesson_html(content_html)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        if lesson_format == 'text':
            video_url = ''
        elif lesson_format == 'video':
            safe_html = ''

        lesson = LessonModel(
            title=title,
            video_url=video_url,
            video_type=video_type,
            description=description,
            content_html=safe_html,
            lesson_format=lesson_format,
            module_id=module_id,
            course_id=course_id,
            visible=visible,
            scheduled_at=scheduled_at,
        )
        return lesson.save_to_db()

    @staticmethod
    def update_lesson(lesson_id, update_data):
        from src.app.utils.html_sanitize import sanitize_lesson_html

        if 'content_html' in update_data:
            try:
                update_data['content_html'] = sanitize_lesson_html(
                    update_data.get('content_html')
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from exc

        if 'lesson_format' in update_data:
            fmt = update_data.get('lesson_format')
            if fmt not in LessonModel.LESSON_FORMATS:
                raise ValueError('Invalid lesson format')
            if fmt == 'text':
                update_data['video_url'] = ''
            elif fmt == 'video':
                update_data['content_html'] = ''

        if update_data.get('scheduled_at'):
            try:
                update_data['scheduled_at'] = datetime.fromisoformat(
                    update_data['scheduled_at']
                )
            except (ValueError, TypeError):
                update_data.pop('scheduled_at', None)
        LessonModel.update(lesson_id, update_data)
        return LessonModel.get_by_id(lesson_id)

    @staticmethod
    def delete_lesson(lesson_id):
        LessonModel.delete(lesson_id)
        return {}

    @staticmethod
    def reorder_lessons(module_id, lesson_ids):
        LessonModel.reorder(module_id, lesson_ids)
        return {}

    # ── Activities ────────────────────────────────────────────────────────────

    @staticmethod
    def create_activity(title, description, module_id, course_id, visible, scheduled_at,
                        feedback_mode='immediate'):
        if feedback_mode not in ActivityModel.FEEDBACK_MODES:
            feedback_mode = 'immediate'
        activity = ActivityModel(
            title=title,
            description=description,
            module_id=module_id,
            course_id=course_id,
            visible=visible,
            scheduled_at=scheduled_at,
            feedback_mode=feedback_mode,
        )
        return activity.save_to_db()

    @staticmethod
    def is_course_teacher(course_id, user_id):
        if not course_id or not user_id:
            return False
        course = CourseModel.get_by_id(course_id)
        return bool(course and str(course.get('teacher_id')) == str(user_id))

    @staticmethod
    def can_see_feedback(activity, answer_doc):
        if not answer_doc:
            return False
        mode = activity.get('feedback_mode') or 'immediate'
        if mode == 'immediate':
            return True
        return bool(answer_doc.get('approved'))

    @staticmethod
    def get_activity_detail(activity_id, user_id=None, is_teacher=False):
        activity = ActivityModel.get_by_id(activity_id)
        if not activity:
            return None
        if user_id is not None:
            is_teacher = CourseService.is_course_teacher(activity.get('course_id'), user_id)

        answer_doc = None
        if user_id and not is_teacher:
            answer_doc = StudentAnswerModel.get_by_student_and_activity(user_id, activity_id)

        include_answers = is_teacher or CourseService.can_see_feedback(activity, answer_doc)
        activity['questions'] = QuestionModel.get_by_activity(
            activity_id, for_student=not include_answers
        )
        return activity

    @staticmethod
    def update_activity(activity_id, update_data):
        if 'scheduled_at' in update_data:
            if update_data['scheduled_at']:
                try:
                    update_data['scheduled_at'] = datetime.fromisoformat(
                        update_data['scheduled_at']
                    )
                except (ValueError, TypeError):
                    update_data.pop('scheduled_at', None)
            else:
                update_data['scheduled_at'] = None
        if 'feedback_mode' in update_data:
            if update_data['feedback_mode'] not in ActivityModel.FEEDBACK_MODES:
                update_data['feedback_mode'] = 'immediate'
        ActivityModel.update(activity_id, update_data)
        return ActivityModel.get_by_id(activity_id)

    @staticmethod
    def delete_activity(activity_id):
        QuestionModel.delete_by_activity(activity_id)
        StudentAnswerModel.delete_by_activity(activity_id)
        ActivityModel.delete(activity_id)
        return {}

    @staticmethod
    def reorder_activities(module_id, activity_ids):
        ActivityModel.reorder(module_id, activity_ids)
        return {}

    # ── Questions ─────────────────────────────────────────────────────────────

    @staticmethod
    def validate_question_payload(text, q_type, options, correct_answer, points):
        if not text or not str(text).strip():
            raise ValueError('Question text is required')
        if q_type not in QuestionModel.VALID_TYPES:
            raise ValueError('Invalid question type')
        try:
            points = int(points)
        except (TypeError, ValueError):
            raise ValueError('Points must be an integer >= 1')
        if points < 1:
            raise ValueError('Points must be an integer >= 1')

        options = [str(o).strip() for o in (options or []) if str(o).strip()]
        text = str(text).strip()

        if q_type in ('multiple_choice', 'checkbox', 'dropdown'):
            if len(options) < 2:
                raise ValueError('At least 2 options are required')
            if q_type == 'checkbox':
                if not isinstance(correct_answer, list) or not correct_answer:
                    raise ValueError('At least one correct option is required')
                correct_answer = [str(c).strip() for c in correct_answer if str(c).strip()]
                if not correct_answer:
                    raise ValueError('At least one correct option is required')
                if not all(c in options for c in correct_answer):
                    raise ValueError('Correct answers must match the options')
            else:
                if correct_answer is None or str(correct_answer).strip() == '':
                    raise ValueError('A correct answer is required')
                correct_answer = str(correct_answer).strip()
                if correct_answer not in options:
                    raise ValueError('Correct answer must match one of the options')

        elif q_type == 'short_answer':
            if correct_answer is None or not str(correct_answer).strip():
                raise ValueError('Expected answer is required')
            correct_answer = str(correct_answer).strip()
            options = []

        elif q_type == 'fill_in_blank':
            n_blanks = count_blanks(text)
            if n_blanks < 1:
                raise ValueError('Fill in the blank questions must contain at least one ___')
            if isinstance(correct_answer, str):
                correct_answer = [correct_answer] if correct_answer.strip() else []
            if not isinstance(correct_answer, list):
                raise ValueError('Each blank must have an expected answer')
            answers = [str(a).strip() for a in correct_answer]
            if len(answers) != n_blanks or any(not a for a in answers):
                raise ValueError('Each blank must have an expected answer')
            correct_answer = answers
            options = []

        elif q_type == 'paragraph':
            options = []
            if correct_answer is not None:
                correct_answer = str(correct_answer).strip() or None

        return {
            'text': text,
            'type': q_type,
            'options': options,
            'correct_answer': correct_answer,
            'points': points,
        }

    @staticmethod
    def create_question(text, q_type, options, correct_answer,
                        show_answer, points, activity_id):
        validated = CourseService.validate_question_payload(
            text, q_type, options, correct_answer, points
        )
        activity = ActivityModel.get_by_id(activity_id)
        mode = (activity or {}).get('feedback_mode') or 'immediate'
        if show_answer is None:
            show_answer = mode == 'immediate'
        question = QuestionModel(
            text=validated['text'],
            type=validated['type'],
            options=validated['options'],
            correct_answer=validated['correct_answer'],
            show_answer=show_answer,
            points=validated['points'],
            activity_id=activity_id,
        )
        return question.save_to_db()

    @staticmethod
    def update_question(question_id, update_data):
        existing = QuestionModel.get_by_id(question_id)
        if not existing:
            raise ValueError('Question not found')
        merged_type = update_data.get('type', existing.get('type'))
        merged_text = update_data.get('text', existing.get('text'))
        merged_options = update_data.get('options', existing.get('options'))
        merged_correct = update_data.get('correct_answer', existing.get('correct_answer'))
        merged_points = update_data.get('points', existing.get('points', 1))
        validated = CourseService.validate_question_payload(
            merged_text, merged_type, merged_options, merged_correct, merged_points
        )
        payload = {
            'text': validated['text'],
            'type': validated['type'],
            'options': validated['options'],
            'correct_answer': validated['correct_answer'],
            'points': validated['points'],
        }
        if 'show_answer' in update_data:
            payload['show_answer'] = bool(update_data['show_answer'])
        QuestionModel.update(question_id, payload)
        return QuestionModel.get_by_id(question_id)

    @staticmethod
    def delete_question(question_id):
        QuestionModel.delete(question_id)
        return {}

    @staticmethod
    def reorder_questions(activity_id, question_ids):
        QuestionModel.reorder(activity_id, question_ids)
        return {}

    # ── Lesson Views ─────────────────────────────────────────────────────────

    @staticmethod
    def mark_lesson_viewed(lesson_id, student_id):
        LessonViewModel.mark_viewed(lesson_id, student_id)
        return {}

    @staticmethod
    def set_lesson_completed(lesson_id, student_id, completed):
        lesson = LessonModel.get_by_id(lesson_id)
        if not lesson:
            return None, 'Lesson not found'
        LessonViewModel.set_completed(lesson_id, student_id, completed)
        return CourseService.get_lesson_for_user(lesson_id, user_id=student_id), None

    @staticmethod
    def get_lesson_view_status(lesson_id, student_id):
        status = LessonViewModel.get_status(lesson_id, student_id)
        return status

    @staticmethod
    def _classroom_lesson_sequence(classroom_id, user_id=None, is_teacher=False):
        courses = CourseModel.get_by_classroom(classroom_id)
        sequence = []
        for course in courses:
            teacher = CourseService._course_teacher_id(course) == str(user_id)
            modules = ModuleModel.get_by_course(
                course['_id'], include_hidden=is_teacher or teacher
            )
            for module in modules:
                lessons = LessonModel.get_by_module(
                    module['_id'], include_hidden=is_teacher or teacher
                )
                for lesson in lessons:
                    sequence.append({
                        '_id': lesson['_id'],
                        'title': lesson.get('title'),
                        'course_id': course['_id'],
                        'course_name': course.get('name') or '',
                        'module_id': module['_id'],
                        'module_name': module.get('name') or '',
                        'lesson_format': lesson.get('lesson_format') or 'text',
                    })
        return sequence

    @staticmethod
    def _course_lesson_sequence(course_id, user_id=None, is_teacher=False):
        course = CourseModel.get_by_id(course_id)
        if not course:
            return []
        teacher = is_teacher or CourseService._course_teacher_id(course) == str(user_id)
        sequence = []
        modules = ModuleModel.get_by_course(course_id, include_hidden=teacher)
        for module in modules:
            lessons = LessonModel.get_by_module(module['_id'], include_hidden=teacher)
            for lesson in lessons:
                sequence.append({
                    '_id': lesson['_id'],
                    'title': lesson.get('title'),
                    'course_id': course_id,
                    'course_name': course.get('name') or '',
                    'module_id': module['_id'],
                    'module_name': module.get('name') or '',
                    'lesson_format': lesson.get('lesson_format') or 'text',
                })
        return sequence

    @staticmethod
    def get_classroom_continue(classroom_id, user_id, is_teacher=False):
        sequence = CourseService._classroom_lesson_sequence(
            classroom_id, user_id=user_id, is_teacher=is_teacher
        )
        lesson_ids = [item['_id'] for item in sequence]
        by_id = {item['_id']: item for item in sequence}
        recent = LessonViewModel.get_recent_for_student(user_id, lesson_ids, limit=3)
        last_viewed = []
        for item in recent:
            lesson = by_id.get(item['lesson_id'])
            if not lesson:
                continue
            last_viewed.append({
                **lesson,
                'completed': item['completed'],
                'last_accessed_at': item['last_accessed_at'],
            })

        next_lesson = None
        if sequence:
            last_id = last_viewed[0]['_id'] if last_viewed else None
            if last_id:
                index = next(
                    (i for i, item in enumerate(sequence) if item['_id'] == last_id),
                    -1,
                )
                if 0 <= index < len(sequence) - 1:
                    nxt = sequence[index + 1]
                    if not last_viewed or nxt['_id'] != last_id:
                        next_lesson = {**nxt, 'completed': LessonViewModel.has_completed(
                            nxt['_id'], user_id
                        )}
            if next_lesson is None and not last_viewed:
                first = sequence[0]
                next_lesson = {
                    **first,
                    'completed': LessonViewModel.has_completed(first['_id'], user_id),
                }

        return {
            'last_viewed': last_viewed,
            'next_lesson': next_lesson,
        }

    @staticmethod
    def get_lesson_for_user(lesson_id, user_id=None):
        try:
            lesson = LessonModel.get_by_id(lesson_id)
        except (InvalidId, TypeError):
            return None
        if not lesson:
            return None
        lesson['my_rating'] = None
        if user_id:
            rating = CourseRatingModel.get(
                user_id, CourseRatingModel.TARGET_LESSON, lesson_id
            )
            if rating:
                lesson['my_rating'] = rating.get('stars')
        is_teacher = False
        if user_id:
            course = CourseModel.get_by_id(lesson.get('course_id'))
            is_teacher = CourseService._course_teacher_id(course) == str(user_id)
        status = (
            LessonViewModel.get_status(lesson_id, user_id)
            if user_id
            else {'viewed': False, 'completed': False}
        )
        lesson['viewed'] = bool(status.get('viewed'))
        lesson['completed'] = bool(status.get('completed'))
        sequence = CourseService._course_lesson_sequence(
            lesson.get('course_id'), user_id=user_id, is_teacher=is_teacher
        )
        index = next(
            (i for i, item in enumerate(sequence) if item['_id'] == str(lesson_id)),
            -1,
        )
        lesson['prev_lesson'] = sequence[index - 1] if index > 0 else None
        lesson['next_lesson'] = (
            sequence[index + 1] if 0 <= index < len(sequence) - 1 else None
        )
        lesson['decks'] = CourseService.list_lesson_decks(
            lesson_id, user_id=user_id, is_teacher=is_teacher
        )
        return lesson

    @staticmethod
    def parse_stars(value):
        try:
            stars = int(value)
        except (TypeError, ValueError):
            return None
        if stars < 1 or stars > 5:
            return None
        return stars

    @staticmethod
    def _course_teacher_id(course):
        if not course:
            return None
        return str(course.get('teacher_id')) if course.get('teacher_id') else None

    @staticmethod
    def rate_lesson(lesson_id, student_id, stars):
        try:
            lesson = LessonModel.get_by_id(lesson_id)
        except (InvalidId, TypeError):
            lesson = None
        if not lesson:
            return None, 'Lesson not found'
        course = CourseModel.get_by_id(lesson.get('course_id'))
        if CourseService._course_teacher_id(course) == str(student_id):
            return None, 'Teachers cannot rate their own course'
        rating = CourseRatingModel.upsert(
            student_id=student_id,
            course_id=lesson.get('course_id'),
            target_type=CourseRatingModel.TARGET_LESSON,
            target_id=lesson_id,
            stars=stars,
        )
        return rating, None

    @staticmethod
    def rate_module(module_id, student_id, stars):
        try:
            module = ModuleModel.get_by_id(module_id)
        except (InvalidId, TypeError):
            module = None
        if not module:
            return None, 'Module not found'
        course = CourseModel.get_by_id(module.get('course_id'))
        if CourseService._course_teacher_id(course) == str(student_id):
            return None, 'Teachers cannot rate their own course'
        rating = CourseRatingModel.upsert(
            student_id=student_id,
            course_id=module.get('course_id'),
            target_type=CourseRatingModel.TARGET_MODULE,
            target_id=module_id,
            stars=stars,
        )
        return rating, None

    @staticmethod
    def dismiss_module_rating(module_id, student_id):
        try:
            module = ModuleModel.get_by_id(module_id)
        except (InvalidId, TypeError):
            module = None
        if not module:
            return None, 'Module not found'
        course = CourseModel.get_by_id(module.get('course_id'))
        if CourseService._course_teacher_id(course) == str(student_id):
            return None, 'Teachers cannot rate their own course'
        rating = CourseRatingModel.upsert(
            student_id=student_id,
            course_id=module.get('course_id'),
            target_type=CourseRatingModel.TARGET_MODULE,
            target_id=module_id,
            dismissed=True,
        )
        return rating, None

    @staticmethod
    def _rating_stats(effective_scores, explicit_count):
        if not effective_scores:
            return {
                'avg': None,
                'explicit_count': 0,
                'implicit_count': 0,
                'distribution': {str(i): 0 for i in range(1, 6)},
            }
        distribution = {str(i): 0 for i in range(1, 6)}
        for score in effective_scores:
            key = str(int(score))
            if key in distribution:
                distribution[key] += 1
        return {
            'avg': round(sum(effective_scores) / len(effective_scores), 2),
            'explicit_count': explicit_count,
            'implicit_count': len(effective_scores) - explicit_count,
            'distribution': distribution,
        }

    @staticmethod
    def get_course_ratings(course_id):
        course = CourseModel.get_by_id(course_id)
        if not course:
            return None

        ratings = CourseRatingModel.get_by_course(course_id)
        rating_map = {
            (r['target_type'], r['target_id'], r['student_id']): r
            for r in ratings
            if r
        }
        modules = ModuleModel.get_by_course(course_id)
        lesson_avgs = []
        module_avgs = []
        modules_out = []

        for module in modules:
            mid = module['_id']
            lessons = LessonModel.get_by_module(mid, include_hidden=True)
            visible_lessons = LessonModel.get_by_module(mid, include_hidden=False)
            visible_ids = [lesson['_id'] for lesson in visible_lessons]

            lessons_out = []
            all_viewer_ids = set()
            for lesson in lessons:
                viewers = LessonViewModel.get_viewers(lesson['_id'])
                viewer_ids = [v['student_id'] for v in viewers]
                all_viewer_ids.update(viewer_ids)
                effective = []
                explicit = 0
                for sid in viewer_ids:
                    rating = rating_map.get(
                        (CourseRatingModel.TARGET_LESSON, lesson['_id'], sid)
                    )
                    if rating and rating.get('stars') is not None:
                        effective.append(rating['stars'])
                        explicit += 1
                    else:
                        effective.append(UNRATED_STARS)
                stats = CourseService._rating_stats(effective, explicit)
                if stats['avg'] is not None:
                    lesson_avgs.append(stats['avg'])
                lessons_out.append({
                    '_id': lesson['_id'],
                    'title': lesson.get('title'),
                    **stats,
                })

            completers = []
            if visible_ids:
                candidate_ids = all_viewer_ids
                for sid in candidate_ids:
                    if all(LessonViewModel.has_viewed(lid, sid) for lid in visible_ids):
                        completers.append(sid)

            effective = []
            explicit = 0
            for sid in completers:
                rating = rating_map.get(
                    (CourseRatingModel.TARGET_MODULE, mid, sid)
                )
                if rating and rating.get('stars') is not None:
                    effective.append(rating['stars'])
                    explicit += 1
                else:
                    effective.append(UNRATED_STARS)
            module_stats = CourseService._rating_stats(effective, explicit)
            if module_stats['avg'] is not None:
                module_avgs.append(module_stats['avg'])
            modules_out.append({
                'module_id': mid,
                'name': module.get('name'),
                'weight': MODULE_RATING_WEIGHT,
                **module_stats,
                'lessons': lessons_out,
            })

        denom = len(lesson_avgs) + MODULE_RATING_WEIGHT * len(module_avgs)
        if denom:
            course_avg = (
                sum(lesson_avgs) + MODULE_RATING_WEIGHT * sum(module_avgs)
            ) / denom
            course_avg = round(course_avg, 2)
        else:
            course_avg = None

        explicit_count = sum(m['explicit_count'] for m in modules_out)
        implicit_count = sum(m['implicit_count'] for m in modules_out)
        for module in modules_out:
            for lesson in module['lessons']:
                explicit_count += lesson['explicit_count']
                implicit_count += lesson['implicit_count']

        return {
            'course': {
                'avg': course_avg,
                'explicit_count': explicit_count,
                'implicit_count': implicit_count,
                'weight_lesson': 1,
                'weight_module': MODULE_RATING_WEIGHT,
            },
            'modules': modules_out,
        }

    @staticmethod
    def get_students_progress(course_id):
        """Teacher-facing: returns enriched views + answers for every lesson/activity."""
        from src.app import mongo
        from bson import ObjectId as ObjId

        # ── Resolve classroom students ──────────────────────────────────────
        course = CourseModel.get_by_id(course_id)
        classroom_id = course.get('classroom_id') if course else None

        students_map = {}  # student_id -> {name, email}
        all_student_ids = []
        if classroom_id:
            classroom = mongo.db.classrooms.find_one({'_id': ObjId(classroom_id)})
            if classroom:
                raw_ids = classroom.get('students', [])
                all_student_ids = [str(sid) for sid in raw_ids]
                # Look up user documents for names/emails
                user_docs = list(mongo.db.users.find(
                    {'_id': {'$in': [ObjId(sid) for sid in all_student_ids]}},
                    {'_id': 1, 'name': 1, 'email': 1}
                ))
                for u in user_docs:
                    uid = str(u['_id'])
                    students_map[uid] = {
                        '_id': uid,
                        'name': u.get('name') or u.get('email', uid[-6:]),
                        'email': u.get('email', ''),
                    }

        def student_info(sid):
            return students_map.get(sid, {'_id': sid, 'name': sid[-6:], 'email': ''})

        # ── Build per-module data ───────────────────────────────────────────
        modules = ModuleModel.get_by_course(course_id)
        result = []

        for module in modules:
            mid = module['_id']
            lessons = LessonModel.get_by_module(mid, include_hidden=True)
            activities = ActivityModel.get_by_module(mid, include_hidden=True)

            lessons_data = []
            for lesson in lessons:
                raw_viewers = LessonViewModel.get_viewers(lesson['_id'])
                viewer_ids = {v['student_id'] for v in raw_viewers}
                viewers_enriched = [
                    {**v, **student_info(v['student_id'])}
                    for v in raw_viewers
                ]
                not_viewed = [
                    student_info(sid)
                    for sid in all_student_ids
                    if sid not in viewer_ids
                ]
                lessons_data.append({
                    '_id': lesson['_id'],
                    'title': lesson['title'],
                    'view_count': len(raw_viewers),
                    'viewers': viewers_enriched,
                    'not_viewed': not_viewed,
                })

            activities_data = []
            for activity in activities:
                raw_answers = StudentAnswerModel.get_by_activity(activity['_id'])
                submitted_ids = {a['student_id'] for a in raw_answers}
                submissions_enriched = [
                    {**a, **student_info(a['student_id'])}
                    for a in raw_answers
                ]
                not_submitted = [
                    student_info(sid)
                    for sid in all_student_ids
                    if sid not in submitted_ids
                ]
                scores = [
                    a['score'] for a in raw_answers
                    if a.get('score') is not None
                ]
                avg_score = (sum(scores) / len(scores)) if scores else None
                activities_data.append({
                    '_id': activity['_id'],
                    'title': activity['title'],
                    'feedback_mode': activity.get('feedback_mode') or 'immediate',
                    'submission_count': len(raw_answers),
                    'submissions': submissions_enriched,
                    'not_submitted': not_submitted,
                    'avg_score': round(avg_score, 1) if avg_score is not None else None,
                })

            result.append({
                'module_id': mid,
                'module_name': module['name'],
                'lessons': lessons_data,
                'activities': activities_data,
            })

        # ── "By student" pre-computed summary ──────────────────────────────
        student_summaries = {}
        for sid in all_student_ids:
            student_summaries[sid] = {
                **student_info(sid),
                'lessons_viewed': 0,
                'total_lessons': 0,
                'activities_submitted': 0,
                'total_activities': 0,
                'scores': [],
                'detail': [],          # list of {type, title, viewed/submitted/score}
            }

        for module in result:
            for lesson in module['lessons']:
                viewer_ids = {v['student_id'] for v in lesson['viewers']}
                for sid in all_student_ids:
                    if sid in student_summaries:
                        student_summaries[sid]['total_lessons'] += 1
                        viewed = sid in viewer_ids
                        if viewed:
                            student_summaries[sid]['lessons_viewed'] += 1
                        student_summaries[sid]['detail'].append({
                            'type': 'lesson',
                            'title': lesson['title'],
                            'module': module['module_name'],
                            'viewed': viewed,
                        })

            for activity in module['activities']:
                submitted_ids = {s['student_id'] for s in activity['submissions']}
                sub_by_student = {s['student_id']: s for s in activity['submissions']}
                for sid in all_student_ids:
                    if sid in student_summaries:
                        student_summaries[sid]['total_activities'] += 1
                        submitted = sid in submitted_ids
                        if submitted:
                            student_summaries[sid]['activities_submitted'] += 1
                            score = sub_by_student[sid].get('score')
                            if score is not None:
                                student_summaries[sid]['scores'].append(score)
                        student_summaries[sid]['detail'].append({
                            'type': 'activity',
                            'title': activity['title'],
                            'module': module['module_name'],
                            'submitted': submitted,
                            'score': sub_by_student[sid].get('score') if submitted else None,
                        })

        students_list = []
        for sid, summary in student_summaries.items():
            scores = summary.pop('scores')
            summary['avg_score'] = (
                round(sum(scores) / len(scores), 1) if scores else None
            )
            students_list.append(summary)

        return {
            'progress': result,
            'students': students_list,
            'total_students': len(all_student_ids),
        }

    # ── Teacher answer management ─────────────────────────────────────────────

    @staticmethod
    def get_student_answer_for_teacher(activity_id, student_id):
        """Return the student's submission alongside the activity questions."""
        from src.app.models.course_model import ActivityModel, QuestionModel
        activity = ActivityModel.get_by_id(activity_id)
        questions = QuestionModel.get_by_activity(activity_id)
        answer_doc = StudentAnswerModel.get_by_student_and_activity(student_id, activity_id)
        return {
            'activity': activity,
            'questions': questions,
            'answer': answer_doc,
        }

    @staticmethod
    def set_student_approved(activity_id, student_id, approved: bool):
        StudentAnswerModel.set_approved(activity_id, student_id, approved)
        return {'approved': approved}

    @staticmethod
    def approve_all_answers(activity_id):
        StudentAnswerModel.approve_all(activity_id)
        return {'approved': True}

    @staticmethod
    def reset_student_answer(activity_id, student_id):
        StudentAnswerModel.reset_by_student(activity_id, student_id)
        return {}

    # ── Student Answers ───────────────────────────────────────────────────────

    @staticmethod
    def _answers_equal(student_ans, correct):
        if correct is None:
            return False
        return str(student_ans).strip().lower() == str(correct).strip().lower()

    @staticmethod
    def _score_question(question, student_ans):
        q_type = question.get('type')
        correct = question.get('correct_answer')
        points = question.get('points', 1) or 1

        if q_type in ('multiple_choice', 'dropdown', 'short_answer'):
            if CourseService._answers_equal(student_ans, correct):
                return points
            return 0

        if q_type == 'fill_in_blank':
            expected = correct if isinstance(correct, list) else (
                [correct] if correct is not None and str(correct).strip() else []
            )
            if not expected:
                return 0
            given = student_ans if isinstance(student_ans, list) else (
                [student_ans] if student_ans is not None else []
            )
            hits = 0
            for i, expected_val in enumerate(expected):
                student_val = given[i] if i < len(given) else ''
                if CourseService._answers_equal(student_val, expected_val):
                    hits += 1
            return round(points * hits / len(expected), 2)

        if q_type == 'checkbox':
            if isinstance(correct, list) and isinstance(student_ans, list):
                if set(str(x) for x in student_ans) == set(str(x) for x in correct):
                    return points
            return 0

        return 0

    @staticmethod
    def _redact_answer(activity, answer_doc):
        if not answer_doc:
            return None
        if CourseService.can_see_feedback(activity, answer_doc):
            return answer_doc
        redacted = dict(answer_doc)
        redacted['score'] = None
        redacted['earned_points'] = None
        redacted['total_points'] = None
        redacted['feedback_pending'] = True
        return redacted

    @staticmethod
    def submit_answers(student_id, activity_id, answers):
        activity = ActivityModel.get_by_id(activity_id)
        if not activity:
            raise ValueError('Activity not found')

        questions = QuestionModel.get_by_activity(activity_id, for_student=False)
        question_map = {q['_id']: q for q in questions}

        total_points = sum(q.get('points', 1) or 1 for q in questions)
        earned_points = 0

        for answer in answers:
            q_id = str(answer.get('question_id', ''))
            student_ans = answer.get('answer')
            question = question_map.get(q_id)
            if not question:
                continue
            earned_points += CourseService._score_question(question, student_ans)

        earned_points = round(earned_points, 2)
        score = round((earned_points / total_points) * 100, 1) if total_points > 0 else None

        mode = activity.get('feedback_mode') or 'immediate'
        approved = mode == 'immediate'

        sa = StudentAnswerModel(
            student_id=student_id,
            activity_id=activity_id,
            answers=answers,
            score=score,
            approved=approved,
            earned_points=earned_points,
            total_points=total_points,
        )
        sa.save_to_db()

        can_see = CourseService.can_see_feedback(activity, {'approved': approved})
        return {
            'score': score if can_see else None,
            'earned_points': earned_points if can_see else None,
            'total_points': total_points if can_see else None,
            'xp_earned': int(round(earned_points)) if can_see else 0,
            'feedback_pending': not can_see,
            'approved': approved,
        }

    @staticmethod
    def get_my_answer(student_id, activity_id):
        activity = ActivityModel.get_by_id(activity_id) or {}
        answer_doc = StudentAnswerModel.get_by_student_and_activity(student_id, activity_id)
        return CourseService._redact_answer(activity, answer_doc)

    @staticmethod
    def _classroom_students(classroom_id):
        from src.app import mongo
        from bson import ObjectId as ObjId

        students_map = {}
        all_student_ids = []
        if not classroom_id:
            return all_student_ids, students_map
        classroom = mongo.db.classrooms.find_one({'_id': ObjId(classroom_id)})
        if not classroom:
            return all_student_ids, students_map
        raw_ids = classroom.get('students', [])
        all_student_ids = [str(sid) for sid in raw_ids]
        if not all_student_ids:
            return all_student_ids, students_map
        user_docs = list(mongo.db.users.find(
            {'_id': {'$in': [ObjId(sid) for sid in all_student_ids]}},
            {'_id': 1, 'name': 1, 'email': 1}
        ))
        for u in user_docs:
            uid = str(u['_id'])
            students_map[uid] = {
                '_id': uid,
                'name': u.get('name') or u.get('email', uid[-6:]),
                'email': u.get('email', ''),
            }
        return all_student_ids, students_map

    @staticmethod
    def get_course_ranking(course_id, user_id=None):
        course = CourseModel.get_by_id(course_id)
        if not course:
            return None

        all_student_ids, students_map = CourseService._classroom_students(
            course.get('classroom_id')
        )
        activities = ActivityModel.get_by_course(course_id)

        stats = {
            sid: {
                **students_map.get(sid, {'_id': sid, 'name': sid[-6:], 'email': ''}),
                'xp': 0,
                'scores': [],
                'submitted': 0,
                'perfect': False,
            }
            for sid in all_student_ids
        }

        for activity in activities:
            answers = StudentAnswerModel.get_by_activity(activity['_id'])
            for answer in answers:
                sid = answer.get('student_id')
                if sid not in stats:
                    continue
                stats[sid]['submitted'] += 1
                if not CourseService.can_see_feedback(activity, answer):
                    continue
                earned = answer.get('earned_points')
                if earned is None and answer.get('score') is not None:
                    # Legacy submissions without earned_points
                    total = sum(
                        q.get('points', 1) or 1
                        for q in QuestionModel.get_by_activity(activity['_id'], for_student=False)
                    )
                    earned = round((answer['score'] / 100) * total, 2) if total else 0
                stats[sid]['xp'] += earned or 0
                if answer.get('score') is not None:
                    stats[sid]['scores'].append(answer['score'])
                    if answer['score'] >= 100:
                        stats[sid]['perfect'] = True

        ranking = []
        for sid, row in stats.items():
            scores = row.pop('scores')
            avg_score = round(sum(scores) / len(scores), 1) if scores else None
            ranking.append({
                **row,
                'xp': int(round(row['xp'])),
                'avg_score': avg_score,
                'badges': [],
            })

        ranking.sort(key=lambda r: (-r['xp'], -(r['avg_score'] or -1), r['name'].lower()))
        for index, row in enumerate(ranking, start=1):
            row['rank'] = index
            badges = []
            if row['submitted'] >= 1:
                badges.append('first_step')
            if row['perfect']:
                badges.append('perfect')
            if index <= 3 and row['xp'] > 0:
                badges.append('podium')
            if row['avg_score'] is not None and row['avg_score'] >= 85:
                badges.append('top_performer')
            if row['avg_score'] is not None and row['avg_score'] < 60:
                badges.append('at_risk')
            row['badges'] = badges
            row.pop('perfect', None)

        me = None
        if user_id:
            me = next((r for r in ranking if r['_id'] == str(user_id)), None)

        return {
            'ranking': ranking,
            'me': me,
            'total_activities': len(activities),
        }

    # ── Lesson decks ─────────────────────────────────────────────────────────

    @staticmethod
    def _lesson_classroom(lesson_id):
        try:
            lesson = LessonModel.get_by_id(lesson_id)
        except (InvalidId, TypeError):
            lesson = None
        if not lesson:
            return None, None, None, 'Lesson not found'
        course = CourseModel.get_by_id(lesson.get('course_id'))
        if not course:
            return lesson, None, None, 'Course not found'
        from src.app.models.classroom_model import ClassroomModel
        classroom = ClassroomModel.get_by_id(course.get('classroom_id'))
        return lesson, course, classroom, None

    @staticmethod
    def _serialize_lesson_deck(link, user_id, is_teacher, viewed):
        from src.app.models.deck_model import DeckModel
        from src.app.models.lesson_deck_model import StudentLessonDeckModel
        from src.app.models.publish_status import is_released

        deck = DeckModel.get_by_id(link['deck_id'])
        if not deck:
            return None
        released = is_released(deck.get('status'), deck.get('scheduled_at'))
        if not is_teacher and not released:
            return None
        unlocked = False
        if user_id:
            unlocked = StudentLessonDeckModel.has_unlocked(
                user_id, link['lesson_id'], link['deck_id']
            )
        card_ids = link.get('card_ids') or []
        total = len(card_ids) if card_ids else len(deck.get('cards') or [])
        return {
            'deck_id': link['deck_id'],
            'lesson_id': link['lesson_id'],
            'name': deck.get('name'),
            'image': deck.get('image'),
            'status': deck.get('status') or 'published',
            'scheduled_at': deck.get('scheduled_at'),
            'card_ids': card_ids,
            'whole_deck': not bool(card_ids),
            'total_cards': total,
            'unlocked': unlocked,
            'viewed': viewed,
            'can_unlock': bool(user_id) and not is_teacher and released and viewed and not unlocked,
        }

    @staticmethod
    def list_lesson_decks(lesson_id, user_id=None, is_teacher=False):
        from src.app.models.lesson_deck_model import LessonDeckModel

        viewed = bool(
            user_id and not is_teacher and LessonViewModel.has_viewed(lesson_id, user_id)
        )
        if is_teacher:
            viewed = True
        items = []
        for link in LessonDeckModel.get_by_lesson(lesson_id):
            serialized = CourseService._serialize_lesson_deck(
                link, user_id, is_teacher, viewed
            )
            if serialized:
                items.append(serialized)
        return items

    @staticmethod
    def link_lesson_deck(lesson_id, user_id, data):
        from src.app.models.deck_model import DeckModel
        from src.app.models.lesson_deck_model import LessonDeckModel
        from src.app.models.publish_status import validate_status_payload
        from src.app.services.deck_service import DeckService

        lesson, course, classroom, error = CourseService._lesson_classroom(lesson_id)
        if error:
            return None, error, 404
        if CourseService._course_teacher_id(course) != str(user_id):
            return None, 'Only the course teacher can link decks', 403
        collection_id = classroom.get('collection') if classroom else None
        if not collection_id:
            return None, 'Classroom collection not found', 400

        card_ids = data.get('card_ids') or []
        deck_id = data.get('deck_id')
        created_new = False
        if not deck_id:
            name = (data.get('name') or '').strip()
            if not name:
                return None, 'deck_id or name is required', 400
            try:
                status, scheduled_at = validate_status_payload(
                    data.get('status') or 'published',
                    data.get('scheduled_at'),
                )
            except ValueError as exc:
                return None, str(exc), 400
            created = DeckService.create_deck(
                name,
                collection_id,
                image=data.get('image'),
                cards=data.get('cards'),
                status=status,
                scheduled_at=scheduled_at,
                init_progress=False,
            )
            deck_id = created.get('deck_id')
            created_new = True

        deck = DeckModel.get_by_id(deck_id)
        if not deck:
            return None, 'Deck not found', 404
        if not created_new:
            collection_decks = [
                str(item) for item in (classroom.get('decks') or [])
            ]
            if str(deck_id) not in collection_decks:
                return None, 'Deck does not belong to this classroom', 400

        deck_card_ids = set(str(cid) for cid in (deck.get('cards') or []))
        normalized_card_ids = [str(cid) for cid in card_ids]
        if normalized_card_ids and not set(normalized_card_ids).issubset(deck_card_ids):
            return None, 'card_ids must belong to the deck', 400

        link = LessonDeckModel.link(lesson_id, deck_id, normalized_card_ids)
        viewed = LessonViewModel.has_viewed(lesson_id, user_id)
        serialized = CourseService._serialize_lesson_deck(
            link, user_id, True, viewed
        )
        return serialized, None, 200

    @staticmethod
    def update_lesson_deck(lesson_id, deck_id, user_id, data):
        from src.app.models.deck_model import DeckModel
        from src.app.models.lesson_deck_model import LessonDeckModel

        lesson, course, classroom, error = CourseService._lesson_classroom(lesson_id)
        if error:
            return None, error, 404
        if CourseService._course_teacher_id(course) != str(user_id):
            return None, 'Only the course teacher can update lesson decks', 403
        deck = DeckModel.get_by_id(deck_id)
        if not deck:
            return None, 'Deck not found', 404
        card_ids = [str(cid) for cid in (data.get('card_ids') or [])]
        deck_card_ids = set(str(cid) for cid in (deck.get('cards') or []))
        if card_ids and not set(card_ids).issubset(deck_card_ids):
            return None, 'card_ids must belong to the deck', 400
        link = LessonDeckModel.update_card_ids(lesson_id, deck_id, card_ids)
        if not link:
            return None, 'Link not found', 404
        viewed = LessonViewModel.has_viewed(lesson_id, user_id)
        return CourseService._serialize_lesson_deck(link, user_id, True, viewed), None, 200

    @staticmethod
    def unlink_lesson_deck(lesson_id, deck_id, user_id):
        from src.app.models.lesson_deck_model import LessonDeckModel

        lesson, course, _classroom, error = CourseService._lesson_classroom(lesson_id)
        if error:
            return None, error, 404
        if CourseService._course_teacher_id(course) != str(user_id):
            return None, 'Only the course teacher can unlink decks', 403
        if not LessonDeckModel.unlink(lesson_id, deck_id):
            return None, 'Link not found', 404
        return {'message': 'Deck unlinked'}, None, 200

    @staticmethod
    def unlock_lesson_deck(lesson_id, deck_id, user_id):
        from src.app.models.deck_model import DeckModel
        from src.app.models.user_progress_model import UserProgressModel
        from src.app.models.lesson_deck_model import (
            LessonDeckModel,
            StudentLessonDeckModel,
            ContentVisibility,
        )
        from src.app.models.publish_status import is_released
        from src.app.models.classroom_model import ClassroomModel

        lesson, course, classroom, error = CourseService._lesson_classroom(lesson_id)
        if error:
            return None, error, 404
        if CourseService._course_teacher_id(course) == str(user_id):
            return None, 'Teachers cannot generate lesson decks', 403
        if not classroom:
            return None, 'Classroom not found', 404
        if not ClassroomModel.is_student(course.get('classroom_id'), user_id):
            return None, 'Only classroom students can unlock this deck', 403

        link = LessonDeckModel.get_link(lesson_id, deck_id)
        if not link:
            return None, 'Deck is not linked to this lesson', 404
        deck = DeckModel.get_by_id(deck_id)
        if not deck or not is_released(deck.get('status'), deck.get('scheduled_at')):
            return None, 'Deck is not available', 403
        if not LessonViewModel.has_viewed(lesson_id, user_id):
            return None, 'Watch the lesson before generating the deck', 403

        StudentLessonDeckModel.unlock(user_id, lesson_id, deck_id)
        filtered = ContentVisibility.filter_deck_for_user(
            deck,
            user_id,
            collection=None,
            is_teacher=False,
        )
        card_ids = (filtered or {}).get('cards') or []
        for card_id in card_ids:
            UserProgressModel.create_or_update(user_id, deck_id, card_id)
        viewed = True
        serialized = CourseService._serialize_lesson_deck(
            link, user_id, False, viewed
        )
        return serialized, None, 200

    # ── Duplication ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_scheduled_at(value):
        if not value:
            return None
        if hasattr(value, 'isoformat'):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _assert_teacher_owns_classroom(user_id, classroom_id):
        from src.app.models.classroom_model import ClassroomModel

        classroom = ClassroomModel.get_by_id(classroom_id)
        if not classroom:
            return None, 'Classroom not found', 404
        if str(classroom.get('teacher')) != str(user_id):
            return None, 'Unauthorized', 403
        return classroom, None, 200

    @staticmethod
    def _get_target_collection_id(classroom):
        return classroom.get('collection') if classroom else None

    @staticmethod
    def _copy_lesson_decks(source_lesson_id, new_lesson_id, target_collection_id, include_decks):
        if not include_decks or not target_collection_id:
            return
        from src.app.models.lesson_deck_model import LessonDeckModel
        from src.app.services.deck_service import DeckService

        for link in LessonDeckModel.get_by_lesson(source_lesson_id):
            cloned = DeckService.clone_deck(link['deck_id'], target_collection_id)
            if not cloned:
                continue
            card_map = cloned.get('card_id_map') or {}
            old_card_ids = link.get('card_ids') or []
            if old_card_ids:
                new_card_ids = [
                    card_map[str(card_id)]
                    for card_id in old_card_ids
                    if str(card_id) in card_map
                ]
            else:
                new_card_ids = []
            LessonDeckModel.link(new_lesson_id, cloned['deck_id'], new_card_ids)

    @staticmethod
    def _copy_activity_questions(source_activity_id, new_activity_id):
        questions = QuestionModel.get_by_activity(source_activity_id, for_student=False)
        for question in questions:
            QuestionModel(
                text=question.get('text'),
                type=question.get('type'),
                options=question.get('options') or [],
                correct_answer=question.get('correct_answer'),
                show_answer=question.get('show_answer', True),
                points=question.get('points') or 1,
                activity_id=new_activity_id,
            ).save_to_db()

    @staticmethod
    def duplicate_lesson(
        lesson_id,
        user_id,
        target_module_id,
        target_course_id,
        include_decks=False,
        title=None,
    ):
        lesson = LessonModel.get_by_id(lesson_id)
        if not lesson:
            return None, 'Lesson not found', 404

        source_course = CourseModel.get_by_id(lesson.get('course_id'))
        if not source_course or CourseService._course_teacher_id(source_course) != str(user_id):
            return None, 'Unauthorized', 403

        target_course = CourseModel.get_by_id(target_course_id)
        if not target_course:
            return None, 'Target course not found', 404

        target_module = ModuleModel.get_by_id(target_module_id)
        if not target_module or str(target_module.get('course_id')) != str(target_course_id):
            return None, 'Target module not found', 404

        classroom, error, status = CourseService._assert_teacher_owns_classroom(
            user_id, target_course.get('classroom_id')
        )
        if error:
            return None, error, status

        _, src_error, src_status = CourseService._assert_teacher_owns_classroom(
            user_id, source_course.get('classroom_id')
        )
        if src_error:
            return None, src_error, src_status

        new_lesson = LessonModel(
            title=title or f"Copy of {lesson.get('title')}",
            video_url=lesson.get('video_url'),
            video_type=lesson.get('video_type'),
            description=lesson.get('description'),
            content_html=lesson.get('content_html') or '',
            lesson_format=lesson.get('lesson_format') or 'text',
            module_id=target_module_id,
            course_id=target_course_id,
            visible=lesson.get('visible', True),
            scheduled_at=CourseService._parse_scheduled_at(lesson.get('scheduled_at')),
        )
        result = new_lesson.save_to_db()
        new_lesson_id = result['lesson_id']
        CourseService._copy_lesson_decks(
            lesson_id,
            new_lesson_id,
            CourseService._get_target_collection_id(classroom),
            include_decks,
        )
        return {'lesson_id': new_lesson_id}, None, 201

    @staticmethod
    def duplicate_module(
        module_id,
        user_id,
        target_course_id,
        include_decks=False,
        name=None,
    ):
        module = ModuleModel.get_by_id(module_id)
        if not module:
            return None, 'Module not found', 404

        source_course = CourseModel.get_by_id(module.get('course_id'))
        if not source_course or CourseService._course_teacher_id(source_course) != str(user_id):
            return None, 'Unauthorized', 403

        target_course = CourseModel.get_by_id(target_course_id)
        if not target_course:
            return None, 'Target course not found', 404

        classroom, error, status = CourseService._assert_teacher_owns_classroom(
            user_id, target_course.get('classroom_id')
        )
        if error:
            return None, error, status

        _, src_error, src_status = CourseService._assert_teacher_owns_classroom(
            user_id, source_course.get('classroom_id')
        )
        if src_error:
            return None, src_error, src_status

        target_collection_id = CourseService._get_target_collection_id(classroom)
        new_module = ModuleModel(
            name=name or f"Copy of {module.get('name')}",
            course_id=target_course_id,
            scheduled_at=CourseService._parse_scheduled_at(module.get('scheduled_at')),
        )
        module_result = new_module.save_to_db()
        new_module_id = module_result['module_id']

        for lesson in LessonModel.get_by_module(module_id, include_hidden=True):
            copied = LessonModel(
                title=lesson.get('title'),
                video_url=lesson.get('video_url'),
                video_type=lesson.get('video_type'),
                description=lesson.get('description'),
                content_html=lesson.get('content_html') or '',
                lesson_format=lesson.get('lesson_format') or 'text',
                module_id=new_module_id,
                course_id=target_course_id,
                visible=lesson.get('visible', True),
                scheduled_at=CourseService._parse_scheduled_at(lesson.get('scheduled_at')),
            )
            lesson_result = copied.save_to_db()
            CourseService._copy_lesson_decks(
                lesson['_id'],
                lesson_result['lesson_id'],
                target_collection_id,
                include_decks,
            )

        for activity in ActivityModel.get_by_module(module_id, include_hidden=True):
            copied_activity = ActivityModel(
                title=activity.get('title'),
                description=activity.get('description'),
                module_id=new_module_id,
                course_id=target_course_id,
                visible=activity.get('visible', True),
                scheduled_at=CourseService._parse_scheduled_at(activity.get('scheduled_at')),
                feedback_mode=activity.get('feedback_mode') or 'immediate',
            )
            activity_result = copied_activity.save_to_db()
            CourseService._copy_activity_questions(
                activity['_id'],
                activity_result['activity_id'],
            )

        return {'module_id': new_module_id}, None, 201

    @staticmethod
    def duplicate_course(
        course_id,
        user_id,
        target_classroom_id,
        include_decks=False,
        name=None,
    ):
        course = CourseModel.get_by_id(course_id)
        if not course or CourseService._course_teacher_id(course) != str(user_id):
            return None, 'Unauthorized', 403

        classroom, error, status = CourseService._assert_teacher_owns_classroom(
            user_id, target_classroom_id
        )
        if error:
            return None, error, status

        _, src_error, src_status = CourseService._assert_teacher_owns_classroom(
            user_id, course.get('classroom_id')
        )
        if src_error:
            return None, src_error, src_status

        new_course = CourseModel(
            name=name or f"Copy of {course.get('name')}",
            description=course.get('description') or '',
            classroom_id=target_classroom_id,
            teacher_id=user_id,
        )
        course_result = new_course.save_to_db()
        new_course_id = course_result['course_id']

        modules = ModuleModel.get_by_course(course_id, include_hidden=True)
        for module in modules:
            CourseService.duplicate_module(
                module['_id'],
                user_id,
                new_course_id,
                include_decks=include_decks,
                name=module.get('name'),
            )

        return {'course_id': new_course_id}, None, 201

    # ── Lesson annotations ────────────────────────────────────────────────────

    @staticmethod
    def list_lesson_annotations(lesson_id, viewer_user_id):
        lesson = LessonModel.get_by_id(lesson_id)
        if not lesson:
            return None, 'Lesson not found', 404
        from src.app.models.lesson_annotation_model import LessonAnnotationModel

        items = LessonAnnotationModel.list_visible(lesson_id, viewer_user_id)
        for item in items:
            item['is_mine'] = str(item['user_id']) == str(viewer_user_id)
        return items, None, 200

    @staticmethod
    def create_lesson_annotation(lesson_id, user_id, author_name, data):
        lesson = LessonModel.get_by_id(lesson_id)
        if not lesson:
            return None, 'Lesson not found', 404
        from src.app.models.lesson_annotation_model import LessonAnnotationModel

        is_teacher = CourseService.is_course_teacher(lesson.get('course_id'), user_id)
        try:
            created = LessonAnnotationModel.create(
                lesson_id,
                user_id,
                author_name,
                is_public=is_teacher,
                data=data,
            )
        except ValueError as exc:
            return None, str(exc), 400
        created['is_mine'] = True
        return created, None, 201

    @staticmethod
    def update_lesson_annotation(annotation_id, user_id, data):
        from src.app.models.lesson_annotation_model import LessonAnnotationModel

        try:
            updated = LessonAnnotationModel.update(annotation_id, user_id, data)
        except PermissionError as exc:
            return None, str(exc), 403
        if not updated:
            return None, 'Annotation not found', 404
        updated['is_mine'] = str(updated['user_id']) == str(user_id)
        return updated, None, 200

    @staticmethod
    def delete_lesson_annotation(annotation_id, user_id):
        from src.app.models.lesson_annotation_model import LessonAnnotationModel

        try:
            deleted = LessonAnnotationModel.delete(annotation_id, user_id)
        except PermissionError as exc:
            return None, str(exc), 403
        if not deleted:
            return None, 'Annotation not found', 404
        return {'message': 'Annotation deleted'}, None, 200

