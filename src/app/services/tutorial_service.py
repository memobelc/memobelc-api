"""Tutorial matching, progress, analytics and Brain catalog."""

from datetime import timedelta, timezone

from bson import ObjectId

from src.app import mongo
from src.app.models.tutorial_model import (
    EVENT_TYPES,
    BrainAvatarModel,
    TutorialEventModel,
    TutorialModel,
    UserTutorialProgressModel,
    localize_tutorial,
    resolve_i18n,
)
from src.app.services.entitlement_service import EntitlementService
from src.app.utils.billing_utils import utcnow


class TutorialService:
    @staticmethod
    def _locale(locale):
        return (locale or "en").replace("-", "_").lower()

    @staticmethod
    def _is_new_user(user, days=14):
        cutoff = utcnow() - timedelta(days=max(int(days or 14), 1))
        try:
            oid = ObjectId(str(user._id))
        except Exception:
            oid = None
        query = {"$or": [{"user_id": str(user._id)}]}
        if oid:
            query["$or"].append({"user_id": oid})
        first = mongo.db.user_access_log.find_one(query, sort=[("created_at", 1)])
        if first and first.get("created_at"):
            created = first["created_at"]
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return created >= cutoff
        return True

    @staticmethod
    def matches_audience(tutorial, user):
        audience = tutorial.get("audience") or {"type": "all"}
        audience_type = audience.get("type") or "all"
        if audience_type == "all":
            return True
        if audience_type == "specific_users":
            return str(user._id) in [str(item) for item in audience.get("user_ids") or []]
        if audience_type == "roles":
            roles = audience.get("roles") or []
            return any(user.has_role(role) for role in roles)
        if audience_type == "premium":
            return bool(EntitlementService.is_subscriber(str(user._id)))
        if audience_type == "free":
            return not EntitlementService.is_subscriber(str(user._id))
        if audience_type == "new_users":
            return TutorialService._is_new_user(user, audience.get("new_user_days") or 14)
        return True

    @staticmethod
    def _done(progress):
        if not progress:
            return False
        return bool(progress.get("completed") or progress.get("skipped"))

    @staticmethod
    def get_active_for_user(user, locale="en", section=None):
        wanted = (section or "home").strip() or "home"
        tutorials = TutorialModel.list_active()
        tutorials.sort(key=lambda item: (0 if item.get("key") == "onboarding" else 1, item.get("published_at") or ""))
        for tutorial in tutorials:
            tutorial_section = tutorial.get("section") or "home"
            if tutorial_section != wanted:
                continue
            if not TutorialService.matches_audience(tutorial, user):
                continue
            progress = UserTutorialProgressModel.get(user._id, tutorial["_id"])
            if TutorialService._done(progress):
                continue
            localized = localize_tutorial(tutorial, TutorialService._locale(locale))
            localized["progress"] = progress
            return localized
        return None

    @staticmethod
    def catalog_for_user(user, locale="en"):
        tutorials = TutorialModel.list_tutorials()
        visible = [
            item
            for item in tutorials
            if item.get("status") in ("active", "archived")
            and TutorialService.matches_audience(item, user)
        ]
        progress_map = {
            item["tutorial_id"]: item for item in UserTutorialProgressModel.list_for_user(user._id)
        }
        result = []
        for tutorial in visible:
            localized = localize_tutorial(tutorial, TutorialService._locale(locale))
            localized["progress"] = progress_map.get(tutorial["_id"])
            result.append(localized)
        return result

    @staticmethod
    def history_for_user(user, locale="en"):
        progress = UserTutorialProgressModel.list_for_user(user._id)
        result = []
        for item in progress:
            tutorial = TutorialModel.get_by_id(item.get("tutorial_id"))
            if not tutorial:
                result.append(item)
                continue
            result.append(
                {
                    **item,
                    "name": resolve_i18n(tutorial.get("name"), TutorialService._locale(locale)),
                    "description": resolve_i18n(
                        tutorial.get("description"), TutorialService._locale(locale)
                    ),
                    "status": tutorial.get("status"),
                }
            )
        return result

    @staticmethod
    def record_event(user, tutorial_id, event_type, step_index=None, duration_ms=None):
        tutorial = TutorialModel.get_by_id(tutorial_id)
        if not tutorial:
            raise ValueError("Tutorial not found")
        if tutorial.get("status") not in ("active", "archived"):
            raise ValueError("Tutorial is not available")
        if event_type not in EVENT_TYPES:
            raise ValueError("Invalid event type")
        patch = {"viewed": True, "last_viewed_at": utcnow()}
        if step_index is not None:
            try:
                patch["current_step"] = max(int(step_index), 0)
            except (TypeError, ValueError):
                pass
        if event_type == "complete":
            patch.update({"completed": True, "skipped": False, "completed_at": utcnow()})
        if event_type == "skip":
            patch.update({"skipped": True, "completed": False, "skipped_at": utcnow()})
        if event_type == "replay":
            patch.update(
                {
                    "completed": False,
                    "skipped": False,
                    "current_step": 0,
                    "completed_at": None,
                    "skipped_at": None,
                }
            )
        progress = UserTutorialProgressModel.upsert(user._id, tutorial, patch)
        event = TutorialEventModel.record(
            user._id, tutorial, event_type, step_index=step_index, duration_ms=duration_ms
        )
        return {"progress": progress, "event": event, "tutorial": tutorial}

    @staticmethod
    def complete(user, tutorial_id, duration_ms=None):
        return TutorialService.record_event(user, tutorial_id, "complete", duration_ms=duration_ms)

    @staticmethod
    def skip(user, tutorial_id, duration_ms=None, step_index=None):
        return TutorialService.record_event(
            user, tutorial_id, "skip", step_index=step_index, duration_ms=duration_ms
        )

    @staticmethod
    def replay(user, tutorial_id, locale="en"):
        result = TutorialService.record_event(user, tutorial_id, "replay")
        tutorial = localize_tutorial(result["tutorial"], TutorialService._locale(locale))
        tutorial["progress"] = result["progress"]
        return tutorial

    @staticmethod
    def list_admin(status=None):
        tutorials = TutorialModel.list_tutorials(status=status)
        return [TutorialService._with_list_metrics(item) for item in tutorials]

    @staticmethod
    def _with_list_metrics(tutorial):
        tutorial_id = str(tutorial["_id"])
        progress = list(mongo.db.user_tutorial_progress.find({"tutorial_id": tutorial_id}))
        viewed = len(progress)
        completed = sum(1 for item in progress if item.get("completed"))
        skipped = sum(1 for item in progress if item.get("skipped") and not item.get("completed"))
        abandoned = sum(
            1
            for item in progress
            if item.get("viewed") and not item.get("completed") and not item.get("skipped")
        )
        def rate(count):
            return round((count / viewed) * 100, 1) if viewed else 0.0

        tutorial["users_impacted"] = viewed
        tutorial["completion_rate"] = rate(completed)
        tutorial["skip_rate"] = rate(skipped)
        tutorial["abandon_rate"] = rate(abandoned)
        return tutorial

    @staticmethod
    def analytics(tutorial_id):
        tutorial = TutorialModel.get_by_id(tutorial_id)
        if not tutorial:
            return None
        tutorial_oid = tutorial_id
        progress = list(mongo.db.user_tutorial_progress.find({"tutorial_id": str(tutorial_oid)}))
        events = list(mongo.db.tutorial_events.find({"tutorial_id": str(tutorial_oid)}))
        viewed = len(progress)
        completed = sum(1 for item in progress if item.get("completed"))
        skipped = sum(1 for item in progress if item.get("skipped") and not item.get("completed"))
        abandoned = sum(
            1
            for item in progress
            if item.get("viewed") and not item.get("completed") and not item.get("skipped")
        )
        times = [int(item.get("time_spent_ms") or 0) for item in progress if item.get("time_spent_ms")]
        avg_ms = int(sum(times) / len(times)) if times else 0
        skip_clicks = sum(1 for item in events if item.get("type") == "skip")
        replay_clicks = sum(1 for item in events if item.get("type") == "replay")
        views = sum(1 for item in events if item.get("type") in ("view", "replay", "step_view"))

        steps = sorted(tutorial.get("steps") or [], key=lambda row: row.get("order") or 0)
        dropoff = []
        max_reached = 0
        for index, step in enumerate(steps):
            reached = sum(
                1
                for item in events
                if item.get("type") in ("step_view", "next", "view")
                and (item.get("step_index") or 0) >= index
            )
            skipped_here = sum(
                1
                for item in events
                if item.get("type") == "skip" and (item.get("step_index") or 0) == index
            )
            dropoff.append(
                {
                    "step_id": step.get("id"),
                    "order": step.get("order"),
                    "title": resolve_i18n(step.get("title"), "en"),
                    "reached": reached,
                    "skipped_here": skipped_here,
                }
            )
            if skipped_here > max_reached:
                max_reached = skipped_here
        highest_abandon_step = None
        if dropoff:
            highest_abandon_step = max(dropoff, key=lambda row: row.get("skipped_here") or 0)

        def rate(count):
            return round((count / viewed) * 100, 1) if viewed else 0.0

        return {
            "tutorial": tutorial,
            "views": views or viewed,
            "users_impacted": viewed,
            "completed": completed,
            "skipped": skipped,
            "abandoned": abandoned,
            "completion_rate": rate(completed),
            "skip_rate": rate(skipped),
            "abandon_rate": rate(abandoned),
            "avg_time_ms": avg_ms,
            "skip_clicks": skip_clicks,
            "replay_clicks": replay_clicks,
            "step_dropoff": dropoff,
            "highest_abandon_step": highest_abandon_step,
        }

    @staticmethod
    def user_profile_status(user_id, locale="en"):
        history = []
        for item in UserTutorialProgressModel.list_for_user(user_id):
            tutorial = TutorialModel.get_by_id(item.get("tutorial_id"))
            history.append(
                {
                    **item,
                    "name": resolve_i18n((tutorial or {}).get("name"), TutorialService._locale(locale))
                    if tutorial
                    else item.get("tutorial_key"),
                    "status": (tutorial or {}).get("status"),
                }
            )
        current = history[0] if history else None
        return {
            "current": current,
            "history": history,
        }

    @staticmethod
    def list_avatars(active_only=False):
        return BrainAvatarModel.list_avatars(active_only=active_only)
