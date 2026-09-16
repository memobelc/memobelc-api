"""Webhook idempotency, admin audit logs and external sales."""

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow, parse_datetime


class WebhookEventModel:
    @staticmethod
    def already_processed(provider, event_id):
        if not event_id:
            return False
        return mongo.db.webhook_events.find_one({"provider": provider, "event_id": str(event_id)}) is not None

    @staticmethod
    def record(provider, event_id, event_type, payload, status="processed"):
        doc = {
            "provider": provider,
            "event_id": str(event_id),
            "event_type": event_type,
            "payload": payload,
            "status": status,
            "processed_at": utcnow(),
        }
        try:
            mongo.db.webhook_events.insert_one(doc)
            return True
        except Exception:
            return False


class AuditLogModel:
    @staticmethod
    def record(admin_id, action, target_type, target_id=None, before=None, after=None):
        doc = {
            "admin_id": str(admin_id) if admin_id else None,
            "action": action,
            "target_type": target_type,
            "target_id": str(target_id) if target_id else None,
            "before": before,
            "after": after,
            "created_at": utcnow(),
        }
        result = mongo.db.admin_audit_logs.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def list_logs(filters=None, skip=0, limit=50):
        filters = filters or {}
        query = {}
        if filters.get("admin_id"):
            query["admin_id"] = str(filters["admin_id"])
        if filters.get("target_type"):
            query["target_type"] = filters["target_type"]
        if filters.get("target_id"):
            query["target_id"] = str(filters["target_id"])
        cursor = mongo.db.admin_audit_logs.find(query).sort("created_at", -1).skip(int(skip)).limit(int(limit))
        return [serialize_doc(doc) for doc in cursor]


class ExternalSaleModel:
    @staticmethod
    def create(data):
        now = utcnow()
        doc = {
            "email": (data.get("email") or "").lower(),
            "name": data.get("name") or "",
            "user_id": str(data["user_id"]) if data.get("user_id") else None,
            "product_type": data.get("product_type"),
            "product_ids": [str(item) for item in (data.get("product_ids") or [])],
            "amount": float(data["amount"]) if data.get("amount") not in (None, "") else None,
            "origin": data.get("origin") or "external",
            "notes": data.get("notes") or "",
            "invite_sent": bool(data.get("invite_sent", False)),
            "created_by": str(data["created_by"]) if data.get("created_by") else None,
            "created_at": now,
        }
        result = mongo.db.external_sales.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def list_sales():
        return [serialize_doc(doc) for doc in mongo.db.external_sales.find().sort("created_at", -1)]

    @staticmethod
    def get_by_id(sale_id):
        try:
            return serialize_doc(mongo.db.external_sales.find_one({"_id": to_object_id(sale_id)}))
        except Exception:
            return None
