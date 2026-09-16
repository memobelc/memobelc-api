from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from src.app import mongo

HIGHLIGHT_COLORS = ('#FEF08A', '#BBF7D0', '#BFDBFE', '#FBCFE8')


class LessonAnnotationModel:
    @staticmethod
    def ensure_indexes():
        mongo.db.lesson_annotations.create_index('lesson_id')
        mongo.db.lesson_annotations.create_index(
            [('lesson_id', 1), ('user_id', 1)]
        )

    @staticmethod
    def _to_dict(doc):
        if not doc:
            return None
        return {
            '_id': str(doc['_id']),
            'lesson_id': str(doc['lesson_id']),
            'user_id': str(doc['user_id']),
            'author_name': doc.get('author_name') or '',
            'is_public': bool(doc.get('is_public')),
            'start_offset': int(doc.get('start_offset', 0)),
            'end_offset': int(doc.get('end_offset', 0)),
            'quote': doc.get('quote') or '',
            'highlight_color': doc.get('highlight_color') or HIGHLIGHT_COLORS[0],
            'comment': doc.get('comment') or '',
            'created_at': doc.get('created_at'),
            'updated_at': doc.get('updated_at'),
        }

    @staticmethod
    def list_visible(lesson_id, viewer_user_id):
        query = {
            'lesson_id': ObjectId(lesson_id),
            '$or': [
                {'is_public': True},
                {'user_id': ObjectId(viewer_user_id)},
            ],
        }
        docs = list(
            mongo.db.lesson_annotations.find(query).sort('start_offset', 1)
        )
        return [LessonAnnotationModel._to_dict(doc) for doc in docs]

    @staticmethod
    def get_by_id(annotation_id):
        try:
            doc = mongo.db.lesson_annotations.find_one({'_id': ObjectId(annotation_id)})
        except (InvalidId, TypeError):
            return None
        return LessonAnnotationModel._to_dict(doc)

    @staticmethod
    def create(lesson_id, user_id, author_name, is_public, data):
        now = datetime.now(timezone.utc)
        start = int(data['start_offset'])
        end = int(data['end_offset'])
        if end <= start:
            raise ValueError('Invalid text range')
        color = data.get('highlight_color') or HIGHLIGHT_COLORS[0]
        if color not in HIGHLIGHT_COLORS:
            color = HIGHLIGHT_COLORS[0]
        doc = {
            'lesson_id': ObjectId(lesson_id),
            'user_id': ObjectId(user_id),
            'author_name': author_name or '',
            'is_public': bool(is_public),
            'start_offset': start,
            'end_offset': end,
            'quote': (data.get('quote') or '').strip(),
            'highlight_color': color,
            'comment': (data.get('comment') or '').strip(),
            'created_at': now,
            'updated_at': now,
        }
        result = mongo.db.lesson_annotations.insert_one(doc)
        return LessonAnnotationModel.get_by_id(result.inserted_id)

    @staticmethod
    def update(annotation_id, user_id, data):
        existing = mongo.db.lesson_annotations.find_one({'_id': ObjectId(annotation_id)})
        if not existing:
            return None
        if str(existing['user_id']) != str(user_id):
            raise PermissionError('Not allowed to edit this annotation')

        update_fields = {'updated_at': datetime.now(timezone.utc)}
        if 'comment' in data:
            update_fields['comment'] = (data.get('comment') or '').strip()
        if 'highlight_color' in data:
            color = data.get('highlight_color') or HIGHLIGHT_COLORS[0]
            update_fields['highlight_color'] = (
                color if color in HIGHLIGHT_COLORS else HIGHLIGHT_COLORS[0]
            )

        mongo.db.lesson_annotations.update_one(
            {'_id': ObjectId(annotation_id)},
            {'$set': update_fields},
        )
        return LessonAnnotationModel.get_by_id(annotation_id)

    @staticmethod
    def delete(annotation_id, user_id):
        existing = mongo.db.lesson_annotations.find_one({'_id': ObjectId(annotation_id)})
        if not existing:
            return False
        if str(existing['user_id']) != str(user_id):
            raise PermissionError('Not allowed to delete this annotation')
        mongo.db.lesson_annotations.delete_one({'_id': ObjectId(annotation_id)})
        return True
