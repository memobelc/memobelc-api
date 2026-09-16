"""Book bundles / collections for sale."""

from src.app import mongo
from src.app.utils.billing_utils import SALE_MODES, serialize_doc, to_object_id, utcnow


class BookBundleModel:
    @staticmethod
    def create(data):
        now = utcnow()
        sale_mode = data.get("sale_mode") or "both"
        if sale_mode not in SALE_MODES:
            raise ValueError("Invalid sale_mode")
        doc = {
            "name": data.get("name"),
            "description": data.get("description") or "",
            "price": float(data.get("price") or 0),
            "book_ids": [str(item) for item in (data.get("book_ids") or [])],
            "sale_mode": sale_mode,
            "is_published": bool(data.get("is_published", True)),
            "google_play_product_id": data.get("google_play_product_id") or None,
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.book_bundles.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

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
        mongo.db.book_bundles.update_one({"_id": to_object_id(bundle_id)}, {"$set": updates})
        return BookBundleModel.get_by_id(bundle_id)

    @staticmethod
    def get_by_id(bundle_id):
        try:
            return serialize_doc(mongo.db.book_bundles.find_one({"_id": to_object_id(bundle_id)}))
        except Exception:
            return None

    @staticmethod
    def get_by_google_sku(sku):
        if not sku:
            return None
        return serialize_doc(mongo.db.book_bundles.find_one({"google_play_product_id": sku}))

    @staticmethod
    def list_bundles(published_only=False):
        query = {"is_published": True} if published_only else {}
        return [serialize_doc(doc) for doc in mongo.db.book_bundles.find(query).sort("created_at", -1)]

    @staticmethod
    def delete(bundle_id):
        result = mongo.db.book_bundles.delete_one({"_id": to_object_id(bundle_id)})
        return result.deleted_count > 0
