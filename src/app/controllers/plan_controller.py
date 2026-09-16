"""Plan catalog endpoints."""

from flask import Blueprint, jsonify, request

from src.app.middlewares.token_required import token_required
from src.app.models.billing_support_model import AuditLogModel
from src.app.models.plan_model import PlanModel
from src.app.utils.billing_utils import PLAN_CYCLES, SERVICE_KEYS


class PlanController:
    @staticmethod
    def list_public():
        return jsonify({"plans": PlanModel.list_plans(active_only=True, public_only=True)}), 200

    @staticmethod
    @token_required
    def list_admin(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        return jsonify({
            "plans": PlanModel.list_plans(),
            "cycles": list(PLAN_CYCLES),
            "service_keys": list(SERVICE_KEYS),
        }), 200

    @staticmethod
    @token_required
    def get_plan(current_user, token, plan_id):
        plan = PlanModel.get_by_id(plan_id)
        if not plan:
            return jsonify({"error": "Plan not found"}), 404
        if not plan.get("is_public") and not current_user.has_role("admin"):
            return jsonify({"error": "Plan not found"}), 404
        return jsonify(plan), 200

    @staticmethod
    @token_required
    def create_plan(current_user, token):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        if not data.get("name"):
            return jsonify({"error": "name is required"}), 400
        try:
            plan = PlanModel.create(data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        AuditLogModel.record(current_user._id, "create", "plan", plan["_id"], None, plan)
        return jsonify(plan), 201

    @staticmethod
    @token_required
    def update_plan(current_user, token, plan_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        data = request.get_json() or {}
        try:
            plan = PlanModel.update(plan_id, data)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if not plan:
            return jsonify({"error": "Plan not found"}), 404
        AuditLogModel.record(current_user._id, "update", "plan", plan_id, None, plan)
        return jsonify(plan), 200

    @staticmethod
    @token_required
    def delete_plan(current_user, token, plan_id):
        if not current_user.has_role("admin"):
            return jsonify({"error": "Unauthorized"}), 403
        plan = PlanModel.soft_delete(plan_id)
        if not plan:
            return jsonify({"error": "Plan not found"}), 404
        AuditLogModel.record(current_user._id, "deactivate", "plan", plan_id, None, plan)
        return jsonify({"message": "Plan deactivated", "plan": plan}), 200


plan_blueprint = Blueprint("plan_blueprint", __name__)
plan_blueprint.route("/public", methods=["GET"])(PlanController.list_public)
plan_blueprint.route("/admin", methods=["GET"])(PlanController.list_admin)
plan_blueprint.route("/admin", methods=["POST"])(PlanController.create_plan)
plan_blueprint.route("/<string:plan_id>", methods=["GET"])(PlanController.get_plan)
plan_blueprint.route("/admin/<string:plan_id>", methods=["PUT"])(PlanController.update_plan)
plan_blueprint.route("/admin/<string:plan_id>", methods=["DELETE"])(PlanController.delete_plan)
