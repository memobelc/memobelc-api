import random
from bson import ObjectId
from datetime import datetime, timedelta, timezone
from src.app import mongo
from .user_model import UserModel
from .user_progress_model import UserProgressModel


class CollectionModel:
    def __init__(self, _id=None, name=None, created_at=None, updated_at=None, image=None, decks=None, user=None, classroom=None, book_id=None, **kwargs):
        self._id = str(_id) if _id else None
        self.name = name
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.image = image
        self.decks = decks or []
        self.user = user
        self.classroom = classroom
        self.book_id = str(book_id) if book_id else None

    def save_to_db(self):
        """Salva o Masterdeck no banco de dados MongoDB"""
        deck_data = {
            'name': self.name,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'image': self.image,
            'decks': self.decks
        }
        if self.book_id is not None:
            deck_data['book_id'] = ObjectId(self.book_id)
        result = mongo.db.collections.insert_one(deck_data)
        self._id = str(result.inserted_id)
        self.id = self._id

        if self.user:
            UserModel.add_collections_to_user(self.user, [str(result.inserted_id)])

        return {"collection_id": str(result.inserted_id)}
    
    @staticmethod
    def get_all_collections():
        """Retorna todos os collections como uma lista de dicionários"""
        collections = mongo.db.collections.find()
        return [CollectionModel(**c).to_dict() for c in collections]
    
    @staticmethod
    def get_by_id(deck_id):
        """Busca um Collection pelo ID e retorna como dicionário"""
        collection = mongo.db.collections.find_one({"_id": ObjectId(deck_id)})
        if collection:
            result = CollectionModel(**collection)
            return result.to_dict()
        return None
    
    
    @staticmethod
    def add_classroom(classroom_id, collection_id):
        mongo.db.collections.update_one(
            {"_id": ObjectId(collection_id)},
            {"$set": {"classroom": ObjectId(classroom_id)}}
        )

    

    @staticmethod
    def get_collections_by_user(user_id, include_book_collections_for_admin=False):
        """Busca collections do user. Se include_book_collections_for_admin=True, inclui também as collections dos livros (visível só para admin)."""
        user = UserModel.find_by_id(user_id)
        if not user:
            return {"collections": []}

        user = user.to_dict()
        collections_list = []

        for collection_id in user.get("collections", []):
            collection = CollectionModel.get_by_id(collection_id)
            if not collection:
                continue
            collection = dict(collection)
            CollectionModel._enrich_collection_with_decks(collection, user_id)
            if collection.get("book_id"):
                collection["is_book_collection"] = True
                book = mongo.db.books.find_one(
                    {"_id": ObjectId(collection["book_id"])},
                    {"titulo": 1},
                )
                collection["book_titulo"] = book.get("titulo", "") if book else ""
            collections_list.append(collection)

        if include_book_collections_for_admin:
            book_collections = CollectionModel.get_book_collections(user_id)
            collections_list.extend(book_collections)

        return {"collections": collections_list}

    @staticmethod
    def _enrich_collection_with_decks(collection, user_id):
        """Enriquece um dict de collection com decks, total_cards, pending_cards e review_collections_cards."""
        from .deck_model import DeckModel
        from .classroom_membership_model import ClassroomMembershipModel
        from .lesson_deck_model import ContentVisibility

        freeze = None
        if collection.get("classroom") and user_id:
            freeze = ClassroomMembershipModel.get_freeze_for_collection(
                user_id, collection.get("_id")
            )

        is_teacher = ContentVisibility.is_classroom_teacher(collection, user_id)
        total_cards_in_collection = 0
        pending_cards_in_collection = 0
        list_deck_in_collection = []
        review_collections_cards = []
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
            else:
                deck = ContentVisibility.filter_deck_for_user(
                    deck, user_id, collection, is_teacher=is_teacher
                )
                if not deck:
                    continue
            cards_count = len(deck.get("cards", []))
            total_cards_in_collection += cards_count
            allowed_ids = set(str(card_id) for card_id in deck.get("cards", []))
            review_cards = UserProgressModel.get_pending_cards(user_id, deck_id) if user_id else []
            review_cards = [
                card for card in review_cards if str(card.get("card_id")) in allowed_ids
            ]
            pending_count = len(review_cards)
            pending_cards_in_collection += pending_count
            for card in review_cards:
                review_collections_cards.append(card)
            deck.update({
                "total_cards": cards_count,
                "pending_cards": pending_count,
                "review_cards": review_cards,
            })
            list_deck_in_collection.append(deck)
        collection.update({
            "total_cards": total_cards_in_collection,
            "pending_cards": pending_cards_in_collection,
            "decks": list_deck_in_collection,
            "review_collections_cards": review_collections_cards,
            "archived_classroom": bool(freeze),
        })
        return collection

    @staticmethod
    def get_book_collections(user_id=None):
        """Retorna as collections dos livros (collection_id dos books). Só para uso admin."""
        books = mongo.db.books.find({"collection_id": {"$exists": True, "$ne": None}})
        collections_list = []
        for book in books:
            collection_id = book.get("collection_id")
            if not collection_id:
                continue
            collection_id_str = str(collection_id)
            collection = CollectionModel.get_by_id(collection_id_str)
            if not collection:
                continue
            collection = dict(collection)
            CollectionModel._enrich_collection_with_decks(collection, user_id)
            collection["is_book_collection"] = True
            collection["book_id"] = str(book["_id"])
            collection["book_titulo"] = book.get("titulo") or ""
            collections_list.append(collection)
        return collections_list

    @staticmethod
    def add_decks_to_collection(collection_id, deck_ids):
        """Adiciona uma lista de deck IDs ao Collection especificado (evita duplicatas com $addToSet)."""
        deck_object_ids = [ObjectId(deck_id) for deck_id in deck_ids]
        result = mongo.db.collections.update_one(
            {"_id": ObjectId(collection_id)},
            {"$addToSet": {"decks": {"$each": deck_object_ids}}, "$set": {"updated_at": datetime.now(timezone.utc)}}
        )
        return result.modified_count > 0
    
    @staticmethod
    def update_collection(collection_id: str, name: str | None = None, image: str | None = None) -> bool:
        """Atualiza os dados básicos de uma collection.

        Args:
            collection_id: ID da collection a ser atualizada.
            name: Novo nome da collection (opcional).
            image: Nova imagem da collection (opcional).

        Returns:
            bool: True se a collection foi atualizada com sucesso, False caso contrário.
        """
        update_fields = {
            "updated_at": datetime.now(timezone.utc),
        }

        if name is not None:
            update_fields["name"] = name

        if image is not None:
            update_fields["image"] = image

        result = mongo.db.collections.update_one(
            {"_id": ObjectId(collection_id)},
            {"$set": update_fields},
        )

        return result.modified_count > 0
    

    @staticmethod
    def get_user_collection_by_book_id(user_id, book_id):
        """Retorna a collection do usuário associada ao livro (criada ao salvar cartas de um capítulo)."""
        user = UserModel.find_by_id(user_id)
        if not user:
            return None
        user = user.to_dict() if hasattr(user, "to_dict") else user
        book_id_str = str(book_id)
        for collection_id in user.get("collections", []):
            collection = CollectionModel.get_by_id(collection_id)
            if collection and collection.get("book_id") == book_id_str:
                return collection
        return None

    def to_dict(self):
        """Converte um documento collection para dicionário"""
        return {
            '_id': self._id,
            'name': self.name,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'image': self.image,
            'decks': [str(deck_id) for deck_id in self.decks],
            'classroom': str(self.classroom) if self.classroom else self.classroom,
            'book_id': self.book_id,
        }

