"""Per-service visibility rules."""

from src.app import mongo
from src.app.utils.billing_utils import (
    AUDIENCES,
    SERVICE_KEYS,
    SERVICE_LABELS,
    VISIBILITY_ACTIONS,
    serialize_doc,
    utcnow,
)


DEFAULT_RULE = {
    "audience": "everyone",
    "action": "allow",
    "plan_ids": [],
}


class ServiceAccessModel:
    @staticmethod
    def canonical_action(rules):
        items = rules or []
        everyone = next(
            (rule for rule in items if (rule.get("audience") or "everyone") == "everyone"),
            None,
        )
        rule = everyone if everyone is not None else (items[0] if items else None)
        action = (rule or {}).get("action") or "allow"
        if action == "redirect_plans":
            return "disabled_upgrade"
        return action

    @staticmethod
    def canonical_rule(rules):
        action = ServiceAccessModel.canonical_action(rules)
        return {"audience": "everyone", "action": action, "plan_ids": []}
    @staticmethod
    def seed_defaults():
        now = utcnow()
        for key in SERVICE_KEYS:
            existing = mongo.db.service_access_rules.find_one({"service_key": key})
            if existing:
                continue
            mongo.db.service_access_rules.insert_one({
                "service_key": key,
                "label": SERVICE_LABELS.get(key, key),
                "rules": [dict(DEFAULT_RULE)],
                "created_at": now,
                "updated_at": now,
            })

    @staticmethod
    def list_rules():
        ServiceAccessModel.seed_defaults()
        results = []
        for doc in mongo.db.service_access_rules.find().sort("service_key", 1):
            rules = doc.get("rules") or []
            canonical = [ServiceAccessModel.canonical_rule(rules)]
            needs_normalize = (
                len(rules) != 1
                or (rules[0].get("audience") or "everyone") != "everyone"
                or (rules[0].get("action") == "redirect_plans")
            )
            if needs_normalize:
                mongo.db.service_access_rules.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"rules": canonical, "updated_at": utcnow()}},
                )
                doc["rules"] = canonical
            results.append(serialize_doc(doc))
        return results

    @staticmethod
    def get_by_key(service_key):
        ServiceAccessModel.seed_defaults()
        return serialize_doc(mongo.db.service_access_rules.find_one({"service_key": service_key}))

    @staticmethod
    def upsert(service_key, rules, label=None):
        if service_key not in SERVICE_KEYS:
            raise ValueError("Invalid service_key")
        cleaned = []
        for rule in rules or []:
            action = rule.get("action") or "allow"
            audience = rule.get("audience") or "everyone"
            if action not in VISIBILITY_ACTIONS:
                raise ValueError(f"Invalid action: {action}")
            if audience not in AUDIENCES:
                raise ValueError(f"Invalid audience: {audience}")
            cleaned.append({
                "audience": audience,
                "action": action,
                "plan_ids": [str(item) for item in (rule.get("plan_ids") or [])],
            })
        if not cleaned:
            cleaned = [dict(DEFAULT_RULE)]
        cleaned = [ServiceAccessModel.canonical_rule(cleaned)]
        updates = {
            "rules": cleaned,
            "updated_at": utcnow(),
            "label": label or SERVICE_LABELS.get(service_key, service_key),
        }
        mongo.db.service_access_rules.update_one(
            {"service_key": service_key},
            {"$set": updates, "$setOnInsert": {"service_key": service_key, "created_at": utcnow()}},
            upsert=True,
        )
        return ServiceAccessModel.get_by_key(service_key)
