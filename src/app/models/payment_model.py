"""Payment / purchase transactions."""

import uuid

from src.app import mongo
from src.app.utils.billing_utils import parse_datetime, serialize_doc, to_object_id, utcnow


class PaymentModel:
    @staticmethod
    def create(data):
        now = utcnow()
        doc = {
            "user_id": str(data["user_id"]) if data.get("user_id") else None,
            "type": data.get("type") or "subscription",
            "provider": data.get("provider") or "asaas",
            "provider_payment_id": data.get("provider_payment_id") or f"local_{uuid.uuid4().hex}",
            "status": data.get("status") or "pending",
            "amount": float(data.get("amount") or 0),
            "currency": data.get("currency") or "BRL",
            "product_type": data.get("product_type"),
            "product_id": str(data["product_id"]) if data.get("product_id") else None,
            "subscription_id": str(data["subscription_id"]) if data.get("subscription_id") else None,
            "coupon_id": data.get("coupon_id"),
            "invoice_url": data.get("invoice_url"),
            "payment_method": data.get("payment_method"),
            "paid_at": parse_datetime(data.get("paid_at")),
            "refunded_at": parse_datetime(data.get("refunded_at")),
            "origin": data.get("origin") or "platform",
            "metadata": data.get("metadata") or {},
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.payments.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(payment_id, data):
        updates = {"updated_at": utcnow()}
        for field in (
            "status",
            "provider_payment_id",
            "invoice_url",
            "payment_method",
            "subscription_id",
            "origin",
        ):
            if field in data:
                updates[field] = data[field]
        if "amount" in data:
            updates["amount"] = float(data["amount"])
        if "paid_at" in data:
            updates["paid_at"] = parse_datetime(data["paid_at"])
        if "refunded_at" in data:
            updates["refunded_at"] = parse_datetime(data["refunded_at"])
        if "metadata" in data:
            updates["metadata"] = data["metadata"]
        mongo.db.payments.update_one({"_id": to_object_id(payment_id)}, {"$set": updates})
        return PaymentModel.get_by_id(payment_id)

    @staticmethod
    def get_by_id(payment_id):
        try:
            return serialize_doc(mongo.db.payments.find_one({"_id": to_object_id(payment_id)}))
        except Exception:
            return None

    @staticmethod
    def get_by_provider_id(provider, provider_payment_id):
        if not provider_payment_id:
            return None
        return serialize_doc(
            mongo.db.payments.find_one({
                "provider": provider,
                "provider_payment_id": provider_payment_id,
            })
        )

    @staticmethod
    def list_for_user(user_id):
        return [
            serialize_doc(doc)
            for doc in mongo.db.payments.find({"user_id": str(user_id)}).sort("created_at", -1)
        ]

    @staticmethod
    def confirmed_for_product(user_id, product_type, product_id):
        return serialize_doc(
            mongo.db.payments.find_one({
                "user_id": str(user_id),
                "product_type": product_type,
                "product_id": str(product_id),
                "status": {"$in": ["confirmed", "received"]},
            })
        )

    @staticmethod
    def query(filters=None, skip=0, limit=50):
        filters = filters or {}
        query = {}
        if filters.get("user_id"):
            query["user_id"] = str(filters["user_id"])
        if filters.get("product_id"):
            query["product_id"] = str(filters["product_id"])
        if filters.get("product_type"):
            query["product_type"] = filters["product_type"]
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
        cursor = mongo.db.payments.find(query).sort("created_at", -1).skip(int(skip)).limit(int(limit))
        total = mongo.db.payments.count_documents(query)
        return [serialize_doc(doc) for doc in cursor], total
