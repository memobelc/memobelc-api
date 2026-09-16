"""Coupon catalog and redemptions."""

from src.app import mongo
from src.app.utils.billing_utils import (
    PRODUCT_TYPES,
    parse_datetime,
    serialize_doc,
    to_object_id,
    utcnow,
)


class CouponModel:
    @staticmethod
    def create(data):
        code = (data.get("code") or "").strip().upper()
        if not code:
            raise ValueError("Coupon code is required")
        if mongo.db.coupons.find_one({"code": code}):
            raise ValueError("Coupon code already exists")
        discount_type = data.get("discount_type") or "percent"
        if discount_type not in ("percent", "fixed"):
            raise ValueError("discount_type must be percent or fixed")
        duration = data.get("duration") or "once"
        if duration not in ("once", "repeating"):
            raise ValueError("duration must be once or repeating")
        now = utcnow()
        doc = {
            "code": code,
            "description": data.get("description") or "",
            "discount_type": discount_type,
            "value": float(data.get("value") or 0),
            "starts_at": parse_datetime(data.get("starts_at")) or now,
            "expires_at": parse_datetime(data.get("expires_at")),
            "max_uses": int(data["max_uses"]) if data.get("max_uses") not in (None, "") else None,
            "used_count": 0,
            "applicable_product_types": [
                item for item in (data.get("applicable_product_types") or []) if item in PRODUCT_TYPES
            ],
            "applicable_plan_ids": [str(item) for item in (data.get("applicable_plan_ids") or [])],
            "applicable_product_ids": [str(item) for item in (data.get("applicable_product_ids") or [])],
            "duration": duration,
            "is_active": bool(data.get("is_active", True)),
            "affiliate_id": str(data["affiliate_id"]) if data.get("affiliate_id") else None,
            "affiliate_product_id": str(data["affiliate_product_id"]) if data.get("affiliate_product_id") else None,
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.coupons.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(coupon_id, data):
        existing = CouponModel.get_by_id(coupon_id)
        if not existing:
            return None
        updates = {"updated_at": utcnow()}
        if "code" in data and data["code"]:
            code = data["code"].strip().upper()
            other = mongo.db.coupons.find_one({"code": code, "_id": {"$ne": to_object_id(coupon_id)}})
            if other:
                raise ValueError("Coupon code already exists")
            updates["code"] = code
        for field in ("description", "discount_type", "duration"):
            if field in data:
                updates[field] = data[field]
        if "value" in data:
            updates["value"] = float(data["value"])
        if "starts_at" in data:
            updates["starts_at"] = parse_datetime(data["starts_at"])
        if "expires_at" in data:
            updates["expires_at"] = parse_datetime(data["expires_at"])
        if "max_uses" in data:
            updates["max_uses"] = int(data["max_uses"]) if data["max_uses"] not in (None, "") else None
        if "applicable_product_types" in data:
            updates["applicable_product_types"] = [
                item for item in data["applicable_product_types"] if item in PRODUCT_TYPES
            ]
        if "applicable_plan_ids" in data:
            updates["applicable_plan_ids"] = [str(item) for item in data["applicable_plan_ids"]]
        if "applicable_product_ids" in data:
            updates["applicable_product_ids"] = [str(item) for item in data["applicable_product_ids"]]
        if "is_active" in data:
            updates["is_active"] = bool(data["is_active"])
        if "affiliate_id" in data:
            updates["affiliate_id"] = str(data["affiliate_id"]) if data.get("affiliate_id") else None
        if "affiliate_product_id" in data:
            updates["affiliate_product_id"] = (
                str(data["affiliate_product_id"]) if data.get("affiliate_product_id") else None
            )
        mongo.db.coupons.update_one({"_id": to_object_id(coupon_id)}, {"$set": updates})
        return CouponModel.get_by_id(coupon_id)

    @staticmethod
    def get_by_id(coupon_id):
        try:
            return serialize_doc(mongo.db.coupons.find_one({"_id": to_object_id(coupon_id)}))
        except Exception:
            return None

    @staticmethod
    def get_by_code(code):
        if not code:
            return None
        return serialize_doc(mongo.db.coupons.find_one({"code": code.strip().upper()}))

    @staticmethod
    def list_coupons():
        return [serialize_doc(doc) for doc in mongo.db.coupons.find().sort("created_at", -1)]

    @staticmethod
    def increment_usage(coupon_id):
        mongo.db.coupons.update_one({"_id": to_object_id(coupon_id)}, {"$inc": {"used_count": 1}})

    @staticmethod
    def record_redemption(coupon_id, user_id, metadata=None):
        doc = {
            "coupon_id": str(coupon_id),
            "user_id": str(user_id),
            "metadata": metadata or {},
            "redeemed_at": utcnow(),
        }
        result = mongo.db.coupon_redemptions.insert_one(doc)
        CouponModel.increment_usage(coupon_id)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def list_redemptions(coupon_id=None):
        query = {}
        if coupon_id:
            query["coupon_id"] = str(coupon_id)
        return [serialize_doc(doc) for doc in mongo.db.coupon_redemptions.find(query).sort("redeemed_at", -1)]

    @staticmethod
    def find_by_affiliate(affiliate_id, product_id=None):
        if not affiliate_id:
            return None
        query = {"affiliate_id": str(affiliate_id), "is_active": True}
        if product_id:
            query["affiliate_product_id"] = str(product_id)
        return serialize_doc(mongo.db.coupons.find_one(query, sort=[("created_at", -1)]))
