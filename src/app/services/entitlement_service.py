"""Central access resolver for plans, purchases, manuals grants and service visibility."""

from datetime import timezone

from src.app.models.book_bundle_model import BookBundleModel
from src.app.models.book_model import BookModel
from src.app.models.entitlement_model import EntitlementModel
from src.app.models.plan_model import PlanModel
from src.app.models.service_access_model import ServiceAccessModel
from src.app.models.subscription_model import SubscriptionModel
from src.app.utils.billing_utils import (
    ACCESS_STATUSES,
    GRACE_ELIGIBLE_STATUSES,
    SERVICE_KEYS,
    parse_datetime,
    utcnow,
)


STATUS_MESSAGES = {
    "trialing": "trialing",
    "active": "active",
    "pending": "pending_payment",
    "overdue": "pending_payment",
    "refused": "payment_refused",
    "canceled": "canceled",
    "expired": "expired",
    "suspended": "canceled",
    "manual": "manual_access",
}


class EntitlementService:
    @staticmethod
    def _subscription_grants_access(subscription):
        if not subscription:
            return False
        status = subscription.get("status")
        if status in ACCESS_STATUSES:
            return True
        if status in GRACE_ELIGIBLE_STATUSES:
            grace = parse_datetime(subscription.get("grace_until"))
            if grace:
                now = utcnow()
                if grace.tzinfo is None:
                    grace = grace.replace(tzinfo=timezone.utc)
                return now <= grace
        return False

    @staticmethod
    def current_subscription(user_id):
        items = SubscriptionModel.list_for_user(user_id)
        for item in items:
            if EntitlementService._subscription_grants_access(item):
                return item
        return items[0] if items else None

    @staticmethod
    def is_subscriber(user_id):
        subscription = EntitlementService.current_subscription(user_id)
        return EntitlementService._subscription_grants_access(subscription)

    @staticmethod
    def grant_subscription_entitlements(user_id, plan, subscription_id):
        EntitlementModel.grant({
            "user_id": user_id,
            "type": "plan",
            "resource_id": plan["_id"],
            "source": "subscription",
            "source_id": subscription_id,
        })
        for service_key in plan.get("included_service_keys") or []:
            EntitlementModel.grant({
                "user_id": user_id,
                "type": "service",
                "resource_id": service_key,
                "source": "subscription",
                "source_id": subscription_id,
            })
        book_ids = list(plan.get("included_book_ids") or [])
        for bundle_id in plan.get("included_bundle_ids") or []:
            EntitlementModel.grant({
                "user_id": user_id,
                "type": "bundle",
                "resource_id": bundle_id,
                "source": "subscription",
                "source_id": subscription_id,
            })
            bundle = BookBundleModel.get_by_id(bundle_id)
            if bundle:
                book_ids.extend(bundle.get("book_ids") or [])
        seen = set()
        for book_id in book_ids:
            if book_id in seen:
                continue
            seen.add(book_id)
            EntitlementService.grant_book(user_id, book_id, source="subscription", source_id=subscription_id)

    @staticmethod
    def revoke_subscription_entitlements(user_id, subscription_id):
        EntitlementModel.revoke_by_source(user_id, "subscription", subscription_id)

    @staticmethod
    def grant_book(user_id, book_id, source="purchase", source_id=None, granted_by=None, notes=""):
        entitlement = EntitlementModel.grant({
            "user_id": user_id,
            "type": "book",
            "resource_id": book_id,
            "source": source,
            "source_id": source_id,
            "granted_by": granted_by,
            "notes": notes,
        })
        BookModel.add_book_to_user(user_id, book_id)
        return entitlement

    @staticmethod
    def grant_bundle(user_id, bundle_id, source="purchase", source_id=None, granted_by=None, notes=""):
        bundle = BookBundleModel.get_by_id(bundle_id)
        if not bundle:
            return None
        entitlement = EntitlementModel.grant({
            "user_id": user_id,
            "type": "bundle",
            "resource_id": bundle_id,
            "source": source,
            "source_id": source_id,
            "granted_by": granted_by,
            "notes": notes,
        })
        for book_id in bundle.get("book_ids") or []:
            EntitlementService.grant_book(
                user_id, book_id, source=source, source_id=source_id, granted_by=granted_by, notes=notes
            )
        return entitlement

    @staticmethod
    def grant_course(user_id, course_id, source="purchase", source_id=None, granted_by=None, notes=""):
        return EntitlementModel.grant({
            "user_id": user_id,
            "type": "course",
            "resource_id": course_id,
            "source": source,
            "source_id": source_id,
            "granted_by": granted_by,
            "notes": notes,
        })

    @staticmethod
    def grant_classroom(user_id, classroom_id, source="purchase", source_id=None, granted_by=None, notes=""):
        return EntitlementModel.grant({
            "user_id": user_id,
            "type": "classroom",
            "resource_id": classroom_id,
            "source": source,
            "source_id": source_id,
            "granted_by": granted_by,
            "notes": notes,
        })

    @staticmethod
    def grant_plan_manual(user_id, plan_id, granted_by=None, notes=""):
        plan = PlanModel.get_by_id(plan_id)
        if not plan:
            return None
        from src.app.models.subscription_model import SubscriptionModel

        subscription = SubscriptionModel.create({
            "user_id": user_id,
            "plan_id": plan_id,
            "provider": "manual",
            "status": "active",
            "value": 0,
            "original_value": plan.get("price") or 0,
            "billing_cycle": plan.get("cycle"),
            "metadata": {"notes": notes},
        })
        EntitlementService.grant_subscription_entitlements(user_id, plan, subscription["_id"])
        EntitlementModel.grant({
            "user_id": user_id,
            "type": "plan",
            "resource_id": plan_id,
            "source": "manual",
            "source_id": subscription["_id"],
            "granted_by": granted_by,
            "notes": notes,
        })
        return subscription

    @staticmethod
    def revoke_entitlement(entitlement_id, notes=None):
        entitlement = EntitlementModel.get_by_id(entitlement_id)
        if not entitlement:
            return None
        return EntitlementModel.revoke(entitlement_id, notes=notes)

    @staticmethod
    def user_book_ids(user_id):
        ids = set()
        for item in EntitlementModel.list_active_for_user(user_id):
            if item.get("type") == "book":
                ids.add(item["resource_id"])
            elif item.get("type") == "bundle":
                bundle = BookBundleModel.get_by_id(item["resource_id"])
                if bundle:
                    ids.update(bundle.get("book_ids") or [])
        subscription = EntitlementService.current_subscription(user_id)
        if EntitlementService._subscription_grants_access(subscription):
            plan = PlanModel.get_by_id(subscription.get("plan_id"))
            if plan:
                ids.update(plan.get("included_book_ids") or [])
                for bundle_id in plan.get("included_bundle_ids") or []:
                    bundle = BookBundleModel.get_by_id(bundle_id)
                    if bundle:
                        ids.update(bundle.get("book_ids") or [])
        return ids

    @staticmethod
    def can_access_book(user, book_id):
        if user and user.has_role("admin"):
            return True, None
        book = BookModel.get_by_id(book_id)
        if not book:
            return False, {"error": "Book not found", "code": "not_found"}
        if book.get("is_free"):
            return True, None
        if str(book_id) in EntitlementService.user_book_ids(user._id):
            return True, None
        from src.app import mongo
        from bson import ObjectId

        owned = mongo.db.user_books.find_one({
            "user_id": ObjectId(user._id),
            "book_id": ObjectId(book_id),
        })
        if owned:
            return True, None
        return False, {
            "error": "Access denied. Book requires payment.",
            "code": "plan_lacks_service",
        }

    @staticmethod
    def _match_rule(rule, is_subscriber, plan_id, has_manual):
        audience = rule.get("audience") or "everyone"
        if audience == "everyone":
            return True
        if audience == "subscribers":
            return is_subscriber
        if audience == "non_subscribers":
            return not is_subscriber
        if audience == "manual":
            return has_manual
        if audience == "plans":
            return is_subscriber and plan_id in (rule.get("plan_ids") or [])
        return False

    @staticmethod
    def _configured_action(service_key):
        config = ServiceAccessModel.get_by_key(service_key) or {"rules": []}
        return ServiceAccessModel.canonical_action(config.get("rules") or [])

    @staticmethod
    def _has_service_entitlement(user, service_key, is_subscriber=None, entitlements=None):
        if not user:
            return False
        if is_subscriber is None:
            is_subscriber = EntitlementService.is_subscriber(user._id)
        if entitlements is None:
            entitlements = EntitlementModel.list_active_for_user(user._id)
        has_manual_service = any(
            item.get("type") == "service"
            and item.get("resource_id") == service_key
            and item.get("source") in ("manual", "external")
            for item in entitlements
        )
        return bool(is_subscriber or has_manual_service)

    @staticmethod
    def service_action(user, service_key):
        is_subscriber = EntitlementService.is_subscriber(user._id) if user else False
        subscription = EntitlementService.current_subscription(user._id) if user else None
        entitlements = EntitlementModel.list_active_for_user(user._id) if user else []
        has_manual_service = any(
            item.get("type") == "service"
            and item.get("resource_id") == service_key
            and item.get("source") in ("manual", "external")
            for item in entitlements
        )
        has_manual_any = any(item.get("source") in ("manual", "external") for item in entitlements)
        configured = EntitlementService._configured_action(service_key)
        action = configured

        if action == "disabled_upgrade":
            entitled = EntitlementService._has_service_entitlement(
                user,
                service_key,
                is_subscriber=is_subscriber,
                entitlements=entitlements,
            )
            if entitled:
                action = "allow"

        status_code = "active"
        if not is_subscriber and has_manual_any:
            status_code = "manual_access"
        elif subscription:
            status_code = STATUS_MESSAGES.get(subscription.get("status"), "active")
        if action != "allow":
            if action == "hide":
                status_code = "hidden"
            elif action == "disabled":
                status_code = "disabled"
            elif not is_subscriber and not has_manual_service:
                status_code = STATUS_MESSAGES.get(
                    subscription.get("status") if subscription else None, "plan_lacks_service"
                )
            else:
                status_code = "plan_lacks_service"
        return action, status_code

    @staticmethod
    def can_access_service(user, service_key):
        if user and user.has_role("admin"):
            return True, None
        action, code = EntitlementService.service_action(user, service_key)
        if action == "allow":
            return True, None
        return False, {
            "error": "Access denied for this service",
            "code": code,
            "action": action,
            "service_key": service_key,
        }

    @staticmethod
    def resolve(user):
        user_id = user._id
        subscription = EntitlementService.current_subscription(user_id)
        plan = PlanModel.get_by_id(subscription["plan_id"]) if subscription else None
        entitlements = EntitlementModel.list_active_for_user(user_id)
        is_subscriber = EntitlementService._subscription_grants_access(subscription)
        has_manual = any(item.get("source") in ("manual", "external") for item in entitlements)
        status = None
        if is_subscriber:
            status = subscription.get("status") if subscription else "active"
        elif has_manual:
            status = "manual"
        elif subscription:
            status = subscription.get("status")
        services = {}
        for key in SERVICE_KEYS:
            action, code = EntitlementService.service_action(user, key)
            configured = EntitlementService._configured_action(key)
            services[key] = {
                "action": action,
                "configured": configured,
                "code": code,
            }
        return {
            "is_subscriber": is_subscriber,
            "has_manual_access": has_manual,
            "status": status,
            "status_code": STATUS_MESSAGES.get(status, status),
            "subscription": subscription,
            "plan": plan,
            "entitlements": entitlements,
            "book_ids": list(EntitlementService.user_book_ids(user_id)),
            "services": services,
        }
