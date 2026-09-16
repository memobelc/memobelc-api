"""Per-product affiliate applications."""

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow

STATUSES = ("pending", "approved", "rejected")


class AffiliateApplicationModel:
    @staticmethod
    def create(affiliate_id, user_id, product_id, terms_accepted_at=None):
        existing = AffiliateApplicationModel.find(affiliate_id, product_id)
        if existing:
            if existing.get("status") == "rejected":
                return AffiliateApplicationModel.update(existing["_id"], {
                    "status": "pending",
                    "terms_accepted_at": terms_accepted_at or utcnow(),
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "notes": "",
                })
            return existing
        now = utcnow()
        doc = {
            "affiliate_id": str(affiliate_id),
            "user_id": str(user_id),
            "product_id": str(product_id),
            "status": "pending",
            "terms_accepted_at": terms_accepted_at or now,
            "reviewed_by": None,
            "reviewed_at": None,
            "notes": "",
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.affiliate_applications.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(application_id, data):
        updates = {"updated_at": utcnow()}
        if "status" in data and data["status"] in STATUSES:
            updates["status"] = data["status"]
        if "terms_accepted_at" in data:
            updates["terms_accepted_at"] = data["terms_accepted_at"]
        if "reviewed_by" in data:
            updates["reviewed_by"] = str(data["reviewed_by"]) if data.get("reviewed_by") else None
        if "reviewed_at" in data:
            updates["reviewed_at"] = data["reviewed_at"]
        if "notes" in data:
            updates["notes"] = data.get("notes") or ""
        mongo.db.affiliate_applications.update_one(
            {"_id": to_object_id(application_id)},
            {"$set": updates},
        )
        return AffiliateApplicationModel.get_by_id(application_id)

    @staticmethod
    def get_by_id(application_id):
        try:
            return serialize_doc(
                mongo.db.affiliate_applications.find_one({"_id": to_object_id(application_id)})
            )
        except Exception:
            return None

    @staticmethod
    def find(affiliate_id, product_id):
        return serialize_doc(
            mongo.db.affiliate_applications.find_one({
                "affiliate_id": str(affiliate_id),
                "product_id": str(product_id),
            })
        )

    @staticmethod
    def list_for_affiliate(affiliate_id):
        return [
            serialize_doc(doc)
            for doc in mongo.db.affiliate_applications.find({"affiliate_id": str(affiliate_id)})
        ]

    @staticmethod
    def list_all(status=None):
        query = {}
        if status in STATUSES:
            query["status"] = status
        return [
            serialize_doc(doc)
            for doc in mongo.db.affiliate_applications.find(query).sort("created_at", -1)
        ]

    @staticmethod
    def is_approved(affiliate_id, product_id):
        doc = AffiliateApplicationModel.find(affiliate_id, product_id)
        return bool(doc and doc.get("status") == "approved")
