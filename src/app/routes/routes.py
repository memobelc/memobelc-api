from flask import Blueprint
from src.app.controllers.auth_controller import auth_blueprint
from src.app.controllers.collections_controller import collection_blueprint
from src.app.controllers.decks_controller import decks_blueprint
from src.app.controllers.card_controller import card_blueprint
from src.app.controllers.user_progress_controller import user_progress_blueprint
from src.app.controllers.videos_controller import video_blueprint
from src.app.controllers.chat_controller import chat_blueprint
from src.app.controllers.classroom_controller import classroom_blueprint
from src.app.controllers.notification_controller import notification_blueprint
from src.app.controllers.user_streak_controller import user_streak_blueprint
from src.app.controllers.books_controller import books_blueprint
from src.app.controllers.invite_controller import invite_blueprint
from src.app.controllers.course_controller import course_blueprint
from src.app.controllers.admin_controller import admin_blueprint
from src.app.controllers.plan_controller import plan_blueprint
from src.app.controllers.coupon_controller import coupon_blueprint
from src.app.controllers.billing_controller import billing_blueprint
from src.app.controllers.bundle_controller import bundle_blueprint
from src.app.controllers.admin_billing_controller import entitlement_blueprint, admin_billing_blueprint
from src.app.controllers.support_controller import support_blueprint, admin_support_blueprint
from src.app.controllers.profile_controller import profile_blueprint, mission_blueprint
from src.app.controllers.affiliate_controller import affiliate_blueprint
from src.app.controllers.admin_affiliate_controller import admin_affiliate_blueprint


routes = Blueprint("main", __name__)


routes.register_blueprint(auth_blueprint, url_prefix="/auth")
routes.register_blueprint(collection_blueprint, url_prefix="/collections")
routes.register_blueprint(decks_blueprint, url_prefix="/deck")
routes.register_blueprint(card_blueprint, url_prefix="/card")
routes.register_blueprint(video_blueprint, url_prefix="/video")
routes.register_blueprint(user_progress_blueprint, url_prefix="/progress")
routes.register_blueprint(chat_blueprint, url_prefix="/chat")
routes.register_blueprint(classroom_blueprint, url_prefix="/classroom")
routes.register_blueprint(notification_blueprint, url_prefix="/notifications")
routes.register_blueprint(user_streak_blueprint, url_prefix="/streak")
routes.register_blueprint(books_blueprint, url_prefix="/books")
routes.register_blueprint(invite_blueprint, url_prefix="/invite")
routes.register_blueprint(course_blueprint, url_prefix="/course")
routes.register_blueprint(admin_blueprint, url_prefix="/admin")
routes.register_blueprint(plan_blueprint, url_prefix="/plans")
routes.register_blueprint(coupon_blueprint, url_prefix="/coupons")
routes.register_blueprint(billing_blueprint, url_prefix="/billing")
routes.register_blueprint(bundle_blueprint, url_prefix="/bundles")
routes.register_blueprint(entitlement_blueprint, url_prefix="/entitlements")
routes.register_blueprint(admin_billing_blueprint, url_prefix="/admin/billing")
routes.register_blueprint(support_blueprint, url_prefix="/support")
routes.register_blueprint(admin_support_blueprint, url_prefix="/admin/support")
routes.register_blueprint(profile_blueprint, url_prefix="/profile")
routes.register_blueprint(mission_blueprint, url_prefix="/missions")
routes.register_blueprint(affiliate_blueprint, url_prefix="/affiliate")
routes.register_blueprint(admin_affiliate_blueprint, url_prefix="/admin/affiliates")
