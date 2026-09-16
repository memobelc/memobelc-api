from src.app.models.card_model import CardModel
from src.app.models.deck_model import DeckModel
from datetime import datetime, timezone
from bson import ObjectId
from src.app import mongo

from src.app.services.notification_service import NotificationService


VALID_CARD_TYPES = ("text", "multiple_choice", "image")


class CardService:
    @staticmethod
    def validate_card_payload(data):
        """Valida e normaliza o payload de criação/atualização de carta."""
        if not data:
            raise ValueError("request body is required")

        card_type = data.get("card_type") or "text"
        if card_type not in VALID_CARD_TYPES:
            raise ValueError("invalid card_type")

        front = data.get("front")
        back = data.get("back")
        audio = data.get("audio")
        image = data.get("image")
        options = data.get("options")
        correct_index = data.get("correct_index")
        media_type = data.get("media_type") or ("image" if card_type == "image" else "text")

        if card_type == "text":
            if not front or not back:
                raise ValueError("front and back are required")
        elif card_type == "multiple_choice":
            if not front:
                raise ValueError("front is required")
            if not isinstance(options, list) or len(options) != 4:
                raise ValueError("options must contain exactly 4 answers")
            if any(not str(opt).strip() for opt in options):
                raise ValueError("all 4 options must be filled")
            try:
                correct_index = int(correct_index)
            except (TypeError, ValueError):
                raise ValueError("correct_index must be an integer between 0 and 3")
            if correct_index < 0 or correct_index > 3:
                raise ValueError("correct_index must be between 0 and 3")
            options = [str(opt) for opt in options]
            back = options[correct_index]
        elif card_type == "image":
            if not image or not back:
                raise ValueError("image and back are required")
            front = front or ""

        return {
            "front": front,
            "back": back,
            "audio": audio,
            "media_type": media_type,
            "card_type": card_type,
            "options": options if card_type == "multiple_choice" else None,
            "correct_index": correct_index if card_type == "multiple_choice" else None,
            "image": image if card_type == "image" else None,
            "status": data.get("status"),
            "scheduled_at": data.get("scheduled_at"),
        }

    @staticmethod
    def create_card(
        front,
        back,
        deck_id=None,
        user=None,
        audio=None,
        media_type="text",
        card_type="text",
        options=None,
        correct_index=None,
        image=None,
        status=None,
        scheduled_at=None,
    ):
        """Cria um novo card e o salva no banco de dados."""
        from src.app.models.publish_status import DEFAULT_STATUS, validate_status_payload

        if status or scheduled_at:
            status, scheduled_at = validate_status_payload(
                status or DEFAULT_STATUS, scheduled_at
            )
        card = CardModel(
            front=front,
            back=back,
            deck=deck_id,
            user=user,
            audio=audio,
            media_type=media_type,
            card_type=card_type,
            options=options,
            correct_index=correct_index,
            image=image,
            status=status,
            scheduled_at=scheduled_at,
        )
        card.save_to_db()
        card_dict = card.to_dict()

        # notifica alunos de classrooms vinculadas a este deck
        if deck_id:
            NotificationService.notify_students_new_cards(deck_id=str(deck_id), amount=1)

        return card_dict

    @staticmethod
    def get_card_by_id(card_id):
        """Busca um card pelo ID e o retorna como dicionário."""
        card = CardModel.get_by_id(card_id)
        return card.to_dict() if card else None
    
    @staticmethod
    def create_card_in_lots(name, image, cards):
        deck_id = CardModel.create_card_in_lots(name, image, cards)

        # notifica alunos que há novas cartas neste deck
        if deck_id and isinstance(deck_id, str):
            NotificationService.notify_students_new_cards(deck_id=deck_id, amount=len(cards))

        return "ok"
    
    @staticmethod
    def get_cards_by_deck(deck_id, user_id=None):
        """This method is responsible for get all cards in deck"""
        
        return CardModel.get_cards_by_deck(deck_id, user_id=user_id)

    @staticmethod
    def get_all_cards():
        """Retorna todos os cards como uma lista de dicionários."""
        cards = CardModel.get_all_cards()
        return [card.to_dict() for card in cards]

    @staticmethod
    def update_card(card_id, data):
        """Atualiza os dados de um card existente."""
        card = CardModel.get_by_id(card_id)
        if not card:
            return None
        if isinstance(card, dict):
            card = CardModel.from_dict(card)

        merged = {
            "front": data.get("front", card.front),
            "back": data.get("back", card.back),
            "audio": data.get("audio", card.audio),
            "media_type": data.get("media_type", card.media_type),
            "card_type": data.get("card_type", card.card_type),
            "options": data.get("options", card.options),
            "correct_index": data.get("correct_index", card.correct_index),
            "image": data.get("image", card.image),
        }
        normalized = CardService.validate_card_payload(merged)

        card.front = normalized["front"]
        card.back = normalized["back"]
        card.audio = normalized["audio"]
        card.media_type = normalized["media_type"]
        card.card_type = normalized["card_type"]
        card.options = normalized["options"]
        card.correct_index = normalized["correct_index"]
        card.image = normalized["image"]
        if "status" in data or "scheduled_at" in data:
            from src.app.models.publish_status import validate_status_payload
            status, scheduled_at = validate_status_payload(
                data.get("status", card.status),
                data.get("scheduled_at") if "scheduled_at" in data else card.scheduled_at,
            )
            card.status = status
            card.scheduled_at = scheduled_at
        card.updated_at = datetime.now(timezone.utc)

        card.save_to_db()
        deck_id = getattr(card, 'deck', None)
        if not deck_id:
            deck_doc = mongo.db.decks.find_one({"cards": ObjectId(card._id)})
            if deck_doc:
                deck_id = str(deck_doc["_id"])
        if deck_id:
            from src.app.models.lesson_deck_model import ContentVisibility
            from src.app.models.user_progress_model import UserProgressModel
            users = CardModel.get_user_by_deck(deck_id)
            for user_id in users:
                if ContentVisibility.student_should_get_progress(user_id, deck_id, card._id):
                    UserProgressModel.create_or_update(user_id, deck_id, card._id)
        return card.to_dict()

    @staticmethod
    def delete_card(card_id):
        """Exclui um card pelo ID."""
        card = CardModel.get_by_id(card_id)
        if not card:
            return False
        if isinstance(card, dict):
            card = CardModel(**card)
        card.delete_from_db()
        return True

    @staticmethod
    def check_card_permission(card_id, user_id, user_role):
        """
        Verifica se o usuário tem permissão para editar/excluir um card.
        Retorna um dict com: {"can_edit": bool, "reason": str}
        """
        roles = user_role if isinstance(user_role, (list, tuple, set)) else [user_role]
        # Admin pode editar tudo
        if "admin" in roles:
            return {"can_edit": True, "reason": "admin"}
        
        # Busca o card
        card = CardModel.get_by_id(card_id)
        if not card:
            return {"can_edit": False, "reason": "card_not_found"}
        
        if isinstance(card, dict):
            card_dict = card
        else:
            card_dict = card.to_dict()
        
        deck_id = card_dict.get("deck")
        if not deck_id:
            return {"can_edit": False, "reason": "no_deck"}
        
        # Busca o deck
        deck = DeckModel.get_by_id(deck_id)
        if not deck:
            return {"can_edit": False, "reason": "deck_not_found"}
        
        if isinstance(deck, dict):
            deck_dict = deck
        else:
            deck_dict = deck.to_dict()
        
        collection_id = deck_dict.get("collection")
        if not collection_id:
            return {"can_edit": False, "reason": "no_collection"}
        
        # Busca a collection
        collection = mongo.db.collections.find_one({"_id": ObjectId(collection_id)})
        if not collection:
            return {"can_edit": False, "reason": "collection_not_found"}
        
        # Verifica se é uma collection de livro
        if collection.get("book_id"):
            return {"can_edit": False, "reason": "book_collection_only_admin"}
        
        # Verifica se é uma collection de classroom
        if collection.get("classroom"):
            classroom = mongo.db.classrooms.find_one({"_id": ObjectId(collection.get("classroom"))})
            if classroom:
                teacher_id = str(classroom.get("teacher"))
                if teacher_id == user_id:
                    return {"can_edit": True, "reason": "classroom_teacher"}
                else:
                    return {"can_edit": False, "reason": "not_classroom_teacher"}
        
        # Collection pessoal - verifica se o usuário é dono
        collection_user_id = str(collection.get("user"))
        if collection_user_id == user_id:
            return {"can_edit": True, "reason": "personal_collection_owner"}
        
        return {"can_edit": False, "reason": "no_permission"}

