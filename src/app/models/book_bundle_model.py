"""Book bundles / collections for sale."""

from src.app.config import Config
from src.app import mongo
from src.app.utils.billing_utils import SALE_MODES, serialize_doc, to_object_id, utcnow


class BookBundleModel:
    @staticmethod
    def build_checkout_url(bundle_id):
        if not bundle_id:
            return None
        base = str(getattr(Config, "FRONT_BASE_URL", "") or "").rstrip("/")
        return f"{base}/checkout/{bundle_id}" if base else f"/checkout/{bundle_id}"

    @staticmethod
    def _serialize(doc):
        out = serialize_doc(doc)
        if not out:
            return None
        out["checkout_enabled"] = bool(out.get("checkout_enabled"))
        out["affiliate_enabled"] = bool(out.get("affiliate_enabled"))
        out["is_published"] = bool(out.get("is_published"))
        out["checkout_url"] = BookBundleModel.build_checkout_url(out.get("_id"))
        return out

    @staticmethod
    def _commerce_flags(data, existing=None):
        existing = existing or {}
        affiliate_enabled = (
            bool(data["affiliate_enabled"])
            if "affiliate_enabled" in data
            else bool(existing.get("affiliate_enabled"))
        )
        checkout_enabled = (
            bool(data["checkout_enabled"])
            if "checkout_enabled" in data
            else bool(existing.get("checkout_enabled"))
        )
        if affiliate_enabled:
            checkout_enabled = True
        return affiliate_enabled, checkout_enabled

    @staticmethod
    def create(data):
        now = utcnow()
        sale_mode = data.get("sale_mode") or "both"
        if sale_mode not in SALE_MODES:
            raise ValueError("Invalid sale_mode")
        affiliate_enabled, checkout_enabled = BookBundleModel._commerce_flags(data)
        doc = {
            "name": data.get("name"),
            "description": data.get("description") or "",
            "price": float(data.get("price") or 0),
            "book_ids": [str(item) for item in (data.get("book_ids") or [])],
            "sale_mode": sale_mode,
            "is_published": bool(data.get("is_published", False)),
            "checkout_enabled": checkout_enabled,
            "affiliate_enabled": affiliate_enabled,
            "google_play_product_id": data.get("google_play_product_id") or None,
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.book_bundles.insert_one(doc)
        doc["_id"] = result.inserted_id
        return BookBundleModel._serialize(doc)

    @staticmethod
    def update(bundle_id, data):
        existing = BookBundleModel.get_by_id(bundle_id)
        if not existing:
            return None
        updates = {"updated_at": utcnow()}
        for field in ("name", "description", "google_play_product_id"):
            if field in data:
                updates[field] = data[field]
        if "price" in data:
            updates["price"] = float(data["price"])
        if "book_ids" in data:
            updates["book_ids"] = [str(item) for item in data["book_ids"]]
        if "sale_mode" in data:
            if data["sale_mode"] not in SALE_MODES:
                raise ValueError("Invalid sale_mode")
            updates["sale_mode"] = data["sale_mode"]
        if "is_published" in data:
            updates["is_published"] = bool(data["is_published"])
        if "checkout_enabled" in data or "affiliate_enabled" in data:
            affiliate_enabled, checkout_enabled = BookBundleModel._commerce_flags(data, existing)
            updates["affiliate_enabled"] = affiliate_enabled
            updates["checkout_enabled"] = checkout_enabled
        mongo.db.book_bundles.update_one({"_id": to_object_id(bundle_id)}, {"$set": updates})
        return BookBundleModel.get_by_id(bundle_id)

    @staticmethod
    def get_by_id(bundle_id):
        try:
            return BookBundleModel._serialize(
                mongo.db.book_bundles.find_one({"_id": to_object_id(bundle_id)})
            )
        except Exception:
            return None

    @staticmethod
    def get_public(bundle_id):
        bundle = BookBundleModel.get_by_id(bundle_id)
        if not bundle or not bundle.get("checkout_enabled"):
            return None
        price = bundle.get("price")
        return {
            "_id": bundle["_id"],
            "name": bundle.get("name"),
            "description": bundle.get("description") or "",
            "price": float(price) if price is not None else None,
            "book_ids": bundle.get("book_ids") or [],
            "checkout_enabled": True,
            "checkout_url": bundle.get("checkout_url"),
        }

    @staticmethod
    def get_by_google_sku(sku):
        if not sku:
            return None
        return BookBundleModel._serialize(
            mongo.db.book_bundles.find_one({"google_play_product_id": sku})
        )

    @staticmethod
    def list_bundles(published_only=False):
        query = {"is_published": True} if published_only else {}
        return [
            BookBundleModel._serialize(doc)
            for doc in mongo.db.book_bundles.find(query).sort("created_at", -1)
        ]

    @staticmethod
    def delete(bundle_id):
        result = mongo.db.book_bundles.delete_one({"_id": to_object_id(bundle_id)})
        return result.deleted_count > 0

    @staticmethod
    def sync_affiliate_product(bundle):
        from src.app.models.affiliate_product_model import AffiliateProductModel

        if not bundle:
            return None
        enabled = bool(bundle.get("affiliate_enabled"))
        existing = AffiliateProductModel.find_by_platform("bundle", bundle["_id"])
        payload = {
            "name": bundle.get("name"),
            "description": bundle.get("description") or "",
            "checkout_url": bundle.get("checkout_url"),
            "source": "platform",
            "product_type": "bundle",
            "product_id": bundle["_id"],
            "affiliate_enabled": enabled,
            "show_in_catalog": enabled,
            "is_active": enabled,
        }
        if existing:
            return AffiliateProductModel.update(existing["_id"], payload)
        if not enabled:
            return None
        return AffiliateProductModel.create(payload)

    @staticmethod
    def deactivate_affiliate_product(bundle_id):
        from src.app.models.affiliate_product_model import AffiliateProductModel

        existing = AffiliateProductModel.find_by_platform("bundle", bundle_id)
        if not existing:
            return None
        return AffiliateProductModel.update(existing["_id"], {
            "affiliate_enabled": False,
            "show_in_catalog": False,
            "is_active": False,
        })
