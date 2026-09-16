"""Admin affiliate management endpoints."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.models.affiliate_application_model import AffiliateApplicationModel
from src.app.models.affiliate_commission_model import AffiliateCommissionModel
from src.app.models.affiliate_model import AffiliateSettingsModel
from src.app.models.affiliate_product_model import AffiliateProductModel
from src.app.models.affiliate_withdrawal_model import AffiliateWithdrawalModel
from src.app.models.user_model import UserModel
from src.app.services.affiliate_service import AffiliateError, AffiliateService


def _handle(exc):
    return jsonify({"error": exc.message}), exc.status_code


def _require_admin(current_user):
    if not current_user.has_role("admin"):
        raise AffiliateError("Unauthorized", 403)


def _enrich_application(item):
    user = UserModel.find_by_id(item.get("user_id"))
    product = AffiliateProductModel.get_by_id(item.get("product_id"))
    return {
        **item,
        "user_name": user.name if user else None,
        "user_email": user.email if user else None,
        "product_name": product.get("name") if product else None,
    }


def _enrich_commission(item):
    user = UserModel.find_by_id(item.get("user_id"))
    product = AffiliateProductModel.get_by_id(item.get("product_id"))
    return {
        **item,
        "user_name": user.name if user else None,
        "user_email": user.email if user else None,
        "product_name": product.get("name") if product else None,
    }


def _enrich_withdrawal(item):
    user = UserModel.find_by_id(item.get("user_id"))
    return {
        **item,
        "user_name": user.name if user else None,
        "user_email": user.email if user else None,
    }


class AdminAffiliateController:
    @staticmethod
    @token_required
    def list_affiliates(current_user, token):
        try:
            _require_admin(current_user)
            status = request.args.get("status")
            return jsonify({"affiliates": AffiliateService.list_affiliates(status=status)}), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def add_affiliate(current_user, token):
        try:
            _require_admin(current_user)
            data = request.get_json() or {}
            user_id = data.get("user_id")
            if not user_id:
                return jsonify({"error": "user_id is required"}), 400
            affiliate = AffiliateService.add_affiliate(user_id, admin_id=current_user._id)
            return jsonify(affiliate), 201
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def update_affiliate(current_user, token, affiliate_id):
        try:
            _require_admin(current_user)
            data = request.get_json() or {}
            status = data.get("status")
            if not status:
                return jsonify({"error": "status is required"}), 400
            return jsonify(AffiliateService.set_status(affiliate_id, status, admin_id=current_user._id)), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def list_products(current_user, token):
        try:
            _require_admin(current_user)
            return jsonify({"products": AffiliateProductModel.list_products()}), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def create_product(current_user, token):
        try:
            _require_admin(current_user)
            product = AffiliateProductModel.create(request.get_json() or {})
            return jsonify(product), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def update_product(current_user, token, product_id):
        try:
            _require_admin(current_user)
            product = AffiliateProductModel.update(product_id, request.get_json() or {})
            if not product:
                return jsonify({"error": "Product not found"}), 404
            return jsonify(product), 200
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def get_settings(current_user, token):
        try:
            _require_admin(current_user)
            return jsonify(AffiliateSettingsModel.get()), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def update_settings(current_user, token):
        try:
            _require_admin(current_user)
            return jsonify(AffiliateSettingsModel.update(request.get_json() or {})), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def list_applications(current_user, token):
        try:
            _require_admin(current_user)
            status = request.args.get("status")
            items = [_enrich_application(item) for item in AffiliateApplicationModel.list_all(status=status)]
            return jsonify({"applications": items}), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def review_application(current_user, token, application_id):
        try:
            _require_admin(current_user)
            data = request.get_json() or {}
            updated = AffiliateService.review_application(
                application_id,
                data.get("status"),
                current_user._id,
                notes=data.get("notes") or "",
            )
            return jsonify(_enrich_application(updated)), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def list_commissions(current_user, token):
        try:
            _require_admin(current_user)
            status = request.args.get("status")
            affiliate_id = request.args.get("affiliate_id")
            items = [
                _enrich_commission(item)
                for item in AffiliateCommissionModel.list_all(status=status, affiliate_id=affiliate_id)
            ]
            return jsonify({"commissions": items}), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def review_commission(current_user, token, commission_id):
        try:
            _require_admin(current_user)
            data = request.get_json() or {}
            updated = AffiliateService.review_commission(
                commission_id,
                data.get("status"),
                current_user._id,
                notes=data.get("notes") or "",
            )
            return jsonify(_enrich_commission(updated)), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def list_withdrawals(current_user, token):
        try:
            _require_admin(current_user)
            status = request.args.get("status")
            items = [_enrich_withdrawal(item) for item in AffiliateWithdrawalModel.list_all(status=status)]
            return jsonify({"withdrawals": items}), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def review_withdrawal(current_user, token, withdrawal_id):
        try:
            _require_admin(current_user)
            data = request.get_json() or {}
            updated = AffiliateService.review_withdrawal(
                withdrawal_id,
                data.get("status"),
                current_user._id,
                notes=data.get("notes") or "",
            )
            return jsonify(_enrich_withdrawal(updated)), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def register_sale(current_user, token):
        try:
            _require_admin(current_user)
            sale = AffiliateService.register_external_sale(current_user, request.get_json() or {})
            return jsonify(sale), 201
        except AffiliateError as exc:
            return _handle(exc)


admin_affiliate_blueprint = Blueprint("admin_affiliate_blueprint", __name__)
admin_affiliate_blueprint.route("/", methods=["GET"], strict_slashes=False)(AdminAffiliateController.list_affiliates)
admin_affiliate_blueprint.route("/", methods=["POST"], strict_slashes=False)(AdminAffiliateController.add_affiliate)
admin_affiliate_blueprint.route("/products", methods=["GET"])(AdminAffiliateController.list_products)
admin_affiliate_blueprint.route("/products", methods=["POST"])(AdminAffiliateController.create_product)
admin_affiliate_blueprint.route("/products/<string:product_id>", methods=["PATCH"])(AdminAffiliateController.update_product)
admin_affiliate_blueprint.route("/settings", methods=["GET"])(AdminAffiliateController.get_settings)
admin_affiliate_blueprint.route("/settings", methods=["PATCH"])(AdminAffiliateController.update_settings)
admin_affiliate_blueprint.route("/applications", methods=["GET"])(AdminAffiliateController.list_applications)
admin_affiliate_blueprint.route("/applications/<string:application_id>", methods=["PATCH"])(
    AdminAffiliateController.review_application
)
admin_affiliate_blueprint.route("/commissions", methods=["GET"])(AdminAffiliateController.list_commissions)
admin_affiliate_blueprint.route("/commissions/<string:commission_id>", methods=["PATCH"])(
    AdminAffiliateController.review_commission
)
admin_affiliate_blueprint.route("/withdrawals", methods=["GET"])(AdminAffiliateController.list_withdrawals)
admin_affiliate_blueprint.route("/withdrawals/<string:withdrawal_id>", methods=["PATCH"])(
    AdminAffiliateController.review_withdrawal
)
admin_affiliate_blueprint.route("/sales", methods=["POST"])(AdminAffiliateController.register_sale)
admin_affiliate_blueprint.route("/<string:affiliate_id>", methods=["PATCH"])(AdminAffiliateController.update_affiliate)
