import os
import json
from flask import Flask, request, Response
from flask_swagger_ui import get_swaggerui_blueprint
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .database.mongo import mongo
from .provider.mail import mail
from .routes.routes import routes
from .config import Config
from .services.notification_service import NotificationService
from flask_cors import CORS


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # CORS explícito para Swagger e API (evita "Failed to fetch" no /doc)
    CORS(
        app,
        resources={r"/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], "allow_headers": ["*"], "expose_headers": ["*"]}},
        supports_credentials=False,
    )

    mongo.init_app(app)
    mail.init_app(app)

    with app.app_context():
        from .models.billing_indexes import ensure_billing_indexes
        from .models.support_ticket_model import SupportTicketModel
        ensure_billing_indexes()
        try:
            SupportTicketModel.ensure_indexes()
        except Exception:
            pass
        try:
            from .services.affiliate_service import AffiliateService
            AffiliateService.ensure_indexes()
        except Exception:
            pass
        try:
            from .models.course_model import CourseRatingModel
            CourseRatingModel.ensure_indexes()
        except Exception:
            pass
        try:
            from .models.lesson_deck_model import LessonDeckModel
            LessonDeckModel.ensure_indexes()
        except Exception:
            pass
        try:
            from .services.settings_service import SettingsService
            SettingsService.bootstrap()
        except Exception:
            pass
        try:
            from .models.tutorial_model import TutorialModel
            TutorialModel.ensure_indexes()
        except Exception:
            pass

    SWAGGER_URL = "/doc"
    # Usar rota da própria app para o spec (mesma origem, evita CORS no fetch do spec)
    API_URL = "/doc/swagger.json"

    # Rota que serve o swagger.json com host/scheme dinâmicos (evita erro de URL scheme)
    static_dir = os.path.join(os.path.dirname(__file__), "static")

    @app.route("/doc/swagger.json")
    def serve_swagger_spec():
        path = os.path.join(static_dir, "swagger.json")
        with open(path, "r", encoding="utf-8") as f:
            spec = json.load(f)
        # Garantir host e scheme válidos para "Try it out"
        try:
            base = request.host_url.rstrip("/")
            if base.startswith("http://") or base.startswith("https://"):
                spec["host"] = request.host
                spec["schemes"] = [base.split(":")[0]]
        except Exception:
            pass
        return Response(
            json.dumps(spec),
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    SWAGGERUI_BLUEPRINT = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_URL,
        config={
            "app_name": "API MemoBelc",
            "docExpansion": "list",
            "filter": "true",
            "tryItOutEnabled": "true",
            "displayRequestDuration": "true",
        },
    )

    app.register_blueprint(SWAGGERUI_BLUEPRINT, url_prefix=SWAGGER_URL)
    app.register_blueprint(routes)

    # Scheduler para envio de lembretes diários (9h da manhã, timezone do servidor)
    # IMPORTANTE: APScheduler deve rodar em APENAS 1 worker para evitar duplicação
    # Verifica se é o worker principal usando variáveis de ambiente do gunicorn
    is_scheduler_enabled = os.environ.get("ENABLE_DAILY_REMINDERS", "false").lower() == "true"
    is_main_worker = os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn") is False or \
                     os.environ.get("WERKZEUG_RUN_MAIN") == "true" or \
                     os.environ.get("GUNICORN_WORKER_ID") in (None, "1")
    
    if is_scheduler_enabled and is_main_worker:
        scheduler = BackgroundScheduler()
        scheduler.add_job(
            func=lambda: _run_daily_reminders(app),
            trigger=CronTrigger(hour=9, minute=0),
            id="daily_study_reminder",
        )
        from apscheduler.triggers.interval import IntervalTrigger
        scheduler.add_job(
            func=lambda: _run_billing_reconcile(app),
            trigger=IntervalTrigger(hours=6),
            id="billing_reconcile",
        )
        scheduler.start()
        app.logger.info("✅ APScheduler iniciado no worker principal")

    return app


def _run_daily_reminders(app):
    """Executa envio de lembretes diários dentro do contexto da app."""
    with app.app_context():
        NotificationService.send_daily_study_notifications()


def _run_billing_reconcile(app):
    with app.app_context():
        from .services.billing_service import BillingService
        BillingService.reconcile()
