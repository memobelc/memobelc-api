"""Affiliate program product catalog."""

import re

from src.app import mongo
from src.app.utils.billing_utils import PRODUCT_TYPES, serialize_doc, to_object_id, utcnow

SOURCES = ("platform", "external")


def _slugify(value):
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "produto"


def _normalize_tiers(raw):
    tiers = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        min_sales = int(item.get("min_sales") or 0)
        max_raw = item.get("max_sales")
        max_sales = None if max_raw in (None, "", "null") else int(max_raw)
        percent = float(item.get("percent") or 0)
        if percent < 0:
            raise ValueError("Commission percent must be >= 0")
        if max_sales is not None and max_sales < min_sales:
            raise ValueError("max_sales must be greater than or equal to min_sales")
        tiers.append({"min_sales": min_sales, "max_sales": max_sales, "percent": percent})
    tiers.sort(key=lambda row: row["min_sales"])
    return tiers


def unique_slug(base, exclude_id=None):
    slug = _slugify(base)
    candidate = slug
    index = 2
    while True:
        query = {"slug": candidate}
        if exclude_id:
            query["_id"] = {"$ne": to_object_id(exclude_id)}
        if not mongo.db.affiliate_products.find_one(query):
            return candidate
        candidate = f"{slug}-{index}"
        index += 1


class AffiliateProductModel:
    @staticmethod
    def create(data):
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        source = data.get("source") or "platform"
        if source not in SOURCES:
            raise ValueError("source must be platform or external")
        product_type = data.get("product_type")
        if product_type and product_type not in PRODUCT_TYPES:
            raise ValueError("invalid product_type")
        now = utcnow()
        doc = {
            "name": name,
            "slug": unique_slug(data.get("slug") or name),
            "image": (data.get("image") or "").strip() or None,
            "description": data.get("description") or "",
            "rules": data.get("rules") or "",
            "terms": data.get("terms") or "",
            "source": source,
            "product_type": product_type if source == "platform" else None,
            "product_id": str(data["product_id"]) if data.get("product_id") and source == "platform" else None,
            "checkout_url": (data.get("checkout_url") or "").strip() or None,
            "affiliate_enabled": bool(data.get("affiliate_enabled", True)),
            "show_in_catalog": bool(data.get("show_in_catalog", True)),
            "is_active": bool(data.get("is_active", True)),
            "commission_tiers": _normalize_tiers(data.get("commission_tiers")),
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.affiliate_products.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(product_id, data):
        existing = AffiliateProductModel.get_by_id(product_id)
        if not existing:
            return None
        updates = {"updated_at": utcnow()}
        if "name" in data and data["name"]:
            updates["name"] = str(data["name"]).strip()
        if "slug" in data and data["slug"]:
            updates["slug"] = unique_slug(data["slug"], exclude_id=product_id)
        for field in ("image", "description", "rules", "terms", "checkout_url"):
            if field in data:
                value = data[field]
                updates[field] = (str(value).strip() or None) if field in ("image", "checkout_url") else (value or "")
        if "source" in data:
            if data["source"] not in SOURCES:
                raise ValueError("source must be platform or external")
            updates["source"] = data["source"]
        source = updates.get("source", existing.get("source"))
        if "product_type" in data:
            product_type = data.get("product_type")
            if product_type and product_type not in PRODUCT_TYPES:
                raise ValueError("invalid product_type")
            updates["product_type"] = product_type if source == "platform" else None
        if "product_id" in data:
            updates["product_id"] = (
                str(data["product_id"]) if data.get("product_id") and source == "platform" else None
            )
        for flag in ("affiliate_enabled", "show_in_catalog", "is_active"):
            if flag in data:
                updates[flag] = bool(data[flag])
        if "commission_tiers" in data:
            updates["commission_tiers"] = _normalize_tiers(data.get("commission_tiers"))
        mongo.db.affiliate_products.update_one({"_id": to_object_id(product_id)}, {"$set": updates})
        return AffiliateProductModel.get_by_id(product_id)

    @staticmethod
    def get_by_id(product_id):
        try:
            return serialize_doc(mongo.db.affiliate_products.find_one({"_id": to_object_id(product_id)}))
        except Exception:
            return None

    @staticmethod
    def get_by_slug(slug):
        if not slug:
            return None
        return serialize_doc(mongo.db.affiliate_products.find_one({"slug": str(slug).strip()}))

    @staticmethod
    def find_platform_product(product_type, product_id):
        if not product_type or not product_id:
            return None
        return serialize_doc(
            mongo.db.affiliate_products.find_one({
                "source": "platform",
                "product_type": product_type,
                "product_id": str(product_id),
                "is_active": True,
                "affiliate_enabled": True,
            })
        )

    @staticmethod
    def related_sale_keys(product_type, product_id):
        keys = []
        if product_type and product_id:
            keys.append((str(product_type), str(product_id)))
        if not product_id:
            return keys
        try:
            from src.app.models.course_model import CourseModel
            if product_type == "classroom":
                for course in CourseModel.get_by_classroom(product_id) or []:
                    course_id = course.get("_id")
                    if course_id:
                        keys.append(("course", str(course_id)))
            if product_type == "course":
                course = CourseModel.get_by_id(product_id)
                classroom_id = (course or {}).get("classroom_id")
                if classroom_id:
                    keys.append(("classroom", str(classroom_id)))
        except Exception:
            pass
        return keys

    @staticmethod
    def find_platform_products_for_sale(product_type, product_id):
        found = []
        seen = set()
        for ptype, pid in AffiliateProductModel.related_sale_keys(product_type, product_id):
            item = AffiliateProductModel.find_platform_product(ptype, pid)
            if item and item.get("_id") not in seen:
                seen.add(item["_id"])
                found.append(item)
        return found

    @staticmethod
    def list_products(active_only=False):
        query = {}
        if active_only:
            query["is_active"] = True
        return [
            serialize_doc(doc)
            for doc in mongo.db.affiliate_products.find(query).sort("created_at", -1)
        ]

    @staticmethod
    def match_tier(product, sale_count):
        tiers = product.get("commission_tiers") or []
        count = int(sale_count or 0)
        matched = None
        for tier in sorted(tiers, key=lambda row: int(row.get("min_sales") or 0)):
            min_sales = int(tier.get("min_sales") or 0)
            max_sales = tier.get("max_sales")
            if count < min_sales:
                continue
            if max_sales is not None and count > int(max_sales):
                continue
            matched = tier
        return matched
