"""Module for handling chat-related endpoints."""

from flask import Blueprint, request, jsonify
from src.app.middlewares.token_required import token_required
from src.app.services.chat_service import ChatService
from src.app.middlewares.require_service_access import require_service_access

class ChatController:
    @staticmethod
    @token_required
    @require_service_access("talk_to_me")
    def chat(current_user, token):
        data = request.get_json() or {}
        history = data.get("history", [])
        id = data.get("id", None)
        message = data.get("message", "")
        settings = data.get("settings", {})
        try:
            result = ChatService.chat(
                current_user._id, id, history, settings, message
            )
            return jsonify(result), 200
        except Exception as e:
            if "429" in str(type(e).__name__) or "ResourceExhausted" in str(e):
                return jsonify({"error": "API quota exceeded"}), 429
            return jsonify({"error": str(e)}), 500
    
    @staticmethod
    @token_required
    def get_chats_by_user_id(current_user, token):
        response = ChatService.get_chats_by_user_id(current_user._id)
        return jsonify(response), 200
    
    def generate_cards_by_chat():
        data = request.get_json() or {}
        response = ChatService.generate_card(
            chat_id=data.get("chat_id"), settings=data.get("settings")
        )
        if response is None:
            return jsonify({"error": "Chat not found"}), 404
        return jsonify(response), 200
    

chat_blueprint = Blueprint("chat_blueprint", __name__)
chat_blueprint.route("/talk_to_me", methods=["POST"])(ChatController.chat)
chat_blueprint.route("/get_chats_by_user", methods=["GET"])(ChatController.get_chats_by_user_id)
chat_blueprint.route('/generate_card', methods=["POST"])(ChatController.generate_cards_by_chat)
