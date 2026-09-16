"""Persistence for dynamic system settings and their audit history."""

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, utcnow

REVISION_KEY = "__revision__"


class SystemSettingModel:
    @staticmethod
    def ensure_indexes():
        mongo.db.system_settings.create_index("key", unique=True)
        mongo.db.system_settings_history.create_index([("key", 1), ("updated_at", -1)])
        mongo.db.system_settings_history.create_index("updated_at")

    @staticmethod
    def get_by_key(key):
        return serialize_doc(mongo.db.system_settings.find_one({"key": key}))

    @staticmethod
    def list_by_keys(keys):
        cursor = mongo.db.system_settings.find({"key": {"$in": list(keys)}})
        return [serialize_doc(doc) for doc in cursor]

    @staticmethod
    def upsert(key, value, updated_by=None):
        now = utcnow()
        mongo.db.system_settings.update_one(
            {"key": key},
            {
                "$set": {
                    "key": key,
                    "value": value,
                    "updated_at": now,
                    "updated_by": updated_by,
                }
            },
            upsert=True,
        )
        return SystemSettingModel.get_by_key(key)

    @staticmethod
    def get_revision():
        doc = mongo.db.system_settings.find_one({"key": REVISION_KEY})
        if not doc:
            return 0
        try:
            return int(doc.get("revision") or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def bump_revision():
        now = utcnow()
        mongo.db.system_settings.update_one(
            {"key": REVISION_KEY},
            {
                "$inc": {"revision": 1},
                "$set": {"key": REVISION_KEY, "updated_at": now},
            },
            upsert=True,
        )
        return SystemSettingModel.get_revision()

    @staticmethod
    def insert_history(key, old_value, new_value, updated_by):
        doc = {
            "key": key,
            "old_value": old_value,
            "new_value": new_value,
            "updated_at": utcnow(),
            "updated_by": updated_by,
        }
        result = mongo.db.system_settings_history.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def list_history(skip=0, limit=50, key=None):
        query = {}
        if key:
            query["key"] = key
        total = mongo.db.system_settings_history.count_documents(query)
        cursor = (
            mongo.db.system_settings_history.find(query)
            .sort("updated_at", -1)
            .skip(int(skip or 0))
            .limit(min(int(limit or 50), 200))
        )
        return [serialize_doc(doc) for doc in cursor], total
