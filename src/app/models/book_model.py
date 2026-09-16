"""Model for handling books."""

from datetime import datetime, timezone
from bson import ObjectId
from src.app import mongo


class BookModel:
    """Model for books with chapters."""

    def __init__(
        self,
        _id=None,
        titulo=None,
        autor=None,
        capa=None,
        idioma=None,
        nivel=None,
        genero=None,
        is_free=True,
        price=None,
        payment_link=None,
        chapters=None,
        collection_id=None,
        created_at=None,
        updated_at=None,
        created_by=None,
        sale_mode="both",
        is_published=True,
        google_play_product_id=None,
        coins_enabled=False,
        coin_price=0,
        **kwargs,
    ):
        self._id = str(_id) if _id else None
        self.titulo = titulo
        self.autor = autor
        self.capa = capa
        self.idioma = idioma
        self.nivel = nivel  # basico, medio, avancado
        self.genero = genero
        self.is_free = is_free
        self.price = price
        self.payment_link = payment_link
        self.chapters = chapters or []
        self.collection_id = str(collection_id) if collection_id else None
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.created_by = ObjectId(created_by) if created_by else None
        self.sale_mode = sale_mode or "both"
        self.is_published = True if is_published is None else bool(is_published)
        self.google_play_product_id = google_play_product_id
        self.coins_enabled = bool(coins_enabled)
        try:
            self.coin_price = int(coin_price or 0)
        except (TypeError, ValueError):
            self.coin_price = 0

    def save_to_db(self):
        """Salva o livro no banco de dados."""
        book_data = {
            'titulo': self.titulo,
            'autor': self.autor,
            'capa': self.capa,
            'idioma': self.idioma,
            'nivel': self.nivel,
            'genero': self.genero,
            'is_free': self.is_free,
            'price': self.price,
            'payment_link': self.payment_link,
            'chapters': self.chapters,
            'collection_id': ObjectId(self.collection_id) if self.collection_id else None,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'created_by': self.created_by,
            'sale_mode': self.sale_mode or 'both',
            'is_published': self.is_published if self.is_published is not None else True,
            'google_play_product_id': self.google_play_product_id,
            'coins_enabled': bool(self.coins_enabled),
            'coin_price': int(self.coin_price or 0),
        }

        result = mongo.db.books.insert_one(book_data)
        self._id = str(result.inserted_id)
        return {"book_id": self._id}

    def update_to_db(self):
        """Atualiza o livro no banco de dados."""
        if not self._id:
            return None

        book_data = {
            'titulo': self.titulo,
            'autor': self.autor,
            'capa': self.capa,
            'idioma': self.idioma,
            'nivel': self.nivel,
            'genero': self.genero,
            'is_free': self.is_free,
            'price': self.price,
            'payment_link': self.payment_link,
            'chapters': self.chapters,
            'collection_id': ObjectId(self.collection_id) if self.collection_id else None,
            'updated_at': datetime.now(timezone.utc),
            'sale_mode': self.sale_mode or 'both',
            'is_published': self.is_published if self.is_published is not None else True,
            'google_play_product_id': self.google_play_product_id,
            'coins_enabled': bool(self.coins_enabled),
            'coin_price': int(self.coin_price or 0),
        }

        result = mongo.db.books.update_one(
            {"_id": ObjectId(self._id)},
            {"$set": book_data}
        )
        return result.modified_count > 0

    @staticmethod
    def get_by_id(book_id):
        """Busca um livro pelo ID."""
        book = mongo.db.books.find_one({"_id": ObjectId(book_id)})
        if book:
            return BookModel(**book).to_dict()
        return None

    @staticmethod
    def get_all():
        """Retorna todos os livros."""
        books = mongo.db.books.find().sort("created_at", -1)
        return [BookModel(**book).to_dict() for book in books]

    @staticmethod
    def get_available_books(user_id):
        """Retorna livros disponíveis para o usuário (gratuitos ou que ele já possui)."""
        user_obj_id = ObjectId(user_id)
        
        # Busca livros do usuário
        user_books = mongo.db.user_books.find({"user_id": user_obj_id})
        user_book_ids = {str(b["book_id"]) for b in user_books}

        # Busca todos os livros
        all_books = mongo.db.books.find({"is_published": {"$ne": False}}).sort("created_at", -1)
        
        available_books = []
        discover_books = []

        for book in all_books:
            book_dict = BookModel(**book).to_dict()
            book_id = book_dict["_id"]

            if book_dict["is_free"] or book_id in user_book_ids:
                available_books.append(book_dict)
            else:
                discover_books.append(book_dict)

        return {
            "my_books": available_books,
            "discover": discover_books,
        }

    @staticmethod
    def add_book_to_user(user_id, book_id):
        """Adiciona um livro à biblioteca do usuário."""
        user_obj_id = ObjectId(user_id)
        book_obj_id = ObjectId(book_id)

        # Verifica se já existe
        existing = mongo.db.user_books.find_one({
            "user_id": user_obj_id,
            "book_id": book_obj_id,
        })

        if not existing:
            mongo.db.user_books.insert_one({
                "user_id": user_obj_id,
                "book_id": book_obj_id,
                "added_at": datetime.now(timezone.utc),
                # Lista de ordens de capítulos que o usuário já marcou como lidos
                "read_chapters_ordem": [],
            })

    @staticmethod
    def delete_book(book_id):
        """Deleta um livro e todos os recursos relacionados (collection e decks do livro)."""
        book = mongo.db.books.find_one({"_id": ObjectId(book_id)})
        if not book:
            return False

        book_obj_id = ObjectId(book_id)
        collection_id = book.get("collection_id")

        # Remove dos usuários
        mongo.db.user_books.delete_many({"book_id": book_obj_id})

        # Remove collection e decks do livro (decks órfãos são removidos)
        if collection_id:
            coll = mongo.db.collections.find_one({"_id": collection_id})
            if coll and coll.get("decks"):
                for deck_id in coll["decks"]:
                    mongo.db.decks.delete_one({"_id": deck_id})
            mongo.db.collections.delete_one({"_id": collection_id})

        # Deleta o livro
        result = mongo.db.books.delete_one({"_id": book_obj_id})
        return result.deleted_count > 0

    @staticmethod
    def get_by_google_sku(sku):
        if not sku:
            return None
        book = mongo.db.books.find_one({"google_play_product_id": sku})
        if book:
            return BookModel(**book).to_dict()
        return None

    def to_dict(self):
        """Converte o objeto BookModel para dicionário."""
        return {
            '_id': self._id,
            'titulo': self.titulo,
            'autor': self.autor,
            'capa': self.capa,
            'idioma': self.idioma,
            'nivel': self.nivel,
            'genero': self.genero,
            'is_free': self.is_free,
            'price': self.price,
            'payment_link': self.payment_link,
            'chapters': self.chapters,
            'collection_id': str(self.collection_id) if self.collection_id else None,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            'updated_at': self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            'created_by': str(self.created_by) if self.created_by else None,
            'sale_mode': self.sale_mode or 'both',
            'is_published': True if self.is_published is None else bool(self.is_published),
            'google_play_product_id': self.google_play_product_id,
            'coins_enabled': bool(self.coins_enabled),
            'coin_price': int(self.coin_price or 0),
        }

