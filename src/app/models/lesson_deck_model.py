"""Lesson-deck links and student unlocks."""

from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId

from src.app import mongo
from src.app.models.publish_status import (
    is_released,
    isoformat_dt,
    normalize_status,
)


def _oid(value):
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    return ObjectId(str(value))


def _sid(value):
    return str(value) if value is not None else None


class LessonDeckModel:
    @staticmethod
    def ensure_indexes():
        mongo.db.lesson_decks.create_index(
            [('lesson_id', 1), ('deck_id', 1)], unique=True
        )
        mongo.db.lesson_decks.create_index('deck_id')
        mongo.db.student_lesson_decks.create_index(
            [('student_id', 1), ('lesson_id', 1), ('deck_id', 1)], unique=True
        )
        mongo.db.student_lesson_decks.create_index(
            [('student_id', 1), ('deck_id', 1)]
        )

    @staticmethod
    def _to_dict(doc):
        if not doc:
            return None
        card_ids = doc.get('card_ids') or []
        return {
            '_id': _sid(doc.get('_id')),
            'lesson_id': _sid(doc.get('lesson_id')),
            'deck_id': _sid(doc.get('deck_id')),
            'card_ids': [_sid(cid) for cid in card_ids],
            'created_at': isoformat_dt(doc.get('created_at')),
            'updated_at': isoformat_dt(doc.get('updated_at')),
        }

    @staticmethod
    def link(lesson_id, deck_id, card_ids=None):
        now = datetime.now(timezone.utc)
        card_oids = [_oid(cid) for cid in (card_ids or [])]
        mongo.db.lesson_decks.update_one(
            {'lesson_id': _oid(lesson_id), 'deck_id': _oid(deck_id)},
            {
                '$set': {
                    'card_ids': card_oids,
                    'updated_at': now,
                },
                '$setOnInsert': {
                    'lesson_id': _oid(lesson_id),
                    'deck_id': _oid(deck_id),
                    'created_at': now,
                },
            },
            upsert=True,
        )
        doc = mongo.db.lesson_decks.find_one(
            {'lesson_id': _oid(lesson_id), 'deck_id': _oid(deck_id)}
        )
        return LessonDeckModel._to_dict(doc)

    @staticmethod
    def unlink(lesson_id, deck_id):
        result = mongo.db.lesson_decks.delete_one(
            {'lesson_id': _oid(lesson_id), 'deck_id': _oid(deck_id)}
        )
        return result.deleted_count > 0

    @staticmethod
    def update_card_ids(lesson_id, deck_id, card_ids):
        card_oids = [_oid(cid) for cid in (card_ids or [])]
        result = mongo.db.lesson_decks.update_one(
            {'lesson_id': _oid(lesson_id), 'deck_id': _oid(deck_id)},
            {
                '$set': {
                    'card_ids': card_oids,
                    'updated_at': datetime.now(timezone.utc),
                }
            },
        )
        if result.matched_count == 0:
            return None
        doc = mongo.db.lesson_decks.find_one(
            {'lesson_id': _oid(lesson_id), 'deck_id': _oid(deck_id)}
        )
        return LessonDeckModel._to_dict(doc)

    @staticmethod
    def get_by_lesson(lesson_id):
        docs = mongo.db.lesson_decks.find({'lesson_id': _oid(lesson_id)})
        return [LessonDeckModel._to_dict(doc) for doc in docs]

    @staticmethod
    def get_by_deck(deck_id):
        docs = mongo.db.lesson_decks.find({'deck_id': _oid(deck_id)})
        return [LessonDeckModel._to_dict(doc) for doc in docs]

    @staticmethod
    def get_link(lesson_id, deck_id):
        doc = mongo.db.lesson_decks.find_one(
            {'lesson_id': _oid(lesson_id), 'deck_id': _oid(deck_id)}
        )
        return LessonDeckModel._to_dict(doc)

    @staticmethod
    def is_deck_linked(deck_id):
        return mongo.db.lesson_decks.count_documents(
            {'deck_id': _oid(deck_id)}, limit=1
        ) > 0

    @staticmethod
    def linked_deck_ids():
        return {
            _sid(doc['deck_id'])
            for doc in mongo.db.lesson_decks.find({}, {'deck_id': 1})
            if doc.get('deck_id')
        }

    @staticmethod
    def delete_by_deck(deck_id):
        mongo.db.lesson_decks.delete_many({'deck_id': _oid(deck_id)})
        mongo.db.student_lesson_decks.delete_many({'deck_id': _oid(deck_id)})

    @staticmethod
    def delete_by_lesson(lesson_id):
        mongo.db.lesson_decks.delete_many({'lesson_id': _oid(lesson_id)})
        mongo.db.student_lesson_decks.delete_many({'lesson_id': _oid(lesson_id)})


