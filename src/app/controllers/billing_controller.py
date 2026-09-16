"""User billing, Asaas webhooks and Google Play verification."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.services.billing_service import BillingService


def _client_ip():
    forwarded = request.headers.get("X-Forwarded-For") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


class BillingController:
    @staticmethod
    def public_checkout():
        data = request.get_json() or {}
        data.pop("password", None)
        data["_remote_ip"] = _client_ip()
        payload, status = BillingService.public_checkout(data)
        return jsonify(payload), status

    @staticmethod
    def public_sync_payment(payment_id):
        data = request.get_json() or {}
        payload, status = BillingService.public_sync_payment(payment_id, data)
        return jsonify(payload), status

    @staticmethod
    def public_pix_qr(payment_id):
        data = request.get_json(silent=True) or {}
        if not data.get("email"):
            data["email"] = request.args.get("email")
            data["cpf_cnpj"] = request.args.get("cpf_cnpj")
        payload, status = BillingService.public_get_pix_qr(payment_id, data)
        return jsonify(payload), status

    @staticmethod
    @token_required
    def checkout(current_user, token):
        data = request.get_json() or {}
        data["_remote_ip"] = _client_ip()
        payload, status = BillingService.checkout(current_user, data)
        return jsonify(payload), status

    @staticmethod
    @token_required
    def me(current_user, token):
        return jsonify(BillingService.my_subscription(current_user)), 200

    @staticmethod
    @token_required
    def payments(current_user, token):
        return jsonify({"payments": BillingService.my_payments(current_user)}), 200

    @staticmethod
    @token_required
    def sync_payment(current_user, token, payment_id):
        payload, status = BillingService.sync_payment(current_user, payment_id)
        return jsonify(payload), status

    @staticmethod
    @token_required
    def pix_qr(current_user, token, payment_id):
        payload, status = BillingService.get_pix_qr(current_user, payment_id)
        return jsonify(payload), status

    @staticmethod
    @token_required
    def cancel(current_user, token):
        payload, status = BillingService.cancel_mine(current_user)
        return jsonify(payload), status

    @staticmethod
    @token_required
    def change_plan(current_user, token):
        data = request.get_json() or {}
        plan_id = data.get("plan_id")
        if not plan_id:
            return jsonify({"error": "plan_id is required"}), 400
        payload, status = BillingService.change_plan(current_user, plan_id)
        return jsonify(payload), status

    @staticmethod
    @token_required
    def update_payment(current_user, token):
        data = request.get_json(silent=True) or {}
        data["_remote_ip"] = _client_ip()
        payload, status = BillingService.update_payment_method(current_user, data)
        return jsonify(payload), status

    @staticmethod
    def asaas_webhook():
        payload = request.get_json(silent=True) or {}
        body, status = BillingService.handle_asaas_webhook(payload, request.headers)
        return jsonify(body), status

    @staticmethod
    @token_required
    def google_verify(current_user, token):
        data = request.get_json() or {}
        body, status = BillingService.verify_google_purchase(current_user, data)
        return jsonify(body), status

    @staticmethod
    def google_rtdn():
        token = request.args.get("token") or request.headers.get("X-Goog-Channel-Token")
        payload = request.get_json(silent=True) or {}
        body, status = BillingService.handle_google_rtdn(payload, token)
        return jsonify(body), status


billing_blueprint = Blueprint("billing_blueprint", __name__)
billing_blueprint.route("/public/checkout", methods=["POST"])(BillingController.public_checkout)
billing_blueprint.route("/public/payments/<payment_id>/sync", methods=["POST"])(BillingController.public_sync_payment)
billing_blueprint.route("/public/payments/<payment_id>/pix", methods=["POST"])(BillingController.public_pix_qr)
billing_blueprint.route("/checkout", methods=["POST"])(BillingController.checkout)
billing_blueprint.route("/me", methods=["GET"])(BillingController.me)
billing_blueprint.route("/payments", methods=["GET"])(BillingController.payments)
billing_blueprint.route("/payments/<payment_id>/sync", methods=["POST"])(BillingController.sync_payment)
billing_blueprint.route("/payments/<payment_id>/pix", methods=["GET"])(BillingController.pix_qr)
billing_blueprint.route("/cancel", methods=["POST"])(BillingController.cancel)
billing_blueprint.route("/change-plan", methods=["POST"])(BillingController.change_plan)
billing_blueprint.route("/update-payment", methods=["POST"])(BillingController.update_payment)
billing_blueprint.route("/asaas/webhook", methods=["POST"])(BillingController.asaas_webhook)
billing_blueprint.route("/google/verify", methods=["POST"])(BillingController.google_verify)
billing_blueprint.route("/google/rtdn", methods=["POST"])(BillingController.google_rtdn)
