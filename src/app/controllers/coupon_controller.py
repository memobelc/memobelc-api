"""Coupon endpoints."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.models.billing_support_model import AuditLogModel
from src.app.models.coupon_model import CouponModel
from src.app.services.coupon_service import CouponService


class CouponController:
    @staticmethod
    @token_required
    def list_admin(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"coupons": CouponModel.list_coupons()}), 200

    @staticmethod
    @token_required
    def create_coupon(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            coupon = CouponModel.create(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        AuditLogModel.record(current_user._id, "create", "coupon", coupon["_id"], None, coupon)
        return jsonify(coupon), 201

    @staticmethod
    @token_required
    def update_coupon(current_user, token, coupon_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            coupon = CouponModel.update(coupon_id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not coupon:
            return jsonify({"error": "Coupon not found"}), 404
        AuditLogModel.record(current_user._id, "update", "coupon", coupon_id, None, coupon)
        return jsonify(coupon), 200

    @staticmethod
    @token_required
    def redemptions(current_user, token, coupon_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"redemptions": CouponModel.list_redemptions(coupon_id)}), 200

    @staticmethod
    @token_required
    def validate_coupon(current_user, token):
        data = request.get_json() or {}
        quoted, error = CouponService.quote(
            data.get("amount") or 0,
            data.get("code"),
            data.get("product_type"),
            data.get("product_id"),
        )
        if error:
            return jsonify({"error": error, "valid": False}), 400
        return jsonify({"valid": True, **quoted}), 200


coupon_blueprint = Blueprint("coupon_blueprint", __name__)
coupon_blueprint.route("/admin", methods=["GET"])(CouponController.list_admin)
coupon_blueprint.route("/admin", methods=["POST"])(CouponController.create_coupon)
coupon_blueprint.route("/admin/<string:coupon_id>", methods=["PUT"])(CouponController.update_coupon)
coupon_blueprint.route("/admin/<string:coupon_id>/redemptions", methods=["GET"])(CouponController.redemptions)
coupon_blueprint.route("/validate", methods=["POST"])(CouponController.validate_coupon)
