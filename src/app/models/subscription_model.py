"""User subscriptions."""

import uuid

from src.app import mongo
from src.app.utils.billing_utils import (
    ACCESS_STATUSES,
    PAID_ACTIVE_STATUSES,
    serialize_doc,
    to_object_id,
    utcnow,
    parse_datetime,
)


class SubscriptionModel:
    @staticmethod
    def create(data):
        now = utcnow()
        doc = {
            "user_id": str(data["user_id"]),
            "plan_id": str(data["plan_id"]),
            "provider": data.get("provider") or "asaas",
            "provider_subscription_id": data.get("provider_subscription_id") or f"local_{uuid.uuid4().hex}",
            "asaas_customer_id": data.get("asaas_customer_id"),
            "status": data.get("status") or "pending",
            "started_at": parse_datetime(data.get("started_at")) or now,
            "current_period_start": parse_datetime(data.get("current_period_start")),
            "current_period_end": parse_datetime(data.get("current_period_end")),
            "next_due_date": parse_datetime(data.get("next_due_date")),
            "canceled_at": parse_datetime(data.get("canceled_at")),
            "billing_cycle": data.get("billing_cycle"),
            "value": float(data.get("value") or 0),
            "original_value": float(data.get("original_value") or data.get("value") or 0),
            "coupon_id": data.get("coupon_id"),
            "payment_method": data.get("payment_method"),
            "grace_until": parse_datetime(data.get("grace_until")),
            "invoice_url": data.get("invoice_url"),
            "metadata": data.get("metadata") or {},
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.subscriptions.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(subscription_id, data):
        updates = {"updated_at": utcnow()}
        for field in (
            "status",
            "provider_subscription_id",
            "asaas_customer_id",
            "billing_cycle",
            "payment_method",
            "coupon_id",
            "invoice_url",
            "plan_id",
            "provider",
        ):
            if field in data:
                updates[field] = data[field]
        for field in (
            "started_at",
            "current_period_start",
            "current_period_end",
            "next_due_date",
            "canceled_at",
            "grace_until",
        ):
            if field in data:
                updates[field] = parse_datetime(data[field])
        if "value" in data:
            updates["value"] = float(data["value"])
        if "original_value" in data:
            updates["original_value"] = float(data["original_value"])
        if "metadata" in data:
            updates["metadata"] = data["metadata"]
        mongo.db.subscriptions.update_one(
            {"_id": to_object_id(subscription_id)},
            {"$set": updates},
        )
        return SubscriptionModel.get_by_id(subscription_id)

    @staticmethod
    def get_by_id(subscription_id):
        try:
            return serialize_doc(mongo.db.subscriptions.find_one({"_id": to_object_id(subscription_id)}))
        except Exception:
            return None

    @staticmethod
    def get_by_provider_id(provider, provider_subscription_id):
        if not provider_subscription_id:
            return None
        return serialize_doc(
            mongo.db.subscriptions.find_one({
                "provider": provider,
                "provider_subscription_id": provider_subscription_id,
            })
        )

    @staticmethod
    def get_active_for_user(user_id):
        return serialize_doc(
            mongo.db.subscriptions.find_one({
                "user_id": str(user_id),
                "status": {"$in": list(PAID_ACTIVE_STATUSES) + ["pending", "overdue"]},
            })
        )

    @staticmethod
    def get_paid_active_for_user(user_id):
        return serialize_doc(
            mongo.db.subscriptions.find_one({
                "user_id": str(user_id),
                "status": {"$in": list(ACCESS_STATUSES)},
            })
        )

    @staticmethod
    def list_for_user(user_id):
        return [
            serialize_doc(doc)
            for doc in mongo.db.subscriptions.find({"user_id": str(user_id)}).sort("created_at", -1)
        ]

    @staticmethod
    def query(filters=None, skip=0, limit=50):
        filters = filters or {}
        query = {}
        if filters.get("user_id"):
            query["user_id"] = str(filters["user_id"])
        if filters.get("plan_id"):
            query["plan_id"] = str(filters["plan_id"])
        if filters.get("status"):
            query["status"] = filters["status"]
        if filters.get("provider"):
            query["provider"] = filters["provider"]
        start = parse_datetime(filters.get("date_from"))
        end = parse_datetime(filters.get("date_to"))
        if start or end:
            query["created_at"] = {}
            if start:
                query["created_at"]["$gte"] = start
            if end:
                query["created_at"]["$lte"] = end
        cursor = mongo.db.subscriptions.find(query).sort("created_at", -1).skip(int(skip)).limit(int(limit))
        total = mongo.db.subscriptions.count_documents(query)
        return [serialize_doc(doc) for doc in cursor], total
