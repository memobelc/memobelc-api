"""Admin billing list enrichment, dashboard metrics and exports."""

from datetime import datetime, timedelta, timezone
from io import StringIO
import csv
import html

from bson import ObjectId

from src.app import mongo
from src.app.models.billing_support_model import AuditLogModel
from src.app.models.payment_model import PaymentModel
from src.app.models.plan_model import PlanModel
from src.app.models.subscription_model import SubscriptionModel
from src.app.models.user_model import UserModel
from src.app.utils.billing_utils import (
    PAID_ACTIVE_STATUSES,
    parse_datetime,
    serialize_doc,
    to_object_id,
    utcnow,
)

SUB_SORT_FIELDS = {
    "created_at": "created_at",
    "started_at": "started_at",
    "status": "status",
    "value": "value",
    "next_due_date": "next_due_date",
    "current_period_end": "current_period_end",
    "provider": "provider",
    "payment_method": "payment_method",
}

PAY_SORT_FIELDS = {
    "created_at": "created_at",
    "paid_at": "paid_at",
    "status": "status",
    "amount": "amount",
    "provider": "provider",
    "payment_method": "payment_method",
}

FAILED_PAYMENT_STATUSES = ("refused", "failed", "overdue", "canceled", "cancelled")
CONFIRMED_PAYMENT_STATUSES = ("confirmed", "received", "paid")


def monthly_value(value, cycle):
    amount = float(value or 0)
    mapping = {
        "WEEKLY": amount * 52 / 12,
        "BIWEEKLY": amount * 26 / 12,
        "MONTHLY": amount,
        "QUARTERLY": amount / 3,
        "SEMIANNUALLY": amount / 6,
        "YEARLY": amount / 12,
    }
    return round(mapping.get((cycle or "MONTHLY").upper(), amount), 2)


