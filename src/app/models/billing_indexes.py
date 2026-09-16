"""Mongo indexes for billing collections."""

from src.app import mongo
from src.app.models.service_access_model import ServiceAccessModel


def ensure_billing_indexes():
    try:
        mongo.db.plans.create_index("is_active")
        mongo.db.plans.create_index("google_play_product_id")
        mongo.db.coupons.create_index("code", unique=True)
        mongo.db.subscriptions.create_index([("user_id", 1), ("status", 1)])
        mongo.db.subscriptions.create_index(
            [("provider", 1), ("provider_subscription_id", 1)],
            unique=True,
            sparse=True,
        )
        mongo.db.payments.create_index(
            [("provider", 1), ("provider_payment_id", 1)],
            unique=True,
            sparse=True,
        )
        mongo.db.payments.create_index([("user_id", 1), ("created_at", -1)])
        mongo.db.entitlements.create_index([("user_id", 1), ("type", 1), ("resource_id", 1)])
        mongo.db.webhook_events.create_index(
            [("provider", 1), ("event_id", 1)],
            unique=True,
        )
        mongo.db.book_bundles.create_index("google_play_product_id")
        mongo.db.service_access_rules.create_index("service_key", unique=True)
        ServiceAccessModel.seed_defaults()
    except Exception:
        pass
