"""Book bundle endpoints."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.models.billing_support_model import AuditLogModel
from src.app.models.book_bundle_model import BookBundleModel


class BundleController:
    @staticmethod
    @token_required
    def list_public(current_user, token):
        return jsonify({"bundles": BookBundleModel.list_bundles(published_only=True)}), 200

    @staticmethod
    @token_required
    def list_admin(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({"bundles": BookBundleModel.list_bundles()}), 200

    @staticmethod
    @token_required
    def create_bundle(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        if not data.get("name"):
            return jsonify({"error": "name is required"}), 400
        try:
            bundle = BookBundleModel.create(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        AuditLogModel.record(current_user._id, "create", "bundle", bundle["_id"], None, bundle)
        return jsonify(bundle), 201

    @staticmethod
    @token_required
    def update_bundle(current_user, token, bundle_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            bundle = BookBundleModel.update(bundle_id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not bundle:
            return jsonify({"error": "Bundle not found"}), 404
        AuditLogModel.record(current_user._id, "update", "bundle", bundle_id, None, bundle)
        return jsonify(bundle), 200

    @staticmethod
    @token_required
    def delete_bundle(current_user, token, bundle_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        deleted = BookBundleModel.delete(bundle_id)
        if not deleted:
            return jsonify({"error": "Bundle not found"}), 404
        AuditLogModel.record(current_user._id, "delete", "bundle", bundle_id)
        return jsonify({"message": "Bundle deleted"}), 200


bundle_blueprint = Blueprint("bundle_blueprint", __name__)
bundle_blueprint.route("/public", methods=["GET"])(BundleController.list_public)
bundle_blueprint.route("/admin", methods=["GET"])(BundleController.list_admin)
bundle_blueprint.route("/admin", methods=["POST"])(BundleController.create_bundle)
bundle_blueprint.route("/admin/<string:bundle_id>", methods=["PUT"])(BundleController.update_bundle)
bundle_blueprint.route("/admin/<string:bundle_id>", methods=["DELETE"])(BundleController.delete_bundle)