def days_remaining(end_value, now=None):
    end = parse_datetime(end_value)
    if not end:
        return None
    now = now or utcnow()
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return int((end - now).total_seconds() // 86400)


def map_asaas_failure(payload):
    payload = payload or {}
    pieces = [
        str(payload.get("lastError") or ""),
        str(payload.get("description") or ""),
        str(payload.get("status") or ""),
        str((payload.get("chargeback") or {}).get("reason") or ""),
        str(payload.get("billingType") or ""),
    ]
    text = " ".join(pieces).lower()
    code = (
        payload.get("lastError")
        or payload.get("status")
        or payload.get("object")
        or "asaas_error"
    )
    if "insufficient" in text or "saldo" in text or "nsf" in text:
        return "insufficient_funds", str(code)
    if "pix" in text and ("expir" in text or "vencid" in text):
        return "pix_expired", str(code)
    if "boleto" in text or "bank_slip" in text or "bankslip" in text:
        return "boleto_overdue", str(code)
    if "timeout" in text or "communication" in text or "conexão" in text or "conexao" in text:
        return "communication_failure", str(code)
    if "refus" in text or "declin" in text or "card" in text or "credit" in text:
        return "card_refused", str(code)
    return "processing_error", str(code)


def _object_ids(ids):
    out = []
    for item in ids:
        try:
            out.append(ObjectId(str(item)))
        except Exception:
            continue
    return out


def _users_by_ids(user_ids):
    ids = list({str(item) for item in user_ids if item})
    if not ids:
        return {}
    docs = mongo.db.users.find(
        {"_id": {"$in": _object_ids(ids)}},
        {"name": 1, "email": 1, "image": 1},
    )
    return {
        str(doc["_id"]): {
            "_id": str(doc["_id"]),
            "name": doc.get("name"),
            "email": doc.get("email"),
            "image": doc.get("image"),
        }
        for doc in docs
    }


def _plans_by_ids(plan_ids):
    ids = list({str(item) for item in plan_ids if item})
    if not ids:
        return {}
    docs = mongo.db.plans.find({"_id": {"$in": _object_ids(ids)}})
    return {str(doc["_id"]): serialize_doc(doc) for doc in docs}


def _search_user_ids(term):
    if not term:
        return None
    users = UserModel.list_users(term)
    return [user["_id"] for user in users]


def _parse_sort(raw, allowed, default_field="created_at"):
    if raw in (None, ""):
        return default_field, -1
    field = str(raw).lstrip("-")
    if field not in allowed:
        field = default_field
        return field, -1
    direction = -1 if str(raw).startswith("-") else 1
    return field, direction


def _date_range(filters, field_name="created_at"):
    date_field = filters.get("date_field") or field_name
    start = parse_datetime(filters.get("date_from"))
    end = parse_datetime(filters.get("date_to"))
    if not start and not end:
        return None, date_field
    query = {}
    if start:
        query["$gte"] = start
    if end:
        query["$lte"] = end
    return {date_field: query}, date_field


def build_subscription_query(filters=None):
    filters = filters or {}
    query = {}
    if filters.get("user_id"):
        query["user_id"] = str(filters["user_id"])
    if filters.get("plan_id"):
        query["plan_id"] = str(filters["plan_id"])
    if filters.get("status"):
        query["status"] = filters["status"]
    elif filters.get("status_group") == "active":
        query["status"] = {"$in": list(PAID_ACTIVE_STATUSES)}
    elif filters.get("status_group") == "canceled":
        query["status"] = "canceled"
    elif filters.get("status_group") == "expired":
        query["status"] = "expired"
    if filters.get("provider"):
        query["provider"] = filters["provider"]
    if filters.get("payment_method"):
        query["payment_method"] = filters["payment_method"]
    q_ids = _search_user_ids(filters.get("q"))
    if q_ids is not None:
        if not q_ids:
            query["user_id"] = "__none__"
        else:
            query["user_id"] = {"$in": q_ids}
    range_query, _ = _date_range(filters, filters.get("date_field") or "created_at")
    if range_query:
        query.update(range_query)
    expiring = filters.get("expiring_in_days")
    if expiring not in (None, ""):
        days = int(expiring)
        now = utcnow()
        query["current_period_end"] = {"$gte": now, "$lte": now + timedelta(days=days)}
    return query


def build_payment_query(filters=None):
    filters = filters or {}
    query = {}
    if filters.get("user_id"):
        query["user_id"] = str(filters["user_id"])
    if filters.get("product_id"):
        query["product_id"] = str(filters["product_id"])
    if filters.get("product_type"):
        query["product_type"] = filters["product_type"]
    if filters.get("status"):
        query["status"] = filters["status"]
    if filters.get("subscription_id"):
        query["subscription_id"] = str(filters["subscription_id"])
    if filters.get("provider"):
        query["provider"] = filters["provider"]
    if filters.get("payment_method"):
        query["payment_method"] = filters["payment_method"]
    if str(filters.get("failed_only")).lower() in ("1", "true", "yes"):
        query["status"] = {"$in": list(FAILED_PAYMENT_STATUSES)}
    q_ids = _search_user_ids(filters.get("q"))
    if q_ids is not None:
        if not q_ids:
            query["user_id"] = "__none__"
        else:
            query["user_id"] = {"$in": q_ids}
    range_query, _ = _date_range(filters, filters.get("date_field") or "created_at")
    if range_query:
        query.update(range_query)
    return query


def enrich_subscription(doc, users=None, plans=None, last_payments=None, now=None):
    now = now or utcnow()
    users = users or {}
    plans = plans or {}
    last_payments = last_payments or {}
    item = serialize_doc(doc) or {}
    user = users.get(str(item.get("user_id")))
    plan = plans.get(str(item.get("plan_id")))
    last_payment = last_payments.get(str(item.get("_id")))
    end = item.get("current_period_end") or item.get("next_due_date")
    item["user"] = user
    item["plan"] = {
        "_id": plan.get("_id") if plan else item.get("plan_id"),
        "name": (plan or {}).get("name"),
        "price": (plan or {}).get("price"),
        "cycle": (plan or {}).get("cycle") or item.get("billing_cycle"),
    } if plan or item.get("plan_id") else None
    item["days_remaining"] = days_remaining(end, now)
    item["last_payment"] = last_payment
    item["next_payment_at"] = item.get("next_due_date")
    return item


def enrich_payment(doc, users=None, plans=None):
    users = users or {}
    plans = plans or {}
    item = serialize_doc(doc) or {}
    user = users.get(str(item.get("user_id")))
    product_id = str(item.get("product_id") or "")
    plan = plans.get(product_id) if item.get("product_type") in ("plan", "subscription") else None
    item["user"] = user
    item["plan"] = {
        "_id": plan.get("_id"),
        "name": plan.get("name"),
    } if plan else None
    item["product_name"] = (plan or {}).get("name") or item.get("product_type")
    return item


def _last_payments_for_subscriptions(subscription_ids):
    ids = [str(item) for item in subscription_ids if item]
    if not ids:
        return {}
    docs = list(
        mongo.db.payments.find({"subscription_id": {"$in": ids}})
        .sort("created_at", -1)
    )
    latest = {}
    confirmed = {}
    for doc in docs:
        key = str(doc.get("subscription_id"))
        item = serialize_doc(doc)
        if key not in latest:
            latest[key] = item
        if key not in confirmed and item.get("status") in CONFIRMED_PAYMENT_STATUSES:
            confirmed[key] = item
    return {key: confirmed.get(key) or value for key, value in latest.items()}


class AdminBillingQuery:
    @staticmethod
    def list_subscriptions(filters=None, skip=0, limit=50, sort=None, for_export=False):
        filters = dict(filters or {})
        query = build_subscription_query(filters)
        field, direction = _parse_sort(sort or filters.get("sort"), SUB_SORT_FIELDS)
        skip = 0 if for_export else int(skip or 0)
        limit = 20000 if for_export else min(int(limit or 50), 200)
        total = mongo.db.subscriptions.count_documents(query)
        cursor = (
            mongo.db.subscriptions.find(query)
            .sort(field, direction)
            .skip(skip)
            .limit(limit)
        )
        docs = list(cursor)
        users = _users_by_ids([doc.get("user_id") for doc in docs])
        plans = _plans_by_ids([doc.get("plan_id") for doc in docs])
        last_payments = _last_payments_for_subscriptions([str(doc.get("_id")) for doc in docs])
        now = utcnow()
        items = [enrich_subscription(doc, users, plans, last_payments, now) for doc in docs]
        if (sort or "").lstrip("-") in ("user_name", "plan_name"):
            reverse = str(sort).startswith("-")
            key = (sort or "").lstrip("-")
            items.sort(
                key=lambda item: (
                    ((item.get("user") or {}).get("name") or "")
                    if key == "user_name"
                    else ((item.get("plan") or {}).get("name") or "")
                ).lower(),
                reverse=reverse,
            )
        return items, total

    @staticmethod
    def list_payments(filters=None, skip=0, limit=50, sort=None, for_export=False):
        filters = dict(filters or {})
        query = build_payment_query(filters)
        field, direction = _parse_sort(sort or filters.get("sort"), PAY_SORT_FIELDS)
        skip = 0 if for_export else int(skip or 0)
        limit = 20000 if for_export else min(int(limit or 50), 200)
        total = mongo.db.payments.count_documents(query)
        docs = list(
            mongo.db.payments.find(query).sort(field, direction).skip(skip).limit(limit)
        )
        users = _users_by_ids([doc.get("user_id") for doc in docs])
        plans = _plans_by_ids([
            doc.get("product_id")
            for doc in docs
            if doc.get("product_type") in ("plan", "subscription")
        ])
        items = [enrich_payment(doc, users, plans) for doc in docs]
        return items, total

    @staticmethod
    def get_subscription(subscription_id):
        try:
            doc = mongo.db.subscriptions.find_one({"_id": to_object_id(subscription_id)})
        except Exception:
            return None
        if not doc:
            return None
        users = _users_by_ids([doc.get("user_id")])
        plans = _plans_by_ids([doc.get("plan_id")])
        last_payments = _last_payments_for_subscriptions([str(doc.get("_id"))])
        return enrich_subscription(doc, users, plans, last_payments)

    @staticmethod
    def summary():
        now = utcnow()
        start_today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        start_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        active = mongo.db.subscriptions.count_documents({"status": "active"})
        trialing = mongo.db.subscriptions.count_documents({"status": "trialing"})
        expired = mongo.db.subscriptions.count_documents({"status": "expired"})
        recurring = list(mongo.db.subscriptions.find(
            {"status": {"$in": list(PAID_ACTIVE_STATUSES)}},
            {"value": 1, "billing_cycle": 1},
        ))
        mrr = round(sum(monthly_value(doc.get("value"), doc.get("billing_cycle")) for doc in recurring), 2)
        confirmed_today = mongo.db.payments.count_documents({
            "status": {"$in": list(CONFIRMED_PAYMENT_STATUSES)},
            "created_at": {"$gte": start_today},
        })
        failed_today = mongo.db.payments.count_documents({
            "status": {"$in": list(FAILED_PAYMENT_STATUSES)},
            "created_at": {"$gte": start_today},
        })
        confirmed_month = mongo.db.payments.count_documents({
            "status": {"$in": list(CONFIRMED_PAYMENT_STATUSES)},
            "created_at": {"$gte": start_month},
        })
        refused_month = mongo.db.payments.count_documents({
            "status": {"$in": ["refused", "failed"]},
            "created_at": {"$gte": start_month},
        })
        canceled_month = mongo.db.subscriptions.count_documents({
            "status": "canceled",
            "canceled_at": {"$gte": start_month},
        })
        conversion_den = confirmed_month + refused_month
        churn_den = active + canceled_month
        return {
            "active_subscriptions": active,
            "trialing_subscriptions": trialing,
            "expired_subscriptions": expired,
            "mrr": mrr,
            "arr": round(mrr * 12, 2),
            "payments_confirmed_today": confirmed_today,
            "payments_failed_today": failed_today,
            "conversion_rate": round((confirmed_month / conversion_den) * 100, 1) if conversion_den else 0,
            "churn_rate": round((canceled_month / churn_den) * 100, 1) if churn_den else 0,
        }

    @staticmethod
    def plan_metrics(plans):
        ids = [plan["_id"] for plan in plans]
        counts = {}
        mrrs = {}
        revenues = {}
        for plan_id in ids:
            subs = list(mongo.db.subscriptions.find({"plan_id": str(plan_id)}))
            active = [item for item in subs if item.get("status") in PAID_ACTIVE_STATUSES]
            counts[plan_id] = len(active)
            mrrs[plan_id] = round(
                sum(monthly_value(item.get("value"), item.get("billing_cycle")) for item in active),
                2,
            )
            revenues[plan_id] = round(sum(
                float(pay.get("amount") or 0)
                for pay in mongo.db.payments.find({
                    "product_id": str(plan_id),
                    "status": {"$in": list(CONFIRMED_PAYMENT_STATUSES)},
                })
            ), 2)
        out = []
        for plan in plans:
            item = dict(plan)
            item["subscriber_count"] = counts.get(plan["_id"], 0)
            item["mrr"] = mrrs.get(plan["_id"], 0)
            item["revenue_total"] = revenues.get(plan["_id"], 0)
            return_item = item
            out.append(return_item)
        return out

    @staticmethod
    def plan_insights(plan_id):
        plan = PlanModel.get_by_id(plan_id)
        if not plan:
            return None
        now = utcnow()
        start_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        start_year = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        subs = list(mongo.db.subscriptions.find({"plan_id": str(plan_id)}).sort("created_at", -1))
        users = _users_by_ids([doc.get("user_id") for doc in subs])
        last_payments = _last_payments_for_subscriptions([str(doc.get("_id")) for doc in subs])
        subscribers = [
            enrich_subscription(doc, users, {str(plan_id): plan}, last_payments, now)
            for doc in subs
            if doc.get("status") in PAID_ACTIVE_STATUSES
        ]
        confirmed = list(mongo.db.payments.find({
            "product_id": str(plan_id),
            "status": {"$in": list(CONFIRMED_PAYMENT_STATUSES)},
        }))
        refused = mongo.db.payments.count_documents({
            "product_id": str(plan_id),
            "status": {"$in": ["refused", "failed"]},
        })
        revenue_month = round(sum(
            float(item.get("amount") or 0)
            for item in confirmed
            if parse_datetime(item.get("paid_at") or item.get("created_at"))
            and parse_datetime(item.get("paid_at") or item.get("created_at")) >= start_month
        ), 2)
        revenue_year = round(sum(
            float(item.get("amount") or 0)
            for item in confirmed
            if parse_datetime(item.get("paid_at") or item.get("created_at"))
            and parse_datetime(item.get("paid_at") or item.get("created_at")) >= start_year
        ), 2)
        conversion_den = len(confirmed) + refused
        logs = AuditLogModel.list_logs({"target_type": "plan", "target_id": str(plan_id)}, limit=50)
        return {
            "plan": plan,
            "subscriber_count": len(subscribers),
            "subscribers": subscribers,
            "mrr": round(sum(monthly_value(item.get("value"), item.get("billing_cycle")) for item in subscribers), 2),
            "revenue_total": round(sum(float(item.get("amount") or 0) for item in confirmed), 2),
            "revenue_month": revenue_month,
            "revenue_year": revenue_year,
            "conversion_rate": round((len(confirmed) / conversion_den) * 100, 1) if conversion_den else 0,
            "audit": logs,
        }

    @staticmethod
    def list_grants(filters=None, skip=0, limit=50):
        filters = filters or {}
        query = {"source": "manual"}
        if filters.get("user_id"):
            query["user_id"] = str(filters["user_id"])
        skip = int(skip or 0)
        limit = min(int(limit or 50), 200)
        total = mongo.db.entitlements.count_documents(query)
        docs = list(
            mongo.db.entitlements.find(query).sort("granted_at", -1).skip(skip).limit(limit)
        )
        users = _users_by_ids([doc.get("user_id") for doc in docs] + [doc.get("granted_by") for doc in docs])
        plans = _plans_by_ids([doc.get("resource_id") for doc in docs if doc.get("type") == "plan"])
        items = []
        for doc in docs:
            item = serialize_doc(doc)
            item["user"] = users.get(str(item.get("user_id")))
            item["admin"] = users.get(str(item.get("granted_by")))
            item["plan"] = plans.get(str(item.get("resource_id"))) if item.get("type") == "plan" else None
            items.append(item)
        return items, total

    @staticmethod
    def user_billing_preview(user_id):
        user = mongo.db.users.find_one({"_id": ObjectId(str(user_id))}, {"name": 1, "email": 1, "image": 1})
        if not user:
            return None
        sub = SubscriptionModel.get_paid_active_for_user(user_id) or SubscriptionModel.get_active_for_user(user_id)
        plan = PlanModel.get_by_id(sub["plan_id"]) if sub else None
        payments = PaymentModel.list_for_user(user_id)
        last = payments[0] if payments else None
        return {
            "_id": str(user["_id"]),
            "name": user.get("name"),
            "email": user.get("email"),
            "image": user.get("image"),
            "plan": {"_id": plan.get("_id"), "name": plan.get("name")} if plan else None,
            "status": (sub or {}).get("status"),
            "last_payment": serialize_doc(last) if last else None,
        }


def failure_updates_from_payload(payload, existing=None):
    reason, code = map_asaas_failure(payload)
    existing = existing or {}
    attempt_count = int(existing.get("attempt_count") or 0) + 1
    next_attempt = payload.get("nextDueDate") or payload.get("dueDate")
    return {
        "failure_reason": reason,
        "failure_code": code,
        "failure_at": utcnow(),
        "attempt_count": attempt_count,
        "next_attempt_at": parse_datetime(next_attempt),
    }


def to_csv(rows, headers):
    buffer = StringIO()
    buffer.write("\ufeff")
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in headers})
    return buffer.getvalue().encode("utf-8")


