"""Module for handling books-related endpoints."""

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Unauthorized
from src.app.services.books_service import BookService
from src.app.middlewares.token_required import token_required
from src.app.services.entitlement_service import EntitlementService
from src.app.models.payment_model import PaymentModel
from src.app import mongo
from bson import ObjectId


class BookController:
    """Class to handle books operations"""

    @staticmethod
    @token_required
    def create_book(current_user, token):
        """Cria um novo livro (apenas admin)."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json()

        if "titulo" not in data:
            return jsonify({"error": "Missing required field: titulo"}), 400

        if "idioma" not in data:
            return jsonify({"error": "Missing required field: idioma"}), 400

        if "nivel" not in data:
            return jsonify({"error": "Missing required field: nivel"}), 400

        try:
            result = BookService.create_book(data, current_user._id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result), 201

    @staticmethod
    @token_required
    def update_book(current_user, token, book_id):
        """Atualiza um livro (apenas admin)."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json()
        try:
            updated = BookService.update_book(book_id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if updated:
            return jsonify({"message": "Book updated successfully"}), 200
        return jsonify({"error": "Book not found"}), 404

    @staticmethod
    @token_required
    def delete_book(current_user, token, book_id):
        """Deleta um livro (apenas admin)."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        deleted = BookService.delete_book(book_id)

        if deleted:
            return jsonify({"message": "Book deleted successfully"}), 200
        return jsonify({"error": "Book not found"}), 404

    @staticmethod
    @token_required
    def get_all_books(current_user, token):
        """Retorna todos os livros (apenas admin para ver tudo)."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        books = BookService.get_all_books()
        return jsonify({"books": books}), 200

    @staticmethod
    @token_required
    def get_available_books(current_user, token):
        """Retorna livros do usuário e para descobrir."""
        result = BookService.get_available_books(current_user._id)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def get_book_by_id(current_user, token, book_id):
        """Busca um livro pelo ID. Para usuário logado retorna capítulos com has_cards e user_has_saved."""
        book = BookService.get_book_by_id_for_user(book_id, current_user._id)
        if not book:
            book = BookService.get_book_by_id(book_id)
        if not book:
            return jsonify({"error": "Book not found"}), 404

        allowed, payload = EntitlementService.can_access_book(current_user, book_id)
        if not allowed:
            return jsonify(payload), 403

        return jsonify(book), 200

    @staticmethod
    @token_required
    def purchase_book(current_user, token):
        """Adiciona um livro à biblioteca do usuário após pagamento."""
        data = request.get_json()

        if "book_id" not in data:
            return jsonify({"error": "Missing book_id"}), 400

        book_id = data["book_id"]
        book = BookService.get_book_by_id(book_id)

        if not book:
            return jsonify({"error": "Book not found"}), 404

        if book.get("is_free"):
            BookService.add_book_to_user(current_user._id, book_id)
            return jsonify({"message": "Book added to your library"}), 200

        allowed, _payload = EntitlementService.can_access_book(current_user, book_id)
        if allowed:
            BookService.add_book_to_user(current_user._id, book_id)
            return jsonify({"message": "Book already available in your library"}), 200

        confirmed = PaymentModel.confirmed_for_product(current_user._id, "book", book_id)
        if not confirmed:
            return jsonify({
                "error": "Payment not confirmed. Use /billing/checkout to buy this book.",
                "code": "payment_required",
            }), 402

        EntitlementService.grant_book(current_user._id, book_id, source="purchase", source_id=confirmed["_id"])
        return jsonify({"message": "Book purchased and added to your library"}), 200

    @staticmethod
    @token_required
    def purchase_with_coins(current_user, token):
        data = request.get_json() or {}
        book_id = data.get("book_id")
        if not book_id:
            return jsonify({"error": "Missing book_id"}), 400
        try:
            result = BookService.purchase_with_coins(current_user._id, book_id)
        except ValueError as exc:
            message = str(exc)
            status = 404 if "not found" in message.lower() else 400
            return jsonify({"error": message}), status
        return jsonify(result), 200

    @staticmethod
    @token_required
    def admin_get_book_with_users(current_user, token, book_id):
        """Retorna detalhes do livro e lista de usuários com informação se possuem o livro (apenas admin)."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        book = BookService.get_book_by_id(book_id)
        if not book:
            return jsonify({"error": "Book not found"}), 404

        # Busca todos os usuários (id, nome, email)
        users_cursor = mongo.db.users.find({}, {"name": 1, "email": 1})
        users = []
        user_ids = []
        for u in users_cursor:
            uid = str(u["_id"])
            users.append(
                {
                    "_id": uid,
                    "name": u.get("name"),
                    "email": u.get("email"),
                }
            )
            user_ids.append(ObjectId(uid))

        # Busca quais usuários possuem o livro
        book_obj_id = ObjectId(book_id)
        user_books_cursor = mongo.db.user_books.find(
            {"book_id": book_obj_id, "user_id": {"$in": user_ids}}
        )
        users_with_book = {str(ub["user_id"]) for ub in user_books_cursor}

        # Marca flag has_book em cada usuário
        for u in users:
            u["has_book"] = u["_id"] in users_with_book

        return jsonify({"book": book, "users": users}), 200

    @staticmethod
    @token_required
    def admin_assign_book_to_user(current_user, token):
        """Atribui um livro a um usuário específico (apenas admin)."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json()
        user_id = data.get("user_id")
        book_id = data.get("book_id")

        if not user_id or not book_id:
            return jsonify({"error": "Missing user_id or book_id"}), 400

        EntitlementService.grant_book(
            user_id, book_id, source="manual", granted_by=current_user._id, notes="admin assign"
        )
        return jsonify({"message": "Book assigned to user"}), 200

    @staticmethod
    @token_required
    def admin_generate_collection(current_user, token, book_id):
        """Gera collection e decks para livro que ainda não tem collection_id (apenas admin)."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        result = BookService.generate_collection_for_book(book_id)
        if result is None:
            return jsonify({"error": "Book not found"}), 404
        if result.get("already"):
            return jsonify({"message": "Book already has collection", "collection_id": result["collection_id"]}), 200
        return jsonify(result), 200

    @staticmethod
    @token_required
    def admin_add_chapter(current_user, token):
        """Adiciona um capítulo ao livro (apenas admin). Cria um deck na collection do livro."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json()
        book_id = data.get("book_id")
        title = data.get("title")
        if not book_id or not title:
            return jsonify({"error": "Missing book_id or title"}), 400

        result = BookService.add_chapter(book_id, title, data.get("content"))
        if not result:
            return jsonify({"error": "Book not found"}), 404
        return jsonify(result), 201

    @staticmethod
    @token_required
    def admin_add_cards_to_chapter(current_user, token):
        """Adiciona cartas ao deck de um capítulo (apenas admin)."""
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json()
        book_id = data.get("book_id")
        deck_id = data.get("deck_id")
        card_ids = data.get("card_ids", [])
        if not book_id or not deck_id or not card_ids:
            return jsonify({"error": "Missing book_id, deck_id or card_ids"}), 400

        ok = BookService.add_cards_to_chapter(book_id, deck_id, card_ids)
        if not ok:
            return jsonify({"error": "Book not found or deck does not belong to book"}), 404
        return jsonify({"message": "Cards added to chapter"}), 200

    @staticmethod
    @token_required
    def save_chapter_cards(current_user, token):
        """Usuário salva as cartas do capítulo: a collection do livro passa a ser dele e é gerado progresso."""
        data = request.get_json()
        book_id = data.get("book_id")
        deck_id = data.get("deck_id")
        if not book_id or not deck_id:
            return jsonify({"error": "Missing book_id or deck_id"}), 400

        result = BookService.save_chapter_cards(current_user._id, book_id, deck_id)
        if result is None:
            return jsonify({"error": "Book not found or deck does not belong to book"}), 404
        return jsonify(result), 200

    @staticmethod
    @token_required
    def mark_chapter_read(current_user, token):
        """Marca ou desmarca um capítulo como lido para o usuário."""
        data = request.get_json()
        book_id = data.get("book_id")
        chapter_ordem = data.get("chapter_ordem")
        read = data.get("read", True)

        if not book_id or chapter_ordem is None:
            return jsonify({"error": "Missing book_id or chapter_ordem"}), 400

        try:
            chapter_ordem_int = int(chapter_ordem)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid chapter_ordem"}), 400

        result = BookService.mark_chapter_read(str(current_user._id), book_id, chapter_ordem_int, read)
        if result is None:
            return jsonify({"error": "Book or chapter not found"}), 404
        return jsonify(result), 200


# Blueprint para as rotas
books_blueprint = Blueprint("books_blueprint", __name__)

# Rotas admin
books_blueprint.route("/admin/create", methods=["POST"])(
    BookController.create_book
)
books_blueprint.route("/admin/update/<string:book_id>", methods=["PUT"])(
    BookController.update_book
)
books_blueprint.route("/admin/delete/<string:book_id>", methods=["DELETE"])(
    BookController.delete_book
)
books_blueprint.route("/admin/list", methods=["GET"])(
    BookController.get_all_books
)
books_blueprint.route("/admin/book/<string:book_id>", methods=["GET"])(
    BookController.admin_get_book_with_users
)
books_blueprint.route("/admin/assign", methods=["POST"])(
    BookController.admin_assign_book_to_user
)
books_blueprint.route("/admin/generate-collection/<string:book_id>", methods=["POST"])(
    BookController.admin_generate_collection
)
books_blueprint.route("/admin/add-chapter", methods=["POST"])(
    BookController.admin_add_chapter
)
books_blueprint.route("/admin/add-cards-to-chapter", methods=["POST"])(
    BookController.admin_add_cards_to_chapter
)

# Rotas usuário
books_blueprint.route("/list", methods=["GET"])(
    BookController.get_available_books
)
books_blueprint.route("/save-chapter-cards", methods=["POST"])(
    BookController.save_chapter_cards
)
books_blueprint.route("/get/<string:book_id>", methods=["GET"])(
    BookController.get_book_by_id
)
books_blueprint.route("/purchase", methods=["POST"])(
    BookController.purchase_book
)
books_blueprint.route("/purchase-with-coins", methods=["POST"])(
    BookController.purchase_with_coins
)
books_blueprint.route("/mark-chapter-read", methods=["POST"])(
    BookController.mark_chapter_read
)