"""Affiliate profiles, settings and public click tracking."""

import random
import string

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow

AFFILIATE_STATUSES = ("active", "suspended")
SETTINGS_ID = "default"


def generate_referral_code():
    for _ in range(30):
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        code = f"MBC-{suffix}"
        if not mongo.db.affiliates.find_one({"referral_code": code}):
            return code
    raise ValueError("Could not generate a unique referral code")


class AffiliateModel:
    @staticmethod
    def ensure_indexes():
        mongo.db.affiliates.create_index("user_id", unique=True)
        mongo.db.affiliates.create_index("referral_code", unique=True)
        mongo.db.affiliates.create_index("status")
        mongo.db.affiliate_products.create_index("slug", unique=True)
        mongo.db.affiliate_products.create_index(
            [("source", 1), ("product_type", 1), ("product_id", 1)]
        )
        mongo.db.affiliate_applications.create_index(
            [("affiliate_id", 1), ("product_id", 1)], unique=True
        )
        mongo.db.affiliate_applications.create_index("status")
        mongo.db.affiliate_commissions.create_index("affiliate_id")
        mongo.db.affiliate_commissions.create_index("status")
        mongo.db.affiliate_commissions.create_index(
            "payment_id", unique=True, sparse=True
        )
        mongo.db.affiliate_commissions.create_index(
            "external_sale_id", unique=True, sparse=True
        )
        mongo.db.affiliate_withdrawals.create_index([("affiliate_id", 1), ("status", 1)])
        mongo.db.affiliate_clicks.create_index([("referral_code", 1), ("created_at", -1)])

    @staticmethod
    def create(user_id, created_by=None):
        existing = AffiliateModel.find_by_user_id(user_id)
        if existing:
            if existing.get("status") != "active":
                return AffiliateModel.update(existing["_id"], {"status": "active"})
            return existing
        now = utcnow()
        doc = {
            "user_id": str(user_id),
            "status": "active",
            "referral_code": generate_referral_code(),
            "created_by": str(created_by) if created_by else None,
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.affiliates.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(affiliate_id, data):
        updates = {"updated_at": utcnow()}
        if "status" in data and data["status"] in AFFILIATE_STATUSES:
            updates["status"] = data["status"]
        mongo.db.affiliates.update_one({"_id": to_object_id(affiliate_id)}, {"$set": updates})
        return AffiliateModel.get_by_id(affiliate_id)

    @staticmethod
    def get_by_id(affiliate_id):
        try:
            return serialize_doc(mongo.db.affiliates.find_one({"_id": to_object_id(affiliate_id)}))
        except Exception:
            return None

    @staticmethod
    def find_by_user_id(user_id):
        if not user_id:
            return None
        return serialize_doc(mongo.db.affiliates.find_one({"user_id": str(user_id)}))

    @staticmethod
    def find_by_code(code):
        if not code:
            return None
        normalized = str(code).strip().upper()
        return serialize_doc(mongo.db.affiliates.find_one({"referral_code": normalized}))

    @staticmethod
    def list_affiliates(status=None):
        query = {}
        if status in AFFILIATE_STATUSES:
            query["status"] = status
        return [
            serialize_doc(doc)
            for doc in mongo.db.affiliates.find(query).sort("created_at", -1)
        ]


class AffiliateSettingsModel:
    @staticmethod
    def defaults():
        return {
            "_id": SETTINGS_ID,
            "min_withdrawal_amount": 50.0,
            "withdrawals_enabled": True,
            "pix_required": True,
        }

    @staticmethod
    def get():
        doc = mongo.db.affiliate_settings.find_one({"_id": SETTINGS_ID})
        if not doc:
            defaults = AffiliateSettingsModel.defaults()
            mongo.db.affiliate_settings.insert_one(defaults)
            return serialize_doc(defaults)
        merged = AffiliateSettingsModel.defaults()
        merged.update(serialize_doc(doc) or {})
        return merged

    @staticmethod
    def update(data):
        current = AffiliateSettingsModel.get()
        updates = {"updated_at": utcnow()}
        if "min_withdrawal_amount" in data:
            updates["min_withdrawal_amount"] = max(float(data["min_withdrawal_amount"] or 0), 0)
        if "withdrawals_enabled" in data:
            updates["withdrawals_enabled"] = bool(data["withdrawals_enabled"])
        if "pix_required" in data:
            updates["pix_required"] = bool(data["pix_required"])
        mongo.db.affiliate_settings.update_one(
            {"_id": SETTINGS_ID},
            {"$set": updates},
            upsert=True,
        )
        current.update(updates)
        return AffiliateSettingsModel.get()


class AffiliateClickModel:
    @staticmethod
    def record(referral_code, product_slug=None, metadata=None):
        doc = {
            "referral_code": (referral_code or "").strip().upper(),
            "product_slug": (product_slug or "").strip() or None,
            "metadata": metadata or {},
            "created_at": utcnow(),
        }
        result = mongo.db.affiliate_clicks.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)
