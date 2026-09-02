"""Coin balance ledger."""

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, utcnow


class CoinLedgerModel:
    @staticmethod
    def record(user_id, amount, entry_type, reason=None, mission_id=None, admin_id=None, book_id=None):
        doc = {
            "user_id": str(user_id),
            "amount": int(amount),
            "type": entry_type,
            "reason": (reason or "").strip() or None,
            "mission_id": str(mission_id) if mission_id else None,
            "admin_id": str(admin_id) if admin_id else None,
            "book_id": str(book_id) if book_id else None,
            "created_at": utcnow(),
        }
        result = mongo.db.coin_ledger.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def list_for_user(user_id, limit=50):
        docs = list(
            mongo.db.coin_ledger.find({"user_id": str(user_id)})
            .sort("created_at", -1)
            .limit(int(limit))
        )
        return [serialize_doc(doc) for doc in docs]
