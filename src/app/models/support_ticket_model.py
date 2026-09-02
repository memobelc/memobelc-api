"""MongoDB model for support tickets (one conversation per user)."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from src.app import mongo

STATUSES = ("open", "in_progress", "closed")
PREVIEW_LEN = 140


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return value


class SupportTicketModel:
    @staticmethod
    def ensure_indexes():
        mongo.db.support_tickets.create_index("user_id", unique=True)
        mongo.db.support_tickets.create_index([("status", 1), ("last_message_at", -1)])
        mongo.db.support_tickets.create_index("last_message_at")
        mongo.db.support_messages.create_index([("ticket_id", 1), ("created_at", 1)])

    @staticmethod
    def serialize(doc):
        if not doc:
            return None
        return {
            "_id": str(doc["_id"]),
            "user_id": str(doc.get("user_id")),
            "status": doc.get("status", "open"),
            "last_message_at": _iso(doc.get("last_message_at")),
            "last_message_preview": doc.get("last_message_preview"),
            "last_author_role": doc.get("last_author_role"),
            "unread_for_user": int(doc.get("unread_for_user") or 0),
            "unread_for_admin": int(doc.get("unread_for_admin") or 0),
            "closed_by": str(doc["closed_by"]) if doc.get("closed_by") else None,
            "closed_at": _iso(doc.get("closed_at")),
            "created_at": _iso(doc.get("created_at")),
            "updated_at": _iso(doc.get("updated_at")),
        }

    @staticmethod
    def find_by_id(ticket_id):
        try:
            doc = mongo.db.support_tickets.find_one({"_id": ObjectId(ticket_id)})
        except (InvalidId, TypeError):
            return None
        return SupportTicketModel.serialize(doc)

    @staticmethod
    def find_by_user_id(user_id):
        doc = mongo.db.support_tickets.find_one({"user_id": str(user_id)})
        return SupportTicketModel.serialize(doc)

    @staticmethod
    def get_or_create_for_user(user_id):
        existing = SupportTicketModel.find_by_user_id(user_id)
        if existing:
            return existing

        now = utcnow()
        doc = {
            "user_id": str(user_id),
            "status": "open",
            "last_message_at": None,
            "last_message_preview": None,
            "last_author_role": None,
            "unread_for_user": 0,
            "unread_for_admin": 0,
            "closed_by": None,
            "closed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            result = mongo.db.support_tickets.insert_one(doc)
            doc["_id"] = result.inserted_id
            return SupportTicketModel.serialize(doc)
        except DuplicateKeyError:
            return SupportTicketModel.find_by_user_id(user_id)

    @staticmethod
    def apply_user_message(ticket_id, preview):
        now = utcnow()
        mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {
                "$set": {
                    "status": "open",
                    "last_message_at": now,
                    "last_message_preview": preview,
                    "last_author_role": "user",
                    "closed_by": None,
                    "closed_at": None,
                    "updated_at": now,
                },
                "$inc": {"unread_for_admin": 1},
            },
        )
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def apply_system_message(ticket_id, preview):
        now = utcnow()
        mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {
                "$set": {
                    "status": "open",
                    "last_message_at": now,
                    "last_message_preview": preview,
                    "last_author_role": "system",
                    "closed_by": None,
                    "closed_at": None,
                    "updated_at": now,
                },
                "$inc": {"unread_for_admin": 1},
            },
        )
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def apply_admin_message(ticket_id, preview):
        now = utcnow()
        ticket = SupportTicketModel.find_by_id(ticket_id)
        next_status = "in_progress"
        if ticket and ticket.get("status") == "closed":
            next_status = "in_progress"
        mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {
                "$set": {
                    "status": next_status,
                    "last_message_at": now,
                    "last_message_preview": preview,
                    "last_author_role": "admin",
                    "updated_at": now,
                },
                "$inc": {"unread_for_user": 1},
            },
        )
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def clear_unread_for_user(ticket_id):
        mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {"$set": {"unread_for_user": 0, "updated_at": utcnow()}},
        )
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def clear_unread_for_admin(ticket_id):
        mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {"$set": {"unread_for_admin": 0, "updated_at": utcnow()}},
        )
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def close(ticket_id, closed_by):
        now = utcnow()
        result = mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {
                "$set": {
                    "status": "closed",
                    "closed_by": str(closed_by),
                    "closed_at": now,
                    "updated_at": now,
                }
            },
        )
        if result.matched_count == 0:
            return None
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def reopen(ticket_id):
        now = utcnow()
        result = mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {
                "$set": {
                    "status": "in_progress",
                    "closed_by": None,
                    "closed_at": None,
                    "updated_at": now,
                }
            },
        )
        if result.matched_count == 0:
            return None
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def list_tickets(status=None, user_ids=None):
        query = {}
        if status and status in STATUSES:
            query["status"] = status
        if user_ids is not None:
            query["user_id"] = {"$in": [str(uid) for uid in user_ids]}

        cursor = mongo.db.support_tickets.find(query).sort(
            [("last_message_at", -1), ("created_at", -1)]
        )
        return [SupportTicketModel.serialize(doc) for doc in cursor]

    @staticmethod
    def unread_admin_total():
        pipeline = [
            {"$group": {"_id": None, "total": {"$sum": "$unread_for_admin"}}}
        ]
        result = list(mongo.db.support_tickets.aggregate(pipeline))
        if not result:
            return 0
        return int(result[0].get("total") or 0)

    @staticmethod
    def preview_from_body(body):
        text = (body or "").strip()
        if len(text) <= PREVIEW_LEN:
            return text
        return text[: PREVIEW_LEN - 1] + "…"