class StudentLessonDeckModel:
    @staticmethod
    def unlock(student_id, lesson_id, deck_id):
        now = datetime.now(timezone.utc)
        mongo.db.student_lesson_decks.update_one(
            {
                'student_id': _oid(student_id),
                'lesson_id': _oid(lesson_id),
                'deck_id': _oid(deck_id),
            },
            {
                '$setOnInsert': {
                    'student_id': _oid(student_id),
                    'lesson_id': _oid(lesson_id),
                    'deck_id': _oid(deck_id),
                    'unlocked_at': now,
                }
            },
            upsert=True,
        )
        doc = mongo.db.student_lesson_decks.find_one(
            {
                'student_id': _oid(student_id),
                'lesson_id': _oid(lesson_id),
                'deck_id': _oid(deck_id),
            }
        )
        return {
            'student_id': _sid(doc.get('student_id')),
            'lesson_id': _sid(doc.get('lesson_id')),
            'deck_id': _sid(doc.get('deck_id')),
            'unlocked_at': isoformat_dt(doc.get('unlocked_at')),
        }

    @staticmethod
    def has_unlocked(student_id, lesson_id, deck_id):
        return mongo.db.student_lesson_decks.count_documents(
            {
                'student_id': _oid(student_id),
                'lesson_id': _oid(lesson_id),
                'deck_id': _oid(deck_id),
            },
            limit=1,
        ) > 0

    @staticmethod
    def has_unlocked_deck(student_id, deck_id):
        return mongo.db.student_lesson_decks.count_documents(
            {
                'student_id': _oid(student_id),
                'deck_id': _oid(deck_id),
            },
            limit=1,
        ) > 0

    @staticmethod
    def get_unlocks_for_deck(student_id, deck_id):
        docs = mongo.db.student_lesson_decks.find(
            {
                'student_id': _oid(student_id),
                'deck_id': _oid(deck_id),
            }
        )
        return [
            {
                'student_id': _sid(doc.get('student_id')),
                'lesson_id': _sid(doc.get('lesson_id')),
                'deck_id': _sid(doc.get('deck_id')),
                'unlocked_at': isoformat_dt(doc.get('unlocked_at')),
            }
            for doc in docs
        ]


class ContentVisibility:
    @staticmethod
    def is_classroom_teacher(collection, user_id):
        if not collection or not user_id:
            return False
        classroom_id = collection.get('classroom')
        if not classroom_id:
            return False
        try:
            classroom = mongo.db.classrooms.find_one(
                {'_id': ObjectId(str(classroom_id))}
            )
        except (InvalidId, TypeError):
            return False
        if not classroom:
            return False
        return str(classroom.get('teacher')) == str(user_id)

    @staticmethod
    def find_collection_for_deck(deck_id):
        try:
            collection = mongo.db.collections.find_one(
                {'decks': ObjectId(str(deck_id))}
            )
        except (InvalidId, TypeError):
            return None
        if not collection:
            return None
        from src.app.models.collection_model import CollectionModel
        return CollectionModel(**collection).to_dict()

    @staticmethod
    def _released_card_ids(card_ids, is_teacher):
        if is_teacher:
            return [_sid(cid) for cid in card_ids]
        from src.app.models.card_model import CardModel

        visible = []
        for card_id in card_ids:
            card = CardModel.get_by_id(card_id)
            if not card:
                continue
            status = getattr(card, 'status', None)
            scheduled_at = getattr(card, 'scheduled_at', None)
            if isinstance(card, dict):
                status = card.get('status')
                scheduled_at = card.get('scheduled_at')
            if is_released(status, scheduled_at):
                visible.append(_sid(card_id))
        return visible

    @staticmethod
    def unlocked_card_ids_for_student(deck_id, user_id, all_card_ids):
        links = LessonDeckModel.get_by_deck(deck_id)
        if not links:
            return set(_sid(cid) for cid in all_card_ids)

        unlocks = StudentLessonDeckModel.get_unlocks_for_deck(user_id, deck_id)
        if not unlocks:
            return set()

        unlocked_lessons = {item['lesson_id'] for item in unlocks}
        allowed = set()
        for link in links:
            if link['lesson_id'] not in unlocked_lessons:
                continue
            subset = link.get('card_ids') or []
            if not subset:
                return set(_sid(cid) for cid in all_card_ids)
            allowed.update(_sid(cid) for cid in subset)
        return allowed

    @staticmethod
    def filter_deck_for_user(deck, user_id, collection=None, is_teacher=None):
        """Return a copy of deck with filtered card ids, or None if hidden."""
        if not deck:
            return None
        deck_id = _sid(deck.get('_id') or deck.get('id'))
        card_ids = [_sid(cid) for cid in (deck.get('cards') or [])]

        if collection is None:
            collection = ContentVisibility.find_collection_for_deck(deck_id)

        classroom_collection = bool(collection and collection.get('classroom'))
        if is_teacher is None:
            is_teacher = ContentVisibility.is_classroom_teacher(
                collection, user_id
            )

        result = dict(deck)
        result['lesson_linked'] = LessonDeckModel.is_deck_linked(deck_id)
        result['status'] = normalize_status(deck.get('status'))
        result['scheduled_at'] = isoformat_dt(deck.get('scheduled_at'))

        if not classroom_collection or is_teacher or not user_id:
            result['cards'] = card_ids
            return result

        if not is_released(deck.get('status'), deck.get('scheduled_at')):
            return None

        if result['lesson_linked']:
            allowed = ContentVisibility.unlocked_card_ids_for_student(
                deck_id, user_id, card_ids
            )
            if not allowed:
                return None
            card_ids = [cid for cid in card_ids if cid in allowed]

        result['cards'] = ContentVisibility._released_card_ids(
            card_ids, is_teacher=False
        )
        return result

    @staticmethod
    def student_should_get_progress(user_id, deck_id, card_id=None):
        collection = ContentVisibility.find_collection_for_deck(deck_id)
        if not collection or not collection.get('classroom'):
            return True
        if ContentVisibility.is_classroom_teacher(collection, user_id):
            return True
        from src.app.models.deck_model import DeckModel

        deck = DeckModel.get_by_id(deck_id)
        filtered = ContentVisibility.filter_deck_for_user(
            deck, user_id, collection, is_teacher=False
        )
        if not filtered:
            return False
        if card_id is None:
            return True
        return _sid(card_id) in (filtered.get('cards') or [])
