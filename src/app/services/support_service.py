"""Business logic for user↔admin support conversations."""

from datetime import datetime, timezone

from src.app import mongo
from src.app.models.support_message_model import SupportMessageModel
from src.app.models.support_ticket_model import SupportTicketModel
from src.app.models.user_model import UserModel

MAX_BODY_LENGTH = 4000


class SupportError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _parse_since(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError as exc:
        raise SupportError("Invalid since parameter", 400) from exc


def _clean_body(body):
    if body is None or not isinstance(body, str):
        raise SupportError("body is required", 400)
    text = body.strip()
    if not text:
        raise SupportError("body is required", 400)
    if len(text) > MAX_BODY_LENGTH:
        raise SupportError(f"body must be at most {MAX_BODY_LENGTH} characters", 400)
    return text


def _enrich_ticket(ticket):
    if not ticket:
        return None
    user = UserModel.find_by_id(ticket["user_id"])
    enriched = dict(ticket)
    enriched["user_name"] = user.name if user else None
    enriched["user_email"] = user.email if user else None
    return enriched


def _user_ids_matching(query):
    if not query:
        return None
    cursor = mongo.db.users.find(
        {
            "$or": [
                {"name": {"$regex": query, "$options": "i"}},
                {"email": {"$regex": query, "$options": "i"}},
            ]
        },
        {"_id": 1},
    )
    return [str(doc["_id"]) for doc in cursor]


class SupportService:
    @staticmethod
    def ensure_indexes():
        SupportTicketModel.ensure_indexes()

    @staticmethod
    def get_user_conversation(user_id, since=None):
        ticket = SupportTicketModel.find_by_user_id(user_id)
        if not ticket:
            return {"ticket": None, "messages": []}
        since_dt = _parse_since(since)
        messages = SupportMessageModel.list_by_ticket(ticket["_id"], since=since_dt)
        return {"ticket": ticket, "messages": messages}

    @staticmethod
    def send_user_message(user_id, body):
        text = _clean_body(body)
        ticket = SupportTicketModel.get_or_create_for_user(user_id)
        message = SupportMessageModel.create(
            ticket_id=ticket["_id"],
            author_id=user_id,
            author_role="user",
            body=text,
        )
        preview = SupportTicketModel.preview_from_body(text)
        ticket = SupportTicketModel.apply_user_message(ticket["_id"], preview)

        try:
            from src.app.services.notification_service import NotificationService

            NotificationService.notify_admins_new_support_message(
                ticket_id=ticket["_id"],
                user_id=user_id,
                preview=preview,
            )
        except Exception:
            pass
        return {"ticket": ticket, "message": message}

    @staticmethod
    def mark_user_messages_read(user_id):
        ticket = SupportTicketModel.find_by_user_id(user_id)
        if not ticket:
            return {"ticket": None, "modified": 0}
        modified = SupportMessageModel.mark_role_as_read(ticket["_id"], "admin")
        ticket = SupportTicketModel.clear_unread_for_user(ticket["_id"])
        return {"ticket": ticket, "modified": modified}

    @staticmethod
    def list_admin_tickets(status=None, q=None):
        search = (q or "").strip() or None
        user_ids = _user_ids_matching(search) if search else None
        if search and not user_ids:
            return {"tickets": [], "unread_total": SupportTicketModel.unread_admin_total()}
        tickets = SupportTicketModel.list_tickets(status=status, user_ids=user_ids)
        return {
            "tickets": [_enrich_ticket(ticket) for ticket in tickets],
            "unread_total": SupportTicketModel.unread_admin_total(),
        }

    @staticmethod
    def get_admin_ticket(ticket_id):
        ticket = SupportTicketModel.find_by_id(ticket_id)
        if not ticket:
            raise SupportError("Ticket not found", 404)
        return _enrich_ticket(ticket)

    @staticmethod
    def list_admin_messages(ticket_id, since=None):
        ticket = SupportTicketModel.find_by_id(ticket_id)
        if not ticket:
            raise SupportError("Ticket not found", 404)
        since_dt = _parse_since(since)
        return {
            "ticket": _enrich_ticket(ticket),
            "messages": SupportMessageModel.list_by_ticket(ticket_id, since=since_dt),
        }

    @staticmethod
    def send_admin_message(admin_id, ticket_id, body):
        text = _clean_body(body)
        ticket = SupportTicketModel.find_by_id(ticket_id)
        if not ticket:
            raise SupportError("Ticket not found", 404)
        if ticket.get("status") == "closed":
            raise SupportError("Ticket is closed", 400)

        message = SupportMessageModel.create(
            ticket_id=ticket_id,
            author_id=admin_id,
            author_role="admin",
            body=text,
        )
        preview = SupportTicketModel.preview_from_body(text)
        ticket = SupportTicketModel.apply_admin_message(ticket_id, preview)

        try:
            from src.app.services.notification_service import NotificationService

            NotificationService.notify_user_support_reply(
                user_id=ticket["user_id"],
                ticket_id=ticket["_id"],
                preview=preview,
                admin_id=admin_id,
            )
        except Exception:
            pass
        return {"ticket": _enrich_ticket(ticket), "message": message}

    @staticmethod
    def mark_admin_messages_read(ticket_id):
        ticket = SupportTicketModel.find_by_id(ticket_id)
        if not ticket:
            raise SupportError("Ticket not found", 404)
        modified = SupportMessageModel.mark_role_as_read(ticket_id, "user")
        ticket = SupportTicketModel.clear_unread_for_admin(ticket_id)
        return {"ticket": _enrich_ticket(ticket), "modified": modified}

    @staticmethod
    def close_ticket(admin_id, ticket_id):
        ticket = SupportTicketModel.find_by_id(ticket_id)
        if not ticket:
            raise SupportError("Ticket not found", 404)
        if ticket.get("status") == "closed":
            return _enrich_ticket(ticket)
        return _enrich_ticket(SupportTicketModel.close(ticket_id, admin_id))

    @staticmethod
    def reopen_ticket(ticket_id):
        ticket = SupportTicketModel.find_by_id(ticket_id)
        if not ticket:
            raise SupportError("Ticket not found", 404)
        if ticket.get("status") != "closed":
            return _enrich_ticket(ticket)
        return _enrich_ticket(SupportTicketModel.reopen(ticket_id))

    @staticmethod
    def post_system_message(user_id, body):
        text = _clean_body(body)
        ticket = SupportTicketModel.get_or_create_for_user(user_id)
        message = SupportMessageModel.create(
            ticket_id=ticket["_id"],
            author_id="system",
            author_role="system",
            body=text,
        )
        preview = SupportTicketModel.preview_from_body(text)
        ticket = SupportTicketModel.apply_system_message(ticket["_id"], preview)
        return {"ticket": ticket, "message": message}
