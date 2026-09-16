"""Badge catalog and user awards."""

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow


class BadgeModel:
    @staticmethod
    def create(data):
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Badge name is required")
        now = utcnow()
        doc = {
            "name": name,
            "description": (data.get("description") or "").strip(),
            "image": (data.get("image") or "").strip() or None,
            "is_active": bool(data.get("is_active", True)),
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.badges.insert_one(doc)
        doc["_id"] = result.inserted_id
        item = serialize_doc(doc)
        item["earners_count"] = 0
        return item

    @staticmethod
    def update(badge_id, data):
        existing = BadgeModel.get_by_id(badge_id)
        if not existing:
            return None
        updates = {"updated_at": utcnow()}
        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("Badge name is required")
            updates["name"] = name
        if "description" in data:
            updates["description"] = (data.get("description") or "").strip()
        if "image" in data:
            updates["image"] = (data.get("image") or "").strip() or None
        if "is_active" in data:
            updates["is_active"] = bool(data.get("is_active"))
        mongo.db.badges.update_one({"_id": to_object_id(badge_id)}, {"$set": updates})
        return BadgeModel.get_by_id(badge_id)

    @staticmethod
    def get_by_id(badge_id):
        try:
            oid = to_object_id(badge_id)
        except Exception:
            return None
        doc = mongo.db.badges.find_one({"_id": oid})
        return serialize_doc(doc)

    @staticmethod
    def list_badges(active_only=False):
        query = {"is_active": True} if active_only else {}
        docs = list(mongo.db.badges.find(query).sort("created_at", -1))
        counts = {}
        for row in mongo.db.user_badges.aggregate([
            {"$group": {"_id": "$badge_id", "count": {"$sum": 1}}},
        ]):
            counts[str(row["_id"])] = int(row.get("count") or 0)
        result = []
        for doc in docs:
            item = serialize_doc(doc)
            item["earners_count"] = counts.get(item["_id"], 0)
            result.append(item)
        return result

    @staticmethod
    def award(user_id, badge_id, awarded_by=None):
        badge = BadgeModel.get_by_id(badge_id)
        if not badge:
            raise ValueError("Badge not found")
        if not badge.get("is_active"):
            raise ValueError("Badge is not active")
        existing = mongo.db.user_badges.find_one({
            "user_id": str(user_id),
            "badge_id": str(badge_id),
        })
        if existing:
            raise ValueError("User already has this badge")
        doc = {
            "user_id": str(user_id),
            "badge_id": str(badge_id),
            "awarded_at": utcnow(),
            "awarded_by": str(awarded_by) if awarded_by else None,
        }
        result = mongo.db.user_badges.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def list_for_user(user_id):
        awards = list(
            mongo.db.user_badges.find({"user_id": str(user_id)}).sort("awarded_at", -1)
        )
        if not awards:
            return []
        badge_ids = [to_object_id(item["badge_id"]) for item in awards if item.get("badge_id")]
        badges = {
            str(doc["_id"]): serialize_doc(doc)
            for doc in mongo.db.badges.find({"_id": {"$in": badge_ids}})
        }
        result = []
        for award in awards:
            badge = badges.get(str(award.get("badge_id")))
            if not badge:
                continue
            result.append({
                **badge,
                "awarded_at": serialize_doc({"awarded_at": award.get("awarded_at")}).get("awarded_at"),
                "awarded_by": award.get("awarded_by"),
            })
        return result

    @staticmethod
    def list_earners(badge_id):
        awards = list(
            mongo.db.user_badges.find({"badge_id": str(badge_id)}).sort("awarded_at", -1)
        )
        if not awards:
            return []
        user_ids = []
        for award in awards:
            try:
                user_ids.append(to_object_id(award.get("user_id")))
            except Exception:
                continue
        users = {
            str(doc["_id"]): doc
            for doc in mongo.db.users.find(
                {"_id": {"$in": user_ids}},
                {"name": 1, "email": 1, "image": 1},
            )
        }
        result = []
        for award in awards:
            user = users.get(str(award.get("user_id"))) or {}
            result.append({
                "user_id": str(award.get("user_id")),
                "name": user.get("name") or "",
                "email": user.get("email") or "",
                "image": user.get("image"),
                "awarded_at": serialize_doc({"awarded_at": award.get("awarded_at")}).get("awarded_at"),
            })
        return result
