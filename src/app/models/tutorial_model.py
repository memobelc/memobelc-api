"""Tutorial catalog, user progress, analytics events and Brain avatars."""

import copy
import uuid

from src.app import mongo
from src.app.utils.billing_utils import serialize_doc, to_object_id, utcnow


LOCALES = ("en", "pt_br", "es", "de", "zh")
STATUSES = ("draft", "active", "inactive", "archived")
AUDIENCE_TYPES = ("all", "new_users", "premium", "free", "specific_users", "roles")
SECTIONS = ("home", "books", "videos", "collections", "talk_to_me", "classrooms", "courses", "plans")
INTERACTIONS = ("next", "tap")
TARGET_KEYS = (
    "",
    "menu",
    "notifications",
    "profile",
    "home_dashboard",
    "study_streak",
    "create_collection",
    "settings",
    "subscription",
    "menu_home",
    "menu_videos",
    "menu_books",
    "menu_collections",
    "menu_talk_to_me",
    "menu_classrooms",
    "menu_courses",
    "menu_plans",
    "menu_affiliate",
    "profile_me",
    "profile_subscription",
    "profile_settings",
    "profile_invite",
    "profile_affiliate",
    "books_list",
    "chat_composer",
    "chat_explore",
    "videos_list",
    "collections_list",
    "classrooms_list",
    "courses_list",
    "plans_list",
)
PLACEMENTS = ("bottom", "top", "left", "right", "center")
BRAIN_EXPRESSIONS = (
    "happy",
    "excited",
    "explaining",
    "thinking",
    "celebrating",
    "proud",
    "motivating",
    "curious",
    "tip",
    "studying",
    "pointing",
    "news",
    "worried",
    "sad",
    "confused",
    "surprised",
    "sleeping",
    "achievement",
    "premium",
    "teacher",
    "mentor",
)
EVENT_TYPES = ("view", "step_view", "next", "back", "skip", "complete", "replay")
BRAIN_EVENTS = ("tutorial", "empty", "error", "achievement", "premium", "streak", "news")


def i18n(en, pt_br=None, es=None, de=None, zh=None):
    return {
        "en": en,
        "pt_br": pt_br or en,
        "es": es or en,
        "de": de or en,
        "zh": zh or en,
    }


def normalize_i18n(value, fallback=""):
    if isinstance(value, dict):
        out = {}
        for locale in LOCALES:
            text = value.get(locale)
            out[locale] = str(text).strip() if text else str(value.get("en") or fallback)
        for key, text in value.items():
            if key not in out and text is not None:
                out[key] = str(text)
        return out
    if isinstance(value, str) and value.strip():
        text = value.strip()
        return {locale: text for locale in LOCALES}
    return {locale: fallback for locale in LOCALES}


def resolve_i18n(value, locale="en"):
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    preferred = locale or "en"
    return (
        value.get(preferred)
        or value.get("en")
        or value.get("pt_br")
        or next((item for item in value.values() if item), "")
    )


def normalize_audience(data):
    payload = data or {}
    audience_type = payload.get("type") if payload.get("type") in AUDIENCE_TYPES else "all"
    user_ids = [str(item) for item in (payload.get("user_ids") or []) if item]
    roles = [str(item) for item in (payload.get("roles") or []) if item]
    try:
        new_user_days = max(int(payload.get("new_user_days") or 14), 1)
    except (TypeError, ValueError):
        new_user_days = 14
    return {
        "type": audience_type,
        "user_ids": user_ids,
        "roles": roles,
        "new_user_days": new_user_days,
    }


