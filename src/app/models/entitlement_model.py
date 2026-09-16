"""Unified access grants."""

from src.app import mongo
from src.app.utils.billing_utils import parse_datetime, serialize_doc, to_object_id, utcnow


class EntitlementModel:
    @staticmethod
    def grant(data):
        now = utcnow()
        existing = mongo.db.entitlements.find_one({
            "user_id": str(data["user_id"]),
            "type": data["type"],
            "resource_id": str(data["resource_id"]),
            "revoked_at": None,
        })
        if existing:
            return serialize_doc(existing)
        doc = {
            "user_id": str(data["user_id"]),
            "type": data["type"],
            "resource_id": str(data["resource_id"]),
            "source": data.get("source") or "manual",
            "source_id": str(data["source_id"]) if data.get("source_id") else None,
            "granted_by": str(data["granted_by"]) if data.get("granted_by") else None,
            "granted_at": now,
            "expires_at": parse_datetime(data.get("expires_at")),
            "revoked_at": None,
            "notes": data.get("notes") or "",
        }
        result = mongo.db.entitlements.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def revoke(entitlement_id, notes=None):
        updates = {"revoked_at": utcnow()}
        if notes:
            updates["notes"] = notes
        mongo.db.entitlements.update_one({"_id": to_object_id(entitlement_id)}, {"$set": updates})
        return EntitlementModel.get_by_id(entitlement_id)

    @staticmethod
    def revoke_by_source(user_id, source, source_id):
        mongo.db.entitlements.update_many(
            {
                "user_id": str(user_id),
                "source": source,
                "source_id": str(source_id),
                "revoked_at": None,
            },
            {"$set": {"revoked_at": utcnow()}},
        )

    @staticmethod
    def get_by_id(entitlement_id):
        try:
            return serialize_doc(mongo.db.entitlements.find_one({"_id": to_object_id(entitlement_id)}))
        except Exception:
            return None

    @staticmethod
    def list_active_for_user(user_id):
        now = utcnow()
        query = {
            "user_id": str(user_id),
            "revoked_at": None,
            "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}],
        }
        return [serialize_doc(doc) for doc in mongo.db.entitlements.find(query)]

    @staticmethod
    def list_for_user(user_id):
        return [
            serialize_doc(doc)
            for doc in mongo.db.entitlements.find({"user_id": str(user_id)}).sort("granted_at", -1)
        ]

    @staticmethod
    def find_active(user_id, entitlement_type, resource_id):
        now = utcnow()
        return serialize_doc(
            mongo.db.entitlements.find_one({
                "user_id": str(user_id),
                "type": entitlement_type,
                "resource_id": str(resource_id),
                "revoked_at": None,
                "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}],
            })
        )
