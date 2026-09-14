import random
from bson import ObjectId
from bson.errors import InvalidId
from datetime import datetime, timedelta, timezone
from src.app import mongo
from src.app.config import Config
from .user_model import UserModel
from .user_progress_model import UserProgressModel
from .deck_model import DeckModel
from .classroom_membership_model import ClassroomMembershipModel


def _parse_price(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ClassroomModel:
    def __init__(self, _id=None, teacher=None,  created_at=None, updated_at=None, students=None, guests=None, name=None, collection=None, collection_data=None, students_data=None, checkout_allowed=False, checkout_enabled=False, price=None, image=None, **kwargs):
        self._id = str(_id) if _id else None
        self.name = name
        self.teacher = teacher
        self.students = students or []
        self.guests = guests or []
        self.collection = collection
        self.collection_data = collection_data
        self.students_data = students_data
        self.checkout_allowed = bool(checkout_allowed)
        self.checkout_enabled = bool(checkout_enabled)
        self.price = _parse_price(price)
        self.image = image
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)

    @staticmethod
    def build_checkout_url(classroom_id):
        if not classroom_id:
            return None
        base = str(getattr(Config, 'FRONT_BASE_URL', '') or '').rstrip('/')
        return f'{base}/checkout/{classroom_id}' if base else f'/checkout/{classroom_id}'
        
    def save_to_db(self):
        class_data = {
            'name': self.name,
            'teacher': ObjectId(self.teacher),
            'collection': ObjectId(self.collection),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'students': self.students,
            'checkout_allowed': bool(self.checkout_allowed),
            'checkout_enabled': bool(self.checkout_enabled),
            'price': self.price,
        }
        
        result = mongo.db.classrooms.insert_one(class_data)
        self.id = str(result.inserted_id)

        return {"class_id": str(result.inserted_id)}
    
    @staticmethod
    def get_classrooms_by_user(user_id):
        
        
        pipeline = [
            {"$match": {"teacher": ObjectId(user_id)}},
            {
                "$lookup": {
                    "from": "collections",
                    "localField": "collection",
                    "foreignField": "_id", 
                    "as": "collection_data"
                }
            },
            {
                "$unwind": {
                    "path": "$collection_data",
                    "preserveNullAndEmptyArrays": True
                }
            },
            {
            "$lookup": {
                "from": "users",
                "localField": "students",
                "foreignField": "_id",
                "as": "students_data"
            }
        }
        ]

        classrooms = list(mongo.db.classrooms.aggregate(pipeline))
        classrooms_list = [ClassroomModel(**classroom).to_dict() for classroom in classrooms]

        return classrooms_list
    
    
    @staticmethod
    def get_classrooms_as_student(user_id):
        pipeline = [
            {"$match": {"students": ObjectId(user_id)}},
            {
                "$lookup": {
                    "from": "collections",
                    "localField": "collection",
                    "foreignField": "_id",
                    "as": "collection_data"
                }
            },
            {
                "$unwind": {
                    "path": "$collection_data",
                    "preserveNullAndEmptyArrays": True
                }
            },
            {
                "$lookup": {
                    "from": "users",
                    "localField": "students",
                    "foreignField": "_id",
                    "as": "students_data"
                }
            }
        ]
        classrooms = list(mongo.db.classrooms.aggregate(pipeline))
        return [ClassroomModel(**classroom).to_dict() for classroom in classrooms]

    @staticmethod
    def get_by_id(classroom_id):
        try:
            match_id = ObjectId(classroom_id)
        except (InvalidId, TypeError):
            return None
        
        pipeline = [
            {"$match": {"_id": match_id}},
            {
                "$lookup": {
                    "from": "collections",
                    "localField": "collection",
                    "foreignField": "_id", 
                    "as": "collection_data"
                }
            },
            {
                "$unwind": {
                    "path": "$collection_data",
                    "preserveNullAndEmptyArrays": True
                }
            },
            {
            "$lookup": {
                "from": "users",
                "localField": "students",
                "foreignField": "_id",
                "as": "students_data"
            }
            }
        ]

        classroom = mongo.db.classrooms.aggregate(pipeline)
        classroom = next(classroom, None) 

        if classroom:
            classroom = ClassroomModel(**classroom).to_dict()
            
        return classroom
    
    @staticmethod
    def is_student(classroom_id, user_id):
        if not classroom_id or not user_id:
            return False
        try:
            doc = mongo.db.classrooms.find_one(
                {'_id': ObjectId(classroom_id), 'students': ObjectId(user_id)},
                {'_id': 1},
            )
        except Exception:
            return False
        return doc is not None

    @staticmethod
    def update(classroom_id, update_data):
        update_data = dict(update_data or {})
        update_data['updated_at'] = datetime.now(timezone.utc)
        mongo.db.classrooms.update_one({'_id': ObjectId(classroom_id)}, {'$set': update_data})
        return ClassroomModel.get_by_id(classroom_id)

    @staticmethod
    def list_all():
        pipeline = [
            {
                '$lookup': {
                    'from': 'users',
                    'localField': 'teacher',
                    'foreignField': '_id',
                    'as': 'teacher_data',
                }
            },
            {
                '$unwind': {
                    'path': '$teacher_data',
                    'preserveNullAndEmptyArrays': True,
                }
            },
            {'$sort': {'created_at': -1}},
        ]
        docs = list(mongo.db.classrooms.aggregate(pipeline))
        result = []
        for doc in docs:
            item = ClassroomModel(**doc).to_dict()
            teacher = doc.get('teacher_data') or {}
            item['teacher_name'] = teacher.get('name')
            item['teacher_email'] = teacher.get('email')
            result.append(item)
        return result

    @staticmethod
    def add_students(classroom_id, user_id):
        
        classroom = ClassroomModel.get_by_id(classroom_id)
        
        mongo.db.classrooms.update_one(
            {"_id": ObjectId(classroom_id)},
            {"$addToSet": {"students": {"$each": [ObjectId(user_id)]}}}
        )
        
        UserModel.add_collections_to_user(user_id, [classroom.get('collection')])
        ClassroomMembershipModel.mark_joined(
            classroom_id, user_id, classroom.get('collection')
        )

        from src.app.models.lesson_deck_model import LessonDeckModel
        from src.app.models.publish_status import is_released
        from src.app.models.card_model import CardModel

        for item in classroom.get('decks') or []:
            deck = DeckModel.get_by_id(item)
            if not deck:
                continue
            if LessonDeckModel.is_deck_linked(deck.get('_id')):
                continue
            if not is_released(deck.get('status'), deck.get('scheduled_at')):
                continue
            for card_id in deck.get("cards", []):
                card = CardModel.get_by_id(card_id)
                if not card:
                    continue
                if not is_released(getattr(card, 'status', None), getattr(card, 'scheduled_at', None)):
                    continue
                UserProgressModel.create_or_update(user_id, deck.get('_id'), card_id)
        
        
    @staticmethod
    def add_guest(classroom_id, email):
        
        mongo.db.classrooms.update_one(
            {"_id": ObjectId(classroom_id)},
            {"$addToSet": {"guests": {"$each": [email]}}}
        )
        
    @staticmethod
    def remove_user_guest(classroom_id, email):
        mongo.db.classrooms.update_one(
            {"_id": ObjectId(classroom_id)},
            { "$pull": { "guests": email } }
        )

    @staticmethod
    def remove_student(classroom_id, user_id):
        classroom = ClassroomModel.get_by_id(classroom_id)
        decks_snapshot = []
        collection_id = None
        if classroom:
            collection_id = classroom.get('collection')
            from src.app.models.lesson_deck_model import ContentVisibility
            from src.app.models.collection_model import CollectionModel
            collection = CollectionModel.get_by_id(collection_id) if collection_id else None
            for deck_id in classroom.get('decks') or []:
                deck = DeckModel.get_by_id(deck_id)
                if not deck:
                    continue
                filtered = ContentVisibility.filter_deck_for_user(
                    deck, user_id, collection, is_teacher=False
                )
                if filtered:
                    decks_snapshot.append(filtered)
        ClassroomMembershipModel.freeze_on_leave(
            classroom_id, user_id, collection_id, decks_snapshot
        )
        mongo.db.classrooms.update_one(
            {"_id": ObjectId(classroom_id)},
            {"$pull": {"students": ObjectId(user_id)}},
        )
        
    def to_dict(self):
        """Converte um documento classroom para dicionário"""
        collection_image = (self.collection_data or {}).get('image')
        return {
            '_id': self._id,
            'name': self.name,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'teacher': str(self.teacher),
            'students': [{'_id': str(student['_id']), 'name': student.get('name', ''), 'email': student.get('email', '')} for student in (self.students_data or [])],
            'guests': [guest for guest in self.guests],
            'collection': str(self.collection),
            'image': self.image or collection_image,
            'cover_image': self.image,
            'collection_image': collection_image,
            'decks': [str(item) for item in (self.collection_data or {}).get('decks') or []],
            'checkout_allowed': bool(self.checkout_allowed),
            'checkout_enabled': bool(self.checkout_enabled),
            'price': self.price,
            'checkout_url': ClassroomModel.build_checkout_url(self._id),
        }