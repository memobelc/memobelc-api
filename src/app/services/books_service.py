"""Service for handling books operations."""

from datetime import datetime, timezone
from bson import ObjectId
from src.app import mongo
from src.app.models.book_model import BookModel
from src.app.models.collection_model import CollectionModel
from src.app.models.deck_model import DeckModel
from src.app.models.user_model import UserModel
from src.app.models.user_progress_model import UserProgressModel
from src.app.services.user_streak_service import UserStreakService


class BookService:
    """Service for managing books."""

    @staticmethod
    def _coin_fields(data, existing=None):
        existing = existing or {}
        if "coins_enabled" in data:
            coins_enabled = bool(data.get("coins_enabled"))
        else:
            coins_enabled = bool(existing.get("coins_enabled", False))
        raw_price = data.get("coin_price") if "coin_price" in data else existing.get("coin_price")
        try:
            coin_price = int(raw_price or 0)
        except (TypeError, ValueError):
            coin_price = 0
        if coins_enabled and coin_price < 1:
            raise ValueError("coin_price must be at least 1 when coins are enabled")
        return coins_enabled, max(coin_price, 0)

    @staticmethod
    def create_book(data, admin_id):
        """Cria um novo livro: gera uma collection com nome e imagem do livro e um deck por capítulo."""
        titulo = data.get("titulo")
        capa = data.get("capa")

        # Cria collection do livro (sem user = collection do sistema)
        collection = CollectionModel(name=titulo, image=capa)
        result = collection.save_to_db()
        collection_id = result["collection_id"]

        # Para cada capítulo, cria um deck na collection e preserva pdf_url, images_urls, audio_url, ordem, titulo
        chapters_with_decks = []
        for ch in data.get("chapters", []):
            chapter_title = ch.get("title") or ch.get("titulo") or "Chapter"
            deck = DeckModel(
                name=chapter_title,
                collection_id=collection_id,
                image=capa,
            )
            deck_id = deck.save_to_db()
            chapter_data = {
                "titulo": ch.get("titulo") or ch.get("title") or chapter_title,
                "title": chapter_title,
                "content": ch.get("content") or ch.get("conteudo") or "",
                "ordem": ch.get("ordem", len(chapters_with_decks) + 1),
                "pdf_url": ch.get("pdf_url") or "",
                "images_urls": ch.get("images_urls") or [],
                "audio_url": ch.get("audio_url") or "",
                "intro_duration": ch.get("intro_duration") or 0,
                "deck_id": deck_id,
            }
            chapters_with_decks.append(chapter_data)

        coins_enabled, coin_price = BookService._coin_fields(data)

        book = BookModel(
            titulo=titulo,
            autor=data.get("autor"),
            capa=capa,
            idioma=data.get("idioma"),
            nivel=data.get("nivel"),
            genero=data.get("genero"),
            is_free=data.get("is_free", True),
            price=data.get("price"),
            payment_link=data.get("payment_link"),
            sale_mode=data.get("sale_mode") or "both",
            is_published=data.get("is_published", True),
            google_play_product_id=data.get("google_play_product_id"),
            coins_enabled=coins_enabled,
            coin_price=coin_price,
            chapters=chapters_with_decks,
            collection_id=collection_id,
            created_by=admin_id,
        )
        return book.save_to_db()

    @staticmethod
    def update_book(book_id, data):
        """Atualiza um livro existente. Novos capítulos (sem deck_id) ganham um deck na collection do livro."""
        book = BookModel.get_by_id(book_id)
        if not book:
            return None

        chapters = data.get("chapters", book.get("chapters", []))
        collection_id = book.get("collection_id")
        capa = data.get("capa") or book.get("capa")
        existing_chapters = book.get("chapters", [])

        # Para capítulos existentes (com deck_id) preserva todos os campos; para novos cria deck
        chapters_with_decks = []
        for idx, ch in enumerate(chapters):
            if ch.get("deck_id"):
                # Mantém campos do app: titulo, ordem, pdf_url, images_urls, audio_url, intro_duration
                merged = dict(ch)
                merged["titulo"] = ch.get("titulo") or ch.get("title") or ""
                merged["ordem"] = ch.get("ordem", idx + 1)
                merged["pdf_url"] = ch.get("pdf_url") or ""
                merged["images_urls"] = ch.get("images_urls") or []
                merged["audio_url"] = ch.get("audio_url") or ""
                merged["intro_duration"] = ch.get("intro_duration") or 0
                # Preserva title e content do capítulo existente (frontend não envia)
                deck_id_val = ch.get("deck_id")
                existing = next(
                    (ec for ec in existing_chapters if str(ec.get("deck_id")) == str(deck_id_val)),
                    None,
                )
                if existing:
                    merged.setdefault("title", existing.get("title") or merged.get("titulo") or "")
                    merged.setdefault("content", existing.get("content") or existing.get("conteudo") or "")
                else:
                    merged.setdefault("title", merged.get("titulo") or "")
                    merged.setdefault("content", "")
                chapters_with_decks.append(merged)
                continue
            chapter_title = ch.get("title") or ch.get("titulo") or "Chapter"
            deck = DeckModel(
                name=chapter_title,
                collection_id=collection_id,
                image=capa,
            )
            deck_id = deck.save_to_db()
            chapter_data = {
                "titulo": ch.get("titulo") or ch.get("title") or chapter_title,
                "title": chapter_title,
                "content": ch.get("content") or ch.get("conteudo") or "",
                "ordem": ch.get("ordem", idx + 1),
                "pdf_url": ch.get("pdf_url") or "",
                "images_urls": ch.get("images_urls") or [],
                "audio_url": ch.get("audio_url") or "",
                "intro_duration": ch.get("intro_duration") or 0,
                "deck_id": deck_id,
            }
            chapters_with_decks.append(chapter_data)

        coins_enabled, coin_price = BookService._coin_fields(data, book)

        book_obj = BookModel(
            _id=book_id,
            titulo=data.get("titulo", book.get("titulo")),
            autor=data.get("autor", book.get("autor")),
            capa=capa,
            idioma=data.get("idioma", book.get("idioma")),
            nivel=data.get("nivel", book.get("nivel")),
            genero=data.get("genero", book.get("genero")),
            is_free=data.get("is_free", book.get("is_free")),
            price=data.get("price", book.get("price")),
            payment_link=data.get("payment_link", book.get("payment_link")),
            sale_mode=data.get("sale_mode", book.get("sale_mode") or "both"),
            is_published=data.get("is_published", book.get("is_published", True)),
            google_play_product_id=data.get("google_play_product_id", book.get("google_play_product_id")),
            coins_enabled=coins_enabled,
            coin_price=coin_price,
            chapters=chapters_with_decks,
            collection_id=collection_id,
            created_at=book.get("created_at"),
        )
        return book_obj.update_to_db()

    @staticmethod
    def get_all_books():
        """Retorna todos os livros."""
        return BookModel.get_all()

    @staticmethod
    def get_available_books(user_id):
        """Retorna livros disponíveis e para descobrir."""
        result = BookModel.get_available_books(user_id)
        from src.app.services.entitlement_service import EntitlementService
        entitled = EntitlementService.user_book_ids(user_id)
        my_ids = {book["_id"] for book in result.get("my_books", [])}
        still_discover = []
        for book in result.get("discover", []):
            if book["_id"] in entitled and book["_id"] not in my_ids:
                result["my_books"].append(book)
                my_ids.add(book["_id"])
            else:
                still_discover.append(book)
        result["discover"] = still_discover
        return result

    @staticmethod
    def get_book_by_id(book_id):
        """Busca um livro pelo ID."""
        return BookModel.get_by_id(book_id)

    @staticmethod
    def get_book_by_id_for_user(book_id, user_id):
        """Busca um livro pelo ID com flags por capítulo: has_cards, user_has_saved e user_has_read."""
        book = BookModel.get_by_id(book_id)
        if not book:
            return None

        # Busca progresso de capítulos lidos pelo usuário (armazenado em user_books)
        user_obj_id = ObjectId(user_id)
        book_obj_id = ObjectId(book_id)
        user_book = mongo.db.user_books.find_one(
            {
                "user_id": user_obj_id,
                "book_id": book_obj_id,
            }
        )
        read_ordens = set(user_book.get("read_chapters_ordem", [])) if user_book else set()

        chapters = book.get("chapters", [])
        enriched = []
        # Usa índice (1-based) como referência estável de capítulo para progresso,
        # inclusive para livros antigos que não têm campo "ordem".
        for idx, ch in enumerate(chapters, start=1):
            deck_id = ch.get("deck_id")
            ordem = ch.get("ordem", idx)
            if not deck_id:
                enriched.append(
                    {
                        **ch,
                        "ordem": ordem,
                        "deck_id": None,
                        "has_cards": False,
                        "user_has_saved": False,
                        "user_has_read": idx in read_ordens,
                    }
                )
                continue
            deck = DeckModel.get_by_id(deck_id)
            cards_count = len(deck.get("cards", [])) if deck else 0
            has_cards = cards_count > 0
            user_has_saved = (
                DeckModel.check_if_the_user_has_the_deck(user_id, deck_id).get("user_has_deck") == "true"
            )
            enriched.append(
                {
                    **ch,
                    "ordem": ordem,
                    "deck_id": deck_id,
                    "has_cards": has_cards,
                    "user_has_saved": user_has_saved,
                    "user_has_read": idx in read_ordens,
                }
            )
        book = dict(book)
        book["chapters"] = enriched
        return book

    @staticmethod
    def generate_collection_for_book(book_id):
        """Gera collection e decks para um livro que ainda não tem collection_id (livros criados antes da atualização)."""
        book = BookModel.get_by_id(book_id)
        if not book:
            return None
        if book.get("collection_id"):
            return {"already": True, "collection_id": book.get("collection_id")}

        titulo = book.get("titulo") or "Book"
        capa = book.get("capa")

        collection = CollectionModel(name=titulo, image=capa)
        result = collection.save_to_db()
        collection_id = result["collection_id"]

        chapters_with_decks = []
        for idx, ch in enumerate(book.get("chapters", [])):
            chapter_title = ch.get("title") or ch.get("titulo") or "Chapter"
            deck = DeckModel(
                name=chapter_title,
                collection_id=collection_id,
                image=capa,
            )
            deck_id = deck.save_to_db()
            chapter_data = dict(ch)
            chapter_data["titulo"] = ch.get("titulo") or ch.get("title") or chapter_title
            chapter_data["title"] = chapter_title
            chapter_data["ordem"] = ch.get("ordem", idx + 1)
            chapter_data["deck_id"] = deck_id
            chapter_data.setdefault("pdf_url", "")
            chapter_data.setdefault("images_urls", [])
            chapter_data.setdefault("audio_url", "")
            chapter_data.setdefault("intro_duration", 0)
            chapter_data.setdefault("content", "")
            chapters_with_decks.append(chapter_data)

        book_obj = BookModel(
            _id=book_id,
            titulo=titulo,
            autor=book.get("autor"),
            capa=capa,
            idioma=book.get("idioma"),
            nivel=book.get("nivel"),
            genero=book.get("genero"),
            is_free=book.get("is_free"),
            price=book.get("price"),
            payment_link=book.get("payment_link"),
            sale_mode=book.get("sale_mode") or "both",
            is_published=book.get("is_published", True),
            google_play_product_id=book.get("google_play_product_id"),
            chapters=chapters_with_decks,
            collection_id=collection_id,
            created_at=book.get("created_at"),
        )
        book_obj.update_to_db()
        return {"collection_id": collection_id, "message": "Collection and decks generated"}

    @staticmethod
    def add_chapter(book_id, title, content=None):
        """Adiciona um capítulo ao livro: cria um deck na collection do livro."""
        book = BookModel.get_by_id(book_id)
        if not book:
            return None
        collection_id = book.get("collection_id")
        if not collection_id:
            return None
        deck = DeckModel(
            name=title or "Chapter",
            collection_id=collection_id,
            image=book.get("capa"),
        )
        deck_id = deck.save_to_db()
        chapters = list(book.get("chapters", []))
        chapters.append({
            "title": title or "Chapter",
            "content": content or "",
            "deck_id": deck_id,
        })
        book_obj = BookModel(
            _id=book_id,
            titulo=book.get("titulo"),
            autor=book.get("autor"),
            capa=book.get("capa"),
            idioma=book.get("idioma"),
            nivel=book.get("nivel"),
            genero=book.get("genero"),
            is_free=book.get("is_free"),
            price=book.get("price"),
            payment_link=book.get("payment_link"),
            sale_mode=book.get("sale_mode") or "both",
            is_published=book.get("is_published", True),
            google_play_product_id=book.get("google_play_product_id"),
            chapters=chapters,
            collection_id=collection_id,
            created_at=book.get("created_at"),
        )
        book_obj.update_to_db()
        return {"deck_id": deck_id, "chapter": chapters[-1]}

    @staticmethod
    def add_cards_to_chapter(book_id, deck_id, card_ids):
        """Admin: adiciona cartas ao deck do capítulo (deck deve pertencer ao livro)."""
        book = BookModel.get_by_id(book_id)
        if not book:
            return False
        for ch in book.get("chapters", []):
            if ch.get("deck_id") == deck_id:
                DeckModel.add_cards_to_deck(deck_id, card_ids)
                return True
        return False

    @staticmethod
    def save_chapter_cards(user_id, book_id, deck_id):
        """Usuário salva as cartas do capítulo: cria/usa collection do livro para o user e gera progresso."""
        book = BookModel.get_by_id(book_id)
        if not book:
            return None
        # Confere se o deck pertence ao livro
        if not any(ch.get("deck_id") == deck_id for ch in book.get("chapters", [])):
            return None
        deck = DeckModel.get_by_id(deck_id)
        if not deck or not deck.get("cards"):
            return {"message": "No cards to save", "collection_id": None}

        # Obtém ou cria a collection do usuário para este livro
        user_coll = CollectionModel.get_user_collection_by_book_id(user_id, book_id)
        if user_coll:
            collection_id = user_coll["_id"]
        else:
            new_coll = CollectionModel(
                name=book.get("titulo"),
                image=book.get("capa"),
                book_id=book_id,
                user=user_id,
            )
            result = new_coll.save_to_db()
            collection_id = result["collection_id"]

        CollectionModel.add_decks_to_collection(collection_id, [deck_id])
        # Se a collection foi criada agora, save_to_db já a adicionou ao user

        for card_id in deck.get("cards", []):
            UserProgressModel.create_or_update(user_id, deck_id, str(card_id))

        return {"message": "Chapter cards saved", "collection_id": collection_id}

    @staticmethod
    def delete_book(book_id):
        """Deleta um livro."""
        return BookModel.delete_book(book_id)

    @staticmethod
    def add_book_to_user(user_id, book_id):
        """Adiciona um livro à biblioteca do usuário."""
        BookModel.add_book_to_user(user_id, book_id)

    @staticmethod
    def mark_chapter_read(user_id, book_id, chapter_ordem: int, read: bool = True):
        """Marca ou desmarca um capítulo como lido para o usuário.

        Também registra o dia de estudo para o streak quando marcado como lido.
        """
        book = BookModel.get_by_id(book_id)
        if not book:
            return None

        chapters = book.get("chapters", [])
        # Garante que o capítulo existe usando índice (1-based)
        if chapter_ordem < 1 or chapter_ordem > len(chapters):
            return None

        user_obj_id = ObjectId(user_id)
        book_obj_id = ObjectId(book_id)

        user_book = mongo.db.user_books.find_one(
            {
                "user_id": user_obj_id,
                "book_id": book_obj_id,
            }
        )

        # Se ainda não existe registro do livro para o usuário (por exemplo, livro gratuito),
        # cria o documento em user_books com controle de capítulos lidos.
        if not user_book:
            user_book = {
                "user_id": user_obj_id,
                "book_id": book_obj_id,
                "added_at": datetime.now(timezone.utc),
                "read_chapters_ordem": [],
            }
            mongo.db.user_books.insert_one(user_book)

        # Atualiza lista de capítulos lidos
        update_query = {}
        if read:
            update_query["$addToSet"] = {"read_chapters_ordem": chapter_ordem}
        else:
            update_query["$pull"] = {"read_chapters_ordem": chapter_ordem}

        mongo.db.user_books.update_one(
            {"user_id": user_obj_id, "book_id": book_obj_id},
            update_query,
        )

        # Se marcou como lido, registra streak do dia
        if read:
            UserStreakService.record_study(user_id)

        # Retorna estado atualizado de capítulos lidos
        updated = mongo.db.user_books.find_one(
            {
                "user_id": user_obj_id,
                "book_id": book_obj_id,
            }
        )
        read_ordens = updated.get("read_chapters_ordem", []) if updated else []
        return {"read_chapters_ordem": read_ordens}

    @staticmethod
    def purchase_with_coins(user_id, book_id):
        from src.app.models.coin_ledger_model import CoinLedgerModel
        from src.app.services.entitlement_service import EntitlementService

        book = BookModel.get_by_id(book_id)
        if not book:
            raise ValueError("Book not found")
        if book.get("is_free"):
            raise ValueError("This book is free")
        if book.get("sale_mode") == "plans_only":
            raise ValueError("This book is only available through a plan")
        if not book.get("coins_enabled"):
            raise ValueError("This book cannot be purchased with coins")
        coin_price = int(book.get("coin_price") or 0)
        if coin_price < 1:
            raise ValueError("This book cannot be purchased with coins")

        existing = mongo.db.user_books.find_one({
            "user_id": ObjectId(str(user_id)),
            "book_id": ObjectId(str(book_id)),
        })
        if existing or book_id in EntitlementService.user_book_ids(user_id):
            raise ValueError("Book already in your library")

        balance = UserModel.spend_coins(user_id, coin_price)
        if balance is None:
            raise ValueError("Insufficient coins")

        ledger = CoinLedgerModel.record(
            user_id,
            -coin_price,
            "book_purchase",
            reason=book.get("titulo"),
            book_id=book_id,
        )
        EntitlementService.grant_book(
            user_id,
            book_id,
            source="coins",
            source_id=ledger.get("_id"),
        )
        return {"granted": True, "coins": balance, "book_id": book_id, "coin_price": coin_price}

