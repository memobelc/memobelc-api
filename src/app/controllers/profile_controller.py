"""Self-service profile endpoints."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.models.mission_model import MissionModel
from src.app.services.profile_service import ProfileService


class ProfileController:
    @staticmethod
    @token_required
    def get_me(current_user, token):
        profile = ProfileService.get_me(current_user._id)
        if not profile:
            return jsonify({"error": "User not found"}), 404
        return jsonify(profile), 200

    @staticmethod
    @token_required
    def update_me(current_user, token):
        data = request.get_json() or {}
        try:
            profile = ProfileService.update_me(current_user._id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not profile:
            return jsonify({"error": "User not found"}), 404
        return jsonify(profile), 200

    @staticmethod
    @token_required
    def complete_mission(current_user, token, mission_id):
        try:
            result = MissionModel.complete(current_user._id, mission_id)
        except ValueError as exc:
            message = str(exc)
            status = 404 if "not found" in message.lower() else 400
            return jsonify({"error": message}), status
        return jsonify(result), 200


profile_blueprint = Blueprint("profile_blueprint", __name__)
profile_blueprint.route("/me", methods=["GET"])(ProfileController.get_me)
profile_blueprint.route("/me", methods=["PATCH"])(ProfileController.update_me)


mission_blueprint = Blueprint("mission_blueprint", __name__)
mission_blueprint.route("/<string:mission_id>/complete", methods=["POST"])(
    ProfileController.complete_mission
)
