"""Admin endpoints for user and role management."""

from flask import Blueprint, jsonify, request
from bson.errors import InvalidId

from src.app.middlewares.token_required import token_required
from src.app.models.badge_model import BadgeModel
from src.app.models.mission_model import MissionModel
from src.app.models.user_model import ALLOWED_ROLES, UserModel
from src.app.services.admin_service import AdminService
from src.app.services.profile_service import ProfileService


class AdminController:
    """User listing and role updates (admin only)."""

    @staticmethod
    @token_required
    def list_users(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        search = request.args.get("search") or request.args.get("q")
        users = UserModel.list_users(search=search.strip() if search else None)
        return jsonify({"users": users}), 200

    @staticmethod
    @token_required
    def get_user_profile(current_user, token, user_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        try:
            result = AdminService.get_user_profile(user_id)
        except InvalidId:
            return jsonify({"error": "User not found"}), 404
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(exc) or "Error loading user profile"}), 500
        if not result:
            return jsonify({"error": "User not found"}), 404
        return jsonify(result), 200

    @staticmethod
    @token_required
    def update_user_roles(current_user, token, user_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json() or {}
        roles = data.get("roles")

        if not isinstance(roles, list) or len(roles) == 0:
            return jsonify({"error": "roles must be a non-empty list"}), 400

        invalid = [role for role in roles if role not in ALLOWED_ROLES]
        if invalid:
            return jsonify({"error": f"Invalid roles: {', '.join(invalid)}"}), 400

        normalized = UserModel.normalize_roles(roles=roles)
        if not normalized:
            return jsonify({"error": "roles must be a non-empty list"}), 400

        if str(current_user._id) == str(user_id) and "admin" not in normalized:
            return jsonify({"error": "You cannot remove your own admin role"}), 400

        try:
            updated = UserModel.update_roles(user_id, normalized)
        except InvalidId:
            return jsonify({"error": "User not found"}), 404

        if not updated:
            return jsonify({"error": "User not found"}), 404

        return jsonify({
            "_id": updated._id,
            "name": updated.name,
            "email": updated.email,
            "role": updated.role,
            "roles": updated.get_roles(),
        }), 200

    @staticmethod
    @token_required
    def list_badges(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"badges": BadgeModel.list_badges()}), 200

    @staticmethod
    @token_required
    def create_badge(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            badge = BadgeModel.create(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(badge), 201

    @staticmethod
    @token_required
    def update_badge(current_user, token, badge_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            badge = BadgeModel.update(badge_id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except InvalidId:
            return jsonify({"error": "Badge not found"}), 404
        if not badge:
            return jsonify({"error": "Badge not found"}), 404
        return jsonify(badge), 200

    @staticmethod
    @token_required
    def list_badge_earners(current_user, token, badge_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        badge = BadgeModel.get_by_id(badge_id)
        if not badge:
            return jsonify({"error": "Badge not found"}), 404
        return jsonify({"badge": badge, "users": BadgeModel.list_earners(badge_id)}), 200

    @staticmethod
    @token_required
    def award_badge(current_user, token, user_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        badge_id = data.get("badge_id")
        if not badge_id:
            return jsonify({"error": "badge_id is required"}), 400
        try:
            if not UserModel.find_by_id(user_id):
                return jsonify({"error": "User not found"}), 404
            award = BadgeModel.award(user_id, badge_id, awarded_by=current_user._id)
        except ValueError as exc:
            message = str(exc)
            status = 404 if "not found" in message.lower() else 400
            return jsonify({"error": message}), status
        except InvalidId:
            return jsonify({"error": "Not found"}), 404
        return jsonify(award), 201

    @staticmethod
    @token_required
    def list_missions(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"missions": MissionModel.list_missions()}), 200

    @staticmethod
    @token_required
    def create_mission(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            mission = MissionModel.create(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(mission), 201

    @staticmethod
    @token_required
    def update_mission(current_user, token, mission_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            mission = MissionModel.update(mission_id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except InvalidId:
            return jsonify({"error": "Mission not found"}), 404
        if not mission:
            return jsonify({"error": "Mission not found"}), 404
        return jsonify(mission), 200

    @staticmethod
    @token_required
    def list_mission_completers(current_user, token, mission_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        mission = MissionModel.get_by_id(mission_id)
        if not mission:
            return jsonify({"error": "Mission not found"}), 404
        return jsonify({
            "mission": mission,
            "users": MissionModel.list_completers(mission_id),
        }), 200

    @staticmethod
    @token_required
    def grant_coins(current_user, token, user_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            result = ProfileService.grant_coins(
                user_id,
                data.get("amount") or 0,
                data.get("reason"),
                current_user._id,
            )
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        except InvalidId:
            return jsonify({"error": "User not found"}), 404
        if not result:
            return jsonify({"error": "User not found"}), 404
        return jsonify(result), 200


admin_blueprint = Blueprint("admin_blueprint", __name__)

admin_blueprint.route("/users", methods=["GET"])(AdminController.list_users)
admin_blueprint.route("/users/<string:user_id>/profile", methods=["GET"])(
    AdminController.get_user_profile
)
admin_blueprint.route("/users/<string:user_id>/roles", methods=["PATCH"])(
    AdminController.update_user_roles
)
admin_blueprint.route("/users/<string:user_id>/badges", methods=["POST"])(
    AdminController.award_badge
)
admin_blueprint.route("/users/<string:user_id>/coins", methods=["POST"])(
    AdminController.grant_coins
)
admin_blueprint.route("/badges", methods=["GET"])(AdminController.list_badges)
admin_blueprint.route("/badges", methods=["POST"])(AdminController.create_badge)
admin_blueprint.route("/badges/<string:badge_id>", methods=["PATCH"])(
    AdminController.update_badge
)
admin_blueprint.route("/badges/<string:badge_id>/users", methods=["GET"])(
    AdminController.list_badge_earners
)
admin_blueprint.route("/missions", methods=["GET"])(AdminController.list_missions)
admin_blueprint.route("/missions", methods=["POST"])(AdminController.create_mission)
admin_blueprint.route("/missions/<string:mission_id>", methods=["PATCH"])(
    AdminController.update_mission
)
admin_blueprint.route("/missions/<string:mission_id>/users", methods=["GET"])(
    AdminController.list_mission_completers
)