def normalize_highlight_rect(data):
    payload = data or {}
    try:
        x = float(payload.get("x"))
        y = float(payload.get("y"))
        width = float(payload.get("width"))
        height = float(payload.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    x = min(max(x, 0.0), 1.0)
    y = min(max(y, 0.0), 1.0)
    width = min(max(width, 0.0), 1.0 - x)
    height = min(max(height, 0.0), 1.0 - y)
    if width < 0.01 or height < 0.01:
        return None
    return {
        "x": round(x, 4),
        "y": round(y, 4),
        "width": round(width, 4),
        "height": round(height, 4),
    }


def normalize_section(value):
    section = str(value or "home").strip()
    return section if section in SECTIONS else "home"


def normalize_step(data, order=1):
    payload = data or {}
    step_id = str(payload.get("id") or "").strip() or uuid.uuid4().hex[:12]
    target = str(payload.get("target_key") or "").strip()
    if target not in TARGET_KEYS:
        target = ""
    placement = payload.get("tooltip_placement") if payload.get("tooltip_placement") in PLACEMENTS else "bottom"
    expression = payload.get("brain_expression") if payload.get("brain_expression") in BRAIN_EXPRESSIONS else "explaining"
    interaction = payload.get("interaction") if payload.get("interaction") in INTERACTIONS else "next"
    try:
        step_order = int(payload.get("order") if payload.get("order") is not None else order)
    except (TypeError, ValueError):
        step_order = order
    return {
        "id": step_id,
        "order": step_order,
        "title": normalize_i18n(payload.get("title")),
        "body": normalize_i18n(payload.get("body")),
        "tip": normalize_i18n(payload.get("tip")),
        "icon": str(payload.get("icon") or "school").strip() or "school",
        "brain_expression": expression,
        "target_key": target or None,
        "highlight_rect": normalize_highlight_rect(payload.get("highlight_rect")),
        "tooltip_placement": placement,
        "image_url": (str(payload.get("image_url") or "").strip() or None),
        "video_url": (str(payload.get("video_url") or "").strip() or None),
        "required_highlight": bool(payload.get("required_highlight", True)),
        "interaction": interaction,
        "tap_label": normalize_i18n(payload.get("tap_label")),
    }


def localize_tutorial(doc, locale="en"):
    if not doc:
        return None
    item = dict(doc)
    item["name"] = resolve_i18n(doc.get("name"), locale)
    item["description"] = resolve_i18n(doc.get("description"), locale)
    item["name_i18n"] = normalize_i18n(doc.get("name"))
    item["description_i18n"] = normalize_i18n(doc.get("description"))
    steps = []
    for step in sorted(doc.get("steps") or [], key=lambda row: row.get("order") or 0):
        localized = dict(step)
        localized["title"] = resolve_i18n(step.get("title"), locale)
        localized["body"] = resolve_i18n(step.get("body"), locale)
        localized["tip"] = resolve_i18n(step.get("tip"), locale)
        localized["tap_label"] = resolve_i18n(step.get("tap_label"), locale)
        localized["title_i18n"] = normalize_i18n(step.get("title"))
        localized["body_i18n"] = normalize_i18n(step.get("body"))
        localized["tip_i18n"] = normalize_i18n(step.get("tip"))
        localized["tap_label_i18n"] = normalize_i18n(step.get("tap_label"))
        steps.append(localized)
    item["steps"] = steps
    return item


class TutorialModel:
    @staticmethod
    def ensure_indexes():
        mongo.db.tutorials.create_index([("key", 1), ("version", 1)], unique=True)
        mongo.db.tutorials.create_index([("key", 1), ("status", 1)])
        mongo.db.tutorials.create_index("status")
        mongo.db.tutorials.create_index("section")
        mongo.db.user_tutorial_progress.create_index(
            [("user_id", 1), ("tutorial_id", 1)], unique=True
        )
        mongo.db.user_tutorial_progress.create_index([("user_id", 1), ("tutorial_key", 1)])
        mongo.db.tutorial_events.create_index([("tutorial_id", 1), ("type", 1)])
        mongo.db.tutorial_events.create_index([("user_id", 1), ("created_at", -1)])
        mongo.db.brain_avatars.create_index("key", unique=True)
        TutorialModel.seed_defaults()
        BrainAvatarModel.seed_defaults()

    @staticmethod
    def create(data, as_draft=True):
        key = str(data.get("key") or "").strip() or "onboarding"
        now = utcnow()
        version = data.get("version")
        if version is None:
            latest = mongo.db.tutorials.find_one({"key": key}, sort=[("version", -1)])
            version = int((latest or {}).get("version") or 0) + 1
        status = data.get("status") if data.get("status") in STATUSES else ("draft" if as_draft else "active")
        steps = [
            normalize_step(step, order=index + 1)
            for index, step in enumerate(data.get("steps") or [])
        ]
        doc = {
            "key": key,
            "version": int(version),
            "status": status,
            "name": normalize_i18n(data.get("name"), fallback=key),
            "description": normalize_i18n(data.get("description")),
            "audience": normalize_audience(data.get("audience")),
            "section": normalize_section(data.get("section")),
            "steps": steps,
            "created_at": now,
            "updated_at": now,
            "published_at": now if status == "active" else None,
        }
        result = mongo.db.tutorials.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(tutorial_id, data):
        existing = TutorialModel.get_by_id(tutorial_id, raw=True)
        if not existing:
            return None
        if existing.get("status") == "archived":
            raise ValueError("Archived tutorials cannot be edited")
        updates = {"updated_at": utcnow()}
        if "key" in data and existing.get("status") == "draft":
            key = str(data.get("key") or "").strip()
            if key:
                updates["key"] = key
        if "name" in data:
            updates["name"] = normalize_i18n(data.get("name"), fallback=existing.get("key"))
        if "description" in data:
            updates["description"] = normalize_i18n(data.get("description"))
        if "audience" in data:
            updates["audience"] = normalize_audience(data.get("audience"))
        if "section" in data:
            updates["section"] = normalize_section(data.get("section"))
        if "steps" in data:
            updates["steps"] = [
                normalize_step(step, order=index + 1)
                for index, step in enumerate(data.get("steps") or [])
            ]
        if "status" in data and data.get("status") in ("draft", "inactive") and existing.get("status") != "archived":
            updates["status"] = data.get("status")
        mongo.db.tutorials.update_one({"_id": to_object_id(tutorial_id)}, {"$set": updates})
        return TutorialModel.get_by_id(tutorial_id)

    @staticmethod
    def get_by_id(tutorial_id, raw=False):
        try:
            oid = to_object_id(tutorial_id)
        except Exception:
            return None
        doc = mongo.db.tutorials.find_one({"_id": oid})
        if raw:
            return doc
        return serialize_doc(doc)

    @staticmethod
    def list_tutorials(status=None, key=None):
        query = {}
        if status:
            query["status"] = status
        if key:
            query["key"] = key
        docs = list(mongo.db.tutorials.find(query).sort([("key", 1), ("version", -1)]))
        return [serialize_doc(doc) for doc in docs]

    @staticmethod
    def list_active():
        docs = list(mongo.db.tutorials.find({"status": "active"}).sort("published_at", 1))
        return [serialize_doc(doc) for doc in docs]

    @staticmethod
    def publish(tutorial_id):
        existing = TutorialModel.get_by_id(tutorial_id, raw=True)
        if not existing:
            return None
        if not (existing.get("steps") or []):
            raise ValueError("A tutorial needs at least one step to be published")
        now = utcnow()
        mongo.db.tutorials.update_many(
            {
                "key": existing["key"],
                "status": "active",
                "_id": {"$ne": existing["_id"]},
            },
            {"$set": {"status": "archived", "updated_at": now}},
        )
        mongo.db.tutorials.update_one(
            {"_id": existing["_id"]},
            {"$set": {"status": "active", "published_at": now, "updated_at": now}},
        )
        return TutorialModel.get_by_id(tutorial_id)

    @staticmethod
    def deactivate(tutorial_id):
        existing = TutorialModel.get_by_id(tutorial_id, raw=True)
        if not existing:
            return None
        if existing.get("status") == "archived":
            raise ValueError("Archived tutorials cannot be deactivated")
        if existing.get("status") == "inactive":
            return serialize_doc(existing)
        now = utcnow()
        mongo.db.tutorials.update_one(
            {"_id": existing["_id"]},
            {"$set": {"status": "inactive", "updated_at": now}},
        )
        return TutorialModel.get_by_id(tutorial_id)

    @staticmethod
    def duplicate(tutorial_id, new_version=False):
        existing = TutorialModel.get_by_id(tutorial_id, raw=True)
        if not existing:
            return None
        payload = copy.deepcopy(existing)
        payload.pop("_id", None)
        payload["status"] = "draft"
        payload["published_at"] = None
        if new_version:
            latest = mongo.db.tutorials.find_one(
                {"key": existing["key"]}, sort=[("version", -1)]
            )
            payload["version"] = int((latest or {}).get("version") or existing.get("version") or 1) + 1
        else:
            payload["key"] = f"{existing.get('key')}-copy"
            payload["version"] = 1
            payload["name"] = normalize_i18n(
                {
                    locale: f"{resolve_i18n(existing.get('name'), locale)} (copy)"
                    for locale in LOCALES
                }
            )
        return TutorialModel.create(payload, as_draft=True)

    @staticmethod
    def seed_defaults():
        if mongo.db.tutorials.count_documents({"key": "onboarding"}) > 0:
            return
        TutorialModel.create(
            {
                "key": "onboarding",
                "version": 1,
                "status": "active",
                "name": i18n(
                    "Welcome to Memobelc",
                    "Bem-vindo ao Memobelc",
                    "Bienvenido a Memobelc",
                    "Willkommen bei Memobelc",
                    "欢迎来到 Memobelc",
                ),
                "description": i18n(
                    "A short tour of the main features.",
                    "Um passeio rápido pelas principais funcionalidades.",
                    "Un recorrido rápido por las funciones principales.",
                    "Eine kurze Tour durch die wichtigsten Funktionen.",
                    "快速了解核心功能。",
                ),
                "audience": {"type": "all"},
                "section": "home",
                "steps": _default_onboarding_steps(),
            },
            as_draft=False,
        )


def _default_onboarding_steps():
    return [
        {
            "id": "welcome",
            "order": 1,
            "icon": "waving-hand",
            "brain_expression": "happy",
            "target_key": "",
            "tooltip_placement": "center",
            "title": i18n(
                "Welcome to Memobelc!",
                "Bem-vindo ao Memobelc!",
                "¡Bienvenido a Memobelc!",
                "Willkommen bei Memobelc!",
                "欢迎来到 Memobelc！",
            ),
            "body": i18n(
                "Hi! I am Brain. Let's take a quick tour so you can get the most out of the platform. It takes less than 2 minutes.",
                "Olá! Eu sou o Brain. Vamos fazer um rápido passeio para mostrar como aproveitar ao máximo a plataforma. Levará menos de 2 minutos.",
                "¡Hola! Soy Brain. Hagamos un recorrido rápido para que aproveches al máximo la plataforma. Tardará menos de 2 minutos.",
                "Hallo! Ich bin Brain. Lass uns eine kurze Tour machen, damit du die Plattform voll nutzen kannst. Es dauert weniger als 2 Minuten.",
                "你好！我是 Brain。我们来快速逛一逛，让你充分利用平台，不到两分钟。",
            ),
            "tip": i18n("You can skip anytime and replay later in Settings."),
        },
        {
            "id": "menu",
            "order": 2,
            "icon": "menu",
            "brain_expression": "pointing",
            "target_key": "menu",
            "interaction": "tap",
            "tap_label": i18n(
                "Tap here to open decks, classrooms, books, videos and more.",
                "Toque aqui para abrir decks, turmas, livros, vídeos e muito mais.",
                "Toca aquí para abrir mazos, clases, libros, vídeos y más.",
                "Tippe hier, um Decks, Klassen, Bücher, Videos und mehr zu öffnen.",
                "点这里打开卡组、课堂、书籍、视频等。",
            ),
            "tooltip_placement": "bottom",
            "title": i18n("Your main menu", "Seu menu principal", "Tu menú principal", "Dein Hauptmenü", "主菜单"),
            "body": i18n(
                "Tap here to open decks, classrooms, books, videos and more. Everything important lives in this menu.",
                "Toque aqui para abrir decks, turmas, livros, vídeos e muito mais. Tudo o que importa mora neste menu.",
                "Toca aquí para abrir mazos, clases, libros, vídeos y más. Todo lo importante está en este menú.",
                "Tippe hier, um Decks, Klassen, Bücher, Videos und mehr zu öffnen. Alles Wichtige liegt in diesem Menü.",
                "点这里打开卡组、课堂、书籍、视频等。重要功能都在这个菜单里。",
            ),
        },
        {
            "id": "notifications",
            "order": 3,
            "icon": "notifications",
            "brain_expression": "curious",
            "target_key": "notifications",
            "tooltip_placement": "bottom",
            "title": i18n("Stay in the loop", "Fique por dentro", "Mantente al día", "Bleib auf dem Laufenden", "及时收到消息"),
            "body": i18n(
                "The bell keeps study reminders, classroom news and messages from teachers in one place.",
                "O sino reúne lembretes de estudo, novidades da turma e recados dos professores.",
                "La campana reúne recordatorios de estudio, novedades de clase y mensajes de tus profesores.",
                "Die Glocke sammelt Lernerinnerungen, Klassen-News und Nachrichten deiner Lehrer.",
                "铃铛会汇总学习提醒、课堂动态和老师消息。",
            ),
        },
        {
            "id": "profile",
            "order": 4,
            "icon": "person",
            "brain_expression": "explaining",
            "target_key": "profile",
            "tooltip_placement": "bottom",
            "title": i18n("Your profile", "Seu perfil", "Tu perfil", "Dein Profil", "你的个人资料"),
            "body": i18n(
                "Open your avatar for language, settings, subscription and a quick way to invite friends.",
                "Abra o avatar para idioma, configurações, assinatura e um jeito rápido de convidar amigos.",
                "Abre tu avatar para idioma, ajustes, suscripción y una forma rápida de invitar amigos.",
                "Öffne deinen Avatar für Sprache, Einstellungen, Abo und schnelle Freundes-Einladungen.",
                "点头像可切换语言、设置、订阅，还能邀请朋友。",
            ),
        },
        {
            "id": "home",
            "order": 5,
            "icon": "home",
            "brain_expression": "motivating",
            "target_key": "home_dashboard",
            "tooltip_placement": "bottom",
            "title": i18n("Your home dashboard", "Seu painel inicial", "Tu panel de inicio", "Dein Start-Dashboard", "首页仪表盘"),
            "body": i18n(
                "This is home base: your collections, what is due today, and a friendly nudge to keep going.",
                "Esta é a base: suas coleções, o que está para revisar hoje e um empurrãozinho amigável para continuar.",
                "Esta es tu base: tus colecciones, lo que toca hoy y un empujoncito amable para seguir.",
                "Das ist deine Basis: Sammlungen, was heute fällig ist, und ein freundlicher Anstoß weiterzumachen.",
                "这里是大本营：你的卡组、今天该复习的内容，还有继续学下去的小鼓励。",
            ),
        },
        {
            "id": "streak",
            "order": 6,
            "icon": "local-fire-department",
            "brain_expression": "celebrating",
            "target_key": "study_streak",
            "tooltip_placement": "top",
            "title": i18n("Spaced reviews and streaks", "Revisões espaçadas e sequência", "Repasos espaciados y racha", "Verteilte Wiederholung und Serie", "间隔复习与连续打卡"),
            "body": i18n(
                "Memobelc brings cards back at the right time. Keep a daily streak and memories stick for longer.",
                "O Memobelc traz as cartas de volta na hora certa. Mantenha a sequência diária e as memórias duram mais.",
                "Memobelc trae las cartas en el momento justo. Mantén tu racha diaria y los recuerdos duran más.",
                "Memobelc holt Karten zur richtigen Zeit zurück. Halte die Tages-Serie und Erinnerungen bleiben länger.",
                "Memobelc 会在合适的时间把卡片带回来。保持每日连续，记忆更牢。",
            ),
            "tip": i18n("A few minutes a day beats a long cram session."),
        },
        {
            "id": "create",
            "order": 7,
            "icon": "add-circle",
            "brain_expression": "excited",
            "target_key": "create_collection",
            "tooltip_placement": "left",
            "title": i18n("Create memories", "Crie memórias", "Crea recuerdos", "Erinnerungen erstellen", "创建记忆"),
            "body": i18n(
                "Tap plus to start a collection, add decks and cards, and turn anything you want to remember into a study set.",
                "Toque no plus para criar uma coleção, adicionar decks e cartas, e transformar o que quiser lembrar em um conjunto de estudo.",
                "Toca el plus para crear una colección, añadir mazos y cartas, y convertir lo que quieras recordar en un set de estudio.",
                "Tippe auf Plus, um eine Sammlung zu starten, Decks und Karten hinzuzufügen und alles Lernenswerte in ein Set zu verwandeln.",
                "点加号即可创建合集、添加卡组和卡片，把想记住的内容变成学习集。",
            ),
        },
        {
            "id": "study",
            "order": 8,
            "icon": "school",
            "brain_expression": "studying",
            "target_key": "",
            "tooltip_placement": "center",
            "title": i18n("Your study area", "Sua área de estudos", "Tu zona de estudio", "Dein Lernbereich", "学习区"),
            "body": i18n(
                "Open a collection to review due cards. Rate how easy each one felt — that is how spaced repetition learns with you.",
                "Abra uma coleção para revisar as cartas do dia. Diga o quão fácil cada uma foi — é assim que a repetição espaçada aprende com você.",
                "Abre una colección para repasar las cartas del día. Di lo fácil que te resultó cada una: así aprende la repetición espaciada.",
                "Öffne eine Sammlung, um fällige Karten zu üben. Sag, wie leicht sie war — so lernt die Wiederholung mit dir.",
                "打开合集复习到期卡片，并给难度打分——间隔重复会据此陪伴你学习。",
            ),
        },
        {
            "id": "settings",
            "order": 9,
            "icon": "settings",
            "brain_expression": "tip",
            "target_key": "settings",
            "tooltip_placement": "center",
            "title": i18n("Settings and help", "Configurações e ajuda", "Ajustes y ayuda", "Einstellungen und Hilfe", "设置与帮助"),
            "body": i18n(
                "In Settings you choose notifications, replay this tour, and check what is new on the platform.",
                "Em Configurações você escolhe notificações, revisita este passeio e vê as novidades da plataforma.",
                "En Ajustes eliges notificaciones, vuelves a ver este recorrido y consultas las novedades.",
                "Unter Einstellungen wählst du Benachrichtigungen, startest die Tour neu und siehst Neuigkeiten.",
                "在设置里可以管理通知、重看本教程，并查看平台新功能。",
            ),
        },
        {
            "id": "premium",
            "order": 10,
            "icon": "workspace-premium",
            "brain_expression": "premium",
            "target_key": "subscription",
            "tooltip_placement": "center",
            "title": i18n("Plans and premium", "Planos e premium", "Planes y premium", "Tarife und Premium", "套餐与高级版"),
            "body": i18n(
                "When you are ready, plans unlock extra content and premium tools. Explore at your pace — Brain will be here.",
                "Quando quiser, os planos liberam conteúdo extra e ferramentas premium. Explore no seu ritmo — o Brain fica por aqui.",
                "Cuando quieras, los planes abren contenido extra y herramientas premium. Explora a tu ritmo: Brain estará aquí.",
                "Wenn du soweit bist, schalten Tarife Extra-Inhalte und Premium-Tools frei. In deinem Tempo — Brain bleibt da.",
                "准备好后，套餐会解锁更多内容和高级工具。按自己的节奏来——Brain 一直在。",
            ),
        },
    ]


class UserTutorialProgressModel:
    @staticmethod
    def get(user_id, tutorial_id):
        doc = mongo.db.user_tutorial_progress.find_one(
            {"user_id": str(user_id), "tutorial_id": str(tutorial_id)}
        )
        return serialize_doc(doc)

    @staticmethod
    def list_for_user(user_id):
        docs = list(
            mongo.db.user_tutorial_progress.find({"user_id": str(user_id)}).sort(
                "last_viewed_at", -1
            )
        )
        return [serialize_doc(doc) for doc in docs]

    @staticmethod
    def upsert(user_id, tutorial, patch):
        now = utcnow()
        tutorial_id = str(tutorial["_id"])
        existing = mongo.db.user_tutorial_progress.find_one(
            {"user_id": str(user_id), "tutorial_id": tutorial_id}
        )
        base = {
            "user_id": str(user_id),
            "tutorial_id": tutorial_id,
            "tutorial_key": tutorial.get("key"),
            "version": tutorial.get("version"),
            "viewed": True,
            "completed": False,
            "skipped": False,
            "current_step": 0,
            "started_at": (existing or {}).get("started_at") or now,
            "last_viewed_at": now,
            "completed_at": (existing or {}).get("completed_at"),
            "skipped_at": (existing or {}).get("skipped_at"),
            "time_spent_ms": int((existing or {}).get("time_spent_ms") or 0),
            "updated_at": now,
        }
        if not existing:
            base["created_at"] = now
        base.update(patch or {})
        mongo.db.user_tutorial_progress.update_one(
            {"user_id": str(user_id), "tutorial_id": tutorial_id},
            {"$set": base},
            upsert=True,
        )
        return UserTutorialProgressModel.get(user_id, tutorial_id)

    @staticmethod
    def add_time(user_id, tutorial_id, duration_ms):
        try:
            extra = max(int(duration_ms or 0), 0)
        except (TypeError, ValueError):
            extra = 0
        if extra <= 0:
            return
        mongo.db.user_tutorial_progress.update_one(
            {"user_id": str(user_id), "tutorial_id": str(tutorial_id)},
            {"$inc": {"time_spent_ms": extra}, "$set": {"last_viewed_at": utcnow()}},
        )


class TutorialEventModel:
    @staticmethod
    def record(user_id, tutorial, event_type, step_index=None, duration_ms=None):
        if event_type not in EVENT_TYPES:
            raise ValueError("Invalid event type")
        doc = {
            "user_id": str(user_id),
            "tutorial_id": str(tutorial["_id"]),
            "tutorial_key": tutorial.get("key"),
            "version": tutorial.get("version"),
            "type": event_type,
            "step_index": step_index,
            "duration_ms": duration_ms,
            "created_at": utcnow(),
        }
        result = mongo.db.tutorial_events.insert_one(doc)
        doc["_id"] = result.inserted_id
        if duration_ms:
            UserTutorialProgressModel.add_time(user_id, tutorial["_id"], duration_ms)
        return serialize_doc(doc)


class BrainAvatarModel:
    @staticmethod
    def seed_defaults():
        builtins = [
            {"key": "happy", "name": "Brain feliz", "builtin_asset": "1.png", "events": ["tutorial"]},
            {"key": "excited", "name": "Brain animado", "builtin_asset": "brain.gif", "events": ["tutorial", "achievement"]},
            {"key": "explaining", "name": "Brain explicando", "builtin_asset": "1.png", "events": ["tutorial"]},
            {"key": "thinking", "name": "Brain pensando", "builtin_asset": "1.png", "events": ["tutorial"]},
            {"key": "celebrating", "name": "Brain comemorando", "builtin_asset": "brain.gif", "events": ["achievement", "streak"]},
            {"key": "proud", "name": "Brain orgulhoso", "builtin_asset": "1.png", "events": ["achievement"]},
            {"key": "motivating", "name": "Brain motivando", "builtin_asset": "1.png", "events": ["tutorial", "streak"]},
            {"key": "curious", "name": "Brain curioso", "builtin_asset": "1.png", "events": ["tutorial", "news"]},
            {"key": "tip", "name": "Brain dando dica", "builtin_asset": "1.png", "events": ["tutorial"]},
            {"key": "studying", "name": "Brain estudando", "builtin_asset": "1.png", "events": ["tutorial"]},
            {"key": "pointing", "name": "Brain apontando", "builtin_asset": "1.png", "events": ["tutorial"]},
            {"key": "news", "name": "Brain novidades", "builtin_asset": "brain.gif", "events": ["news"]},
            {"key": "worried", "name": "Brain preocupado", "builtin_asset": "shame.png", "events": ["error"]},
            {"key": "sad", "name": "Brain triste", "builtin_asset": "empty.png", "events": ["empty"]},
            {"key": "confused", "name": "Brain confuso", "builtin_asset": "shame.png", "events": ["error", "empty"]},
            {"key": "surprised", "name": "Brain surpreso", "builtin_asset": "brain.gif", "events": ["news"]},
            {"key": "sleeping", "name": "Brain dormindo", "builtin_asset": "empty.png", "events": ["empty"]},
            {"key": "achievement", "name": "Brain conquista", "builtin_asset": "brain.gif", "events": ["achievement"]},
            {"key": "premium", "name": "Brain premium", "builtin_asset": "1.png", "events": ["premium"]},
            {"key": "teacher", "name": "Brain professor", "builtin_asset": "1.png", "events": ["tutorial"]},
            {"key": "mentor", "name": "Brain mentor", "builtin_asset": "1.png", "events": ["tutorial"]},
        ]
        now = utcnow()
        for item in builtins:
            mongo.db.brain_avatars.update_one(
                {"key": item["key"]},
                {
                    "$setOnInsert": {
                        **item,
                        "image": None,
                        "image_dark": None,
                        "is_active": True,
                        "created_at": now,
                        "updated_at": now,
                    }
                },
                upsert=True,
            )

    @staticmethod
    def list_avatars(active_only=False):
        query = {"is_active": True} if active_only else {}
        docs = list(mongo.db.brain_avatars.find(query).sort("key", 1))
        return [serialize_doc(doc) for doc in docs]

    @staticmethod
    def get_by_id(avatar_id):
        try:
            oid = to_object_id(avatar_id)
        except Exception:
            return None
        return serialize_doc(mongo.db.brain_avatars.find_one({"_id": oid}))

    @staticmethod
    def get_by_key(key):
        return serialize_doc(mongo.db.brain_avatars.find_one({"key": str(key)}))

    @staticmethod
    def create(data):
        key = str(data.get("key") or "").strip()
        if not key:
            raise ValueError("Avatar key is required")
        if BrainAvatarModel.get_by_key(key):
            raise ValueError("Avatar key already exists")
        now = utcnow()
        events = [item for item in (data.get("events") or []) if item in BRAIN_EVENTS]
        doc = {
            "key": key,
            "name": str(data.get("name") or key).strip(),
            "image": (str(data.get("image") or "").strip() or None),
            "image_dark": (str(data.get("image_dark") or "").strip() or None),
            "builtin_asset": (str(data.get("builtin_asset") or "").strip() or None),
            "events": events,
            "is_active": bool(data.get("is_active", True)),
            "created_at": now,
            "updated_at": now,
        }
        result = mongo.db.brain_avatars.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize_doc(doc)

    @staticmethod
    def update(avatar_id, data):
        existing = BrainAvatarModel.get_by_id(avatar_id)
        if not existing:
            return None
        updates = {"updated_at": utcnow()}
        if "name" in data:
            updates["name"] = str(data.get("name") or existing["key"]).strip()
        if "image" in data:
            updates["image"] = (str(data.get("image") or "").strip() or None)
        if "image_dark" in data:
            updates["image_dark"] = (str(data.get("image_dark") or "").strip() or None)
        if "builtin_asset" in data:
            updates["builtin_asset"] = (str(data.get("builtin_asset") or "").strip() or None)
        if "events" in data:
            updates["events"] = [item for item in (data.get("events") or []) if item in BRAIN_EVENTS]
        if "is_active" in data:
            updates["is_active"] = bool(data.get("is_active"))
        mongo.db.brain_avatars.update_one({"_id": to_object_id(avatar_id)}, {"$set": updates})
        return BrainAvatarModel.get_by_id(avatar_id)
