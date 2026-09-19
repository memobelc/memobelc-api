"""HTTP endpoints for user and admin support conversations."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.services.support_service import SupportError, SupportService


def _error(exc):
    return jsonify({"error": exc.message}), exc.status_code


def _json_body():
    return request.get_json(silent=True) or {}


class SupportController:
    @staticmethod
    @token_required
    def list_tickets(current_user, token):
        result = SupportService.list_user_tickets(str(current_user._id))
        return jsonify(result), 200

    @staticmethod
    @token_required
    def get_conversation(current_user, token):
        since = request.args.get("since")
        ticket_id = request.args.get("ticket_id")
        try:
            result = SupportService.get_user_conversation(
                str(current_user._id), since=since, ticket_id=ticket_id
            )
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def get_ticket(current_user, token, ticket_id):
        since = request.args.get("since")
        try:
            result = SupportService.get_user_conversation(
                str(current_user._id), since=since, ticket_id=ticket_id
            )
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def list_messages(current_user, token):
        since = request.args.get("since")
        ticket_id = request.args.get("ticket_id")
        try:
            result = SupportService.get_user_conversation(
                str(current_user._id), since=since, ticket_id=ticket_id
            )
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def send_message(current_user, token):
        data = _json_body()
        try:
            result = SupportService.send_user_message(
                str(current_user._id),
                data.get("body"),
                ticket_id=data.get("ticket_id"),
            )
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 201

    @staticmethod
    @token_required
    def mark_read(current_user, token):
        data = _json_body()
        ticket_id = data.get("ticket_id") or request.args.get("ticket_id")
        try:
            result = SupportService.mark_user_messages_read(
                str(current_user._id), ticket_id=ticket_id
            )
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def submit_csat(current_user, token, ticket_id):
        data = _json_body()
        try:
            result = SupportService.submit_csat(
                str(current_user._id), ticket_id, data.get("score")
            )
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 200


class AdminSupportController:
    @staticmethod
    def _forbid_unless_admin(current_user):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return None

    @staticmethod
    @token_required
    def list_tickets(current_user, token):
        forbidden = AdminSupportController._forbid_unless_admin(current_user)
        if forbidden:
            return forbidden
        status = request.args.get("status")
        query = request.args.get("q") or request.args.get("search")
        try:
            result = SupportService.list_admin_tickets(status=status, q=query)
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def csat_metrics(current_user, token):
        forbidden = AdminSupportController._forbid_unless_admin(current_user)
        if forbidden:
            return forbidden
        return jsonify(SupportService.csat_metrics()), 200

    @staticmethod
    @token_required
    def get_ticket(current_user, token, ticket_id):
        forbidden = AdminSupportController._forbid_unless_admin(current_user)
        if forbidden:
            return forbidden
        try:
            ticket = SupportService.get_admin_ticket(ticket_id)
        except SupportError as exc:
            return _error(exc)
        return jsonify({"ticket": ticket}), 200

    @staticmethod
    @token_required
    def list_messages(current_user, token, ticket_id):
        forbidden = AdminSupportController._forbid_unless_admin(current_user)
        if forbidden:
            return forbidden
        since = request.args.get("since")
        try:
            result = SupportService.list_admin_messages(ticket_id, since=since)
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def send_message(current_user, token, ticket_id):
        forbidden = AdminSupportController._forbid_unless_admin(current_user)
        if forbidden:
            return forbidden
        data = _json_body()
        try:
            result = SupportService.send_admin_message(
                str(current_user._id), ticket_id, data.get("body")
            )
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 201

    @staticmethod
    @token_required
    def mark_read(current_user, token, ticket_id):
        forbidden = AdminSupportController._forbid_unless_admin(current_user)
        if forbidden:
            return forbidden
        try:
            result = SupportService.mark_admin_messages_read(ticket_id)
        except SupportError as exc:
            return _error(exc)
        return jsonify(result), 200

    @staticmethod
    @token_required
    def close_ticket(current_user, token, ticket_id):
        forbidden = AdminSupportController._forbid_unless_admin(current_user)
        if forbidden:
            return forbidden
        data = _json_body()
        try:
            ticket = SupportService.close_ticket(
                str(current_user._id),
                ticket_id,
                skip_csat=bool(data.get("skip_csat")),
            )
        except SupportError as exc:
            return _error(exc)
        return jsonify({"ticket": ticket}), 200

    @staticmethod
    @token_required
    def reopen_ticket(current_user, token, ticket_id):
        forbidden = AdminSupportController._forbid_unless_admin(current_user)
        if forbidden:
            return forbidden
        try:
            ticket = SupportService.reopen_ticket(ticket_id)
        except SupportError as exc:
            return _error(exc)
        return jsonify({"ticket": ticket}), 200


support_blueprint = Blueprint("support_blueprint", __name__)
support_blueprint.route("/tickets", methods=["GET"])(SupportController.list_tickets)
support_blueprint.route("/tickets/<string:ticket_id>", methods=["GET"])(
    SupportController.get_ticket
)
support_blueprint.route("/tickets/<string:ticket_id>/csat", methods=["POST"])(
    SupportController.submit_csat
)
support_blueprint.route("/conversation", methods=["GET"])(SupportController.get_conversation)
support_blueprint.route("/messages", methods=["GET"])(SupportController.list_messages)
support_blueprint.route("/messages", methods=["POST"])(SupportController.send_message)
support_blueprint.route("/messages/read", methods=["POST"])(SupportController.mark_read)

admin_support_blueprint = Blueprint("admin_support_blueprint", __name__)
admin_support_blueprint.route("/tickets", methods=["GET"])(AdminSupportController.list_tickets)
admin_support_blueprint.route("/metrics", methods=["GET"])(AdminSupportController.csat_metrics)
admin_support_blueprint.route("/tickets/<string:ticket_id>", methods=["GET"])(
    AdminSupportController.get_ticket
)
admin_support_blueprint.route("/tickets/<string:ticket_id>/messages", methods=["GET"])(
    AdminSupportController.list_messages
)
admin_support_blueprint.route("/tickets/<string:ticket_id>/messages", methods=["POST"])(
    AdminSupportController.send_message
)
admin_support_blueprint.route("/tickets/<string:ticket_id>/messages/read", methods=["POST"])(
    AdminSupportController.mark_read
)
admin_support_blueprint.route("/tickets/<string:ticket_id>/close", methods=["PATCH"])(
    AdminSupportController.close_ticket
)
admin_support_blueprint.route("/tickets/<string:ticket_id>/reopen", methods=["PATCH"])(
    AdminSupportController.reopen_ticket
)
