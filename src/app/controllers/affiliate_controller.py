"""Affiliate self-service endpoints."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.services.affiliate_service import AffiliateError, AffiliateService


def _handle(exc):
    return jsonify({"error": exc.message}), exc.status_code


class AffiliateController:
    @staticmethod
    @token_required
    def get_me(current_user, token):
        try:
            return jsonify(AffiliateService.get_me(current_user)), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def list_products(current_user, token):
        try:
            return jsonify(AffiliateService.list_affiliate_products(current_user)), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def get_product(current_user, token, product_id):
        try:
            return jsonify(AffiliateService.get_affiliate_product(current_user, product_id)), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def apply(current_user, token, product_id):
        data = request.get_json() or {}
        try:
            application = AffiliateService.apply_to_product(
                current_user,
                product_id,
                accepted_terms=bool(data.get("accepted_terms")),
            )
            return jsonify(application), 201
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def sales(current_user, token):
        try:
            return jsonify({"sales": AffiliateService.list_sales(current_user)}), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def wallet(current_user, token):
        try:
            return jsonify(AffiliateService.get_wallet(current_user)), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def list_withdrawals(current_user, token):
        try:
            wallet = AffiliateService.get_wallet(current_user)
            return jsonify({"withdrawals": wallet.get("withdrawals") or []}), 200
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    @token_required
    def request_withdrawal(current_user, token):
        data = request.get_json() or {}
        try:
            withdrawal = AffiliateService.request_withdrawal(current_user, data)
            return jsonify(withdrawal), 201
        except AffiliateError as exc:
            return _handle(exc)

    @staticmethod
    def public_click():
        data = request.get_json() or {}
        try:
            click = AffiliateService.record_click(
                data.get("referral_code") or data.get("ref") or request.args.get("ref"),
                product_slug=data.get("product_slug") or data.get("slug") or request.args.get("slug"),
            )
            return jsonify(click), 201
        except AffiliateError as exc:
            return _handle(exc)


affiliate_blueprint = Blueprint("affiliate_blueprint", __name__)
affiliate_blueprint.route("/me", methods=["GET"])(AffiliateController.get_me)
affiliate_blueprint.route("/products", methods=["GET"])(AffiliateController.list_products)
affiliate_blueprint.route("/products/<string:product_id>", methods=["GET"])(AffiliateController.get_product)
affiliate_blueprint.route("/products/<string:product_id>/apply", methods=["POST"])(AffiliateController.apply)
affiliate_blueprint.route("/sales", methods=["GET"])(AffiliateController.sales)
affiliate_blueprint.route("/wallet", methods=["GET"])(AffiliateController.wallet)
affiliate_blueprint.route("/withdrawals", methods=["GET"])(AffiliateController.list_withdrawals)
affiliate_blueprint.route("/withdrawals", methods=["POST"])(AffiliateController.request_withdrawal)
affiliate_blueprint.route("/public/click", methods=["POST", "GET"])(AffiliateController.public_click)
