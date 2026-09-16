"""Admin-defined recipient groups for custom notifications."""

from bson.errors import InvalidId

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow


class NotificationGroupModel:
    @staticmethod
    def _normalize_user_ids(user_ids):
        if not user_ids:
            return []
        if not isinstance(user_ids, list):
            raise ValueError("user_ids must be a list")
        seen = []
        for item in user_ids:
            uid = str(item or "").strip()
            if not uid or uid in seen:
                continue
            try:
                to_object_id(uid)
            except (InvalidId, TypeError, ValueError):
                raise ValueError(f"Invalid user id: {uid}")
            seen.append(uid)
        return seen

    @staticmethod
    def _hydrate_members(user_ids):
        object_ids = []
        for uid in user_ids or []:
            try:
                object_ids.append(to_object_id(uid))
            except Exception:
                continue
        if not object_ids:
            return []
        docs = list(
            mongo.db.users.find(
                {"_id": {"$in": object_ids}},
                {"name": 1, "email": 1},
            )
        )
        by_id = {
            str(doc["_id"]): {
                "_id": str(doc["_id"]),
                "name": doc.get("name") or "",
                "email": doc.get("email") or "",
            }
            for doc in docs
        }
        return [by_id[uid] for uid in user_ids if uid in by_id]

    @staticmethod
    def serialize(doc):
        item = serialize_doc(doc)
        if not item:
            return None
        user_ids = [str(uid) for uid in (item.get("user_ids") or [])]
        item["user_ids"] = user_ids
        item["members"] = NotificationGroupModel._hydrate_members(user_ids)
        item["member_count"] = len(item["members"])
        return item

    @staticmethod
    def create(data, created_by):
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Group name is required")
        user_ids = NotificationGroupModel._normalize_user_ids(data.get("user_ids"))
        now = utcnow()
        doc = {
            "name": name,
            "description": (data.get("description") or "").strip(),
            "user_ids": user_ids,
            "created_by": str(created_by) if created_by else None,
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.notification_groups.insert_one(doc)
        doc["_id"] = result.inserted_id
        return NotificationGroupModel.serialize(doc)

    @staticmethod
    def update(group_id, data):
        existing = NotificationGroupModel.get_by_id(group_id)
        if not existing:
            return None
        updates = {"updated_at": utcnow()}
        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("Group name is required")
            updates["name"] = name
        if "description" in data:
            updates["description"] = (data.get("description") or "").strip()
        if "user_ids" in data:
            updates["user_ids"] = NotificationGroupModel._normalize_user_ids(data.get("user_ids"))
        mongo.db.notification_groups.update_one(
            {"_id": to_object_id(group_id)},
            {"$set": updates},
        )
        return NotificationGroupModel.get_by_id(group_id)

    @staticmethod
    def get_by_id(group_id):
        try:
            oid = to_object_id(group_id)
        except Exception:
            return None
        doc = mongo.db.notification_groups.find_one({"_id": oid})
        return NotificationGroupModel.serialize(doc)

    @staticmethod
    def list_groups():
        docs = list(mongo.db.notification_groups.find().sort("created_at", -1))
        return [NotificationGroupModel.serialize(doc) for doc in docs]

    @staticmethod
    def delete(group_id):
        try:
            oid = to_object_id(group_id)
        except Exception:
            return False
        result = mongo.db.notification_groups.delete_one({"_id": oid})
        return result.deleted_count > 0
