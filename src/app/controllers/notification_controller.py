from flask import Blueprint, jsonify, request
from werkzeug.exceptions import BadRequest, Unauthorized

from src.app.services.notification_service import NotificationService
from src.app.models.push_notification_model import PushNotificationModel
from src.app.middlewares.token_required import token_required


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
        if not current_user.has_role("admin"):
            raise Unauthorized(description="User Invalid!")

        result = NotificationService.send_daily_study_notifications()
        return jsonify(result), 200

    @staticmethod
    @token_required
    def teacher_custom(current_user, token):
        """Professor envia notificação livre para uma turma."""
        if not current_user.has_role("teacher"):
            raise Unauthorized(description="User Invalid!")

        data = request.get_json() or {}
        classroom_id = data.get("classroom_id")
        title = data.get("title")
        body = data.get("body")

        if not all([classroom_id, title, body]):
            raise BadRequest(description="classroom_id, title e body são obrigatórios")

        result = NotificationService.teacher_custom_notification(
            teacher_id=str(current_user._id),
            classroom_id=classroom_id,
            title=title,
            body=body,
        )
        return jsonify(result), 200

    @staticmethod
    @token_required
    def admin_custom(current_user, token):
        """Admin envia notificação livre para um ou mais usuários (ou para todos se não passar lista)."""
        if not current_user.has_role("admin"):
            raise Unauthorized(description="User Invalid!")

        data = request.get_json() or {}
        title = data.get("title")
        body = data.get("body")
        user_ids = data.get("user_ids")  # opcional lista de ids

        if not all([title, body]):
            raise BadRequest(description="title e body são obrigatórios")

        result = NotificationService.admin_custom_notification(
            admin_id=str(current_user._id),
            title=title,
            body=body,
            user_ids=user_ids,
        )
        return jsonify(result), 200


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


