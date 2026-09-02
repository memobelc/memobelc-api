"""Affiliate withdrawal requests."""

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow

STATUSES = ("processing", "paid", "rejected")


class AffiliateWithdrawalModel:
    @staticmethod
    def create(data):
        now = utcnow()
        doc = {
            "affiliate_id": str(data["affiliate_id"]),
            "user_id": str(data["user_id"]),
            "amount": round(float(data.get("amount") or 0), 2),
            "pix_key": (data.get("pix_key") or "").strip(),
            "full_name": (data.get("full_name") or "").strip(),
            "cpf": re_digits(data.get("cpf")),
            "bank": (data.get("bank") or "").strip() or None,
            "status": "processing",
            "reviewed_by": None,
            "reviewed_at": None,
            "notes": data.get("notes") or "",
            "requested_at": now,
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.affiliate_withdrawals.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(withdrawal_id, data):
        updates = {"updated_at": utcnow()}
        if "status" in data and data["status"] in STATUSES:
            updates["status"] = data["status"]
        if "reviewed_by" in data:
            updates["reviewed_by"] = str(data["reviewed_by"]) if data.get("reviewed_by") else None
        if "reviewed_at" in data:
            updates["reviewed_at"] = data["reviewed_at"]
        if "notes" in data:
            updates["notes"] = data.get("notes") or ""
        mongo.db.affiliate_withdrawals.update_one(
            {"_id": to_object_id(withdrawal_id)},
            {"$set": updates},
        )
        return AffiliateWithdrawalModel.get_by_id(withdrawal_id)

    @staticmethod
    def get_by_id(withdrawal_id):
        try:
            return serialize_doc(
                mongo.db.affiliate_withdrawals.find_one({"_id": to_object_id(withdrawal_id)})
            )
        except Exception:
            return None

    @staticmethod
    def list_for_affiliate(affiliate_id, limit=100):
        return [
            serialize_doc(doc)
            for doc in mongo.db.affiliate_withdrawals.find({"affiliate_id": str(affiliate_id)})
            .sort("created_at", -1)
            .limit(int(limit))
        ]

    @staticmethod
    def list_all(status=None, limit=200):
        query = {}
        if status in STATUSES:
            query["status"] = status
        return [
            serialize_doc(doc)
            for doc in mongo.db.affiliate_withdrawals.find(query)
            .sort("created_at", -1)
            .limit(int(limit))
        ]

    @staticmethod
    def sum_reserved(affiliate_id):
        pipeline = [
            {
                "$match": {
                    "affiliate_id": str(affiliate_id),
                    "status": {"$in": ["processing", "paid"]},
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]
        result = list(mongo.db.affiliate_withdrawals.aggregate(pipeline))
        if not result:
            return 0.0
        return round(float(result[0].get("total") or 0), 2)

    @staticmethod
    def sum_paid(affiliate_id):
        pipeline = [
            {"$match": {"affiliate_id": str(affiliate_id), "status": "paid"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]
        result = list(mongo.db.affiliate_withdrawals.aggregate(pipeline))
        if not result:
            return 0.0
        return round(float(result[0].get("total") or 0), 2)


def re_digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())
