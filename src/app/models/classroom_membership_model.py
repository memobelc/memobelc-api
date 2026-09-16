"""Membership history for classroom collections (freeze decks/cards on leave)."""

from datetime import datetime, timezone
from bson import ObjectId
from src.app import mongo


class ClassroomMembershipModel:
    @staticmethod
    def mark_joined(classroom_id, user_id, collection_id):
        if not classroom_id or not user_id:
            return
        update = {
            "left_at": None,
            "frozen_deck_ids": [],
            "frozen_cards_by_deck": {},
        }
        if collection_id:
            update["collection_id"] = ObjectId(collection_id)
        mongo.db.classroom_memberships.update_one(
            {
                "classroom_id": ObjectId(classroom_id),
                "user_id": ObjectId(user_id),
            },
            {
                "$set": update,
                "$setOnInsert": {"joined_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    @staticmethod
    def freeze_on_leave(classroom_id, user_id, collection_id, decks):
        frozen_deck_ids = []
        frozen_cards_by_deck = {}
        for deck in decks or []:
            deck_id = str(deck.get("_id") or "")
            if not deck_id:
                continue
            frozen_deck_ids.append(ObjectId(deck_id))
            frozen_cards_by_deck[deck_id] = [
                str(card_id) for card_id in (deck.get("cards") or [])
            ]

        payload = {
            "left_at": datetime.now(timezone.utc),
            "frozen_deck_ids": frozen_deck_ids,
            "frozen_cards_by_deck": frozen_cards_by_deck,
        }
        if collection_id:
            payload["collection_id"] = ObjectId(collection_id)

        mongo.db.classroom_memberships.update_one(
            {
                "classroom_id": ObjectId(classroom_id),
                "user_id": ObjectId(user_id),
            },
            {
                "$set": payload,
                "$setOnInsert": {"joined_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    @staticmethod
    def get_freeze_for_collection(user_id, collection_id):
        if not user_id or not collection_id:
            return None
        membership = mongo.db.classroom_memberships.find_one(
            {
                "user_id": ObjectId(user_id),
                "collection_id": ObjectId(collection_id),
                "left_at": {"$ne": None},
            }
        )
        if not membership:
            return None
        allowed_decks = {
            str(deck_id) for deck_id in (membership.get("frozen_deck_ids") or [])
        }
        allowed_cards = membership.get("frozen_cards_by_deck") or {}
        return {
            "left_at": membership.get("left_at"),
            "allowed_decks": allowed_decks,
            "allowed_cards": {str(k): [str(c) for c in v] for k, v in allowed_cards.items()},
        }

    @staticmethod
    def user_left_classroom_collection(user_id, collection_id):
        freeze = ClassroomMembershipModel.get_freeze_for_collection(
            user_id, collection_id
        )
        return freeze is not None

    @staticmethod
    def list_for_user(user_id):
        docs = list(
            mongo.db.classroom_memberships.find({"user_id": ObjectId(user_id)})
        )
        result = []
        for doc in docs:
            result.append({
                "classroom_id": str(doc.get("classroom_id")) if doc.get("classroom_id") else None,
                "collection_id": str(doc.get("collection_id")) if doc.get("collection_id") else None,
                "joined_at": (
                    doc["joined_at"].isoformat()
                    if doc.get("joined_at") and hasattr(doc["joined_at"], "isoformat")
                    else doc.get("joined_at")
                ),
                "left_at": (
                    doc["left_at"].isoformat()
                    if doc.get("left_at") and hasattr(doc["left_at"], "isoformat")
                    else doc.get("left_at")
                ),
                "active": not doc.get("left_at"),
            })
        return result