def to_xlsx(rows, headers):
    cells = []
    def cell(value):
        text = html.escape("" if value is None else str(value))
        return f'<Cell><Data ss:Type="String">{text}</Data></Cell>'

    header_row = "<Row>" + "".join(cell(item) for item in headers) + "</Row>"
    body = []
    for row in rows:
        body.append("<Row>" + "".join(cell(row.get(key, "")) for key in headers) + "</Row>")
    xml = (
        '<?xml version="1.0"?>'
        '<?mso-application progid="Excel.Sheet"?>'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"'
        ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        "<Worksheet ss:Name=\"Sheet1\"><Table>"
        + header_row
        + "".join(body)
        + "</Table></Worksheet></Workbook>"
    )
    return xml.encode("utf-8")


def flatten_subscription(item):
    user = item.get("user") or {}
    plan = item.get("plan") or {}
    last = item.get("last_payment") or {}
    return {
        "user_name": user.get("name"),
        "user_email": user.get("email"),
        "user_id": item.get("user_id"),
        "plan_name": plan.get("name"),
        "status": item.get("status"),
        "started_at": item.get("started_at"),
        "current_period_end": item.get("current_period_end"),
        "next_due_date": item.get("next_due_date"),
        "days_remaining": item.get("days_remaining"),
        "value": item.get("value"),
        "payment_method": item.get("payment_method"),
        "provider": item.get("provider"),
        "last_payment_status": last.get("status"),
        "last_payment_at": last.get("paid_at") or last.get("created_at"),
        "subscription_id": item.get("_id"),
    }


def flatten_payment(item):
    user = item.get("user") or {}
    plan = item.get("plan") or {}
    return {
        "user_name": user.get("name"),
        "user_email": user.get("email"),
        "product_name": item.get("product_name") or plan.get("name"),
        "plan_name": plan.get("name"),
        "amount": item.get("amount"),
        "status": item.get("status"),
        "created_at": item.get("created_at"),
        "paid_at": item.get("paid_at"),
        "payment_method": item.get("payment_method"),
        "provider": item.get("provider"),
        "transaction_id": item.get("provider_payment_id") or item.get("_id"),
        "failure_reason": item.get("failure_reason"),
        "failure_code": item.get("failure_code"),
    }
