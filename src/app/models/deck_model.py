import random
from bson import ObjectId
from datetime import datetime, timedelta, timezone
from src.app import mongo
from .collection_model import CollectionModel
from .user_model import UserModel
from .user_progress_model import UserProgressModel
from .publish_status import (
    DEFAULT_STATUS,
    isoformat_dt,
    normalize_status,
    parse_scheduled_at,
)


class DeckModel:
    def __init__(
        self,
        _id=None,
        name=None,
        created_at=None,
        updated_at=None,
        collection_id=None,
        image=None,
        cards=None,
        status=None,
        scheduled_at=None,
        **kwargs,
    ):
        self.id = str(_id) if _id else None
        self.name = name
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.collection_id = collection_id
        self.image = image
        self.cards = cards or []
        self.status = normalize_status(status)
        self.scheduled_at = parse_scheduled_at(scheduled_at)

    @staticmethod
    def get_by_id(deck_id):
        """Busca um Deck pelo ID e retorna como dicionário"""
        deck = mongo.db.decks.find_one({"_id": ObjectId(deck_id)})
        if deck:
            result = DeckModel(**deck)
            return result.to_dict()
        return None

    def save_to_db(self):
        """Salva o  deck no banco de dados MongoDB"""
        deck_data = {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "image": self.image,
            "cards": self.cards,
            "status": self.status or DEFAULT_STATUS,
            "scheduled_at": self.scheduled_at,
        }
        result = mongo.db.decks.insert_one(deck_data)
        self.id = str(result.inserted_id)
        if self.collection_id:
            CollectionModel.add_decks_to_collection(
                self.collection_id, [str(result.inserted_id)]
            )
        return str(result.inserted_id)

    @staticmethod
    def get_all_decks():
        """Retorna todos os  decks como uma lista de dicionários"""
        decks = mongo.db.decks.find()
        return [DeckModel(**d).to_dict() for d in decks]

    @staticmethod
    def add_cards_to_deck(deck_id, cards_ids):
        """Adiciona uma lista de cards IDs ao deck especificado"""
        # Converte os IDs de decks para ObjectId
        cards_object_ids = [ObjectId(card_id) for card_id in cards_ids]

        # Atualiza o Collection, adicionando os IDs dos decks
        result = mongo.db.decks.update_one(
            {"_id": ObjectId(deck_id)},
            {
                "$push": {"cards": {"$each": cards_object_ids}},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )

        return result.modified_count > 0

    @staticmethod
    def get_decks_by_collection_id(collection_id, user_id):
        """ "Busca todos os decks do user e retorna a quantidade de cartas totais e pendentes."""
        collection = CollectionModel.get_by_id(collection_id)
        if not collection:
            return {"decks": []}

        from .classroom_membership_model import ClassroomMembershipModel
        from .lesson_deck_model import ContentVisibility

        freeze = None
        if collection.get("classroom") and user_id:
            freeze = ClassroomMembershipModel.get_freeze_for_collection(
                user_id, collection.get("_id")
            )

        is_teacher = ContentVisibility.is_classroom_teacher(collection, user_id)
        decks_list = []

        for deck_id in collection.get("decks", []):
            deck_id_str = str(deck_id)
            if freeze and deck_id_str not in freeze["allowed_decks"]:
                continue
            deck = DeckModel.get_by_id(deck_id)
            if not deck:
                continue
            if freeze:
                allowed_cards = set(freeze["allowed_cards"].get(deck_id_str) or [])
                deck["cards"] = [
                    card_id for card_id in deck.get("cards", []) if str(card_id) in allowed_cards
                ]
            elif not freeze:
                deck = ContentVisibility.filter_deck_for_user(
                    deck, user_id, collection, is_teacher=is_teacher
                )
                if not deck:
                    continue

            allowed_ids = set(str(card_id) for card_id in deck.get("cards", []))
            review_cards = UserProgressModel.get_pending_cards(user_id, deck.get("_id") or deck.get("id"))
            review_cards = [
                card for card in review_cards if str(card.get("card_id")) in allowed_ids
            ]
            pending_count = len(review_cards)

            deck.update(
                {
                    "total_cards": len(deck.get("cards", [])),
                    "pending_cards": pending_count,
                }
            )

            from .card_model import CardModel

            cards_list = []

            for card_id in deck.get("cards", []):
                card = CardModel.get_by_id(card_id)
                cards_list.append(card.to_dict() if card and hasattr(card, "to_dict") else card)

            deck.update(
                {
                    "cards": cards_list,
                }
            )
            decks_list.append(deck)

        return {"decks": decks_list}

    @staticmethod
    def update_deck(deck_id, data):
        current = DeckModel.get_by_id(deck_id)
        if not current:
            return None
        from .publish_status import validate_status_payload

        update_fields = {"updated_at": datetime.now(timezone.utc)}
        if "name" in data and data["name"] is not None:
            update_fields["name"] = data["name"]
        if "image" in data:
            update_fields["image"] = data["image"]
        if "status" in data or "scheduled_at" in data:
            status, scheduled_at = validate_status_payload(
                data.get("status", current.get("status")),
                data.get("scheduled_at") if "scheduled_at" in data else current.get("scheduled_at"),
            )
            update_fields["status"] = status
            update_fields["scheduled_at"] = scheduled_at
        mongo.db.decks.update_one(
            {"_id": ObjectId(deck_id)},
            {"$set": update_fields},
        )
        return DeckModel.get_by_id(deck_id)

    @staticmethod
    def delete_deck(deck_id):
        deck = DeckModel.get_by_id(deck_id)
        if not deck:
            return False
        from .lesson_deck_model import LessonDeckModel

        LessonDeckModel.delete_by_deck(deck_id)
        mongo.db.collections.update_many(
            {"decks": ObjectId(deck_id)},
            {"$pull": {"decks": ObjectId(deck_id)}},
        )
        for card_id in deck.get("cards") or []:
            try:
                mongo.db.cards.delete_one({"_id": ObjectId(str(card_id))})
            except Exception:
                pass
        mongo.db.user_progress.delete_many({"deck_id": ObjectId(deck_id)})
        mongo.db.decks.delete_one({"_id": ObjectId(deck_id)})
        return True
    
    @staticmethod
    def save_deck(user_id, deck_id, collection_id):
        deck = DeckModel.get_by_id(deck_id)
        
        if(deck):
            CollectionModel.add_decks_to_collection(
                    collection_id, [deck.get("_id")]
                )
        else:
            return


        for card_id in deck.get("cards", []):
            UserProgressModel.create_or_update(user_id, deck_id, card_id)
            
        return True
    
    @staticmethod
    def check_if_the_user_has_the_deck(user_id, deck_id):
        user = UserModel.find_by_id(user_id)
        if not user:
            return {"user_has_deck": "false", "error": "User not found"}
        user = user.to_dict() if hasattr(user, "to_dict") else user

        for collection_id in user.get("collections", []):
            collection = CollectionModel.get_by_id(collection_id)
            
            if not collection:
                continue  

            if deck_id in collection.get("decks", []):
                return {"user_has_deck": "true"}

        return {"user_has_deck": "false"} 
    
    

    def to_dict(self):
        """Converte um documento deck para dicionário"""
        return {
            "_id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "image": self.image,
            "cards": [str(ObjectId(card_id)) for card_id in self.cards],
            "status": self.status or DEFAULT_STATUS,
            "scheduled_at": isoformat_dt(self.scheduled_at),
        }
