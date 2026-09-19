from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Unauthorized

from src.app.middlewares.token_required import token_required
from src.app.models.tutorial_model import BrainAvatarModel, TutorialModel
from src.app.services.tutorial_service import TutorialService


tutorial_blueprint = Blueprint("tutorials", __name__)
admin_tutorial_blueprint = Blueprint("admin_tutorials", __name__)


def _require_admin(current_user):
    if not current_user.has_role("admin"):
        raise Unauthorized(description="User Invalid!")


def _locale():
    return (
        request.args.get("locale")
        or request.headers.get("Accept-Language", "en").split(",")[0].strip()
    )


class TutorialController:
    @staticmethod
    @token_required
    def me(current_user, token):
        section = request.args.get("section") or "home"
        tutorial = TutorialService.get_active_for_user(
            current_user, locale=_locale(), section=section
        )
        return jsonify({"tutorial": tutorial}), 200

    @staticmethod
    @token_required
    def catalog(current_user, token):
        tutorials = TutorialService.catalog_for_user(current_user, locale=_locale())
        return jsonify({"tutorials": tutorials}), 200

    @staticmethod
    @token_required
    def history(current_user, token):
        return jsonify({"history": TutorialService.history_for_user(current_user, locale=_locale())}), 200

    @staticmethod
    @token_required
    def record_event(current_user, token, tutorial_id):
        data = request.get_json() or {}
        event_type = data.get("type")
        if not event_type:
            raise BadRequest(description="type is required")
        try:
            result = TutorialService.record_event(
                current_user,
                tutorial_id,
                event_type,
                step_index=data.get("step_index"),
                duration_ms=data.get("duration_ms"),
            )
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(result), 200

    @staticmethod
    @token_required
    def complete(current_user, token, tutorial_id):
        data = request.get_json() or {}
        try:
            result = TutorialService.complete(
                current_user, tutorial_id, duration_ms=data.get("duration_ms")
            )
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(result), 200

    @staticmethod
    @token_required
    def skip(current_user, token, tutorial_id):
        data = request.get_json() or {}
        try:
            result = TutorialService.skip(
                current_user,
                tutorial_id,
                duration_ms=data.get("duration_ms"),
                step_index=data.get("step_index"),
            )
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(result), 200

    @staticmethod
    @token_required
    def replay(current_user, token, tutorial_id):
        try:
            tutorial = TutorialService.replay(current_user, tutorial_id, locale=_locale())
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify({"tutorial": tutorial}), 200


