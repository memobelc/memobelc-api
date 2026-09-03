"""Module for handling cards-related endpoints."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, current_user
from werkzeug.exceptions import BadRequest, Unauthorized
from src.app.services.card_service import CardService


class CardController:
    """Class to handle cards operations"""

    @staticmethod
    def create_card():
        """This Method create a card"""

        data = request.get_json()
        try:
            payload = CardService.validate_card_payload(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        user_id = data.get("user_id") if data else None
        deck_id = data.get("deck_id") if data else None

        try:
            result = CardService.create_card(
                payload["front"],
                payload["back"],
                deck_id,
                user_id,
                payload["audio"],
                payload["media_type"],
                payload["card_type"],
                payload["options"],
                payload["correct_index"],
                payload["image"],
                status=payload.get("status"),
                scheduled_at=payload.get("scheduled_at"),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result), 201
    
    @staticmethod
    def create_card_in_lots():
        """Create cards in lote"""
        
        data = request.get_json()
        
        if ("cards") not in data:
            return jsonify({"error": "Missing required information11"}), 400
        
        if "image" in data:
            image = data["image"]
        else:
            image = None
        
        if ("deck_name") in data:
            
           response = CardService.create_card_in_lots(data["deck_name"], image, data["cards"])
           return jsonify(response), 201

    @staticmethod
    def get_card_by_id(card_id):
        """This Method get a card by its id"""

        result = CardService.get_card_by_id(card_id)
        if result:
            return jsonify(result), 200
        return jsonify({"error": "Card não encontrado"}), 404
    
    @staticmethod
    def get_cards_by_deck(deck_id):
        "This Method is responsible for get all cards in deck"
        
        user_id = request.args.get("user_id")
        response = CardService.get_cards_by_deck(deck_id, user_id=user_id)
        
        if response:
            return jsonify(response), 200
        return jsonify('error'), 400

    @staticmethod
    def get_all_cards():
        """This Method get all cards"""
        result = CardService.get_all_cards()
        return jsonify(result), 200

    @staticmethod
    def update_card(card_id):
        """This Method update a card by id"""

        data = request.get_json()
        try:
            result = CardService.update_card(card_id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if result:
            return jsonify(result), 200
        return jsonify({"error": "Card não encontrado"}), 404

    @staticmethod
    def delete_card(card_id):
        """This Method delete a card by id(its not recommended)."""

        if CardService.delete_card(card_id):
            return jsonify({"message": "Card excluído com sucesso"}), 200
        return jsonify({"error": "Card não encontrado"}), 404

    @staticmethod
    @jwt_required()
    def check_card_permission(card_id):
        """Verifica se o usuário atual tem permissão para editar/excluir um card."""
        user_id = str(current_user._id)
        if hasattr(current_user, "get_roles"):
            user_role = current_user.get_roles()
        else:
            user_role = getattr(current_user, "role", "user")
        
        result = CardService.check_card_permission(card_id, user_id, user_role)
        return jsonify(result), 200



card_blueprint = Blueprint("card_blueprint", __name__)


card_blueprint.route("/create", methods=["POST"])(CardController.create_card)
card_blueprint.route("/get_all_cards", methods=["GET"])(CardController.get_all_cards)

card_blueprint.route("/<string:card_id>", methods=["GET"])(
    CardController.get_card_by_id
)
card_blueprint.route("/<string:card_id>", methods=["PUT"])(CardController.update_card)
card_blueprint.route("/<string:card_id>", methods=["DELETE"])(
    CardController.delete_card
)
card_blueprint.route("/get_cards_by_deck/<string:deck_id>", methods=['GET'])(CardController.get_cards_by_deck)
card_blueprint.route("/create_card_in_lots", methods=["POST"])(CardController.create_card_in_lots)
card_blueprint.route("/check_permission/<string:card_id>", methods=["GET"])(CardController.check_card_permission)

