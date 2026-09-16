"""Module for handling decks-related endpoints."""

from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Unauthorized

from src.app.services.deck_service import DeckService


class DecksController:
    """class to control decks"""

    @staticmethod
    def create_deck():
        """create a new deck"""

        data = request.get_json()
        if not data or "name" not in data or "collection_id" not in data:
            return jsonify({"error": "Missing required information"}), 400
        
        if "image" in data:
            image = data["image"]
        else:
            image = None
        
        if "cards" in data:
            cards = data["cards"]
        else:
            cards = None

        try:
            result = DeckService.create_deck(
                data["name"],
                data["collection_id"],
                image,
                cards,
                status=data.get("status"),
                scheduled_at=data.get("scheduled_at"),
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result), 200

    @staticmethod
    def get_all_decks():
        """Get all decks"""

        result = DeckService.get_all_decks()
        return jsonify(result), 200

    @staticmethod
    def get_decks_by_collection_id():
        """This method get decks by user_id"""

        collection_id = request.args.get("collection_id")
        user_id = request.args.get("user_id")

        if not collection_id or not user_id:
            return jsonify({"error": "info is required"}), 400

        result = DeckService.get_decks_by_collection_id(collection_id, user_id)
        return jsonify(result), 200
    
    @staticmethod
    def save_deck():
        """This method save the deck in user collection"""
        
        data = request.get_json()
        
        user_id = data.get("user_id")
        deck_id = data.get("deck_id")
        collection_id = data.get("collection_id")

        if not all([user_id, deck_id, collection_id]):
            return jsonify({"error": "Missing required information"}), 400
        
        result = DeckService.save_deck(user_id, deck_id, collection_id)
        if result:
            return jsonify(result), 200
        else:
            return BadRequest(description="error")
        
    @staticmethod
    def check_if_the_user_has_the_deck():
        """This method is responsible for verify if the deck has the user"""
        
        data = request.get_json()
        
        user_id = data.get("user_id")
        deck_id = data.get("deck_id")

        if not all([user_id, deck_id]):
            return jsonify({"error": "Missing required information"}), 400
        
        response = DeckService.check_if_the_user_has_the_deck(user_id, deck_id)
        
        return jsonify(response), 200

    @staticmethod
    def update_deck(deck_id):
        data = request.get_json() or {}
        try:
            result = DeckService.update_deck(deck_id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not result:
            return jsonify({"error": "Deck not found"}), 404
        return jsonify(result), 200

    @staticmethod
    def delete_deck(deck_id):
        if DeckService.delete_deck(deck_id):
            return jsonify({"message": "Deck deleted"}), 200
        return jsonify({"error": "Deck not found"}), 404

    @staticmethod
    def get_deck(deck_id):
        result = DeckService.get_deck(deck_id)
        if not result:
            return jsonify({"error": "Deck not found"}), 404
        return jsonify(result), 200
        


decks_blueprint = Blueprint("decks_blueprint", __name__)

decks_blueprint.route("/create", methods=["POST"])(DecksController.create_deck)
decks_blueprint.route("/get", methods=["GET"])(DecksController.get_all_decks)
decks_blueprint.route("/get_by_collection_id", methods=["GET"])(
    DecksController.get_decks_by_collection_id
)
decks_blueprint.route("/save_deck", methods=["POST"])(DecksController.save_deck)
decks_blueprint.route("/check_if_the_user_has_the_deck", methods=["POST"])(DecksController.check_if_the_user_has_the_deck)
decks_blueprint.route("/<string:deck_id>", methods=["GET"])(DecksController.get_deck)
decks_blueprint.route("/<string:deck_id>", methods=["PUT"])(DecksController.update_deck)
decks_blueprint.route("/<string:deck_id>", methods=["DELETE"])(DecksController.delete_deck)
