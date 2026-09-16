"""Entitlements and admin billing management."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.models.billing_support_model import AuditLogModel, ExternalSaleModel
from src.app.models.classroom_model import ClassroomModel
from src.app.models.entitlement_model import EntitlementModel
from src.app.models.payment_model import PaymentModel
from src.app.models.service_access_model import ServiceAccessModel
from src.app.models.subscription_model import SubscriptionModel
from src.app.services.billing_service import BillingService
from src.app.services.classroom_service import ClassroomService
from src.app.services.entitlement_service import EntitlementService
from src.app.utils.billing_utils import SERVICE_KEYS, VISIBILITY_ACTIONS, AUDIENCES


class EntitlementController:
    @staticmethod
    @token_required
    def me(current_user, token):
        return jsonify(EntitlementService.resolve(current_user)), 200


class AdminBillingController:
    @staticmethod
    @token_required
    def list_subscriptions(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        items, total = SubscriptionModel.query(request.args, skip=request.args.get("skip", 0), limit=request.args.get("limit", 50))
        return jsonify({"subscriptions": items, "total": total}), 200

    @staticmethod
    @token_required
    def get_subscription(current_user, token, subscription_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        subscription = SubscriptionModel.get_by_id(subscription_id)
        if not subscription:
            return jsonify({"error": "Subscription not found"}), 404
        payments = [
            item for item in PaymentModel.list_for_user(subscription["user_id"])
            if item.get("subscription_id") == subscription_id
        ]
        return jsonify({"subscription": subscription, "payments": payments}), 200

    @staticmethod
    @token_required
    def list_payments(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        items, total = PaymentModel.query(request.args, skip=request.args.get("skip", 0), limit=request.args.get("limit", 50))
        return jsonify({"payments": items, "total": total}), 200

    @staticmethod
    @token_required
    def subscription_action(current_user, token, subscription_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        payload, status = BillingService.admin_set_status(
            current_user,
            subscription_id,
            data.get("status"),
            data.get("action"),
        )
        return jsonify(payload), status

    @staticmethod
    @token_required
    def grant(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        payload, status = BillingService.admin_grant(current_user, request.get_json() or {})
        return jsonify(payload), status

    @staticmethod
    @token_required
    def revoke(current_user, token, entitlement_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        payload, status = BillingService.admin_revoke(current_user, entitlement_id)
        return jsonify(payload), status

    @staticmethod
    @token_required
    def user_entitlements(current_user, token, user_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"entitlements": EntitlementModel.list_for_user(user_id)}), 200

    @staticmethod
    @token_required
    def external_sale(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        payload, status = BillingService.register_external_sale(current_user, request.get_json() or {})
        return jsonify(payload), status

    @staticmethod
    @token_required
    def list_external_sales(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"sales": ExternalSaleModel.list_sales()}), 200

    @staticmethod
    @token_required
    def list_access_rules(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({
            "rules": ServiceAccessModel.list_rules(),
            "service_keys": list(SERVICE_KEYS),
            "actions": list(VISIBILITY_ACTIONS),
            "audiences": list(AUDIENCES),
        }), 200

    @staticmethod
    @token_required
    def update_access_rule(current_user, token, service_key):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            rule = ServiceAccessModel.upsert(service_key, data.get("rules") or [], data.get("label"))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        AuditLogModel.record(current_user._id, "update", "service_access", service_key, None, rule)
        return jsonify(rule), 200

    @staticmethod
    @token_required
    def list_classrooms(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"classrooms": ClassroomModel.list_all()}), 200

    @staticmethod
    @token_required
    def update_classroom_checkout(current_user, token, classroom_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        result, status = ClassroomService.update_classroom(current_user, classroom_id, data)
        if status >= 400:
            return jsonify(result), status
        return jsonify(result), status

    @staticmethod
    @token_required
    def list_classroom_checkouts(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        payload = BillingService.admin_classroom_checkouts(
            request.args,
            skip=request.args.get("skip", 0),
            limit=request.args.get("limit", 50),
        )
        return jsonify(payload), 200

    @staticmethod
    @token_required
    def audit_logs(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"logs": AuditLogModel.list_logs(request.args)}), 200


entitlement_blueprint = Blueprint("entitlement_blueprint", __name__)
entitlement_blueprint.route("/me", methods=["GET"])(EntitlementController.me)

admin_billing_blueprint = Blueprint("admin_billing_blueprint", __name__)
admin_billing_blueprint.route("/subscriptions", methods=["GET"])(AdminBillingController.list_subscriptions)
admin_billing_blueprint.route("/subscriptions/<string:subscription_id>", methods=["GET"])(AdminBillingController.get_subscription)
admin_billing_blueprint.route("/subscriptions/<string:subscription_id>/action", methods=["POST"])(AdminBillingController.subscription_action)
admin_billing_blueprint.route("/payments", methods=["GET"])(AdminBillingController.list_payments)
admin_billing_blueprint.route("/grants", methods=["POST"])(AdminBillingController.grant)
admin_billing_blueprint.route("/grants/<string:entitlement_id>", methods=["DELETE"])(AdminBillingController.revoke)
admin_billing_blueprint.route("/users/<string:user_id>/entitlements", methods=["GET"])(AdminBillingController.user_entitlements)
admin_billing_blueprint.route("/external-sales", methods=["GET"])(AdminBillingController.list_external_sales)
admin_billing_blueprint.route("/external-sales", methods=["POST"])(AdminBillingController.external_sale)
admin_billing_blueprint.route("/access", methods=["GET"])(AdminBillingController.list_access_rules)
admin_billing_blueprint.route("/access/<string:service_key>", methods=["PUT"])(AdminBillingController.update_access_rule)
admin_billing_blueprint.route("/classrooms", methods=["GET"])(AdminBillingController.list_classrooms)
admin_billing_blueprint.route("/classrooms/<string:classroom_id>", methods=["PUT"])(AdminBillingController.update_classroom_checkout)
admin_billing_blueprint.route("/classroom-checkouts", methods=["GET"])(AdminBillingController.list_classroom_checkouts)
admin_billing_blueprint.route("/audit", methods=["GET"])(AdminBillingController.audit_logs)