class AdminTutorialController:
    @staticmethod
    @token_required
    def list_tutorials(current_user, token):
        _require_admin(current_user)
        status = request.args.get("status")
        return jsonify({"tutorials": TutorialService.list_admin(status=status)}), 200

    @staticmethod
    @token_required
    def get_tutorial(current_user, token, tutorial_id):
        _require_admin(current_user)
        tutorial = TutorialModel.get_by_id(tutorial_id)
        if not tutorial:
            return jsonify({"error": "Tutorial not found"}), 404
        return jsonify(tutorial), 200

    @staticmethod
    @token_required
    def create_tutorial(current_user, token):
        _require_admin(current_user)
        data = request.get_json() or {}
        try:
            tutorial = TutorialModel.create(data, as_draft=True)
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(tutorial), 201

    @staticmethod
    @token_required
    def update_tutorial(current_user, token, tutorial_id):
        _require_admin(current_user)
        data = request.get_json() or {}
        try:
            tutorial = TutorialModel.update(tutorial_id, data)
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        if not tutorial:
            return jsonify({"error": "Tutorial not found"}), 404
        return jsonify(tutorial), 200

    @staticmethod
    @token_required
    def duplicate_tutorial(current_user, token, tutorial_id):
        _require_admin(current_user)
        data = request.get_json() or {}
        tutorial = TutorialModel.duplicate(
            tutorial_id, new_version=bool(data.get("new_version"))
        )
        if not tutorial:
            return jsonify({"error": "Tutorial not found"}), 404
        return jsonify(tutorial), 201

    @staticmethod
    @token_required
    def publish_tutorial(current_user, token, tutorial_id):
        _require_admin(current_user)
        try:
            tutorial = TutorialModel.publish(tutorial_id)
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        if not tutorial:
            return jsonify({"error": "Tutorial not found"}), 404
        return jsonify(tutorial), 200

    @staticmethod
    @token_required
    def deactivate_tutorial(current_user, token, tutorial_id):
        _require_admin(current_user)
        try:
            tutorial = TutorialModel.deactivate(tutorial_id)
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        if not tutorial:
            return jsonify({"error": "Tutorial not found"}), 404
        return jsonify(tutorial), 200

    @staticmethod
    @token_required
    def analytics(current_user, token, tutorial_id):
        _require_admin(current_user)
        result = TutorialService.analytics(tutorial_id)
        if not result:
            return jsonify({"error": "Tutorial not found"}), 404
        return jsonify(result), 200

    @staticmethod
    @token_required
    def list_avatars(current_user, token):
        _require_admin(current_user)
        return jsonify({"avatars": BrainAvatarModel.list_avatars()}), 200

    @staticmethod
    @token_required
    def create_avatar(current_user, token):
        _require_admin(current_user)
        data = request.get_json() or {}
        try:
            avatar = BrainAvatarModel.create(data)
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(avatar), 201

    @staticmethod
    @token_required
    def update_avatar(current_user, token, avatar_id):
        _require_admin(current_user)
        data = request.get_json() or {}
        avatar = BrainAvatarModel.update(avatar_id, data)
        if not avatar:
            return jsonify({"error": "Avatar not found"}), 404
        return jsonify(avatar), 200


tutorial_blueprint.route("/me", methods=["GET"])(TutorialController.me)
tutorial_blueprint.route("/catalog", methods=["GET"])(TutorialController.catalog)
tutorial_blueprint.route("/me/history", methods=["GET"])(TutorialController.history)
tutorial_blueprint.route("/<string:tutorial_id>/events", methods=["POST"])(
    TutorialController.record_event
)
tutorial_blueprint.route("/<string:tutorial_id>/complete", methods=["POST"])(
    TutorialController.complete
)
tutorial_blueprint.route("/<string:tutorial_id>/skip", methods=["POST"])(
    TutorialController.skip
)
tutorial_blueprint.route("/<string:tutorial_id>/replay", methods=["POST"])(
    TutorialController.replay
)

admin_tutorial_blueprint.route("/", methods=["GET"], strict_slashes=False)(
    AdminTutorialController.list_tutorials
)
admin_tutorial_blueprint.route("/", methods=["POST"], strict_slashes=False)(
    AdminTutorialController.create_tutorial
)
admin_tutorial_blueprint.route("/brain-avatars", methods=["GET"])(
    AdminTutorialController.list_avatars
)
admin_tutorial_blueprint.route("/brain-avatars", methods=["POST"])(
    AdminTutorialController.create_avatar
)
admin_tutorial_blueprint.route("/brain-avatars/<string:avatar_id>", methods=["PATCH"])(
    AdminTutorialController.update_avatar
)
admin_tutorial_blueprint.route("/<string:tutorial_id>", methods=["GET"])(
    AdminTutorialController.get_tutorial
)
admin_tutorial_blueprint.route("/<string:tutorial_id>", methods=["PATCH"])(
    AdminTutorialController.update_tutorial
)
admin_tutorial_blueprint.route("/<string:tutorial_id>/duplicate", methods=["POST"])(
    AdminTutorialController.duplicate_tutorial
)
admin_tutorial_blueprint.route("/<string:tutorial_id>/publish", methods=["POST"])(
    AdminTutorialController.publish_tutorial
)
admin_tutorial_blueprint.route("/<string:tutorial_id>/deactivate", methods=["POST"])(
    AdminTutorialController.deactivate_tutorial
)
admin_tutorial_blueprint.route("/<string:tutorial_id>/analytics", methods=["GET"])(
    AdminTutorialController.analytics
)
