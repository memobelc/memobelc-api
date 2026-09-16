"""Affiliate commission ledger."""

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow

STATUSES = ("pending", "available", "cancelled")


class AffiliateCommissionModel:
    @staticmethod
    def create(data):
        now = utcnow()
        doc = {
            "affiliate_id": str(data["affiliate_id"]),
            "user_id": str(data["user_id"]) if data.get("user_id") else None,
            "product_id": str(data["product_id"]),
            "payment_id": str(data["payment_id"]) if data.get("payment_id") else None,
            "external_sale_id": str(data["external_sale_id"]) if data.get("external_sale_id") else None,
            "buyer_user_id": str(data["buyer_user_id"]) if data.get("buyer_user_id") else None,
            "sale_amount": float(data.get("sale_amount") or 0),
            "percent": float(data.get("percent") or 0),
            "amount": round(float(data.get("amount") or 0), 2),
            "sale_count_at": int(data.get("sale_count_at") or 1),
            "status": data.get("status") or "pending",
            "approved_by": None,
            "approved_at": None,
            "notes": data.get("notes") or "",
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.affiliate_commissions.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(commission_id, data):
        updates = {"updated_at": utcnow()}
        if "status" in data and data["status"] in STATUSES:
            updates["status"] = data["status"]
        if "approved_by" in data:
            updates["approved_by"] = str(data["approved_by"]) if data.get("approved_by") else None
        if "approved_at" in data:
            updates["approved_at"] = data["approved_at"]
        if "notes" in data:
            updates["notes"] = data.get("notes") or ""
        mongo.db.affiliate_commissions.update_one(
            {"_id": to_object_id(commission_id)},
            {"$set": updates},
        )
        return AffiliateCommissionModel.get_by_id(commission_id)

    @staticmethod
    def get_by_id(commission_id):
        try:
            return serialize_doc(
                mongo.db.affiliate_commissions.find_one({"_id": to_object_id(commission_id)})
            )
        except Exception:
            return None

    @staticmethod
    def find_by_payment(payment_id):
        if not payment_id:
            return None
        return serialize_doc(
            mongo.db.affiliate_commissions.find_one({"payment_id": str(payment_id)})
        )

    @staticmethod
    def find_by_external_sale(external_sale_id):
        if not external_sale_id:
            return None
        return serialize_doc(
            mongo.db.affiliate_commissions.find_one({"external_sale_id": str(external_sale_id)})
        )

    @staticmethod
    def list_for_affiliate(affiliate_id, status=None, limit=100):
        query = {"affiliate_id": str(affiliate_id)}
        if status in STATUSES:
            query["status"] = status
        return [
            serialize_doc(doc)
            for doc in mongo.db.affiliate_commissions.find(query)
            .sort("created_at", -1)
            .limit(int(limit))
        ]

    @staticmethod
    def list_all(status=None, affiliate_id=None, limit=200):
        query = {}
        if status in STATUSES:
            query["status"] = status
        if affiliate_id:
            query["affiliate_id"] = str(affiliate_id)
        return [
            serialize_doc(doc)
            for doc in mongo.db.affiliate_commissions.find(query)
            .sort("created_at", -1)
            .limit(int(limit))
        ]

    @staticmethod
    def count_credited(affiliate_id, product_id):
        return mongo.db.affiliate_commissions.count_documents({
            "affiliate_id": str(affiliate_id),
            "product_id": str(product_id),
            "status": {"$in": ["pending", "available"]},
        })

    @staticmethod
    def sum_by_status(affiliate_id, status):
        pipeline = [
            {"$match": {"affiliate_id": str(affiliate_id), "status": status}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]
        result = list(mongo.db.affiliate_commissions.aggregate(pipeline))
        if not result:
            return 0.0
        return round(float(result[0].get("total") or 0), 2)
