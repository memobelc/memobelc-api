"""Model class for notification"""

from datetime import datetime, timezone
from bson import ObjectId
from src.app import mongo


class NotificationModel:

    @staticmethod
    def create(user_id, notification_type, data=None):
        """Cria uma nova notificação para o usuário.

        Campos principais:
        - user_id: string do id do usuário (mantém compatibilidade com uso atual)
        - type: tipo da notificação (ex: daily_study, classroom_added, new_cards, teacher_custom, admin_custom)
        - data: payload livre com informações adicionais (title, body, etc.)
        - is_read: controle de leitura
        """
        now = datetime.now(timezone.utc)
        doc = {
            "user_id": str(user_id),
            "type": notification_type,
            "data": data or {},
            "created_at": now,
            "status": "sent",
            "is_read": False,
            "read_at": None,
        }
        result = mongo.db.notifications.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        return doc

    @staticmethod
    def find_last(user_id, notification_type):
        return mongo.db.notifications.find_one(
            {"user_id": user_id, "type": notification_type},
            sort=[("created_at", -1)]
        )

    @staticmethod
    def list_by_user(user_id, limit=50):
        """Lista notificações de um usuário, ordenadas da mais recente para a mais antiga."""
        cursor = (
            mongo.db.notifications.find({"user_id": str(user_id)})
            .sort("created_at", -1)
            .limit(limit)
        )
        notifications = []
        for n in cursor:
            notifications.append(
                {
                    "_id": str(n.get("_id")),
                    "type": n.get("type"),
                    "data": n.get("data", {}),
                    "created_at": n.get("created_at"),
                    "status": n.get("status", "sent"),
                    "is_read": bool(n.get("is_read", False)),
                    "read_at": n.get("read_at"),
                }
            )
        return notifications

    @staticmethod
    def count_unread(user_id):
        """Conta notificações não lidas do usuário."""
        return mongo.db.notifications.count_documents(
            {
                "user_id": str(user_id),
                "is_read": {"$ne": True},
            }
        )

    @staticmethod
    def mark_as_read(user_id, notification_id=None, mark_all=False):
        """Marca uma ou todas as notificações do usuário como lidas."""
        if not notification_id and not mark_all:
            return 0

        query = {"user_id": str(user_id), "is_read": {"$ne": True}}
        if notification_id and not mark_all:
            query["_id"] = ObjectId(notification_id)

        result = mongo.db.notifications.update_many(
            query,
            {
                "$set": {
                    "is_read": True,
                    "status": "read",
                    "read_at": datetime.now(timezone.utc),
                }
            },
        )
        return result.modified_count

    @staticmethod
    def delete_by_batch_id(batch_id):
        """Remove todas as notificações de um envio agrupado."""
        if not batch_id:
            return 0
        result = mongo.db.notifications.delete_many({"data.batch_id": str(batch_id)})
        return result.deleted_count

    @staticmethod
    def delete_ids(ids):
        oids = []
        for item in ids or []:
            try:
                oids.append(ObjectId(str(item)))
            except Exception:
                continue
        if not oids:
            return 0
        result = mongo.db.notifications.delete_many({"_id": {"$in": oids}})
        return result.deleted_count

    @staticmethod
    def list_admin_custom():
        return list(
            mongo.db.notifications.find({"type": "admin_custom"}).sort("created_at", -1)
        )

    @staticmethod
    def delete_by_user(user_id):
        result = mongo.db.notifications.delete_many({"user_id": str(user_id)})
        return result.deleted_count
