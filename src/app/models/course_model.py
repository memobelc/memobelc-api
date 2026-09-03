import re
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timezone
from src.app import mongo
from src.app.config import Config

BLANK_RE = re.compile(r'_{3,}')


def count_blanks(text):
    return len(BLANK_RE.findall(text or ''))


def _parse_price(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class CourseModel:
    def __init__(self, _id=None, name=None, description=None, classroom_id=None,
                 teacher_id=None, created_at=None, updated_at=None,
                 checkout_enabled=False, price=None, **kwargs):
        self._id = str(_id) if _id else None
        self.name = name
        self.description = description or ''
        self.classroom_id = classroom_id
        self.teacher_id = teacher_id
        self.checkout_enabled = bool(checkout_enabled)
        self.price = _parse_price(price)
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)

    @staticmethod
    def build_checkout_url(course_id):
        if not course_id:
            return None
        base = str(getattr(Config, 'FRONT_BASE_URL', '') or '').rstrip('/')
        return f'{base}/checkout/{course_id}' if base else f'/checkout/{course_id}'

    def save_to_db(self):
        data = {
            'name': self.name,
            'description': self.description,
            'classroom_id': ObjectId(self.classroom_id),
            'teacher_id': ObjectId(self.teacher_id),
            'checkout_enabled': bool(self.checkout_enabled),
            'price': self.price,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        result = mongo.db.courses.insert_one(data)
        self._id = str(result.inserted_id)
        return {'course_id': self._id}

    def to_dict(self):
        return {
            '_id': self._id,
            'name': self.name,
            'description': self.description,
            'classroom_id': str(self.classroom_id) if self.classroom_id else None,
            'teacher_id': str(self.teacher_id) if self.teacher_id else None,
            'checkout_enabled': bool(self.checkout_enabled),
            'price': self.price,
            'checkout_url': CourseModel.build_checkout_url(self._id),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    @staticmethod
    def get_by_id(course_id):
        try:
            doc = mongo.db.courses.find_one({'_id': ObjectId(course_id)})
        except (InvalidId, TypeError):
            return None
        if doc:
            return CourseModel(**doc).to_dict()
        return None

    @staticmethod
    def has_visible_content(course_id):
        now = datetime.now(timezone.utc)
        released_modules = list(
            mongo.db.course_modules.find(
                {
                    'course_id': ObjectId(course_id),
                    '$or': [
                        {'scheduled_at': None},
                        {'scheduled_at': {'$lte': now}},
                    ],
                },
                {'_id': 1},
            )
        )
        module_ids = [module['_id'] for module in released_modules]
        if not module_ids:
            return False
        visible_filter = {
            'module_id': {'$in': module_ids},
            'visible': True,
            '$or': [
                {'scheduled_at': None},
                {'scheduled_at': {'$lte': now}},
            ],
        }
        return (
            mongo.db.lessons.find_one(visible_filter) is not None
            or mongo.db.activities.find_one(visible_filter) is not None
        )

    @staticmethod
    def get_by_classroom(classroom_id):
        docs = list(
            mongo.db.courses
            .find({'classroom_id': ObjectId(classroom_id)})
            .sort('created_at', 1)
        )
        return [CourseModel(**doc).to_dict() for doc in docs]

    @staticmethod
    def update(course_id, update_data):
        update_data['updated_at'] = datetime.now(timezone.utc)
        mongo.db.courses.update_one({'_id': ObjectId(course_id)}, {'$set': update_data})

    @staticmethod
    def delete(course_id):
        mongo.db.courses.delete_one({'_id': ObjectId(course_id)})


class ModuleModel:
    def __init__(self, _id=None, name=None, order=0, course_id=None,
                 scheduled_at=None, created_at=None, updated_at=None, **kwargs):
        self._id = str(_id) if _id else None
        self.name = name
        self.order = order
        self.course_id = course_id
        self.scheduled_at = scheduled_at
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)

    def save_to_db(self):
        max_doc = mongo.db.course_modules.find_one(
            {'course_id': ObjectId(self.course_id)},
            sort=[('order', -1)]
        )
        self.order = (max_doc['order'] + 1) if max_doc else 0

        data = {
            'name': self.name,
            'order': self.order,
            'course_id': ObjectId(self.course_id),
            'scheduled_at': self.scheduled_at,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        result = mongo.db.course_modules.insert_one(data)
        self._id = str(result.inserted_id)
        return {'module_id': self._id}

    def to_dict(self):
        return {
            '_id': self._id,
            'name': self.name,
            'order': self.order,
            'course_id': str(self.course_id) if self.course_id else None,
            'scheduled_at': (
                self.scheduled_at.isoformat()
                if self.scheduled_at and hasattr(self.scheduled_at, 'isoformat')
                else self.scheduled_at
            ),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    @staticmethod
    def get_by_id(module_id):
        doc = mongo.db.course_modules.find_one({'_id': ObjectId(module_id)})
        if doc:
            return ModuleModel(**doc).to_dict()
        return None

    @staticmethod
    def get_by_course(course_id, include_hidden=True):
        query = {'course_id': ObjectId(course_id)}
        if not include_hidden:
            # Hide modules whose scheduled release is still in the future
            now = datetime.now(timezone.utc)
            query['$or'] = [
                {'scheduled_at': None},
                {'scheduled_at': {'$lte': now}},
            ]
        docs = list(
            mongo.db.course_modules
            .find(query)
            .sort('order', 1)
        )
        return [ModuleModel(**doc).to_dict() for doc in docs]

    @staticmethod
    def update(module_id, update_data):
        update_data['updated_at'] = datetime.now(timezone.utc)
        mongo.db.course_modules.update_one({'_id': ObjectId(module_id)}, {'$set': update_data})

    @staticmethod
    def delete(module_id):
        CourseRatingModel.delete_by_target(CourseRatingModel.TARGET_MODULE, module_id)
        mongo.db.course_modules.delete_one({'_id': ObjectId(module_id)})

    @staticmethod
    def reorder(course_id, module_ids):
        for index, module_id in enumerate(module_ids):
            mongo.db.course_modules.update_one(
                {'_id': ObjectId(module_id), 'course_id': ObjectId(course_id)},
                {'$set': {'order': index, 'updated_at': datetime.now(timezone.utc)}}
            )


class LessonModel:
    def __init__(self, _id=None, title=None, video_url=None, video_type='youtube',
                 description=None, order=0, module_id=None, course_id=None,
                 visible=True, scheduled_at=None, created_at=None, updated_at=None, **kwargs):
        self._id = str(_id) if _id else None
        self.title = title
        self.video_url = video_url or ''
        self.video_type = video_type or 'youtube'
        self.description = description or ''
        self.order = order
        self.module_id = module_id
        self.course_id = course_id
        self.visible = visible if visible is not None else True
        self.scheduled_at = scheduled_at
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)

    def save_to_db(self):
        max_doc = mongo.db.lessons.find_one(
            {'module_id': ObjectId(self.module_id)},
            sort=[('order', -1)]
        )
        self.order = (max_doc['order'] + 1) if max_doc else 0

        data = {
            'title': self.title,
            'video_url': self.video_url,
            'video_type': self.video_type,
            'description': self.description,
            'order': self.order,
            'module_id': ObjectId(self.module_id),
            'course_id': ObjectId(self.course_id),
            'visible': self.visible,
            'scheduled_at': self.scheduled_at,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        result = mongo.db.lessons.insert_one(data)
        self._id = str(result.inserted_id)
        return {'lesson_id': self._id}

    def to_dict(self):
        return {
            '_id': self._id,
            'title': self.title,
            'video_url': self.video_url,
            'video_type': self.video_type,
            'description': self.description,
            'order': self.order,
            'module_id': str(self.module_id) if self.module_id else None,
            'course_id': str(self.course_id) if self.course_id else None,
            'visible': self.visible,
            'scheduled_at': (
                self.scheduled_at.isoformat()
                if self.scheduled_at and hasattr(self.scheduled_at, 'isoformat')
                else self.scheduled_at
            ),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    @staticmethod
    def get_by_id(lesson_id):
        doc = mongo.db.lessons.find_one({'_id': ObjectId(lesson_id)})
        if doc:
            return LessonModel(**doc).to_dict()
        return None

    @staticmethod
    def get_by_module(module_id, include_hidden=True):
        query = {'module_id': ObjectId(module_id)}
        if not include_hidden:
            now = datetime.now(timezone.utc)
            query['visible'] = True
            query['$or'] = [
                {'scheduled_at': None},
                {'scheduled_at': {'$lte': now}}
            ]
        docs = list(mongo.db.lessons.find(query).sort('order', 1))
        return [LessonModel(**doc).to_dict() for doc in docs]

    @staticmethod
    def update(lesson_id, update_data):
        update_data['updated_at'] = datetime.now(timezone.utc)
        mongo.db.lessons.update_one({'_id': ObjectId(lesson_id)}, {'$set': update_data})

    @staticmethod
    def delete(lesson_id):
        mongo.db.lesson_views.delete_many({'lesson_id': ObjectId(lesson_id)})
        CourseRatingModel.delete_by_target(CourseRatingModel.TARGET_LESSON, lesson_id)
        mongo.db.lessons.delete_one({'_id': ObjectId(lesson_id)})

    @staticmethod
    def reorder(module_id, lesson_ids):
        for index, lesson_id in enumerate(lesson_ids):
            mongo.db.lessons.update_one(
                {'_id': ObjectId(lesson_id), 'module_id': ObjectId(module_id)},
                {'$set': {'order': index, 'updated_at': datetime.now(timezone.utc)}}
            )


class ActivityModel:
    FEEDBACK_MODES = ('immediate', 'after_correction')

    def __init__(self, _id=None, title=None, description=None, order=0,
                 module_id=None, course_id=None, visible=True, scheduled_at=None,
                 feedback_mode='immediate', created_at=None, updated_at=None, **kwargs):
        self._id = str(_id) if _id else None
        self.title = title
        self.description = description or ''
        self.order = order
        self.module_id = module_id
        self.course_id = course_id
        self.visible = visible if visible is not None else True
        self.scheduled_at = scheduled_at
        self.feedback_mode = (
            feedback_mode if feedback_mode in self.FEEDBACK_MODES else 'immediate'
        )
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)

    def save_to_db(self):
        max_doc = mongo.db.activities.find_one(
            {'module_id': ObjectId(self.module_id)},
            sort=[('order', -1)]
        )
        self.order = (max_doc['order'] + 1) if max_doc else 0

        data = {
            'title': self.title,
            'description': self.description,
            'order': self.order,
            'module_id': ObjectId(self.module_id),
            'course_id': ObjectId(self.course_id),
            'visible': self.visible,
            'scheduled_at': self.scheduled_at,
            'feedback_mode': self.feedback_mode,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        result = mongo.db.activities.insert_one(data)
        self._id = str(result.inserted_id)
        return {'activity_id': self._id}

    def to_dict(self):
        return {
            '_id': self._id,
            'title': self.title,
            'description': self.description,
            'order': self.order,
            'module_id': str(self.module_id) if self.module_id else None,
            'course_id': str(self.course_id) if self.course_id else None,
            'visible': self.visible,
            'feedback_mode': self.feedback_mode or 'immediate',
            'scheduled_at': (
                self.scheduled_at.isoformat()
                if self.scheduled_at and hasattr(self.scheduled_at, 'isoformat')
                else self.scheduled_at
            ),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }

    @staticmethod
    def get_by_id(activity_id):
        doc = mongo.db.activities.find_one({'_id': ObjectId(activity_id)})
        if doc:
            return ActivityModel(**doc).to_dict()
        return None

    @staticmethod
    def get_by_module(module_id, include_hidden=True):
        query = {'module_id': ObjectId(module_id)}
        if not include_hidden:
            now = datetime.now(timezone.utc)
            query['visible'] = True
            query['$or'] = [
                {'scheduled_at': None},
                {'scheduled_at': {'$lte': now}}
            ]
        docs = list(mongo.db.activities.find(query).sort('order', 1))
        return [ActivityModel(**doc).to_dict() for doc in docs]

    @staticmethod
    def update(activity_id, update_data):
        update_data['updated_at'] = datetime.now(timezone.utc)
        mongo.db.activities.update_one({'_id': ObjectId(activity_id)}, {'$set': update_data})

    @staticmethod
    def delete(activity_id):
        mongo.db.activities.delete_one({'_id': ObjectId(activity_id)})

    @staticmethod
    def get_by_course(course_id):
        docs = list(
            mongo.db.activities.find({'course_id': ObjectId(course_id)}).sort('order', 1)
        )
        return [ActivityModel(**doc).to_dict() for doc in docs]

    @staticmethod
    def reorder(module_id, activity_ids):
        for index, activity_id in enumerate(activity_ids):
            mongo.db.activities.update_one(
                {'_id': ObjectId(activity_id), 'module_id': ObjectId(module_id)},
                {'$set': {'order': index, 'updated_at': datetime.now(timezone.utc)}}
            )


class QuestionModel:
    VALID_TYPES = [
        'multiple_choice', 'checkbox', 'dropdown',
        'paragraph', 'short_answer', 'fill_in_blank'
    ]

    def __init__(self, _id=None, text=None, type=None, options=None, correct_answer=None,
                 show_answer=True, points=1, activity_id=None, order=0,
                 created_at=None, updated_at=None, **kwargs):
        self._id = str(_id) if _id else None
        self.text = text
        self.type = type
        self.options = options or []
        self.correct_answer = correct_answer
        self.show_answer = show_answer if show_answer is not None else True
        self.points = points or 1
        self.activity_id = activity_id
        self.order = order
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)

    def save_to_db(self):
        max_doc = mongo.db.questions.find_one(
            {'activity_id': ObjectId(self.activity_id)},
            sort=[('order', -1)]
        )
        self.order = (max_doc['order'] + 1) if max_doc else 0

        data = {
            'text': self.text,
            'type': self.type,
            'options': self.options,
            'correct_answer': self.correct_answer,
            'show_answer': self.show_answer,
            'points': self.points,
            'activity_id': ObjectId(self.activity_id),
            'order': self.order,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        result = mongo.db.questions.insert_one(data)
        self._id = str(result.inserted_id)
        return {'question_id': self._id}

    def to_dict(self, include_correct_answer=True):
        d = {
            '_id': self._id,
            'text': self.text,
            'type': self.type,
            'options': self.options,
            'show_answer': self.show_answer,
            'points': self.points,
            'activity_id': str(self.activity_id) if self.activity_id else None,
            'order': self.order,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        if include_correct_answer:
            d['correct_answer'] = self.correct_answer
        return d

    @staticmethod
    def get_by_id(question_id):
        doc = mongo.db.questions.find_one({'_id': ObjectId(question_id)})
        if doc:
            return QuestionModel(**doc).to_dict()
        return None

    @staticmethod
    def get_by_activity(activity_id, for_student=False):
        docs = list(
            mongo.db.questions
            .find({'activity_id': ObjectId(activity_id)})
            .sort('order', 1)
        )
        return [QuestionModel(**doc).to_dict(include_correct_answer=not for_student) for doc in docs]

    @staticmethod
    def update(question_id, update_data):
        update_data['updated_at'] = datetime.now(timezone.utc)
        mongo.db.questions.update_one({'_id': ObjectId(question_id)}, {'$set': update_data})

    @staticmethod
    def delete(question_id):
        mongo.db.questions.delete_one({'_id': ObjectId(question_id)})

    @staticmethod
    def delete_by_activity(activity_id):
        mongo.db.questions.delete_many({'activity_id': ObjectId(activity_id)})

    @staticmethod
    def reorder(activity_id, question_ids):
        for index, question_id in enumerate(question_ids):
            mongo.db.questions.update_one(
                {'_id': ObjectId(question_id), 'activity_id': ObjectId(activity_id)},
                {'$set': {'order': index, 'updated_at': datetime.now(timezone.utc)}}
            )


class LessonViewModel:
    """Tracks which students have viewed a lesson."""

    @staticmethod
    def mark_viewed(lesson_id, student_id):
        mongo.db.lesson_views.update_one(
            {
                'lesson_id': ObjectId(lesson_id),
                'student_id': ObjectId(student_id),
            },
            {'$set': {'viewed_at': datetime.now(timezone.utc)}},
            upsert=True,
        )

    @staticmethod
    def get_viewers(lesson_id):
        docs = list(mongo.db.lesson_views.find({'lesson_id': ObjectId(lesson_id)}))
        return [
            {
                'student_id': str(doc['student_id']),
                'viewed_at': doc['viewed_at'].isoformat() if hasattr(doc['viewed_at'], 'isoformat') else doc['viewed_at'],
            }
            for doc in docs
        ]

    @staticmethod
    def has_viewed(lesson_id, student_id):
        doc = mongo.db.lesson_views.find_one({
            'lesson_id': ObjectId(lesson_id),
            'student_id': ObjectId(student_id),
        })
        return doc is not None

    @staticmethod
    def delete_by_lesson(lesson_id):
        mongo.db.lesson_views.delete_many({'lesson_id': ObjectId(lesson_id)})


class CourseRatingModel:
    """Student star ratings for lessons and modules."""

    TARGET_LESSON = 'lesson'
    TARGET_MODULE = 'module'
    VALID_TARGETS = (TARGET_LESSON, TARGET_MODULE)

    @staticmethod
    def ensure_indexes():
        mongo.db.course_ratings.create_index(
            [('student_id', 1), ('target_type', 1), ('target_id', 1)],
            unique=True,
        )
        mongo.db.course_ratings.create_index([('course_id', 1), ('target_type', 1)])
        mongo.db.course_ratings.create_index('target_id')

    @staticmethod
    def _to_dict(doc):
        if not doc:
            return None
        stars = doc.get('stars')
        return {
            '_id': str(doc['_id']) if doc.get('_id') else None,
            'student_id': str(doc['student_id']) if doc.get('student_id') else None,
            'course_id': str(doc['course_id']) if doc.get('course_id') else None,
            'target_type': doc.get('target_type'),
            'target_id': str(doc['target_id']) if doc.get('target_id') else None,
            'stars': int(stars) if stars is not None else None,
            'dismissed': bool(doc.get('dismissed')),
            'created_at': (
                doc['created_at'].isoformat()
                if doc.get('created_at') and hasattr(doc['created_at'], 'isoformat')
                else doc.get('created_at')
            ),
            'updated_at': (
                doc['updated_at'].isoformat()
                if doc.get('updated_at') and hasattr(doc['updated_at'], 'isoformat')
                else doc.get('updated_at')
            ),
        }

    @staticmethod
    def upsert(student_id, course_id, target_type, target_id, stars=None, dismissed=False):
        now = datetime.now(timezone.utc)
        filt = {
            'student_id': ObjectId(student_id),
            'target_type': target_type,
            'target_id': ObjectId(target_id),
        }
        existing = mongo.db.course_ratings.find_one(filt)
        set_fields = {
            'course_id': ObjectId(course_id),
            'dismissed': bool(dismissed),
            'updated_at': now,
        }
        if stars is not None:
            set_fields['stars'] = int(stars)
            set_fields['dismissed'] = False
        elif dismissed:
            if existing is None or existing.get('stars') is None:
                set_fields['stars'] = None
        update = {'$set': set_fields}
        if existing is None:
            update['$setOnInsert'] = {'created_at': now}
        mongo.db.course_ratings.update_one(filt, update, upsert=True)
        return CourseRatingModel.get(student_id, target_type, target_id)

    @staticmethod
    def get(student_id, target_type, target_id):
        doc = mongo.db.course_ratings.find_one({
            'student_id': ObjectId(student_id),
            'target_type': target_type,
            'target_id': ObjectId(target_id),
        })
        return CourseRatingModel._to_dict(doc)

    @staticmethod
    def get_by_course(course_id):
        docs = list(mongo.db.course_ratings.find({'course_id': ObjectId(course_id)}))
        return [CourseRatingModel._to_dict(doc) for doc in docs]

    @staticmethod
    def get_student_ratings_for_course(student_id, course_id):
        docs = list(mongo.db.course_ratings.find({
            'student_id': ObjectId(student_id),
            'course_id': ObjectId(course_id),
        }))
        return [CourseRatingModel._to_dict(doc) for doc in docs]

    @staticmethod
    def delete_by_target(target_type, target_id):
        mongo.db.course_ratings.delete_many({
            'target_type': target_type,
            'target_id': ObjectId(target_id),
        })

    @staticmethod
    def delete_by_course(course_id):
        mongo.db.course_ratings.delete_many({'course_id': ObjectId(course_id)})


class StudentAnswerModel:
    def __init__(self, _id=None, student_id=None, activity_id=None, answers=None,
                 submitted_at=None, score=None, approved=False,
                 earned_points=None, total_points=None, **kwargs):
        self._id = str(_id) if _id else None
        self.student_id = student_id
        self.activity_id = activity_id
        self.answers = answers or []
        self.submitted_at = submitted_at or datetime.now(timezone.utc)
        self.score = score
        self.approved = approved
        self.earned_points = earned_points
        self.total_points = total_points

    def save_to_db(self):
        data = {
            'student_id': ObjectId(self.student_id),
            'activity_id': ObjectId(self.activity_id),
            'answers': self.answers,
            'submitted_at': self.submitted_at,
            'score': self.score,
            'approved': self.approved or False,
            'earned_points': self.earned_points,
            'total_points': self.total_points,
        }
        mongo.db.student_answers.update_one(
            {
                'student_id': ObjectId(self.student_id),
                'activity_id': ObjectId(self.activity_id),
            },
            {'$set': data},
            upsert=True,
        )
        return {}

    def to_dict(self):
        return {
            '_id': self._id,
            'student_id': str(self.student_id) if self.student_id else None,
            'activity_id': str(self.activity_id) if self.activity_id else None,
            'answers': self.answers,
            'submitted_at': (
                self.submitted_at.isoformat()
                if self.submitted_at and hasattr(self.submitted_at, 'isoformat')
                else self.submitted_at
            ),
            'score': self.score,
            'approved': self.approved or False,
            'earned_points': self.earned_points,
            'total_points': self.total_points,
        }

    @staticmethod
    def get_by_student_and_activity(student_id, activity_id):
        doc = mongo.db.student_answers.find_one({
            'student_id': ObjectId(student_id),
            'activity_id': ObjectId(activity_id),
        })
        if doc:
            return StudentAnswerModel(**doc).to_dict()
        return None

    @staticmethod
    def get_by_activity(activity_id):
        docs = list(mongo.db.student_answers.find({'activity_id': ObjectId(activity_id)}))
        result = []
        for doc in docs:
            item = StudentAnswerModel(**doc).to_dict()
            if doc.get('_id') and not item.get('_id'):
                item['_id'] = str(doc['_id'])
            result.append(item)
        return result

    @staticmethod
    def set_approved(activity_id, student_id, approved: bool):
        mongo.db.student_answers.update_one(
            {
                'activity_id': ObjectId(activity_id),
                'student_id': ObjectId(student_id),
            },
            {'$set': {'approved': approved}},
        )

    @staticmethod
    def approve_all(activity_id):
        mongo.db.student_answers.update_many(
            {'activity_id': ObjectId(activity_id)},
            {'$set': {'approved': True}},
        )

    @staticmethod
    def reset_by_student(activity_id, student_id):
        mongo.db.student_answers.delete_one({
            'activity_id': ObjectId(activity_id),
            'student_id': ObjectId(student_id),
        })

    @staticmethod
    def delete_by_activity(activity_id):
        mongo.db.student_answers.delete_many({'activity_id': ObjectId(activity_id)})
