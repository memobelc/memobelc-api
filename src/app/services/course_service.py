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

    # ── Lessons ───────────────────────────────────────────────────────────────

    @staticmethod
    def create_lesson(title, video_url, video_type, description,
                      module_id, course_id, visible, scheduled_at):
        lesson = LessonModel(
            title=title,
            video_url=video_url,
            video_type=video_type,
            description=description,
            module_id=module_id,
            course_id=course_id,
            visible=visible,
            scheduled_at=scheduled_at,
        )
        return lesson.save_to_db()

    @staticmethod
    def update_lesson(lesson_id, update_data):
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
    def get_lesson_view_status(lesson_id, student_id):
        viewed = LessonViewModel.has_viewed(lesson_id, student_id)
        return {'viewed': viewed}

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
