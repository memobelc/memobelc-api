from src.app import mongo
import random
from bson import ObjectId
import string
from datetime import datetime, timedelta, timezone

class PushNotificationModel:
    def __init__(self, _id=None, user_id=None, push_token=None, device_info=None,created_at=None, updated_at=None, **kwargs):
        self._id = str(_id) if _id else None
        self.user_id = user_id
        self.push_token = push_token
        self.device_info = device_info
        created_at: created_at or datetime.now(timezone.utc)  # type: ignore



    @staticmethod
    def save_token(user_id, push_token, device_info=None):
        existing = mongo.db.push_notification.find_one({
            "user_id": user_id,
            "push_token": push_token
        })
        if not existing:
            mongo.db.push_notification.insert_one({
                "user_id": user_id,
                "push_token": push_token,
                "device_info": device_info,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            })
        else:
            mongo.db.push_notification.update_one(
                {"_id": existing["_id"]},
                {"$set": {"updated_at": datetime.utcnow()}}
            )

    @staticmethod
    def remove_tokens_by_user(user_id):
        """Remove todos os tokens de push associados a um usuário (logout global)."""
        mongo.db.push_notification.delete_many({"user_id": str(user_id)})