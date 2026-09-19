from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Unauthorized

from src.app.services.notification_service import NotificationService
from src.app.models.notification.notification_group_model import NotificationGroupModel
from src.app.models.push_notification_model import PushNotificationModel
from src.app.middlewares.token_required import token_required


def _require_admin(current_user):
    if not current_user.has_role("admin"):
        raise Unauthorized(description="User Invalid!")


def _target_payload(data):
    return {
        "target_type": data.get("target_type"),
        "user_ids": data.get("user_ids"),
        "roles": data.get("roles"),
        "classroom_id": data.get("classroom_id"),
        "group_id": data.get("group_id"),
    }


class NotificationController:
    """Endpoints para gerenciamento de notificações do usuário."""

    @staticmethod
    @token_required
    def list_notifications(current_user, token):
        notifications = NotificationService.list_notifications(str(current_user._id))
        return jsonify({"notifications": notifications}), 200

    @staticmethod
    @token_required
    def unread_count(current_user, token):
        count = NotificationService.count_unread(str(current_user._id))
        return jsonify({"unread_count": count}), 200

    @staticmethod
    @token_required
    def mark_as_read(current_user, token):
        data = request.get_json() or {}
        notification_id = data.get("notification_id")
        mark_all = data.get("mark_all", False)

        if not notification_id and not mark_all:
            raise BadRequest(description="notification_id ou mark_all são obrigatórios")

        modified = NotificationService.mark_as_read(
            user_id=str(current_user._id),
            notification_id=notification_id,
            mark_all=mark_all,
        )
        return jsonify({"modified": modified}), 200

    @staticmethod
    @token_required
    def register_token(current_user, token):
        """Registra o token de push do dispositivo para notificações (somente app mobile)."""
        data = request.get_json() or {}
        push_token = data.get("push_token")

        if not push_token:
            raise BadRequest(description="push_token é obrigatório")

        device_info = data.get("device_info")

        PushNotificationModel.save_token(
            user_id=str(current_user._id),
            push_token=push_token,
            device_info=device_info,
        )
        return jsonify({"message": "Token registrado com sucesso"}), 200

    @staticmethod
    @token_required
    def get_settings(current_user, token):
        settings = NotificationService.get_user_settings(str(current_user._id))
        return jsonify(settings), 200

    @staticmethod
    @token_required
    def update_settings(current_user, token):
        data = request.get_json() or {}
        try:
            settings = NotificationService.update_user_settings(str(current_user._id), data)
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(settings), 200

    @staticmethod
    @token_required
    def send_daily(current_user, token):
        """Permite disparar manualmente as notificações diárias (restrito a admin)."""
        _require_admin(current_user)

        result = NotificationService.send_daily_study_notifications()
        return jsonify(result), 200

    @staticmethod
    @token_required
    def teacher_custom(current_user, token):
        """Professor ou admin envia notificação livre para alunos de uma turma."""
        is_admin = current_user.has_role("admin")
        if not is_admin and not current_user.has_role("teacher"):
            raise Unauthorized(description="User Invalid!")

        data = request.get_json() or {}
        classroom_id = data.get("classroom_id")
        title = data.get("title")
        body = data.get("body")
        student_ids = data.get("student_ids")

        if not all([classroom_id, title, body]):
            raise BadRequest(description="classroom_id, title e body são obrigatórios")

        if student_ids is not None and not isinstance(student_ids, list):
            raise BadRequest(description="student_ids deve ser uma lista")

        result, status = NotificationService.teacher_custom_notification(
            actor_id=str(current_user._id),
            classroom_id=classroom_id,
            title=title,
            body=body,
            student_ids=student_ids,
            is_admin=is_admin,
        )
        return jsonify(result), status

    @staticmethod
    @token_required
    def admin_custom(current_user, token):
        """Admin envia notificação livre para um alvo (todos, usuários, papéis, turma ou grupo)."""
        _require_admin(current_user)

        data = request.get_json() or {}
        title = data.get("title")
        body = data.get("body")

        if not all([title, body]):
            raise BadRequest(description="title e body são obrigatórios")

        try:
            result = NotificationService.admin_custom_notification(
                admin_id=str(current_user._id),
                title=title,
                body=body,
                **_target_payload(data),
            )
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(result), 200

    @staticmethod
    @token_required
    def admin_preview(current_user, token):
        """Conta destinatários de um alvo admin sem enviar a notificação."""
        _require_admin(current_user)
        data = request.get_json() or {}
        try:
            result = NotificationService.preview_admin_targets(**_target_payload(data))
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(result), 200

    @staticmethod
    @token_required
    def list_groups(current_user, token):
        _require_admin(current_user)
        return jsonify({"groups": NotificationGroupModel.list_groups()}), 200

    @staticmethod
    @token_required
    def create_group(current_user, token):
        _require_admin(current_user)
        data = request.get_json() or {}
        try:
            group = NotificationGroupModel.create(data, created_by=str(current_user._id))
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        return jsonify(group), 201

    @staticmethod
    @token_required
    def update_group(current_user, token, group_id):
        _require_admin(current_user)
        data = request.get_json() or {}
        try:
            group = NotificationGroupModel.update(group_id, data)
        except ValueError as exc:
            raise BadRequest(description=str(exc))
        if not group:
            return jsonify({"error": "Group not found"}), 404
        return jsonify(group), 200

    @staticmethod
    @token_required
    def delete_group(current_user, token, group_id):
        _require_admin(current_user)
        deleted = NotificationGroupModel.delete(group_id)
        if not deleted:
            return jsonify({"error": "Group not found"}), 404
        return jsonify({"deleted": True}), 200

    @staticmethod
    @token_required
    def list_admin_sent(current_user, token):
        _require_admin(current_user)
        return jsonify({"notifications": NotificationService.list_admin_sent()}), 200

    @staticmethod
    @token_required
    def delete_admin_sent(current_user, token, batch_id):
        _require_admin(current_user)
        deleted = NotificationService.delete_admin_sent(batch_id)
        if deleted <= 0:
            return jsonify({"error": "Notification not found"}), 404
        return jsonify({"deleted": True, "count": deleted}), 200


