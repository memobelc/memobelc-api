"""Subscription plan catalog."""

from src.app import mongo
from src.app.utils.billing_utils import (
    PLAN_CYCLES,
    SERVICE_KEYS,
    parse_datetime,
    serialize_doc,
    to_object_id,
    utcnow,
)


class PlanModel:
    @staticmethod
    def create(data):
        cycle = data.get("cycle") or "MONTHLY"
        if cycle not in PLAN_CYCLES:
            raise ValueError(f"Invalid cycle: {cycle}")
        now = utcnow()
        doc = {
            "name": data.get("name"),
            "description": data.get("description") or "",
            "price": float(data.get("price") or 0),
            "currency": data.get("currency") or "BRL",
            "cycle": cycle,
            "trial_days": int(data.get("trial_days") or 0),
            "included_service_keys": [
                key for key in (data.get("included_service_keys") or []) if key in SERVICE_KEYS
            ],
            "included_book_ids": [str(item) for item in (data.get("included_book_ids") or [])],
            "included_bundle_ids": [str(item) for item in (data.get("included_bundle_ids") or [])],
            "usage_limits": data.get("usage_limits") or {},
            "is_active": bool(data.get("is_active", True)),
            "is_public": bool(data.get("is_public", True)),
            "google_play_product_id": data.get("google_play_product_id") or None,
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.plans.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(plan_id, data):
        existing = PlanModel.get_by_id(plan_id)
        if not existing:
            return None
        updates = {"updated_at": utcnow()}
        for field in (
            "name",
            "description",
            "currency",
            "usage_limits",
            "google_play_product_id",
        ):
            if field in data:
                updates[field] = data[field]
        if "price" in data:
            updates["price"] = float(data["price"])
        if "trial_days" in data:
            updates["trial_days"] = int(data["trial_days"] or 0)
        if "cycle" in data:
            if data["cycle"] not in PLAN_CYCLES:
                raise ValueError(f"Invalid cycle: {data['cycle']}")
            updates["cycle"] = data["cycle"]
        if "included_service_keys" in data:
            updates["included_service_keys"] = [
                key for key in data["included_service_keys"] if key in SERVICE_KEYS
            ]
        if "included_book_ids" in data:
            updates["included_book_ids"] = [str(item) for item in data["included_book_ids"]]
        if "included_bundle_ids" in data:
            updates["included_bundle_ids"] = [str(item) for item in data["included_bundle_ids"]]
        if "is_active" in data:
            updates["is_active"] = bool(data["is_active"])
        if "is_public" in data:
            updates["is_public"] = bool(data["is_public"])
        mongo.db.plans.update_one({"_id": to_object_id(plan_id)}, {"$set": updates})
        return PlanModel.get_by_id(plan_id)

    @staticmethod
    def get_by_id(plan_id):
        try:
            doc = mongo.db.plans.find_one({"_id": to_object_id(plan_id)})
        except Exception:
            return None
        return serialize_doc(doc)

    @staticmethod
    def get_by_google_sku(sku):
        if not sku:
            return None
        return serialize_doc(mongo.db.plans.find_one({"google_play_product_id": sku}))

    @staticmethod
    def list_plans(active_only=False, public_only=False):
        query = {}
        if active_only:
            query["is_active"] = True
        if public_only:
            query["is_public"] = True
        return [serialize_doc(doc) for doc in mongo.db.plans.find(query).sort("price", 1)]

    @staticmethod
    def soft_delete(plan_id):
        return PlanModel.update(plan_id, {"is_active": False, "is_public": False})

    @staticmethod
    def delete(plan_id):
        result = mongo.db.plans.delete_one({"_id": to_object_id(plan_id)})
        return result.deleted_count > 0
