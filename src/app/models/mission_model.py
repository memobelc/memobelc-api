"""Mission catalog, completions and coin rewards."""

from src.app import mongo
from src.app.models.coin_ledger_model import CoinLedgerModel
from src.app.models.user_model import UserModel
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow

MISSION_TYPES = ("manual", "streak")


def _mission_type_fields(data, existing=None):
    existing = existing or {}
    mission_type = (data.get("type") if "type" in data else existing.get("type") or "manual")
    mission_type = str(mission_type or "manual").strip().lower()
    if mission_type not in MISSION_TYPES:
        raise ValueError("type must be manual or streak")
    required_streak = existing.get("required_streak")
    if "required_streak" in data or mission_type == "streak":
        raw = data.get("required_streak") if "required_streak" in data else existing.get("required_streak")
        try:
            required_streak = int(raw or 0)
        except (TypeError, ValueError):
            required_streak = 0
    if mission_type == "streak" and int(required_streak or 0) < 1:
        raise ValueError("required_streak must be at least 1")
    if mission_type == "manual":
        required_streak = None
    return mission_type, required_streak


class MissionModel:
    @staticmethod
    def create(data):
        title = (data.get("title") or "").strip()
        if not title:
            raise ValueError("Mission title is required")
        coins = int(data.get("coins") or 0)
        if coins < 0:
            raise ValueError("coins must be zero or greater")
        mission_type, required_streak = _mission_type_fields(data)
        now = utcnow()
        doc = {
            "title": title,
            "description": (data.get("description") or "").strip(),
            "image": (data.get("image") or "").strip() or None,
            "coins": coins,
            "type": mission_type,
            "required_streak": required_streak,
            "is_active": bool(data.get("is_active", True)),
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.missions.insert_one(doc)
        doc["_id"] = result.inserted_id
        item = serialize_doc(doc)
        item["completers_count"] = 0
        return item

    @staticmethod
    def update(mission_id, data):
        existing = MissionModel.get_by_id(mission_id)
        if not existing:
            return None
        updates = {"updated_at": utcnow()}
        if "title" in data:
            title = (data.get("title") or "").strip()
            if not title:
                raise ValueError("Mission title is required")
            updates["title"] = title
        if "description" in data:
            updates["description"] = (data.get("description") or "").strip()
        if "image" in data:
            updates["image"] = (data.get("image") or "").strip() or None
        if "coins" in data:
            coins = int(data.get("coins") or 0)
            if coins < 0:
                raise ValueError("coins must be zero or greater")
            updates["coins"] = coins
        if "is_active" in data:
            updates["is_active"] = bool(data.get("is_active"))
        if "type" in data or "required_streak" in data:
            mission_type, required_streak = _mission_type_fields(data, existing)
            updates["type"] = mission_type
            updates["required_streak"] = required_streak
        mongo.db.missions.update_one({"_id": to_object_id(mission_id)}, {"$set": updates})
        return MissionModel.get_by_id(mission_id)

    @staticmethod
    def get_by_id(mission_id):
        try:
            oid = to_object_id(mission_id)
        except Exception:
            return None
        doc = mongo.db.missions.find_one({"_id": oid})
        return serialize_doc(doc)

    @staticmethod
    def list_missions(active_only=False):
        query = {"is_active": True} if active_only else {}
        docs = list(mongo.db.missions.find(query).sort("created_at", -1))
        counts = {}
        for row in mongo.db.user_missions.aggregate([
            {"$group": {"_id": "$mission_id", "count": {"$sum": 1}}},
        ]):
            counts[str(row["_id"])] = int(row.get("count") or 0)
        result = []
        for doc in docs:
            item = serialize_doc(doc)
            item["completers_count"] = counts.get(item["_id"], 0)
            result.append(item)
        return result

    @staticmethod
    def list_for_user(user_id):
        completions = {
            str(item.get("mission_id")): serialize_doc(item)
            for item in mongo.db.user_missions.find({"user_id": str(user_id)})
        }
        active = list(mongo.db.missions.find({"is_active": True}).sort("created_at", -1))
        extra_ids = [
            to_object_id(mission_id)
            for mission_id in completions.keys()
            if mission_id not in {str(doc["_id"]) for doc in active}
        ]
        extra = list(mongo.db.missions.find({"_id": {"$in": extra_ids}})) if extra_ids else []
        from src.app.models.user_streak_model import UserStreakModel
        current_streak = int(
            (UserStreakModel.get_streak_info(user_id) or {}).get("current_streak") or 0
        )
        result = []
        for doc in active + extra:
            item = serialize_doc(doc)
            completion = completions.get(item["_id"])
            item["status"] = "completed" if completion else "pending"
            item["completed_at"] = completion.get("completed_at") if completion else None
            item["coins_awarded"] = completion.get("coins_awarded") if completion else None
            item["type"] = item.get("type") or "manual"
            item["required_streak"] = item.get("required_streak")
            item["current_streak"] = current_streak
            result.append(item)
        return result

    @staticmethod
    def complete(user_id, mission_id):
        mission = MissionModel.get_by_id(mission_id)
        if not mission:
            raise ValueError("Mission not found")
        if not mission.get("is_active"):
            raise ValueError("Mission is not active")
        existing = mongo.db.user_missions.find_one({
            "user_id": str(user_id),
            "mission_id": str(mission_id),
        })
        if existing:
            raise ValueError("Mission already completed")
        if (mission.get("type") or "manual") == "streak":
            from src.app.models.user_streak_model import UserStreakModel
            current_streak = int(
                (UserStreakModel.get_streak_info(user_id) or {}).get("current_streak") or 0
            )
            required = int(mission.get("required_streak") or 0)
            if current_streak < required:
                raise ValueError("Streak requirement not met")
        coins = int(mission.get("coins") or 0)
        doc = {
            "user_id": str(user_id),
            "mission_id": str(mission_id),
            "completed_at": utcnow(),
            "coins_awarded": coins,
        }
        result = mongo.db.user_missions.insert_one(doc)
        doc["_id"] = result.inserted_id
        balance = UserModel.increment_coins(user_id, coins) if coins else int(
            (UserModel.get_document(user_id) or {}).get("coins") or 0
        )
        if coins:
            CoinLedgerModel.record(
                user_id,
                coins,
                "mission",
                reason=mission.get("title"),
                mission_id=mission_id,
            )
        return {
            "mission": serialize_doc(doc),
            "coins_awarded": coins,
            "coins": balance if balance is not None else coins,
        }

    @staticmethod
    def list_completers(mission_id):
        completions = list(
            mongo.db.user_missions.find({"mission_id": str(mission_id)}).sort("completed_at", -1)
        )
        if not completions:
            return []
        user_ids = []
        for item in completions:
            try:
                user_ids.append(to_object_id(item.get("user_id")))
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
        for item in completions:
            user = users.get(str(item.get("user_id"))) or {}
            serialized = serialize_doc(item)
            result.append({
                "user_id": str(item.get("user_id")),
                "name": user.get("name") or "",
                "email": user.get("email") or "",
                "image": user.get("image"),
                "completed_at": serialized.get("completed_at"),
                "coins_awarded": serialized.get("coins_awarded") or 0,
            })
        return result

    @staticmethod
    def complete_eligible_streak_missions(user_id):
        from src.app.models.user_streak_model import UserStreakModel
        current_streak = int(
            (UserStreakModel.get_streak_info(user_id) or {}).get("current_streak") or 0
        )
        if current_streak < 1:
            return []
        pending = list(mongo.db.missions.find({
            "is_active": True,
            "type": "streak",
            "required_streak": {"$lte": current_streak},
        }))
        completed = []
        for mission in pending:
            try:
                completed.append(MissionModel.complete(user_id, str(mission["_id"])))
            except ValueError:
                continue
        return completed
