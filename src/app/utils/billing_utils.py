"""Constants and helpers for billing, subscriptions and entitlements."""

from datetime import datetime, timezone, timedelta
from bson import ObjectId


SERVICE_KEYS = (
    "home",
    "videos",
    "books",
    "collections",
    "talk_to_me",
    "classrooms",
    "courses",
)

SERVICE_LABELS = {
    "home": "Home",
    "videos": "Videos",
    "books": "Books",
    "collections": "Collections",
    "talk_to_me": "Talk to me",
    "classrooms": "Classrooms",
    "courses": "Courses",
}

PLAN_CYCLES = (
    "WEEKLY",
    "BIWEEKLY",
    "MONTHLY",
    "QUARTERLY",
    "SEMIANNUALLY",
    "YEARLY",
)

SUBSCRIPTION_STATUSES = (
    "trialing",
    "active",
    "pending",
    "overdue",
    "refused",
    "suspended",
    "canceled",
    "expired",
)

PAID_ACTIVE_STATUSES = ("trialing", "active")
ACCESS_STATUSES = ("trialing", "active")
GRACE_ELIGIBLE_STATUSES = ("trialing", "active", "pending", "overdue")

# redirect_plans is a legacy alias resolved as disabled_upgrade.
VISIBILITY_ACTIONS = (
    "allow",
    "hide",
    "disabled",
    "disabled_upgrade",
    "redirect_plans",
)

AUDIENCES = ("everyone", "non_subscribers", "subscribers", "plans", "manual")
SALE_MODES = ("separate", "plans_only", "both")
PRODUCT_TYPES = ("plan", "book", "bundle", "course", "classroom")
PROVIDERS = ("asaas", "google_play", "manual", "external")
GRANT_SOURCES = ("subscription", "purchase", "manual", "external", "coins")
NATIVE_BILLING_TYPES = ("PIX", "CREDIT_CARD")
ASAAS_PAID_STATUSES = ("CONFIRMED", "RECEIVED", "RECEIVED_IN_CASH")

GRACE_HOURS = 48


def utcnow():
    return datetime.now(timezone.utc)


def to_object_id(value):
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    return ObjectId(str(value))


def serialize_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_value(item) for key, item in value.items()}
    return value


def serialize_doc(doc):
    if not doc:
        return None
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return serialize_value(out)


def parse_datetime(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    return None


def cycle_timedelta(cycle):
    mapping = {
        "WEEKLY": timedelta(days=7),
        "BIWEEKLY": timedelta(days=14),
        "MONTHLY": timedelta(days=30),
        "QUARTERLY": timedelta(days=90),
        "SEMIANNUALLY": timedelta(days=180),
        "YEARLY": timedelta(days=365),
    }
    return mapping.get(cycle, timedelta(days=30))


def compute_grace_until(next_due_date):
    due = parse_datetime(next_due_date)
    if not due:
        return utcnow() + timedelta(hours=GRACE_HOURS)
    return due + timedelta(hours=GRACE_HOURS)


def apply_discount(amount, coupon):
    if not coupon or amount is None:
        return float(amount or 0)
    value = float(amount)
    discount_value = float(coupon.get("value") or 0)
    if coupon.get("discount_type") == "percent":
        value = value * (1 - discount_value / 100.0)
    else:
        value = value - discount_value
    return max(round(value, 2), 0)


def asaas_discount_payload(coupon):
    if not coupon:
        return None
    duration = coupon.get("duration") or "once"
    payload = {
        "value": float(coupon.get("value") or 0),
        "type": "PERCENTAGE" if coupon.get("discount_type") == "percent" else "FIXED",
    }
    if duration == "once":
        payload["dueDateLimitDays"] = 0
    return payload


def invoice_description(product_type, product):
    if product_type == "book":
        chapters = product.get("chapters") or []
        parts = [f"Livro: {product.get('titulo') or 'Sem título'}"]
        if product.get("autor"):
            parts.append(f"Autor: {product.get('autor')}")
        if product.get("idioma"):
            parts.append(f"Idioma: {product.get('idioma')}")
        if product.get("nivel"):
            parts.append(f"Nível: {product.get('nivel')}")
        if product.get("genero"):
            parts.append(f"Gênero: {product.get('genero')}")
        if chapters:
            titles = [item.get("titulo") for item in chapters if item.get("titulo")]
            parts.append(f"Capítulos: {len(chapters)}")
            if titles:
                parts.append("Títulos: " + "; ".join(titles[:8]))
        parts.append(f"ID: {product.get('_id')}")
        return " | ".join(parts)[:500]
    if product_type == "bundle":
        book_ids = product.get("book_ids") or []
        parts = [f"Conjunto: {product.get('name') or 'Sem nome'}"]
        if product.get("description"):
            parts.append(str(product.get("description")))
        parts.append(f"Livros: {len(book_ids)}")
        parts.append(f"ID: {product.get('_id')}")
        return " | ".join(parts)[:500]
    if product_type == "course":
        parts = [f"Curso: {product.get('name') or 'Sem nome'}"]
        if product.get("description"):
            parts.append(str(product.get("description"))[:120])
        parts.append(f"ID: {product.get('_id')}")
        return " | ".join(parts)[:500]
    if product_type == "classroom":
        parts = [f"Turma: {product.get('name') or 'Sem nome'}"]
        parts.append(f"ID: {product.get('_id')}")
        return " | ".join(parts)[:500]
    return (product.get("name") or product.get("titulo") or str(product.get("_id") or ""))[:500]


def product_snapshot(product_type, product):
    if product_type == "book":
        chapters = product.get("chapters") or []
        return {
            "titulo": product.get("titulo"),
            "autor": product.get("autor"),
            "idioma": product.get("idioma"),
            "nivel": product.get("nivel"),
            "genero": product.get("genero"),
            "price": product.get("price"),
            "chapters_count": len(chapters),
            "chapter_titles": [item.get("titulo") for item in chapters if item.get("titulo")],
        }
    if product_type == "bundle":
        return {
            "name": product.get("name"),
            "description": product.get("description"),
            "price": product.get("price"),
            "book_ids": product.get("book_ids") or [],
        }
    if product_type == "course":
        return {
            "name": product.get("name"),
            "description": product.get("description"),
            "price": product.get("price"),
            "classroom_id": product.get("classroom_id"),
        }
    if product_type == "classroom":
        return {
            "name": product.get("name"),
            "price": product.get("price"),
            "classroom_id": product.get("_id"),
        }
    return {"name": product.get("name"), "price": product.get("price")}