notification_blueprint = Blueprint("notification_blueprint", __name__)

notification_blueprint.route("/list", methods=["GET"])(NotificationController.list_notifications)
notification_blueprint.route("/unread_count", methods=["GET"])(NotificationController.unread_count)
notification_blueprint.route("/mark_as_read", methods=["POST"])(NotificationController.mark_as_read)
notification_blueprint.route("/register_token", methods=["POST"])(NotificationController.register_token)
notification_blueprint.route("/settings", methods=["GET"])(NotificationController.get_settings)
notification_blueprint.route("/settings", methods=["PATCH"])(NotificationController.update_settings)

# Rotas de disparo (teacher/admin)
notification_blueprint.route("/send_daily", methods=["POST"])(NotificationController.send_daily)
notification_blueprint.route("/teacher/custom", methods=["POST"])(NotificationController.teacher_custom)
notification_blueprint.route("/admin/custom", methods=["POST"])(NotificationController.admin_custom)
notification_blueprint.route("/admin/preview", methods=["POST"])(NotificationController.admin_preview)
notification_blueprint.route("/admin/groups", methods=["GET"])(NotificationController.list_groups)
notification_blueprint.route("/admin/groups", methods=["POST"])(NotificationController.create_group)
notification_blueprint.route("/admin/groups/<string:group_id>", methods=["PATCH"])(NotificationController.update_group)
notification_blueprint.route("/admin/groups/<string:group_id>", methods=["DELETE"])(NotificationController.delete_group)
notification_blueprint.route("/admin/sent", methods=["GET"])(NotificationController.list_admin_sent)
notification_blueprint.route("/admin/sent/<string:batch_id>", methods=["DELETE"])(
    NotificationController.delete_admin_sent
)
