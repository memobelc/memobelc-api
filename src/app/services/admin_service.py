"""Admin aggregation for a full user profile."""

from datetime import date, datetime, timezone
from bson import ObjectId

from src.app import mongo
from src.app.models.user_model import ADDRESS_FIELDS, UserModel
from src.app.models.user_streak_model import UserStreakModel
from src.app.models.chat_model import ChatModel
from src.app.models.classroom_membership_model import ClassroomMembershipModel
from src.app.models.collection_model import CollectionModel
from src.app.models.badge_model import BadgeModel
from src.app.models.mission_model import MissionModel
from src.app.models.card_model import CardModel
from src.app.models.deck_model import DeckModel
from src.app.models.notification.notification_model import NotificationModel
from src.app.models.push_notification_model import PushNotificationModel
from src.app.services.classroom_service import ClassroomService
from src.app.services.collections_service import CollectionService
from src.app.services.profile_service import empty_address


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _is_due(next_review, now):
    if not next_review or not isinstance(next_review, datetime):
        return False
    if next_review.tzinfo is None:
        next_review = next_review.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return next_review <= now


def _chat_text(parts):
    if not parts:
        return ""
    first = parts[0]
    if isinstance(first, dict):
        return str(first.get("text") or "")[:180]
    if isinstance(first, list) and first:
        return _chat_text(first)
        return str(first)[:180]


def _as_object_id(value):
    return ObjectId(str(value))


def _card_preview(text):
    front = " ".join(str(text or "").split())
    if len(front) > 80:
        return front[:80] + "…"
    return front


