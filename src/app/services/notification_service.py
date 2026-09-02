from typing import Any, Dict, List, Optional
from bson import ObjectId
from datetime import datetime, timezone

from flask import current_app
from flask_mail import Message

from src.app import mail, mongo
from src.app.config import Config
from src.app.models.notification.notification_model import NotificationModel
from src.app.models.notification.user_notification_settings_model import UserSettingsModel
from src.app.models.user_model import UserModel
from src.app.models.user_progress_model import UserProgressModel
from src.app.models.classroom_model import ClassroomModel
from src.app.models.deck_model import DeckModel
from src.app.services.push_notification_service import PushNotificationService


class NotificationService:
    """Serviço central de notificações (internas + push)."""

    TYPE_DAILY_STUDY = "daily_study"
    TYPE_CLASSROOM_ADDED = "classroom_added"
    TYPE_NEW_CARDS = "new_cards"
    TYPE_TEACHER_CUSTOM = "teacher_custom"
    TYPE_ADMIN_CUSTOM = "admin_custom"
    TYPE_SUPPORT = "support"
    TYPE_AFFILIATE = "affiliate"

    # ---------- Preferências ----------
    @staticmethod
    def get_user_settings(user_id: str) -> Dict[str, Any]:
        return UserSettingsModel.get_settings(user_id)

    @staticmethod
    def update_user_settings(user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return UserSettingsModel.update_settings(user_id, data)

    @staticmethod
    def _service_pref(user_id: str, notification_type: str) -> Dict[str, bool]:
        settings = UserSettingsModel.get_settings(user_id)
        pref = (settings.get("services") or {}).get(notification_type) or {"enabled": True, "email": False}
        return {"enabled": bool(pref.get("enabled", True)), "email": bool(pref.get("email", False))}

    @staticmethod
    def _should_notify(user_id: str, notification_type: str) -> bool:
        return NotificationService._service_pref(user_id, notification_type)["enabled"]

    @staticmethod
    def _should_email(user_id: str, notification_type: str) -> bool:
        pref = NotificationService._service_pref(user_id, notification_type)
        return pref["enabled"] and pref["email"]

    @staticmethod
    def _send_notification_email(user_id: str, title: str, body: str) -> None:
        user = UserModel.find_by_id(user_id)
        if not user or not getattr(user, "email", None):
            return
        msg = Message(
            subject=f"Memobelc: {title}",
            recipients=[user.email],
            sender=Config.MAIL_DEFAULT_SENDER or Config.MAIL_USERNAME,
        )
        msg.body = f"""Olá {user.name or ''}!

{title}

{body}

Você recebeu este e-mail porque ativou notificações por e-mail no Memobelc.

Equipe Memobelc
""".strip()
        try:
            mail.send(msg)
        except Exception as exc:
            current_app.logger.error(f"Failed to send notification email to {user.email}: {exc}")

    # ---------- Funções utilitárias ----------
    @staticmethod
    def _create_and_push(
        user_id: str,
        notification_type: str,
        title: str,
        body: str,
        extra_data: Optional[Dict[str, Any]] = None,
    ):
        if not NotificationService._should_notify(user_id, notification_type):
            return

        data = {"title": title, "body": body}
        if extra_data:
            data.update(extra_data)

        NotificationModel.create(user_id=user_id, notification_type=notification_type, data=data)
        PushNotificationService.send_to_user(user_id=user_id, title=title, body=body, data=extra_data or {})

        if NotificationService._should_email(user_id, notification_type):
            NotificationService._send_notification_email(user_id, title, body)

    # ---------- API para controllers ----------
    @staticmethod
    def list_notifications(user_id: str):
        return NotificationModel.list_by_user(user_id)

    @staticmethod
    def count_unread(user_id: str) -> int:
        return NotificationModel.count_unread(user_id)

    @staticmethod
    def mark_as_read(user_id: str, notification_id: Optional[str] = None, mark_all: bool = False) -> int:
        return NotificationModel.mark_as_read(user_id=user_id, notification_id=notification_id, mark_all=mark_all)

    # ---------- Casos de uso específicos ----------
    @staticmethod
    def send_daily_study_notifications() -> Dict[str, Any]:
        """Envia notificação diária de estudos para usuários com cartas pendentes."""
        users_cursor = mongo.db.users.find({"is_confirmed": True})
        notified_users: List[str] = []

        for user in users_cursor:
            user_id = str(user["_id"])
            pending = UserProgressModel.count_pending_cards(user_id)

            if pending <= 0:
                continue

            # Garante no máximo UMA notificação "daily_study" por dia por usuário
            last = NotificationModel.find_last(
                user_id=user_id, notification_type=NotificationService.TYPE_DAILY_STUDY
            )
            if last and isinstance(last.get("created_at"), datetime):
                last_date = last["created_at"].date()
                today_date = datetime.now(timezone.utc).date()
                if last_date == today_date:
                    # Já foi enviada hoje, pula este usuário
                    continue

            title = "Hora de estudar!"
            body = f"Você tem {pending} cartas para revisar hoje. Vamos continuar sua jornada?"

            NotificationService._create_and_push(
                user_id=user_id,
                notification_type=NotificationService.TYPE_DAILY_STUDY,
                title=title,
                body=body,
                extra_data={"pending_cards": pending},
            )
            notified_users.append(user_id)

        return {"notified_users": notified_users}

    @staticmethod
    def notify_user_added_to_classroom(classroom_id: str, user_id: str):
        """Notifica o usuário quando for adicionado a uma classroom."""
        classroom = ClassroomModel.get_by_id(classroom_id)
        if not classroom:
            return

        title = "Você foi adicionado a uma turma!"
        body = f"Você agora faz parte da classroom '{classroom.get('name')}'."

        NotificationService._create_and_push(
            user_id=str(user_id),
            notification_type=NotificationService.TYPE_CLASSROOM_ADDED,
            title=title,
            body=body,
            extra_data={"classroom_id": classroom_id},
        )

    @staticmethod
    def notify_students_new_cards(deck_id: str, amount: int):
        """Notifica os alunos de classrooms quando um professor adiciona novas cartas em um deck."""
        deck = DeckModel.get_by_id(deck_id)
        if not deck:
            return

        # Descobre quais collections possuem esse deck
        collection_doc = mongo.db.collections.find_one({"decks": ObjectId(deck_id)})
        if not collection_doc:
            return

        collection_id = str(collection_doc["_id"])

        # Turmas que usam essa collection
        classrooms_cursor = mongo.db.classrooms.find({"collection": collection_doc["_id"]})

        for classroom in classrooms_cursor:
            classroom_id = str(classroom["_id"])
            students = classroom.get("students", [])

            for student_id in students:
                student_id_str = str(student_id)
                title = "Novas cartas disponíveis!"
                body = f"Foram adicionadas {amount} novas cartas no deck '{deck.get('name')}'."

                NotificationService._create_and_push(
                    user_id=student_id_str,
                    notification_type=NotificationService.TYPE_NEW_CARDS,
                    title=title,
                    body=body,
                    extra_data={
                        "deck_id": deck_id,
                        "classroom_id": classroom_id,
                        "collection_id": collection_id,
                    },
                )

    @staticmethod
    def teacher_custom_notification(teacher_id: str, classroom_id: str, title: str, body: str):
        """Professor envia uma notificação de texto livre para todos os alunos da turma."""
        classroom = ClassroomModel.get_by_id(classroom_id)
        if not classroom:
            return {"error": "Classroom not found"}

        students = classroom.get("students", [])
        for student in students:
            # no to_dict de ClassroomModel, students são dicionários com name/email
            # portanto precisamos buscar o user_id via email
            email = student.get("email")
            if not email:
                continue
            user = UserModel.find_by_email(email)
            if not user:
                continue

            NotificationService._create_and_push(
                user_id=user._id,
                notification_type=NotificationService.TYPE_TEACHER_CUSTOM,
                title=title,
                body=body,
                extra_data={"classroom_id": classroom_id, "from_teacher_id": teacher_id},
            )

        return {"sent_to": len(students)}

    @staticmethod
    def admin_custom_notification(admin_id: str, title: str, body: str, user_ids: Optional[List[str]] = None):
        """Admin envia notificação de texto livre.

        - Se user_ids for informado: envia apenas para esses usuários.
        - Caso contrário: envia para todos usuários confirmados.
        """
        if user_ids:
            target_users = [str(uid) for uid in user_ids]
        else:
            cursor = mongo.db.users.find({"is_confirmed": True})
            target_users = [str(u["_id"]) for u in cursor]

        for uid in target_users:
            NotificationService._create_and_push(
                user_id=uid,
                notification_type=NotificationService.TYPE_ADMIN_CUSTOM,
                title=title,
                body=body,
                extra_data={"from_admin_id": admin_id},
            )

        return {"sent_to": len(target_users)}

    @staticmethod
    def _admin_user_ids(exclude_user_id: Optional[str] = None) -> List[str]:
        cursor = mongo.db.users.find(
            {"$or": [{"role": "admin"}, {"roles": "admin"}]},
            {"_id": 1},
        )
        ids = [str(user["_id"]) for user in cursor]
        if exclude_user_id:
            ids = [uid for uid in ids if uid != str(exclude_user_id)]
        return ids

    @staticmethod
    def notify_admins_new_support_message(ticket_id: str, user_id: str, preview: str):
        """Notifica admins quando um usuário envia mensagem de suporte."""
        user = UserModel.find_by_id(user_id)
        sender_name = (user.name if user and user.name else None) or "Usuário"
        title = "Nova mensagem de suporte"
        body = f"{sender_name}: {preview}" if preview else f"{sender_name} enviou uma mensagem."

        for admin_id in NotificationService._admin_user_ids(exclude_user_id=user_id):
            NotificationService._create_and_push(
                user_id=admin_id,
                notification_type=NotificationService.TYPE_SUPPORT,
                title=title,
                body=body,
                extra_data={"ticket_id": str(ticket_id), "user_id": str(user_id)},
            )

    @staticmethod
    def notify_user_support_reply(user_id: str, ticket_id: str, preview: str, admin_id: str):
        """Notifica o usuário quando o admin responde no suporte."""
        if str(user_id) == str(admin_id):
            return

        title = "Resposta do suporte"
        body = preview or "O suporte respondeu a sua mensagem."
        NotificationService._create_and_push(
            user_id=str(user_id),
            notification_type=NotificationService.TYPE_SUPPORT,
            title=title,
            body=body,
            extra_data={"ticket_id": str(ticket_id)},
        )

    @staticmethod
    def notify_admins_affiliate(title: str, body: str, kind: str, extra_data: Optional[Dict[str, Any]] = None):
        payload = {"kind": kind}
        if extra_data:
            payload.update(extra_data)
        for admin_id in NotificationService._admin_user_ids(exclude_user_id=payload.get("user_id")):
            NotificationService._create_and_push(
                user_id=admin_id,
                notification_type=NotificationService.TYPE_AFFILIATE,
                title=title,
                body=body,
                extra_data=payload,
            )


