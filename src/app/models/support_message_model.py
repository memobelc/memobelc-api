"""MongoDB model for support conversation messages."""

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from src.app import mongo


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


class SupportMessageModel:
    @staticmethod
    def serialize(doc):
        if not doc:
            return None
        return {
            "_id": str(doc["_id"]),
            "ticket_id": str(doc.get("ticket_id")),
            "author_id": str(doc.get("author_id")),
            "author_role": doc.get("author_role"),
            "body": doc.get("body") or "",
            "read_at": _iso(doc.get("read_at")),
            "created_at": _iso(doc.get("created_at")),
        }

    @staticmethod
    def create(ticket_id, author_id, author_role, body):
        now = utcnow()
        doc = {
            "ticket_id": ObjectId(ticket_id),
            "author_id": str(author_id),
            "author_role": author_role,
            "body": body,
            "read_at": None,
            "created_at": now,
        }
        result = mongo.db.support_messages.insert_one(doc)
        doc["_id"] = result.inserted_id
        return SupportMessageModel.serialize(doc)

    @staticmethod
    def list_by_ticket(ticket_id, since=None):
        try:
            query = {"ticket_id": ObjectId(ticket_id)}
        except (InvalidId, TypeError):
            return []
        if since is not None:
            query["created_at"] = {"$gt": since}
        cursor = mongo.db.support_messages.find(query).sort("created_at", 1)
        return [SupportMessageModel.serialize(doc) for doc in cursor]

    @staticmethod
    def mark_role_as_read(ticket_id, author_role):
        """Mark messages from the given author_role as read (the other party read them)."""
        now = utcnow()
        try:
            oid = ObjectId(ticket_id)
        except (InvalidId, TypeError):
            return 0
        result = mongo.db.support_messages.update_many(
            {
                "ticket_id": oid,
                "author_role": author_role,
                "read_at": None,
            },
            {"$set": {"read_at": now}},
        )
        return result.modified_count