class AdminService:
    @staticmethod
    def _is_shared_collection(collection):
        if not collection:
            return False
        if collection.get("classroom"):
            return True
        if collection.get("book_id"):
            return True
        collection_id = collection.get("_id")
        if not collection_id:
            return False
        try:
            if mongo.db.books.find_one({"collection_id": _as_object_id(collection_id)}):
                return True
        except Exception:
            return False
        return False

    @staticmethod
    def _user_collection_ids(user_id):
        user = mongo.db.users.find_one({"_id": _as_object_id(user_id)}, {"collections": 1})
        if not user:
            return set()
        return {str(item) for item in (user.get("collections") or [])}

    @staticmethod
    def _user_has_collection(user_id, collection_id):
        return str(collection_id) in AdminService._user_collection_ids(user_id)

    @staticmethod
    def _collections_for_deck(deck_id):
        try:
            oid = _as_object_id(deck_id)
        except Exception:
            return []
        return list(mongo.db.collections.find({"decks": oid}))

    @staticmethod
    def _delete_user_progress(user_id, extra=None):
        extra = extra or {}
        uid = str(user_id)
        queries = [{"user_id": uid, **extra}]
        try:
            queries.append({"user_id": _as_object_id(uid), **extra})
        except Exception:
            pass
        for query in queries:
            mongo.db.user_progress.delete_many(query)

    @staticmethod
    def _progress_for_collection(user_id, collection):
        deck_ids = []
        for deck_id in collection.get("decks") or []:
            try:
                deck_ids.append(_as_object_id(deck_id))
            except Exception:
                continue
        if not deck_ids:
            return
        AdminService._delete_user_progress(user_id, {"deck_id": {"$in": deck_ids}})

    @staticmethod
    def _card_summaries(card_ids):
        oids = []
        ordered = []
        for card_id in card_ids or []:
            cid = str(card_id)
            ordered.append(cid)
            try:
                oids.append(_as_object_id(cid))
            except Exception:
                continue
        docs = {}
        if oids:
            docs = {
                str(doc["_id"]): doc
                for doc in mongo.db.cards.find({"_id": {"$in": oids}}, {"front": 1})
            }
        result = []
        for cid in ordered:
            doc = docs.get(cid) or {}
            result.append({
                "_id": cid,
                "front": _card_preview(doc.get("front")) or "",
            })
        return result

    @staticmethod
    def _content_owned_only_by_user(user_id, collections):
        """True if every collection is personal and not assigned to anyone else."""
        if not collections:
            return False
        user_oid = _as_object_id(user_id)
        for collection in collections:
            serialized = CollectionModel.get_by_id(str(collection.get("_id"))) or collection
            if AdminService._is_shared_collection(serialized):
                return False
            cid = collection.get("_id")
            if not cid:
                return False
            others = mongo.db.users.count_documents({
                "_id": {"$ne": user_oid},
                "$or": [
                    {"collections": _as_object_id(cid)},
                    {"collections": str(cid)},
                ],
            })
            if others > 0:
                return False
        return True

    @staticmethod
    def get_user_profile(user_id):
        user = mongo.db.users.find_one({"_id": ObjectId(str(user_id))})
        if not user:
            return None

        roles = UserModel.normalize_roles(
            role=user.get("role"),
            roles=user.get("roles"),
        )

        access_logs_raw = list(
            mongo.db.user_access_log.find({"user_id": ObjectId(str(user_id))}).sort(
                "created_at", -1
            )
        )
        active_days = set()
        logs = []
        for log in access_logs_raw[:50]:
            ts = log.get("created_at")
            if ts and hasattr(ts, "date"):
                active_days.add(ts.date())
            logs.append({
                "created_at": _iso(ts),
                "deviceName": log.get("deviceName"),
                "deviceType": log.get("deviceType"),
                "osName": log.get("osName"),
                "osVersion": log.get("osVersion"),
            })
        for log in access_logs_raw[50:]:
            ts = log.get("created_at")
            if ts and hasattr(ts, "date"):
                active_days.add(ts.date())

        last_access = logs[0]["created_at"] if logs else None
        address = user.get("address") if isinstance(user.get("address"), dict) else {}
        completed_missions = [
            item for item in MissionModel.list_for_user(str(user_id))
            if item.get("status") == "completed"
        ]

        progress_docs = list(
            mongo.db.user_progress.find({"user_id": ObjectId(str(user_id))})
        )
        now = datetime.now(timezone.utc)
        total_cards = len(progress_docs)
        cards_reviewed = sum(1 for item in progress_docs if item.get("attempts", 0) > 0)
        cards_pending = sum(
            1 for item in progress_docs if _is_due(item.get("next_review"), now)
        )

        collections = []
        try:
            collections_payload = CollectionModel.get_collections_by_user(str(user_id))
            for collection in collections_payload.get("collections") or []:
                shared = AdminService._is_shared_collection(collection)
                collections.append({
                    "_id": str(collection.get("_id") or ""),
                    "name": collection.get("name"),
                    "classroom": collection.get("classroom"),
                    "book_id": collection.get("book_id"),
                    "archived_classroom": collection.get("archived_classroom", False),
                    "is_shared": shared,
                    "total_cards": collection.get("total_cards", 0),
                    "pending_cards": collection.get("pending_cards", 0),
                    "decks": [
                        {
                            "_id": str(deck.get("_id") or ""),
                            "name": deck.get("name"),
                            "total_cards": deck.get(
                                "total_cards", len(deck.get("cards") or [])
                            ),
                            "pending_cards": deck.get("pending_cards", 0),
                            "cards": AdminService._card_summaries(deck.get("cards") or []),
                        }
                        for deck in (collection.get("decks") or [])
                        if isinstance(deck, dict)
                    ],
                })
        except Exception:
            collections = []

        classrooms = []
        try:
            classrooms = (
                ClassroomService.getClassrooms(str(user_id)).get("classrooms") or []
            )
        except Exception:
            classrooms = []

        seen = {item.get("_id") for item in classrooms}
        try:
            memberships = ClassroomMembershipModel.list_for_user(str(user_id))
        except Exception:
            memberships = []

        from src.app.models.classroom_model import ClassroomModel

        for membership in memberships:
            classroom_id = membership.get("classroom_id")
            if not classroom_id or classroom_id in seen:
                for item in classrooms:
                    if item.get("_id") == classroom_id:
                        item["joined_at"] = membership.get("joined_at")
                        item["left_at"] = membership.get("left_at")
                        item["membership_active"] = membership.get("active")
                continue
            try:
                classroom = ClassroomModel.get_by_id(classroom_id)
            except Exception:
                classroom = None
            classrooms.append({
                "_id": classroom_id,
                "name": classroom.get("name") if classroom else "",
                "user_role": "former_student",
                "joined_at": membership.get("joined_at"),
                "left_at": membership.get("left_at"),
                "membership_active": False,
            })
            seen.add(classroom_id)

        courses = []
        for classroom in classrooms:
            try:
                profile = ClassroomService.get_student_classroom_profile(
                    classroom.get("_id"), str(user_id)
                )
            except Exception:
                continue
            if not profile:
                continue
            for course in profile.get("courses") or []:
                course["classroom_id"] = classroom.get("_id")
                course["classroom_name"] = classroom.get("name") or ""
                courses.append(course)

        chats = []
        try:
            chats_raw = ChatModel.get_by_user_id(str(user_id))
        except Exception:
            chats_raw = []
        for chat in chats_raw:
            history = chat.get("history") or []
            last_text = ""
            if history:
                last = history[-1] if isinstance(history[-1], dict) else {}
                last_text = _chat_text(last.get("parts") or [])
            sanitized_history = []
            for message in history[-20:]:
                if not isinstance(message, dict):
                    continue
                sanitized_history.append({
                    "role": message.get("role") or "",
                    "parts": [{"text": _chat_text(message.get("parts") or [])}],
                })
            chats.append({
                "_id": str(chat.get("_id") or ""),
                "created_at": _iso(chat.get("created_at")),
                "message_count": len(history),
                "last_message": last_text,
                "history": sanitized_history,
            })

        member_since = _iso(user.get("created_at"))
        if not member_since and access_logs_raw:
            oldest = access_logs_raw[-1].get("created_at")
            member_since = _iso(oldest)

        try:
            streak = UserStreakModel.get_streak_info(str(user_id))
        except Exception:
            streak = {
                "current_streak": 0,
                "last_study_date": None,
                "week_study_days": [False] * 7,
            }

        payload = {
            "user": {
                "_id": str(user["_id"]),
                "name": user.get("name") or "",
                "email": user.get("email") or "",
                "image": user.get("image"),
                "cpf_cnpj": user.get("cpf_cnpj") or None,
                "address": {**empty_address(), **{
                    field: str(address.get(field) or "") for field in ADDRESS_FIELDS
                }},
                "coins": int(user.get("coins") or 0),
                "role": UserModel.primary_role(roles),
                "roles": roles,
                "member_since": member_since,
            },
            "access": {
                "last_access": last_access,
                "total_logins": len(access_logs_raw),
                "active_days": len(active_days),
                "logs": logs,
            },
            "streak": streak,
            "cards": {
                "total": total_cards,
                "reviewed": cards_reviewed,
                "pending": cards_pending,
            },
            "collections": collections,
            "classrooms": [
                {
                    "_id": item.get("_id"),
                    "name": item.get("name"),
                    "user_role": item.get("user_role"),
                    "joined_at": item.get("joined_at"),
                    "left_at": item.get("left_at"),
                    "membership_active": item.get(
                        "membership_active",
                        item.get("user_role") != "former_student",
                    ),
                }
                for item in classrooms
            ],
            "courses": courses,
            "chats": chats,
            "badges": BadgeModel.list_for_user(str(user_id)),
            "missions": completed_missions,
        }
        return _json_safe(payload)

    @staticmethod
    def delete_user(user_id, actor_id):
        if str(user_id) == str(actor_id):
            raise ValueError("You cannot delete your own account")
        user = mongo.db.users.find_one({"_id": _as_object_id(user_id)})
        if not user:
            return None
        if mongo.db.classrooms.find_one({"teacher": _as_object_id(user_id)}):
            raise ValueError("Cannot delete a user who still teaches a classroom")

        for collection_id in list(user.get("collections") or []):
            collection = CollectionModel.get_by_id(str(collection_id))
            if collection and not AdminService._is_shared_collection(collection):
                CollectionService.delete_collection(str(collection_id))
            else:
                try:
                    mongo.db.users.update_one(
                        {"_id": _as_object_id(user_id)},
                        {"$pull": {"collections": _as_object_id(collection_id)}},
                    )
                except Exception:
                    mongo.db.users.update_one(
                        {"_id": _as_object_id(user_id)},
                        {"$pull": {"collections": collection_id}},
                    )

        mongo.db.classrooms.update_many(
            {"students": _as_object_id(user_id)},
            {"$pull": {"students": _as_object_id(user_id)}},
        )
        mongo.db.classroom_memberships.delete_many({"user_id": _as_object_id(user_id)})
        AdminService._delete_user_progress(user_id)
        mongo.db.user_badges.delete_many({"user_id": str(user_id)})
        mongo.db.user_missions.delete_many({"user_id": str(user_id)})
        NotificationModel.delete_by_user(user_id)
        mongo.db.user_notification_settings.delete_many({"user_id": str(user_id)})
        PushNotificationModel.remove_tokens_by_user(user_id)
        mongo.db.chats.delete_many({"user_id": _as_object_id(user_id)})
        mongo.db.user_streaks.delete_many({"user_id": _as_object_id(user_id)})
        mongo.db.user_access_log.delete_many({"user_id": _as_object_id(user_id)})
        mongo.db.user_books.delete_many({"user_id": _as_object_id(user_id)})
        mongo.db.coin_ledger.delete_many({"user_id": str(user_id)})
        mongo.db.support_tickets.delete_many({"user_id": str(user_id)})
        mongo.db.notification_groups.update_many(
            {},
            {"$pull": {"user_ids": str(user_id)}},
        )
        mongo.db.users.delete_one({"_id": _as_object_id(user_id)})
        return True

    @staticmethod
    def delete_user_collection(user_id, collection_id):
        if not UserModel.find_by_id(user_id):
            return None
        if not AdminService._user_has_collection(user_id, collection_id):
            raise ValueError("Collection not found for this user")
        collection = CollectionModel.get_by_id(collection_id)
        if not collection:
            raise ValueError("Collection not found")
        shared = AdminService._is_shared_collection(collection)
        if shared:
            AdminService._progress_for_collection(user_id, collection)
            mongo.db.users.update_one(
                {"_id": _as_object_id(user_id)},
                {"$pull": {"collections": _as_object_id(collection_id)}},
            )
            return {"deleted": True, "mode": "progress"}
        deleted = CollectionService.delete_collection(collection_id)
        if not deleted:
            raise ValueError("Collection could not be deleted")
        return {"deleted": True, "mode": "content"}

    @staticmethod
    def delete_user_deck(user_id, deck_id):
        if not UserModel.find_by_id(user_id):
            return None
        collections = AdminService._collections_for_deck(deck_id)
        if not collections:
            raise ValueError("Deck not found")
        user_cols = AdminService._user_collection_ids(user_id)
        owned = [item for item in collections if str(item.get("_id")) in user_cols]
        if not owned:
            raise ValueError("Deck not found for this user")
        if AdminService._content_owned_only_by_user(user_id, owned):
            DeckModel.delete_deck(deck_id)
            return {"deleted": True, "mode": "content"}
        AdminService._delete_user_progress(user_id, {"deck_id": _as_object_id(deck_id)})
        return {"deleted": True, "mode": "progress"}

    @staticmethod
    def delete_user_card(user_id, card_id):
        if not UserModel.find_by_id(user_id):
            return None
        card = CardModel.get_by_id(card_id)
        if not card:
            raise ValueError("Card not found")
        decks = list(mongo.db.decks.find({
            "$or": [
                {"cards": _as_object_id(card_id)},
                {"cards": str(card_id)},
            ]
        }))
        collections = []
        for deck in decks:
            collections.extend(AdminService._collections_for_deck(deck.get("_id")))
        user_cols = AdminService._user_collection_ids(user_id)
        owned = [item for item in collections if str(item.get("_id")) in user_cols]
        if decks and not owned:
            raise ValueError("Card not found for this user")
        if owned and AdminService._content_owned_only_by_user(user_id, owned):
            mongo.db.decks.update_many(
                {"cards": _as_object_id(card_id)},
                {"$pull": {"cards": _as_object_id(card_id)}},
            )
            mongo.db.decks.update_many(
                {"cards": str(card_id)},
                {"$pull": {"cards": str(card_id)}},
            )
            mongo.db.cards.delete_one({"_id": _as_object_id(card_id)})
            AdminService._delete_user_progress(user_id, {"card_id": _as_object_id(card_id)})
            return {"deleted": True, "mode": "content"}
        AdminService._delete_user_progress(user_id, {"card_id": _as_object_id(card_id)})
        return {"deleted": True, "mode": "progress"}
