"""MongoDB model for support tickets (multiple conversations per user)."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from src.app import mongo

STATUSES = ("open", "in_progress", "closed")
ACTIVE_STATUSES = ("open", "in_progress")
PREVIEW_LEN = 140
CSAT_MIN = 0
CSAT_MAX = 5


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


def _csat_score(doc):
    value = doc.get("csat_score")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class SupportTicketModel:
    @staticmethod
    def ensure_indexes():
        indexes = mongo.db.support_tickets.index_information()
        user_id_index = indexes.get("user_id_1")
        if user_id_index and user_id_index.get("unique"):
            mongo.db.support_tickets.drop_index("user_id_1")
        mongo.db.support_tickets.create_index("user_id")
        mongo.db.support_tickets.create_index([("user_id", 1), ("last_message_at", -1)])
        mongo.db.support_tickets.create_index([("user_id", 1), ("status", 1)])
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
            "handled_by": str(doc["handled_by"]) if doc.get("handled_by") else None,
            "closed_at": _iso(doc.get("closed_at")),
            "csat_required": bool(doc.get("csat_required")),
            "csat_score": _csat_score(doc),
            "csat_submitted_at": _iso(doc.get("csat_submitted_at")),
            "created_at": _iso(doc.get("created_at")),
            "updated_at": _iso(doc.get("updated_at")),
        }

    @staticmethod
    def _new_doc(user_id):
        now = utcnow()
        return {
            "user_id": str(user_id),
            "status": "open",
            "last_message_at": None,
            "last_message_preview": None,
            "last_author_role": None,
            "unread_for_user": 0,
            "unread_for_admin": 0,
            "closed_by": None,
            "handled_by": None,
            "closed_at": None,
            "csat_required": False,
            "csat_score": None,
            "csat_submitted_at": None,
            "created_at": now,
            "updated_at": now,
        }

    @staticmethod
    def find_by_id(ticket_id):
        try:
            doc = mongo.db.support_tickets.find_one({"_id": ObjectId(ticket_id)})
        except (InvalidId, TypeError):
            return None
        return SupportTicketModel.serialize(doc)

    @staticmethod
    def find_active_for_user(user_id):
        doc = mongo.db.support_tickets.find_one(
            {"user_id": str(user_id), "status": {"$in": list(ACTIVE_STATUSES)}},
            sort=[("last_message_at", -1), ("created_at", -1)],
        )
        return SupportTicketModel.serialize(doc)

    @staticmethod
    def find_latest_for_user(user_id):
        doc = mongo.db.support_tickets.find_one(
            {"user_id": str(user_id)},
            sort=[("last_message_at", -1), ("created_at", -1)],
        )
        return SupportTicketModel.serialize(doc)

    @staticmethod
    def list_for_user(user_id):
        cursor = mongo.db.support_tickets.find({"user_id": str(user_id)}).sort(
            [("last_message_at", -1), ("created_at", -1)]
        )
        return [SupportTicketModel.serialize(doc) for doc in cursor]

    @staticmethod
    def create_for_user(user_id):
        doc = SupportTicketModel._new_doc(user_id)
        result = mongo.db.support_tickets.insert_one(doc)
        doc["_id"] = result.inserted_id
        return SupportTicketModel.serialize(doc)

    @staticmethod
    def get_or_create_for_user(user_id):
        existing = SupportTicketModel.find_active_for_user(user_id)
        if existing:
            return existing
        return SupportTicketModel.create_for_user(user_id)

    @staticmethod
    def apply_user_message(ticket_id, preview):
        now = utcnow()
        mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {
                "$set": {
                    "last_message_at": now,
                    "last_message_preview": preview,
                    "last_author_role": "user",
                    "updated_at": now,
                },
                "$inc": {"unread_for_admin": 1},
            },
        )
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def apply_system_message(ticket_id, preview, increment_unread=True):
        now = utcnow()
        update = {
            "$set": {
                "last_message_at": now,
                "last_message_preview": preview,
                "last_author_role": "system",
                "updated_at": now,
            }
        }
        if increment_unread:
            update["$inc"] = {"unread_for_admin": 1}
        mongo.db.support_tickets.update_one({"_id": ObjectId(ticket_id)}, update)
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def apply_admin_message(ticket_id, preview, admin_id=None):
        now = utcnow()
        fields = {
            "status": "in_progress",
            "last_message_at": now,
            "last_message_preview": preview,
            "last_author_role": "admin",
            "updated_at": now,
        }
        if admin_id:
            fields["handled_by"] = str(admin_id)
        mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {"$set": fields, "$inc": {"unread_for_user": 1}},
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
    def close(ticket_id, closed_by, csat_required=True, handled_by=None):
        now = utcnow()
        result = mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {
                "$set": {
                    "status": "closed",
                    "closed_by": str(closed_by),
                    "handled_by": str(handled_by or closed_by),
                    "closed_at": now,
                    "csat_required": bool(csat_required),
                    "csat_score": None,
                    "csat_submitted_at": None,
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
        ticket = SupportTicketModel.find_by_id(ticket_id)
        if not ticket:
            return None
        updates = {
            "status": "in_progress",
            "closed_by": None,
            "closed_at": None,
            "updated_at": now,
        }
        if not ticket.get("csat_submitted_at"):
            updates["csat_required"] = False
            updates["csat_score"] = None
        result = mongo.db.support_tickets.update_one(
            {"_id": ObjectId(ticket_id)},
            {"$set": updates},
        )
        if result.matched_count == 0:
            return None
        return SupportTicketModel.find_by_id(ticket_id)

    @staticmethod
    def submit_csat(ticket_id, score):
        now = utcnow()
        result = mongo.db.support_tickets.update_one(
            {
                "_id": ObjectId(ticket_id),
                "status": "closed",
                "csat_required": True,
                "csat_submitted_at": None,
            },
            {
                "$set": {
                    "csat_score": int(score),
                    "csat_submitted_at": now,
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
    def unread_user_total(user_id):
        pipeline = [
            {"$match": {"user_id": str(user_id)}},
            {"$group": {"_id": None, "total": {"$sum": "$unread_for_user"}}},
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
