"""Model class for cards"""

from datetime import datetime, timezone
from bson import ObjectId
from src.app import mongo
from src.app.models.deck_model import DeckModel
from src.app.models.user_progress_model import UserProgressModel
from src.app.models.publish_status import (
    DEFAULT_STATUS,
    isoformat_dt,
    normalize_status,
    parse_scheduled_at,
)


class CardModel:
    """Class to handle model cards"""

    VALID_CARD_TYPES = ("text", "multiple_choice", "image")

    def __init__(
        self,
        _id=None,
        front=None,
        back=None,
        audio=None,
        media_type="text",
        card_type="text",
        options=None,
        correct_index=None,
        image=None,
        created_at=None,
        updated_at=None,
        deck=None,
        user=None,
        status=None,
        scheduled_at=None,
        **kwargs,
    ):
        """
        Inicializa um CardModel representando uma carta de estudo.

        :param _id: ID do documento no MongoDB (gerado automaticamente se não fornecido)
        :param front: Conteúdo da frente da carta
        :param back: Conteúdo do verso da carta
        :param media_type: Tipo de mídia (text, image, audio)
        :param card_type: Tipo da carta (text, multiple_choice, image)
        :param options: Lista de 4 respostas (multiple_choice)
        :param correct_index: Índice da resposta correta (0-3)
        :param image: URL da imagem na frente
        :param created_at: Data de criação (atualizado automaticamente se não fornecido)
        :param updated_at: Data de atualização (atualizado automaticamente se não fornecido)
        """
        self._id = str(_id) if _id else None
        self.front = front
        self.back = back
        self.audio = audio
        self.media_type = media_type
        self.card_type = card_type or "text"
        self.options = options
        self.correct_index = correct_index
        self.image = image
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.deck = deck
        self.user = user
        self.status = normalize_status(status)
        self.scheduled_at = parse_scheduled_at(scheduled_at)

    @staticmethod
    def get_user_by_deck(deck_id):
        collections = list(mongo.db.collections.find({"decks": ObjectId(deck_id)}))
        collection_ids = [col["_id"] for col in collections]
        if not collection_ids:
            return []

        pipeline = [
            {"$match": {"collections": {"$in": collection_ids}}},
            {"$project": {"_id": 1}},
        ]
        user_ids = [str(user["_id"]) for user in mongo.db.users.aggregate(pipeline)]

        from src.app.models.classroom_membership_model import ClassroomMembershipModel

        allowed = []
        for user_id in user_ids:
            include = False
            for col in collections:
                if not col.get("classroom"):
                    include = True
                    break
                if not ClassroomMembershipModel.user_left_classroom_collection(
                    user_id, col["_id"]
                ):
                    include = True
                    break
            if include:
                allowed.append(user_id)
        return allowed

    def save_to_db(self):
        """Salva ou atualiza a carta no banco de dados MongoDB."""
        card_data = {
            "front": self.front,
            "back": self.back,
            "audio": self.audio,
            "media_type": self.media_type,
            "card_type": self.card_type or "text",
            "options": self.options,
            "correct_index": self.correct_index,
            "image": self.image,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status or DEFAULT_STATUS,
            "scheduled_at": self.scheduled_at,
        }

        users = CardModel.get_user_by_deck(self.deck) if self.deck else []

        if self._id:
            mongo.db.cards.update_one({"_id": ObjectId(self._id)}, {"$set": card_data})
            return str(self._id)
        result = mongo.db.cards.insert_one(card_data)
        self._id = str(result.inserted_id)

        if self.deck:
            DeckModel.add_cards_to_deck(
                self.deck, [str(result.inserted_id)]
            )

        from src.app.models.lesson_deck_model import ContentVisibility

        for i in users:
            if ContentVisibility.student_should_get_progress(i, self.deck, self._id):
                UserProgressModel.create_or_update(i, self.deck, self._id)

        return str(result.inserted_id)

    @staticmethod
    def create_card_in_lots(name, image, cards):
        """
        Cria um objeto dentro de db.decks com name e image,
        depois cria vários objetos de cards em db.cards e adiciona os ObjectId dos cards ao deck criado.
        """

        # Criando o deck
        deck_data = {
            "name": name,
            "image": image,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "cards": [],
            "status": DEFAULT_STATUS,
            "scheduled_at": None,
        }
        result = mongo.db.decks.insert_one(deck_data)
        deck_id = str(result.inserted_id)

        card_ids = []
        for card in cards:
            card_data = CardModel.from_dict(card)
            card_id = card_data.save_to_db()
            card_ids.append(card_id)

        DeckModel.add_cards_to_deck(deck_id, card_ids)

        return deck_id

    def delete_from_db(self):
        """Remove a carta do banco de dados MongoDB."""
        if self._id:
            mongo.db.cards.delete_one({"_id": ObjectId(self._id)})

    @staticmethod
    def get_by_id(card_id):
        """Busca um card pelo ID e retorna instância CardModel ou None."""
        card = mongo.db.cards.find_one({"_id": ObjectId(card_id)})
        if card:
            return CardModel.from_dict(card)
        return None

    @staticmethod
    def get_cards_by_deck(deck_id, user_id=None):
        deck = DeckModel.get_by_id(deck_id)
        if not deck:
            return {"cards": []}
        from src.app.models.lesson_deck_model import ContentVisibility
        from src.app.models.classroom_membership_model import ClassroomMembershipModel

        collection = ContentVisibility.find_collection_for_deck(deck_id)
        freeze = None
        if collection and collection.get("classroom") and user_id:
            freeze = ClassroomMembershipModel.get_freeze_for_collection(
                user_id, collection.get("_id")
            )
        if freeze:
            allowed_cards = set(freeze["allowed_cards"].get(str(deck_id)) or [])
            deck["cards"] = [
                card_id for card_id in deck.get("cards", []) if str(card_id) in allowed_cards
            ]
        elif user_id:
            is_teacher = ContentVisibility.is_classroom_teacher(collection, user_id)
            filtered = ContentVisibility.filter_deck_for_user(
                deck, user_id, collection, is_teacher=is_teacher
            )
            if not filtered:
                return {"cards": []}
            deck = filtered

        list_cards = []
        for card_id in deck.get("cards", []):
            card_doc = mongo.db.cards.find_one({"_id": ObjectId(card_id)})
            if not card_doc:
                continue
            card = CardModel.from_dict(card_doc)
            list_cards.append(card.to_dict())

        return {'cards': list_cards}

    @staticmethod
    def get_all_cards():
        """Retorna uma lista de todas as cartas no banco de dados."""
        cards = mongo.db.cards.find()
        return [CardModel.from_dict(card) for card in cards]

    @staticmethod
    def from_dict(card_data):
        """Converte um dicionário do MongoDB para uma instância de CardModel."""
        if not card_data:
            return None
        card_type = card_data.get("card_type") or "text"
        media_type = card_data.get("media_type") or (
            "image" if card_type == "image" else "text"
        )
        return CardModel(
            _id=card_data.get("_id"),
            front=card_data.get("front"),
            back=card_data.get("back"),
            audio=card_data.get("audio"),
            media_type=media_type,
            card_type=card_type,
            options=card_data.get("options"),
            correct_index=card_data.get("correct_index"),
            image=card_data.get("image"),
            created_at=card_data.get("created_at"),
            updated_at=card_data.get("updated_at"),
            deck=card_data.get("deck"),
            user=card_data.get("user"),
            status=card_data.get("status"),
            scheduled_at=card_data.get("scheduled_at"),
        )

    def to_dict(self):
        """Converte a instância de CardModel para um dicionário."""
        return {
            "_id": self._id,
            "front": self.front,
            "back": self.back,
            "audio": self.audio,
            "media_type": self.media_type,
            "card_type": self.card_type or "text",
            "options": self.options,
            "correct_index": self.correct_index,
            "image": self.image,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status or DEFAULT_STATUS,
            "scheduled_at": isoformat_dt(self.scheduled_at),
        }
