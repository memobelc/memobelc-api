from typing import Any, Dict, List, Optional
from bson import ObjectId
from datetime import datetime, timezone

from flask import current_app
from flask_mail import Message

from src.app import mail, mongo
from src.app.models.notification.notification_model import NotificationModel
from src.app.models.notification.notification_group_model import NotificationGroupModel
from src.app.models.notification.user_notification_settings_model import UserSettingsModel
from src.app.models.user_model import UserModel, ALLOWED_ROLES
from src.app.models.user_progress_model import UserProgressModel
from src.app.models.classroom_model import ClassroomModel
from src.app.models.deck_model import DeckModel
from src.app.services.push_notification_service import PushNotificationService
from src.app.services.settings_service import SettingsService


class NotificationService:
    """Serviço central de notificações (internas + push)."""

    TYPE_DAILY_STUDY = "daily_study"
    TYPE_CLASSROOM_ADDED = "classroom_added"
    TYPE_NEW_CARDS = "new_cards"
    TYPE_TEACHER_CUSTOM = "teacher_custom"
    TYPE_ADMIN_CUSTOM = "admin_custom"
    TYPE_SUPPORT = "support"
    TYPE_AFFILIATE = "affiliate"
    TYPE_AFFILIATE_SALE = "affiliate_sales"

    TARGET_TYPES = ("all", "users", "roles", "classroom", "group")
    AUDIENCE_ROLES = tuple(role for role in ALLOWED_ROLES if role != "super_admin")

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
            sender=SettingsService.mail_sender(),
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
            app = current_app._get_current_object()
            def _send_email_async():
                with app.app_context():
                    NotificationService._send_notification_email(user_id, title, body)
            try:
                import threading
                threading.Thread(target=_send_email_async, daemon=True).start()
            except Exception as exc:
                current_app.logger.error(f"Failed to start notification email thread: {exc}")

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
    def _classroom_student_ids(classroom: Dict[str, Any]) -> List[str]:
        ids: List[str] = []
        seen = set()
        for student in classroom.get("students") or []:
            if isinstance(student, dict):
                uid = str(student.get("_id") or "")
            else:
                uid = str(student or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            ids.append(uid)
        return ids

    @staticmethod
    def _confirmed_user_ids(user_ids: List[str]) -> List[str]:
        object_ids = []
        ordered: List[str] = []
        seen = set()
        for uid in user_ids or []:
            sid = str(uid or "").strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            ordered.append(sid)
            try:
                object_ids.append(ObjectId(sid))
            except Exception:
                continue
        if not object_ids:
            return []
        found = {
            str(user["_id"])
            for user in mongo.db.users.find(
                {"_id": {"$in": object_ids}, "is_confirmed": True},
                {"_id": 1},
            )
        }
        return [uid for uid in ordered if uid in found]

    @staticmethod
    def resolve_admin_targets(
        target_type: Optional[str] = None,
        user_ids: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        classroom_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> List[str]:
        resolved_type = (target_type or "").strip() or ("users" if user_ids else "all")
        if resolved_type not in NotificationService.TARGET_TYPES:
            raise ValueError("Invalid target_type")

        if resolved_type == "all":
            return [
                str(user["_id"])
                for user in mongo.db.users.find({"is_confirmed": True}, {"_id": 1})
            ]

        if resolved_type == "users":
            if not user_ids:
                raise ValueError("user_ids is required")
            return NotificationService._confirmed_user_ids([str(uid) for uid in user_ids])

        if resolved_type == "roles":
            if not roles:
                raise ValueError("roles is required")
            valid_roles = [
                role for role in roles if role in NotificationService.AUDIENCE_ROLES
            ]
            if not valid_roles:
                raise ValueError("Invalid roles")
            return list(
                {
                    str(user["_id"])
                    for user in mongo.db.users.find(
                        {
                            "is_confirmed": True,
                            "$or": [
                                {"role": {"$in": valid_roles}},
                                {"roles": {"$in": valid_roles}},
                            ],
                        },
                        {"_id": 1},
                    )
                }
            )

        if resolved_type == "classroom":
            if not classroom_id:
                raise ValueError("classroom_id is required")
            classroom = ClassroomModel.get_by_id(classroom_id)
            if not classroom:
                raise ValueError("Classroom not found")
            return NotificationService._confirmed_user_ids(
                NotificationService._classroom_student_ids(classroom)
            )

        if resolved_type == "group":
            if not group_id:
                raise ValueError("group_id is required")
            group = NotificationGroupModel.get_by_id(group_id)
            if not group:
                raise ValueError("Group not found")
            return NotificationService._confirmed_user_ids(group.get("user_ids") or [])

        raise ValueError("Invalid target_type")

    @staticmethod
    def preview_admin_targets(
        target_type: Optional[str] = None,
        user_ids: Optional[List[str]] = None,
        roles: Optional[List[str]] = None,
        classroom_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        targets = NotificationService.resolve_admin_targets(
            target_type=target_type,
            user_ids=user_ids,
            roles=roles,
            classroom_id=classroom_id,
            group_id=group_id,
        )
        return {"count": len(targets)}

    @staticmethod
    def teacher_custom_notification(
        actor_id: str,
        classroom_id: str,
        title: str,
        body: str,
        student_ids: Optional[List[str]] = None,
        is_admin: bool = False,
    ):
        """Professor/admin envia notificação livre para alunos da turma."""
        classroom = ClassroomModel.get_by_id(classroom_id)
        if not classroom:
            return {"error": "Classroom not found"}, 404

        is_owner = str(classroom.get("teacher") or "") == str(actor_id)
        if not is_admin and not is_owner:
            return {"error": "Unauthorized"}, 403

        classroom_student_ids = NotificationService._classroom_student_ids(classroom)
        if student_ids is not None:
            requested = [str(sid) for sid in student_ids if str(sid or "").strip()]
            if not requested:
                return {"error": "student_ids is required"}, 400
            invalid = [sid for sid in requested if sid not in classroom_student_ids]
            if invalid:
                return {"error": "Some students are not in this classroom"}, 400
            target_ids = requested
        else:
            target_ids = classroom_student_ids

        for uid in target_ids:
            NotificationService._create_and_push(
                user_id=uid,
                notification_type=NotificationService.TYPE_TEACHER_CUSTOM,
                title=title,
                body=body,
                extra_data={"classroom_id": classroom_id, "from_teacher_id": actor_id},
            )

        return {"sent_to": len(target_ids)}, 200

    @staticmethod
    def admin_custom_notification(
        admin_id: str,
        title: str,
        body: str,
        user_ids: Optional[List[str]] = None,
        target_type: Optional[str] = None,
        roles: Optional[List[str]] = None,
        classroom_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ):
        """Admin envia notificação livre para um alvo (todos, usuários, papéis, turma ou grupo)."""
        target_users = NotificationService.resolve_admin_targets(
            target_type=target_type,
            user_ids=user_ids,
            roles=roles,
            classroom_id=classroom_id,
            group_id=group_id,
        )
        extra_data: Dict[str, Any] = {"from_admin_id": admin_id}
        resolved_type = (target_type or "").strip() or ("users" if user_ids else "all")
        extra_data["target_type"] = resolved_type
        if classroom_id:
            extra_data["classroom_id"] = classroom_id
        if group_id:
            extra_data["group_id"] = group_id

        for uid in target_users:
            NotificationService._create_and_push(
                user_id=uid,
                notification_type=NotificationService.TYPE_ADMIN_CUSTOM,
                title=title,
                body=body,
                extra_data=extra_data,
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

    @staticmethod
    def notify_affiliate_sale(user_id: str, title: str, body: str, extra_data: Optional[Dict[str, Any]] = None):
        """Notifica o afiliado sobre uma venda (app + e-mail conforme preferências)."""
        if not user_id:
            return
        NotificationService._create_and_push(
            user_id=str(user_id),
            notification_type=NotificationService.TYPE_AFFILIATE_SALE,
            title=title,
            body=body,
            extra_data=extra_data or {},
        )


