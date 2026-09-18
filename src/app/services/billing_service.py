"""Checkout, webhooks, subscription lifecycle and admin billing operations."""

from datetime import datetime, timezone, timedelta

from flask import current_app
from flask_mail import Message
from werkzeug.security import generate_password_hash
from src.app import mail
from src.app.config import Config
from src.app.models.billing_support_model import AuditLogModel, ExternalSaleModel, WebhookEventModel
from src.app.models.book_bundle_model import BookBundleModel
from src.app.models.book_model import BookModel
from src.app.models.classroom_model import ClassroomModel
from src.app.models.coupon_model import CouponModel
from src.app.models.course_model import CourseModel
from src.app.models.entitlement_model import EntitlementModel
from src.app.models.payment_model import PaymentModel
from src.app.models.plan_model import PlanModel
from src.app.models.subscription_model import SubscriptionModel
from src.app.models.user_model import UserModel
from src.app.provider.asaas import Asaas, AsaasError
from src.app.provider.google_play import GooglePlay, GooglePlayError
from src.app.services.admin_billing_query import failure_updates_from_payload
from src.app.services.coupon_service import CouponService
from src.app.services.entitlement_service import EntitlementService
from src.app.services.affiliate_service import AffiliateService
from src.app.services.settings_service import SettingsService
from src.app.utils.billing_utils import (
    ACCESS_STATUSES,
    ASAAS_PAID_STATUSES,
    NATIVE_BILLING_TYPES,
    asaas_discount_payload,
    compute_grace_until,
    cycle_timedelta,
    invoice_description,
    parse_datetime,
    product_snapshot,
    utcnow,
)


ACTIVE_BLOCKING_STATUSES = list(ACCESS_STATUSES) + ["pending", "overdue", "suspended"]


def _digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _normalize_cpf_cnpj(value):
    digits = _digits_only(value)
    if len(digits) in (11, 14):
        return digits
    return None


def _asaas_error_message(exc):
    payload = exc.payload if isinstance(getattr(exc, "payload", None), dict) else {}
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict) and first.get("description"):
            return first["description"]
    return str(exc)


def _normalize_billing_type(value):
    billing_type = str(value or "").strip().upper().replace("-", "_")
    if billing_type in ("CREDITCARD", "CARD"):
        return "CREDIT_CARD"
    return billing_type


def _client_ip_from_data(data):
    ip = str((data or {}).get("_remote_ip") or (data or {}).get("remote_ip") or "").split(",")[0].strip()
    return ip or "127.0.0.1"


def _asaas_is_paid(status):
    return str(status or "").upper() in ASAAS_PAID_STATUSES or str(status or "").upper() == "ACTIVE"


def _serialize_pix(pix):
    if not pix:
        return None
    encoded = pix.get("encodedImage") or pix.get("encoded_image")
    payload = pix.get("payload")
    expiration = pix.get("expirationDate") or pix.get("expiration_date")
    if not encoded and not payload:
        return None
    return {
        "encoded_image": encoded,
        "payload": payload,
        "expiration_date": expiration,
    }


def _extract_credit_card(data):
    card = data.get("credit_card") if isinstance((data or {}).get("credit_card"), dict) else {}
    number = _digits_only(card.get("number") or data.get("card_number"))
    holder = str(card.get("holder_name") or data.get("holder_name") or "").strip()
    month = _digits_only(card.get("expiry_month") or data.get("expiry_month"))
    year = _digits_only(card.get("expiry_year") or data.get("expiry_year"))
    ccv = _digits_only(card.get("ccv") or card.get("cvv") or data.get("ccv") or data.get("cvv"))
    postal = _digits_only(card.get("postal_code") or data.get("postal_code"))
    address_number = str(card.get("address_number") or data.get("address_number") or "").strip()
    phone = _digits_only(card.get("phone") or data.get("phone"))
    if year and len(year) == 2:
        year = f"20{year}"
    if month:
        month = month.zfill(2)
    if not all([number, holder, month, year, ccv, postal, address_number, phone]):
        return None, None, "Informe os dados completos do cartão, CEP, número do endereço e telefone."
    asaas_card = {
        "holderName": holder,
        "number": number,
        "expiryMonth": month,
        "expiryYear": year,
        "ccv": ccv,
    }
    holder_info = {
        "name": holder,
        "postalCode": postal,
        "addressNumber": address_number,
        "phone": phone,
        "mobilePhone": phone,
    }
    return asaas_card, holder_info, None


class BillingService:
    @staticmethod
    def _ensure_asaas_customer(user, cpf_cnpj=None):
        stored_cpf = _normalize_cpf_cnpj(getattr(user, "cpf_cnpj", None))
        effective_cpf = stored_cpf or cpf_cnpj
        if user.asaas_customer_id:
            if effective_cpf:
                Asaas.update_customer(user.asaas_customer_id, {
                    "name": user.name or user.email,
                    "email": user.email,
                    "cpfCnpj": effective_cpf,
                })
                if not stored_cpf and cpf_cnpj:
                    UserModel.set_cpf_cnpj(user._id, cpf_cnpj)
                    user.cpf_cnpj = cpf_cnpj
            return user.asaas_customer_id
        created = Asaas.create_customer(
            user.name,
            user.email,
            external_reference=str(user._id),
            cpf_cnpj=effective_cpf,
        )
        customer_id = created.get("id")
        UserModel.set_asaas_customer_id(user._id, customer_id)
        if not stored_cpf and cpf_cnpj:
            UserModel.set_cpf_cnpj(user._id, cpf_cnpj)
            user.cpf_cnpj = cpf_cnpj
        user.asaas_customer_id = customer_id
        return customer_id

    @staticmethod
    def _blocking_subscription(user_id):
        for item in SubscriptionModel.list_for_user(user_id):
            if item.get("status") in ACTIVE_BLOCKING_STATUSES:
                return item
        return None

    @staticmethod
    def _product(product_type, product_id):
        if product_type == "plan":
            return PlanModel.get_by_id(product_id)
        if product_type == "book":
            return BookModel.get_by_id(product_id)
        if product_type == "bundle":
            return BookBundleModel.get_by_id(product_id)
        if product_type == "course":
            return CourseModel.get_by_id(product_id)
        if product_type == "classroom":
            return ClassroomModel.get_by_id(product_id)
        return None

    @staticmethod
    def _first_asaas_payment(asaas_subscription_id):
        if not asaas_subscription_id:
            return None
        try:
            payments = Asaas.list_subscription_payments(asaas_subscription_id)
        except AsaasError:
            return None
        data = payments.get("data") or []
        return data[0] if data else None

    @staticmethod
    def _unpaid_asaas_payment(asaas_subscription_id):
        if not asaas_subscription_id:
            return None
        try:
            payments = Asaas.list_subscription_payments(asaas_subscription_id)
        except AsaasError:
            return None
        unpaid = [
            item for item in (payments.get("data") or [])
            if str(item.get("status") or "").upper() in ("PENDING", "OVERDUE")
        ]
        return unpaid[0] if unpaid else None

    @staticmethod
    def _first_invoice_url(asaas_subscription_id):
        first = BillingService._first_asaas_payment(asaas_subscription_id)
        if first:
            return first.get("invoiceUrl") or first.get("bankSlipUrl") or first.get("transactionReceiptUrl")
        return None

    @staticmethod
    def _pix_for_payment(provider_payment_id):
        if not provider_payment_id:
            return None
        try:
            return _serialize_pix(Asaas.get_pix_qr_code(provider_payment_id))
        except AsaasError:
            return None

    @staticmethod
    def _attach_card_to_payload(payload, user, customer_id, cpf_cnpj, data):
        asaas_card, holder_info, error = _extract_credit_card(data)
        if error:
            return error
        holder_info["email"] = user.email
        holder_info["cpfCnpj"] = cpf_cnpj
        holder_info["name"] = holder_info.get("name") or user.name or user.email
        remote_ip = _client_ip_from_data(data)
        payload["remoteIp"] = remote_ip
        payload["creditCardHolderInfo"] = holder_info
        try:
            tokenized = Asaas.tokenize_credit_card(customer_id, asaas_card, holder_info, remote_ip)
            token = tokenized.get("creditCardToken")
            if token:
                payload["creditCardToken"] = token
                return None
        except AsaasError:
            pass
        payload["creditCard"] = asaas_card
        return None

    @staticmethod
    def _native_checkout_result(billing_type, subscription=None, payment=None, pix=None, granted=False, invoice_url=None):
        result = {
            "provider": "asaas",
            "billing_type": billing_type,
            "granted": granted,
        }
        if subscription is not None:
            result["subscription"] = subscription
        if payment is not None:
            result["payment"] = payment
        if pix is not None:
            result["pix"] = pix
        if invoice_url:
            result["checkout_url"] = invoice_url
        return result, 200

    @staticmethod
    def checkout(user, data):
        product_type = data.get("product_type") or "plan"
        product_id = data.get("product_id")
        billing_type = _normalize_billing_type(data.get("billing_type"))
        coupon_code = data.get("coupon_code")
        stored_cpf = _normalize_cpf_cnpj(getattr(user, "cpf_cnpj", None))
        incoming_cpf = _normalize_cpf_cnpj(data.get("cpf_cnpj"))
        cpf_cnpj = stored_cpf or incoming_cpf
        if not product_id:
            return {"error": "product_id is required"}, 400

        product = BillingService._product(product_type, product_id)
        if not product:
            return {"error": "Product not found"}, 404
        if product_type == "plan" and not product.get("is_active"):
            return {"error": "Plan is not available"}, 400
        if product_type == "book" and product.get("sale_mode") == "plans_only":
            return {"error": "This book is only available through a plan"}, 400
        if product_type == "book" and product.get("is_free"):
            EntitlementService.grant_book(user._id, product["_id"], source="purchase")
            return {"provider": "free", "granted": True, "product_id": product["_id"]}, 200
        if product_type == "bundle":
            if not product.get("is_published") and not product.get("checkout_enabled"):
                return {"error": "Bundle is not available"}, 400
            if float(product.get("price") or 0) <= 0:
                return {"error": "Bundle price is not set"}, 400
        if product_type == "course":
            if not product.get("checkout_enabled"):
                return {"error": "Course checkout is not available"}, 400
            classroom_id = product.get("classroom_id")
            classroom = ClassroomModel.get_by_id(classroom_id) if classroom_id else None
            if classroom and not classroom.get("checkout_allowed"):
                return {"error": "Checkout is not allowed for this classroom"}, 400
            if classroom_id and ClassroomModel.is_student(classroom_id, user._id):
                return {
                    "provider": "free",
                    "granted": True,
                    "already_enrolled": True,
                    "product_id": product["_id"],
                }, 200
            if float(product.get("price") or 0) <= 0:
                return {"error": "Course price is not set"}, 400
        if product_type == "classroom":
            if not product.get("checkout_allowed"):
                return {"error": "Checkout is not allowed for this classroom"}, 400
            if not product.get("checkout_enabled"):
                return {"error": "Classroom checkout is not available"}, 400
            if ClassroomModel.is_student(product["_id"], user._id):
                return {
                    "provider": "free",
                    "granted": True,
                    "already_enrolled": True,
                    "product_id": product["_id"],
                }, 200
            if float(product.get("price") or 0) <= 0:
                return {"error": "Classroom price is not set"}, 400

        amount = float(product.get("price") or 0)
        coupon = None
        if coupon_code:
            quoted, error = CouponService.quote(amount, coupon_code, product_type, product_id)
            if error:
                return {"error": error}, 400
            coupon = quoted["coupon"]
            amount = quoted["final_amount"]

        if billing_type not in NATIVE_BILLING_TYPES:
            return {"error": "Escolha PIX ou cartão de crédito.", "code": "billing_type_required"}, 400
        # New purchases are always Asaas (PIX / card), including Android and iOS.
        if not cpf_cnpj:
            return {
                "error": "Informe um CPF ou CNPJ válido para assinar.",
                "code": "cpf_required",
            }, 400
        if not stored_cpf and incoming_cpf:
            UserModel.set_cpf_cnpj(user._id, incoming_cpf)
            user.cpf_cnpj = incoming_cpf

        affiliate_meta = AffiliateService.attribution_metadata(
            data, coupon, product_type, product_id
        )
        # #region agent log
        try:
            import json
            import time
            with open(r"e:\Usuários\cleby\Music\MEMOBELC\memobelc-api\debug-75e675.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "75e675",
                    "hypothesisId": "E",
                    "location": "billing_service.py:checkout",
                    "message": "checkout attribution",
                    "data": {
                        "product_type": product_type,
                        "product_id": str(product_id) if product_id else None,
                        "has_affiliate_code": bool(data.get("affiliate_code") or data.get("ref")),
                        "has_coupon": bool(coupon),
                        "affiliate_meta_keys": list((affiliate_meta or {}).keys()),
                        "has_affiliate_id": bool((affiliate_meta or {}).get("affiliate_id")),
                        "billing_type": billing_type,
                    },
                    "timestamp": int(time.time() * 1000),
                }, default=str) + "\n")
        except Exception:
            pass
        # #endregion

        if product_type == "plan":
            blocking = BillingService._blocking_subscription(user._id)
            if blocking and blocking.get("status") in ACCESS_STATUSES:
                if blocking.get("provider") == "google_play":
                    return {
                        "error": "You already have an active Google Play subscription. Cancel it in the Play Store before subscribing with Asaas.",
                        "code": "duplicate_subscription",
                        "subscription": blocking,
                    }, 409
                if blocking.get("plan_id") == str(product_id):
                    return {"error": "You already have an active subscription", "code": "duplicate_subscription"}, 409
                return {"error": "Cancel or change your current plan before starting a new one", "code": "duplicate_subscription"}, 409

        try:
            customer_id = BillingService._ensure_asaas_customer(user, cpf_cnpj)
            trial_days = int(product.get("trial_days") or 0) if product_type == "plan" else 0
            next_due = Asaas.default_next_due_date(trial_days) if trial_days > 0 else Asaas.due_date_today()
            discount = asaas_discount_payload(coupon)
            if product_type == "plan":
                payload = {
                    "customer": customer_id,
                    "billingType": billing_type,
                    "value": amount,
                    "nextDueDate": next_due,
                    "cycle": product.get("cycle") or "MONTHLY",
                    "description": product.get("name"),
                    "externalReference": f"plan:{user._id}:{product['_id']}",
                }
                if discount:
                    payload["discount"] = discount
                asaas_sub = Asaas.create_subscription(payload)
                first_pay = BillingService._first_asaas_payment(asaas_sub.get("id"))
                invoice_url = (
                    asaas_sub.get("invoiceUrl")
                    or (first_pay or {}).get("invoiceUrl")
                    or BillingService._first_invoice_url(asaas_sub.get("id"))
                )
                asaas_pay_status = ((first_pay or {}).get("status") or asaas_sub.get("status") or "").upper()
                paid = _asaas_is_paid(asaas_pay_status)
                if paid:
                    status = "active"
                elif trial_days > 0:
                    status = "trialing"
                else:
                    status = "pending"
                subscription = SubscriptionModel.create({
                    "user_id": user._id,
                    "plan_id": product["_id"],
                    "provider": "asaas",
                    "provider_subscription_id": asaas_sub.get("id"),
                    "asaas_customer_id": customer_id,
                    "status": status,
                    "billing_cycle": product.get("cycle"),
                    "value": amount,
                    "original_value": float(product.get("price") or 0),
                    "coupon_id": coupon["_id"] if coupon else None,
                    "payment_method": billing_type,
                    "invoice_url": invoice_url,
                    "next_due_date": next_due,
                    "grace_until": compute_grace_until(next_due),
                    "current_period_start": utcnow(),
                    "current_period_end": utcnow() + cycle_timedelta(product.get("cycle")),
                    "metadata": dict(affiliate_meta),
                })
                if coupon:
                    CouponModel.record_redemption(coupon["_id"], user._id, {"subscription_id": subscription["_id"]})
                payment = None
                if first_pay and first_pay.get("id"):
                    payment = PaymentModel.create({
                        "user_id": user._id,
                        "type": "subscription",
                        "provider": "asaas",
                        "provider_payment_id": first_pay.get("id"),
                        "status": "confirmed" if paid else "pending",
                        "amount": amount,
                        "product_type": "plan",
                        "product_id": product["_id"],
                        "subscription_id": subscription["_id"],
                        "coupon_id": coupon["_id"] if coupon else None,
                        "invoice_url": invoice_url,
                        "payment_method": billing_type,
                        "paid_at": utcnow() if paid else None,
                        "metadata": dict(affiliate_meta),
                    })
                granted = False
                if status in ACCESS_STATUSES:
                    EntitlementService.grant_subscription_entitlements(user._id, product, subscription["_id"])
                    granted = True
                    if payment and payment.get("status") == "confirmed":
                        AffiliateService.accrue_from_payment(payment, subscription)
                pix = BillingService._pix_for_payment((first_pay or {}).get("id")) if billing_type == "PIX" else None
                return BillingService._native_checkout_result(
                    billing_type,
                    subscription=subscription,
                    payment=payment,
                    pix=pix,
                    granted=granted,
                    invoice_url=invoice_url,
                )

            snapshot = product_snapshot(product_type, product)
            payload = {
                "customer": customer_id,
                "billingType": billing_type,
                "value": amount,
                "dueDate": Asaas.due_date_today(),
                "description": invoice_description(product_type, product),
                "externalReference": f"{product_type}:{user._id}:{product['_id']}",
            }
            if discount:
                payload["discount"] = discount
            asaas_pay = Asaas.create_payment(payload)
            paid = _asaas_is_paid(asaas_pay.get("status"))
            # #region agent log
            try:
                import json
                import time
                with open(r"e:\Usuários\cleby\Music\MEMOBELC\memobelc-api\debug-75e675.log", "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "sessionId": "75e675",
                        "hypothesisId": "F",
                        "location": "billing_service.py:checkout",
                        "message": "one-time payment created",
                        "data": {
                            "paid": bool(paid),
                            "asaas_status": asaas_pay.get("status"),
                            "billing_type": billing_type,
                            "will_fulfill": bool(paid),
                        },
                        "timestamp": int(time.time() * 1000),
                    }, default=str) + "\n")
            except Exception:
                pass
            # #endregion
            payment = PaymentModel.create({
                "user_id": user._id,
                "type": product_type,
                "provider": "asaas",
                "provider_payment_id": asaas_pay.get("id"),
                "status": "confirmed" if paid else "pending",
                "amount": amount,
                "product_type": product_type,
                "product_id": product["_id"],
                "coupon_id": coupon["_id"] if coupon else None,
                "invoice_url": asaas_pay.get("invoiceUrl"),
                "payment_method": billing_type,
                "paid_at": utcnow() if paid else None,
                "metadata": {
                    "external_reference": payload["externalReference"],
                    "invoice_description": payload["description"],
                    "product": snapshot,
                    "user_created": bool(data.get("_user_created")),
                    "must_change_password": bool(data.get("_must_change_password")),
                    **affiliate_meta,
                },
            })
            if coupon:
                CouponModel.record_redemption(coupon["_id"], user._id, {"payment_id": payment["_id"]})
            granted = False
            if paid:
                BillingService._fulfill_one_time(payment)
                granted = True
            pix = BillingService._pix_for_payment(asaas_pay.get("id")) if billing_type == "PIX" else None
            return BillingService._native_checkout_result(
                billing_type,
                payment=payment,
                pix=pix,
                granted=granted,
                invoice_url=asaas_pay.get("invoiceUrl"),
            )
        except AsaasError as exc:
            return {"error": _asaas_error_message(exc), "code": "asaas_error", "details": exc.payload}, exc.status_code

    @staticmethod
    def handle_asaas_webhook(payload, headers):
        if not Asaas.verify_webhook(headers):
            return {"error": "Invalid webhook token"}, 401
        event_type = payload.get("event") or payload.get("type")
        payment = payload.get("payment") or {}
        subscription_payload = payload.get("subscription") or {}
        event_id = (
            payload.get("id")
            or payment.get("id") and f"{event_type}:{payment.get('id')}"
            or subscription_payload.get("id") and f"{event_type}:{subscription_payload.get('id')}"
        )
        if event_id and WebhookEventModel.already_processed("asaas", event_id):
            return {"message": "already processed"}, 200
        if event_id:
            WebhookEventModel.record("asaas", event_id, event_type, payload)

        if event_type in ("PAYMENT_CONFIRMED", "PAYMENT_RECEIVED"):
            BillingService._on_asaas_payment(payment, "confirmed")
        elif event_type == "PAYMENT_OVERDUE":
            BillingService._on_asaas_payment(payment, "overdue")
        elif event_type in ("PAYMENT_REFUSED", "PAYMENT_DELETED"):
            BillingService._on_asaas_payment(payment, "refused")
        elif event_type in ("PAYMENT_REFUNDED", "PAYMENT_REFUND_DENIED"):
            BillingService._on_asaas_payment(payment, "refunded")
        elif event_type in ("SUBSCRIPTION_DELETED", "SUBSCRIPTION_INACTIVATED"):
            BillingService._on_asaas_subscription_status(subscription_payload, "canceled" if event_type == "SUBSCRIPTION_DELETED" else "suspended")
        elif event_type == "SUBSCRIPTION_UPDATED":
            BillingService._on_asaas_subscription_status(subscription_payload, None)

        return {"message": "ok"}, 200

    @staticmethod
    def _on_asaas_payment(payment_payload, status):
        provider_payment_id = payment_payload.get("id")
        provider_sub_id = payment_payload.get("subscription")
        payment = PaymentModel.get_by_provider_id("asaas", provider_payment_id)
        subscription = SubscriptionModel.get_by_provider_id("asaas", provider_sub_id) if provider_sub_id else None
        failure = None
        if status in ("refused", "overdue"):
            failure = failure_updates_from_payload(payment_payload, payment or {})
        if not payment and provider_payment_id:
            user_id = None
            product_type = "subscription" if provider_sub_id else None
            product_id = None
            if subscription:
                user_id = subscription.get("user_id")
                product_type = "plan"
                product_id = subscription.get("plan_id")
            else:
                external = payment_payload.get("externalReference") or ""
                parts = external.split(":")
                if len(parts) == 3:
                    product_type, user_id, product_id = parts
            if user_id:
                payload = {
                    "user_id": user_id,
                    "type": "subscription" if provider_sub_id else product_type,
                    "provider": "asaas",
                    "provider_payment_id": provider_payment_id,
                    "status": status,
                    "amount": payment_payload.get("value") or 0,
                    "product_type": product_type,
                    "product_id": product_id,
                    "subscription_id": subscription["_id"] if subscription else None,
                    "invoice_url": payment_payload.get("invoiceUrl"),
                    "payment_method": payment_payload.get("billingType"),
                    "paid_at": utcnow() if status == "confirmed" else None,
                    "metadata": dict((subscription or {}).get("metadata") or {}),
                }
                if failure:
                    payload.update(failure)
                payment = PaymentModel.create(payload)
        elif payment:
            updates = {
                "status": status,
                "invoice_url": payment_payload.get("invoiceUrl") or payment.get("invoice_url"),
                "payment_method": payment_payload.get("billingType") or payment.get("payment_method"),
            }
            if status == "confirmed":
                updates["paid_at"] = utcnow()
            if status == "refunded":
                updates["refunded_at"] = utcnow()
            if failure:
                updates.update(failure)
            payment = PaymentModel.update(payment["_id"], updates)

        # #region agent log
        try:
            import json
            import time
            with open(r"e:\Usuários\cleby\Music\MEMOBELC\memobelc-api\debug-75e675.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "75e675",
                    "hypothesisId": "H",
                    "location": "billing_service.py:_on_asaas_payment",
                    "message": "webhook payment",
                    "data": {
                        "status": status,
                        "has_payment": bool(payment),
                        "has_subscription": bool(subscription),
                    },
                    "timestamp": int(time.time() * 1000),
                }, default=str) + "\n")
        except Exception:
            pass
        # #endregion
        if subscription:
            BillingService._apply_subscription_payment(subscription, status, payment_payload, payment)
        elif payment and status == "confirmed":
            BillingService._fulfill_one_time(payment)
        elif payment and status == "refunded":
            BillingService._revoke_one_time(payment)

    @staticmethod
    def _apply_subscription_payment(subscription, status, payment_payload, payment=None):
        user_id = subscription["user_id"]
        plan = PlanModel.get_by_id(subscription["plan_id"])
        next_due = payment_payload.get("dueDate") or subscription.get("next_due_date")
        updates = {
            "next_due_date": next_due,
            "grace_until": compute_grace_until(next_due),
            "invoice_url": payment_payload.get("invoiceUrl") or subscription.get("invoice_url"),
            "payment_method": payment_payload.get("billingType") or subscription.get("payment_method"),
        }
        if status == "confirmed":
            updates["status"] = "active"
            updates["current_period_start"] = utcnow()
            if plan:
                updates["current_period_end"] = utcnow() + cycle_timedelta(plan.get("cycle"))
            EntitlementService.grant_subscription_entitlements(user_id, plan, subscription["_id"])
            if payment:
                AffiliateService.accrue_from_payment(payment, subscription)
        elif status == "overdue":
            updates["status"] = "overdue"
        elif status == "refused":
            updates["status"] = "refused"
        elif status == "refunded":
            updates["status"] = "canceled"
            updates["canceled_at"] = utcnow()
            EntitlementService.revoke_subscription_entitlements(user_id, subscription["_id"])
            if payment:
                AffiliateService.cancel_from_payment(payment)
        SubscriptionModel.update(subscription["_id"], updates)

    @staticmethod
    def _on_asaas_subscription_status(payload, status):
        provider_id = payload.get("id")
        subscription = SubscriptionModel.get_by_provider_id("asaas", provider_id)
        if not subscription:
            return
        updates = {}
        asaas_status = (payload.get("status") or "").upper()
        mapped = status
        if not mapped:
            mapped = {
                "ACTIVE": "active",
                "EXPIRED": "expired",
                "INACTIVE": "suspended",
            }.get(asaas_status)
        if mapped:
            updates["status"] = mapped
            if mapped in ("canceled", "expired", "suspended"):
                updates["canceled_at"] = utcnow()
                EntitlementService.revoke_subscription_entitlements(subscription["user_id"], subscription["_id"])
            elif mapped == "active":
                plan = PlanModel.get_by_id(subscription["plan_id"])
                if plan:
                    EntitlementService.grant_subscription_entitlements(subscription["user_id"], plan, subscription["_id"])
        if payload.get("nextDueDate"):
            updates["next_due_date"] = payload.get("nextDueDate")
            updates["grace_until"] = compute_grace_until(payload.get("nextDueDate"))
        if updates:
            SubscriptionModel.update(subscription["_id"], updates)

    @staticmethod
    def _fulfill_one_time(payment):
        user_id = payment.get("user_id")
        product_type = payment.get("product_type")
        product_id = payment.get("product_id")
        # #region agent log
        try:
            import json
            import time
            with open(r"e:\Usuários\cleby\Music\MEMOBELC\memobelc-api\debug-75e675.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "75e675",
                    "hypothesisId": "G",
                    "location": "billing_service.py:_fulfill_one_time",
                    "message": "fulfill called",
                    "data": {
                        "has_user_id": bool(user_id),
                        "has_product_id": bool(product_id),
                        "product_type": product_type,
                        "payment_status": (payment or {}).get("status"),
                        "has_affiliate_id": bool(((payment or {}).get("metadata") or {}).get("affiliate_id")),
                    },
                    "timestamp": int(time.time() * 1000),
                }, default=str) + "\n")
        except Exception:
            pass
        # #endregion
        if not user_id or not product_id:
            return
        try:
            AffiliateService.accrue_from_payment(payment)
        except Exception as exc:
            current_app.logger.error(f"Failed to accrue affiliate commission: {exc}")
        try:
            if product_type == "book":
                EntitlementService.grant_book(user_id, product_id, source="purchase", source_id=payment["_id"])
            elif product_type == "bundle":
                EntitlementService.grant_bundle(user_id, product_id, source="purchase", source_id=payment["_id"])
            elif product_type == "course":
                EntitlementService.grant_course(user_id, product_id, source="purchase", source_id=payment["_id"])
                BillingService._enroll_course_buyer(user_id, product_id)
                BillingService._confirm_buyer_email(user_id)
            elif product_type == "classroom":
                EntitlementService.grant_classroom(user_id, product_id, source="purchase", source_id=payment["_id"])
                BillingService._enroll_classroom_buyer(user_id, product_id)
                BillingService._confirm_buyer_email(user_id)
            if product_type in ("course", "classroom"):
                BillingService._send_purchase_receipt(payment)
        except Exception as exc:
            current_app.logger.error(f"Failed to finish one-time fulfillment: {exc}")

    @staticmethod
    def _enroll_course_buyer(user_id, course_id):
        course = CourseModel.get_by_id(course_id)
        if not course:
            return
        classroom_id = course.get("classroom_id")
        if not classroom_id:
            return
        if ClassroomModel.is_student(classroom_id, user_id):
            user = UserModel.find_by_id(user_id)
            if user and user.email:
                ClassroomModel.remove_user_guest(classroom_id, user.email)
            return
        classroom = ClassroomModel.get_by_id(classroom_id)
        if not classroom:
            return
        ClassroomModel.add_students(classroom_id, user_id)
        user = UserModel.find_by_id(user_id)
        if user and user.email:
            ClassroomModel.remove_user_guest(classroom_id, user.email)

    @staticmethod
    def _enroll_classroom_buyer(user_id, classroom_id):
        if not classroom_id:
            return
        if ClassroomModel.is_student(classroom_id, user_id):
            user = UserModel.find_by_id(user_id)
            if user and user.email:
                ClassroomModel.remove_user_guest(classroom_id, user.email)
            return
        classroom = ClassroomModel.get_by_id(classroom_id)
        if not classroom:
            return
        ClassroomModel.add_students(classroom_id, user_id)
        user = UserModel.find_by_id(user_id)
        if user and user.email:
            ClassroomModel.remove_user_guest(classroom_id, user.email)

    @staticmethod
    def _confirm_buyer_email(user_id):
        user = UserModel.find_by_id(user_id)
        if user and user.email and not UserModel.verify_is_confirmed(user.email):
            UserModel.turn_confirmed(user.email)

    @staticmethod
    def _send_purchase_receipt(payment):
        metadata = dict(payment.get("metadata") or {})
        if metadata.get("receipt_sent"):
            return
        user = UserModel.find_by_id(payment.get("user_id"))
        if not user or not user.email:
            return
        product = metadata.get("product") or {}
        product_name = product.get("name") or product.get("titulo") or (
            "Turma" if payment.get("product_type") == "classroom" else "Curso"
        )
        amount = payment.get("amount") or 0
        transaction_id = payment.get("_id")
        provider_id = payment.get("provider_payment_id") or ""
        paid_at = payment.get("paid_at") or utcnow()
        paid_label = paid_at.strftime("%d/%m/%Y %H:%M") if hasattr(paid_at, "strftime") else str(paid_at)
        try:
            is_new = bool(
                metadata.get("user_created")
                or metadata.get("must_change_password")
                or getattr(user, "must_change_password", False)
            )
            if is_new:
                access_instructions = f"""
Como acessar:
1. Entre em {Config.FRONT_BASE_URL}/login
2. Use este e-mail: {user.email}
3. A senha inicial é o seu CPF (somente números)
4. No primeiro acesso você deverá criar uma nova senha
""".strip()
            else:
                access_instructions = f"""
Como acessar:
1. Entre em {Config.FRONT_BASE_URL}/login
2. Use este e-mail: {user.email}
3. Use a senha da sua conta Memobelc
Se não lembrar, toque em "Esqueci minha senha"
""".strip()
            msg = Message(
                subject="Compra confirmada e boas-vindas - Memobelc",
                recipients=[user.email],
                sender=SettingsService.mail_sender(),
            )
            msg.body = f"""
Olá {user.name or ''}!

Bem-vindo(a) à Memobelc!

Sua compra foi confirmada.

Produto: {product_name}
Valor: R$ {float(amount):.2f}
Número da transação: {transaction_id}
ID do pagamento: {provider_id}
Data: {paid_label}

{access_instructions}

O acesso à turma já está liberado na sua conta.

Equipe Memobelc
""".strip()
            mail.send(msg)
            metadata["receipt_sent"] = True
            PaymentModel.update(payment["_id"], {"metadata": metadata})
        except Exception as exc:
            current_app.logger.error(f"Failed to send purchase receipt: {exc}")

    @staticmethod
    def _resolve_checkout_buyer(email, name, cpf_cnpj):
        """Find or create the buyer profile. Never asks for a password."""
        email = (email or "").strip().lower()
        name = (name or "").strip()
        by_email = UserModel.find_by_email(email)
        by_cpf = UserModel.find_by_cpf_cnpj(cpf_cnpj)
        if by_email and by_cpf and str(by_email._id) != str(by_cpf._id):
            return None, {
                "error": "Este CPF já está vinculado a outro e-mail.",
                "code": "cpf_mismatch",
            }, 409
        user = by_email or by_cpf
        if user:
            stored_cpf = _normalize_cpf_cnpj(getattr(user, "cpf_cnpj", None))
            if stored_cpf and stored_cpf != cpf_cnpj:
                return None, {
                    "error": "Este e-mail já possui outro CPF cadastrado.",
                    "code": "cpf_mismatch",
                }, 409
            if not stored_cpf:
                UserModel.set_cpf_cnpj(user._id, cpf_cnpj)
                user.cpf_cnpj = cpf_cnpj
            if name and not (user.name or "").strip():
                UserModel.set_name(user._id, name)
                user.name = name
            return {"user": user, "created": False}, None, 200
        if not name:
            return None, {"error": "name is required"}, 400
        UserModel(
            name=name,
            email=email,
            password=generate_password_hash(cpf_cnpj),
            cpf_cnpj=cpf_cnpj,
            must_change_password=True,
        ).save_to_db()
        user = UserModel.find_by_email(email)
        if not user:
            return None, {"error": "Could not create user"}, 500
        return {"user": user, "created": True}, None, 200

    @staticmethod
    def _guest_payment_user(payment_id, email, cpf_cnpj):
        payment = PaymentModel.get_by_id(payment_id)
        if not payment:
            return None, None
        user = UserModel.find_by_id(payment.get("user_id"))
        if not user:
            return None, None
        email = (email or "").strip().lower()
        cpf_cnpj = _normalize_cpf_cnpj(cpf_cnpj)
        if user.email and user.email.strip().lower() != email:
            return None, None
        stored_cpf = _normalize_cpf_cnpj(getattr(user, "cpf_cnpj", None))
        if stored_cpf and cpf_cnpj and stored_cpf != cpf_cnpj:
            return None, None
        return user, payment

    @staticmethod
    def public_checkout(data):
        data = dict(data or {})
        data.pop("password", None)
        product_type = data.get("product_type") or "classroom"
        if product_type == "course":
            course = CourseModel.get_by_id(data.get("product_id"))
            classroom_id = (course or {}).get("classroom_id")
            if not classroom_id:
                return {"error": "Only classroom public checkout is supported"}, 400
            data["product_type"] = "classroom"
            data["product_id"] = classroom_id
            product_type = "classroom"
        if product_type not in ("classroom", "bundle"):
            return {"error": "Only classroom and bundle public checkout is supported"}, 400
        product_id = data.get("product_id")
        if not product_id:
            return {"error": "product_id is required"}, 400
        email = (data.get("email") or "").strip().lower()
        name = (data.get("name") or "").strip()
        cpf_cnpj = _normalize_cpf_cnpj(data.get("cpf_cnpj"))
        if not email:
            return {"error": "email is required"}, 400
        if not cpf_cnpj:
            return {"error": "Informe um CPF ou CNPJ válido.", "code": "cpf_required"}, 400

        product = BillingService._product(product_type, product_id)
        if product_type == "classroom":
            if not product or not product.get("checkout_allowed") or not product.get("checkout_enabled"):
                return {"error": "Product not found"}, 404
            if float(product.get("price") or 0) <= 0:
                return {"error": "Classroom price is not set"}, 400
        else:
            if not product or not product.get("checkout_enabled"):
                return {"error": "Product not found"}, 404
            if float(product.get("price") or 0) <= 0:
                return {"error": "Bundle price is not set"}, 400

        buyer, error, status = BillingService._resolve_checkout_buyer(email, name, cpf_cnpj)
        if error:
            return error, status
        user = buyer["user"]
        created = buyer["created"]
        classroom_id = product.get("_id") if product_type == "classroom" else None
        if classroom_id and ClassroomModel.is_student(classroom_id, user._id):
            return {
                "granted": True,
                "already_enrolled": True,
                "provider": "free",
                "product_id": product["_id"],
                "user_created": False,
                "must_change_password": bool(getattr(user, "must_change_password", False)),
            }, 200

        data["_user_created"] = created
        data["_must_change_password"] = bool(getattr(user, "must_change_password", False) or created)
        result, status = BillingService.checkout(user, data)
        if status >= 400:
            return result, status
        from src.app.services.auth_service import AuthService
        result.update(AuthService.issue_auth_token(user))
        result["user_created"] = created
        result["must_change_password"] = bool(getattr(user, "must_change_password", False) or created)
        return result, status

    @staticmethod
    def public_sync_payment(payment_id, data):
        user, _payment = BillingService._guest_payment_user(
            payment_id,
            (data or {}).get("email"),
            (data or {}).get("cpf_cnpj"),
        )
        if not user:
            return {"error": "Payment not found"}, 404
        return BillingService.sync_payment(user, payment_id)

    @staticmethod
    def public_get_pix_qr(payment_id, data):
        user, _payment = BillingService._guest_payment_user(
            payment_id,
            (data or {}).get("email"),
            (data or {}).get("cpf_cnpj"),
        )
        if not user:
            return {"error": "Payment not found"}, 404
        return BillingService.get_pix_qr(user, payment_id)

    @staticmethod
    def _revoke_one_time(payment):
        user_id = payment.get("user_id")
        if not user_id:
            return
        EntitlementModel.revoke_by_source(user_id, "purchase", payment["_id"])
        AffiliateService.cancel_from_payment(payment)

    @staticmethod
    def my_subscription(user):
        return EntitlementService.resolve(user)

    @staticmethod
    def my_payments(user):
        return PaymentModel.list_for_user(user._id)

    @staticmethod
    def sync_payment(user, payment_id):
        # #region agent log
        try:
            import json
            import time
            with open(r"e:\Usuários\cleby\Music\MEMOBELC\memobelc-api\debug-75e675.log", "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "75e675",
                    "hypothesisId": "I",
                    "location": "billing_service.py:sync_payment",
                    "message": "sync_payment called",
                    "data": {"has_payment_id": bool(payment_id)},
                    "timestamp": int(time.time() * 1000),
                }, default=str) + "\n")
        except Exception:
            pass
        # #endregion
        payment = PaymentModel.get_by_id(payment_id)
        if not payment or str(payment.get("user_id")) != str(user._id):
            return {"error": "Payment not found"}, 404
        if payment.get("status") == "confirmed":
            if payment.get("subscription_id"):
                return {"payment": payment, "granted": True}, 200
            BillingService._fulfill_one_time(payment)
            return {"payment": payment, "granted": True}, 200
        if payment.get("provider") != "asaas" or not payment.get("provider_payment_id"):
            return {"payment": payment, "granted": False}, 200
        try:
            asaas_pay = Asaas.get_payment(payment["provider_payment_id"])
        except AsaasError as exc:
            return {"error": _asaas_error_message(exc), "code": "asaas_error", "details": exc.payload}, exc.status_code
        status = (asaas_pay.get("status") or "").upper()
        if status in ASAAS_PAID_STATUSES:
            payment = PaymentModel.update(payment["_id"], {
                "status": "confirmed",
                "paid_at": utcnow(),
                "invoice_url": asaas_pay.get("invoiceUrl") or payment.get("invoice_url"),
                "payment_method": asaas_pay.get("billingType") or payment.get("payment_method"),
            })
            if payment.get("subscription_id"):
                subscription = SubscriptionModel.get_by_id(payment["subscription_id"])
                if subscription:
                    BillingService._apply_subscription_payment(subscription, "confirmed", asaas_pay)
            else:
                BillingService._fulfill_one_time(payment)
            return {"payment": payment, "granted": True, "asaas_status": status}, 200
        return {"payment": payment, "granted": False, "asaas_status": status}, 200

    @staticmethod
    def cancel_mine(user):
        subscription = BillingService._blocking_subscription(user._id)
        if not subscription:
            return {"error": "No active subscription"}, 404
        if subscription.get("provider") == "google_play":
            return {
                "error": "Cancel this subscription in the Google Play Store",
                "code": "manage_on_play",
            }, 400
        if subscription.get("provider") == "asaas" and subscription.get("provider_subscription_id"):
            try:
                Asaas.cancel_subscription(subscription["provider_subscription_id"])
            except AsaasError as exc:
                return {"error": str(exc)}, exc.status_code
        updated = SubscriptionModel.update(subscription["_id"], {
            "status": "canceled",
            "canceled_at": utcnow(),
        })
        EntitlementService.revoke_subscription_entitlements(user._id, subscription["_id"])
        return {"subscription": updated}, 200

    @staticmethod
    def change_plan(user, plan_id):
        plan = PlanModel.get_by_id(plan_id)
        if not plan or not plan.get("is_active"):
            return {"error": "Plan not found"}, 404
        subscription = BillingService._blocking_subscription(user._id)
        if not subscription:
            return {"error": "No active subscription"}, 404
        if subscription.get("provider") != "asaas":
            return {"error": "Plan changes must be done with the same payment provider"}, 400
        try:
            Asaas.update_subscription(subscription["provider_subscription_id"], {
                "value": float(plan.get("price") or 0),
                "cycle": plan.get("cycle"),
                "description": plan.get("name"),
            })
        except AsaasError as exc:
            return {"error": str(exc)}, exc.status_code
        EntitlementService.revoke_subscription_entitlements(user._id, subscription["_id"])
        updated = SubscriptionModel.update(subscription["_id"], {
            "plan_id": plan["_id"],
            "value": float(plan.get("price") or 0),
            "original_value": float(plan.get("price") or 0),
            "billing_cycle": plan.get("cycle"),
            "status": "active",
        })
        EntitlementService.grant_subscription_entitlements(user._id, plan, subscription["_id"])
        return {"subscription": updated, "plan": plan}, 200

    @staticmethod
    def get_pix_qr(user, payment_id):
        payment = PaymentModel.get_by_id(payment_id)
        if not payment or str(payment.get("user_id")) != str(user._id):
            return {"error": "Payment not found"}, 404
        if payment.get("provider") != "asaas" or not payment.get("provider_payment_id"):
            return {"error": "PIX is not available for this payment", "code": "pix_unavailable"}, 400
        try:
            pix = _serialize_pix(Asaas.get_pix_qr_code(payment["provider_payment_id"]))
        except AsaasError as exc:
            return {"error": _asaas_error_message(exc), "code": "asaas_error", "details": exc.payload}, exc.status_code
        if not pix:
            return {"error": "PIX QR code is not available yet", "code": "pix_unavailable"}, 400
        return {"payment": payment, "pix": pix}, 200

    @staticmethod
    def update_payment_method(user, data=None):
        data = data or {}
        subscription = BillingService._blocking_subscription(user._id)
        if not subscription:
            subscription = next(
                (
                    item for item in SubscriptionModel.list_for_user(user._id)
                    if item.get("status") == "refused"
                ),
                None,
            )
        if not subscription:
            return {"error": "No active subscription"}, 404
        if subscription.get("provider") == "google_play":
            return {
                "provider": "google_play",
                "manage_url": "https://play.google.com/store/account/subscriptions",
            }, 200
        if subscription.get("provider") != "asaas" or not subscription.get("provider_subscription_id"):
            return {"error": "No Asaas subscription"}, 400
        billing_type = _normalize_billing_type(data.get("billing_type"))
        if billing_type not in NATIVE_BILLING_TYPES:
            return {"error": "Escolha PIX ou cartão de crédito.", "code": "billing_type_required"}, 400
        stored_cpf = _normalize_cpf_cnpj(getattr(user, "cpf_cnpj", None))
        incoming_cpf = _normalize_cpf_cnpj(data.get("cpf_cnpj"))
        cpf_cnpj = stored_cpf or incoming_cpf
        if not cpf_cnpj:
            return {"error": "Informe um CPF ou CNPJ válido.", "code": "cpf_required"}, 400
        if not stored_cpf and incoming_cpf:
            UserModel.set_cpf_cnpj(user._id, incoming_cpf)
            user.cpf_cnpj = incoming_cpf
        try:
            customer_id = BillingService._ensure_asaas_customer(user, cpf_cnpj)
            Asaas.update_subscription(subscription["provider_subscription_id"], {
                "billingType": billing_type,
            })
        except AsaasError as exc:
            return {"error": _asaas_error_message(exc), "code": "asaas_error", "details": exc.payload}, exc.status_code

        needs_charge = subscription.get("status") in ("pending", "overdue", "refused")
        asaas_pay = BillingService._unpaid_asaas_payment(subscription["provider_subscription_id"])
        current_type = _normalize_billing_type((asaas_pay or {}).get("billingType"))
        if asaas_pay and current_type != billing_type:
            try:
                asaas_pay = Asaas.update_payment(asaas_pay["id"], {"billingType": billing_type})
            except AsaasError:
                pass
        if needs_charge and not asaas_pay:
            try:
                asaas_pay = Asaas.create_payment({
                    "customer": customer_id,
                    "billingType": billing_type,
                    "value": float(subscription.get("value") or 0),
                    "dueDate": Asaas.due_date_today(),
                    "subscription": subscription["provider_subscription_id"],
                    "description": "Atualização de pagamento",
                    "externalReference": f"plan:{user._id}:{subscription.get('plan_id')}",
                })
            except AsaasError as exc:
                return {"error": _asaas_error_message(exc), "code": "asaas_error", "details": exc.payload}, exc.status_code

        invoice_url = None
        payment = None
        pix = None
        granted = subscription.get("status") in ACCESS_STATUSES
        if asaas_pay:
            invoice_url = asaas_pay.get("invoiceUrl") or asaas_pay.get("bankSlipUrl")
            paid = _asaas_is_paid(asaas_pay.get("status"))
            local = PaymentModel.get_by_provider_id("asaas", asaas_pay.get("id"))
            payload = {
                "status": "confirmed" if paid else "pending",
                "invoice_url": invoice_url,
                "payment_method": billing_type,
            }
            if local:
                if paid:
                    payload["paid_at"] = utcnow()
                payment = PaymentModel.update(local["_id"], payload)
            else:
                payment = PaymentModel.create({
                    "user_id": user._id,
                    "type": "subscription",
                    "provider": "asaas",
                    "provider_payment_id": asaas_pay.get("id"),
                    "status": "confirmed" if paid else "pending",
                    "amount": float(asaas_pay.get("value") or subscription.get("value") or 0),
                    "product_type": "plan",
                    "product_id": subscription.get("plan_id"),
                    "subscription_id": subscription["_id"],
                    "invoice_url": invoice_url,
                    "payment_method": billing_type,
                    "paid_at": utcnow() if paid else None,
                })
            if billing_type == "PIX":
                pix = BillingService._pix_for_payment(asaas_pay.get("id"))
            if paid:
                BillingService._apply_subscription_payment(subscription, "confirmed", asaas_pay, payment)
                granted = True

        updated = SubscriptionModel.update(subscription["_id"], {
            "payment_method": billing_type,
            "invoice_url": invoice_url or subscription.get("invoice_url"),
            "asaas_customer_id": customer_id,
        })
        result, status = BillingService._native_checkout_result(
            billing_type,
            subscription=updated,
            payment=payment,
            pix=pix,
            granted=granted,
            invoice_url=invoice_url,
        )
        result["updated"] = True
        return result, status

    @staticmethod
    def admin_set_status(admin, subscription_id, status, action=None):
        subscription = SubscriptionModel.get_by_id(subscription_id)
        if not subscription:
            return {"error": "Subscription not found"}, 404
        before = dict(subscription)
        provider_id = subscription.get("provider_subscription_id")
        try:
            if action == "cancel" and subscription.get("provider") == "asaas" and provider_id:
                Asaas.cancel_subscription(provider_id)
                status = "canceled"
            elif action == "suspend":
                status = "suspended"
            elif action == "reactivate" and subscription.get("provider") == "asaas" and provider_id:
                Asaas.update_subscription(provider_id, {"status": "ACTIVE"})
                status = "active"
        except AsaasError as exc:
            return {"error": str(exc)}, exc.status_code
        updates = {"status": status}
        if status in ("canceled", "expired", "suspended"):
            updates["canceled_at"] = utcnow()
            EntitlementService.revoke_subscription_entitlements(subscription["user_id"], subscription["_id"])
        elif status in ACCESS_STATUSES:
            plan = PlanModel.get_by_id(subscription["plan_id"])
            if plan:
                EntitlementService.grant_subscription_entitlements(subscription["user_id"], plan, subscription["_id"])
        updated = SubscriptionModel.update(subscription_id, updates)
        AuditLogModel.record(admin._id, action or f"set_status_{status}", "subscription", subscription_id, before, updated)
        return {"subscription": updated}, 200

    @staticmethod
    def admin_grant(admin, data):
        from datetime import timedelta
        from src.app.utils.billing_utils import parse_datetime, utcnow

        user_id = data.get("user_id")
        grant_type = data.get("type")
        resource_id = data.get("resource_id")
        notes = data.get("notes") or ""
        reason = data.get("reason") or ""
        expires_at = parse_datetime(data.get("expires_at"))
        if not expires_at and data.get("duration_days"):
            expires_at = utcnow() + timedelta(days=int(data.get("duration_days")))
        if not user_id or not grant_type or not resource_id:
            return {"error": "user_id, type and resource_id are required"}, 400
        if grant_type == "plan":
            result = EntitlementService.grant_plan_manual(
                user_id,
                resource_id,
                granted_by=admin._id,
                notes=notes,
                expires_at=expires_at,
                reason=reason,
            )
        elif grant_type == "book":
            result = EntitlementService.grant_book(user_id, resource_id, source="manual", granted_by=admin._id, notes=notes)
        elif grant_type == "bundle":
            result = EntitlementService.grant_bundle(user_id, resource_id, source="manual", granted_by=admin._id, notes=notes)
        elif grant_type == "course":
            result = EntitlementService.grant_course(user_id, resource_id, source="manual", granted_by=admin._id, notes=notes)
            BillingService._enroll_course_buyer(user_id, resource_id)
        elif grant_type == "classroom":
            result = EntitlementService.grant_classroom(user_id, resource_id, source="manual", granted_by=admin._id, notes=notes)
            BillingService._enroll_classroom_buyer(user_id, resource_id)
        elif grant_type == "service":
            result = EntitlementModel.grant({
                "user_id": user_id,
                "type": "service",
                "resource_id": resource_id,
                "source": "manual",
                "granted_by": admin._id,
                "notes": notes,
                "reason": reason,
                "expires_at": expires_at,
            })
        else:
            return {"error": "Invalid grant type"}, 400
        if not result:
            return {"error": "Unable to grant access"}, 400
        AuditLogModel.record(admin._id, "grant", grant_type, resource_id, None, {
            "grant": result,
            "reason": reason,
            "notes": notes,
            "expires_at": str(expires_at) if expires_at else None,
        })
        return {"grant": result}, 200

    @staticmethod
    def admin_revoke(admin, entitlement_id):
        before = EntitlementModel.get_by_id(entitlement_id)
        if not before:
            return {"error": "Entitlement not found"}, 404
        result = EntitlementService.revoke_entitlement(entitlement_id, notes="revoked by admin")
        AuditLogModel.record(admin._id, "revoke", before.get("type"), entitlement_id, before, result)
        return {"entitlement": result}, 200

    @staticmethod
    def register_external_sale(admin, data):
        email = (data.get("email") or "").strip().lower()
        if not email:
            return {"error": "email is required"}, 400
        product_type = data.get("product_type")
        product_ids = data.get("product_ids") or []
        if data.get("product_id"):
            product_ids = [data.get("product_id")]
        if not product_type or not product_ids:
            return {"error": "product_type and product_ids are required"}, 400
        created = False
        user = UserModel.find_by_email(email)
        if not user:
            user = UserModel.create_pending_user(data.get("name"), email)
            created = True
            BillingService._send_access_invite(email, data.get("name") or "")
        grants = []
        for product_id in product_ids:
            if product_type == "plan":
                grants.append(EntitlementService.grant_plan_manual(user._id, product_id, granted_by=admin._id, notes="external sale"))
            elif product_type == "book":
                grants.append(EntitlementService.grant_book(user._id, product_id, source="external", granted_by=admin._id, notes="external sale"))
            elif product_type == "bundle":
                grants.append(EntitlementService.grant_bundle(user._id, product_id, source="external", granted_by=admin._id, notes="external sale"))
            elif product_type == "course":
                grants.append(EntitlementService.grant_course(user._id, product_id, source="external", granted_by=admin._id, notes="external sale"))
                BillingService._enroll_course_buyer(user._id, product_id)
            elif product_type == "classroom":
                grants.append(EntitlementService.grant_classroom(user._id, product_id, source="external", granted_by=admin._id, notes="external sale"))
                BillingService._enroll_classroom_buyer(user._id, product_id)
            elif product_type == "service":
                grants.append(EntitlementModel.grant({
                    "user_id": user._id,
                    "type": "service",
                    "resource_id": product_id,
                    "source": "external",
                    "granted_by": admin._id,
                    "notes": "external sale",
                }))
        sale = ExternalSaleModel.create({
            "email": email,
            "name": data.get("name") or user.name,
            "user_id": user._id,
            "product_type": product_type,
            "product_ids": product_ids,
            "amount": data.get("amount"),
            "origin": data.get("origin") or "external",
            "notes": data.get("notes") or "",
            "invite_sent": created,
            "created_by": admin._id,
        })
        PaymentModel.create({
            "user_id": user._id,
            "type": product_type,
            "provider": "external",
            "status": "confirmed",
            "amount": data.get("amount") or 0,
            "product_type": product_type,
            "product_id": product_ids[0],
            "paid_at": utcnow(),
            "origin": "external",
            "metadata": {"sale_id": sale["_id"], "product_ids": product_ids},
        })
        AuditLogModel.record(admin._id, "external_sale", product_type, sale["_id"], None, sale)
        return {"sale": sale, "user_created": created, "grants": grants}, 201

    @staticmethod
    def admin_classroom_checkouts(filters=None, skip=0, limit=50):
        filters = dict(filters or {})
        product_type = filters.get("product_type") or "classroom"
        if product_type not in ("classroom", "course"):
            product_type = "classroom"
        query_filters = {"product_type": product_type}
        if filters.get("status"):
            query_filters["status"] = filters.get("status")
        if filters.get("product_id"):
            query_filters["product_id"] = filters.get("product_id")
        items, total = PaymentModel.query(query_filters, skip=skip, limit=limit)
        enriched = []
        for item in items:
            user = UserModel.find_by_id(item.get("user_id"))
            classroom = None
            if item.get("product_type") == "classroom":
                classroom = ClassroomModel.get_by_id(item.get("product_id"))
            elif item.get("product_type") == "course":
                course = CourseModel.get_by_id(item.get("product_id"))
                if course:
                    classroom = ClassroomModel.get_by_id(course.get("classroom_id"))
            snapshot = (item.get("metadata") or {}).get("product") or {}
            enriched.append({
                **item,
                "buyer_name": user.name if user else None,
                "buyer_email": user.email if user else None,
                "classroom_name": (classroom or {}).get("name") or snapshot.get("name"),
                "receipt_url": item.get("invoice_url"),
                "transaction_id": item.get("_id"),
            })
        return {"payments": enriched, "total": total}

    @staticmethod
    def _send_access_invite(email, name):
        try:
            msg = Message(
                subject="Você recebeu acesso ao Memobelc",
                recipients=[email],
                sender=SettingsService.mail_sender(),
            )
            msg.body = f"""
Olá {name or ''}!

Uma compra foi registrada para você na plataforma Memobelc.
Para concluir seu cadastro e acessar o conteúdo, use este e-mail em:
{Config.FRONT_BASE_URL}/register

Se já possuir conta, faça login em:
{Config.FRONT_BASE_URL}/login

Equipe Memobelc
"""
            mail.send(msg)
        except Exception as exc:
            current_app.logger.error(f"Failed to send external sale invite: {exc}")

    @staticmethod
    def verify_google_purchase(user, data):
        sku = data.get("sku") or data.get("productId")
        token = data.get("purchase_token") or data.get("purchaseToken")
        product_type = data.get("product_type") or "plan"
        if not sku or not token:
            return {"error": "sku and purchase_token are required"}, 400
        if WebhookEventModel.already_processed("google_play", token):
            existing = SubscriptionModel.get_by_provider_id("google_play", token) or PaymentModel.get_by_provider_id("google_play", token)
            return {"message": "already processed", "record": existing}, 200
        try:
            if product_type == "plan":
                payload = GooglePlay.verify_subscription(sku, token)
            else:
                payload = GooglePlay.verify_product(sku, token)
        except GooglePlayError as exc:
            return {"error": str(exc)}, exc.status_code

        WebhookEventModel.record("google_play", token, "VERIFY", payload)
        if product_type == "plan":
            blocking = BillingService._blocking_subscription(user._id)
            if blocking and blocking.get("provider") == "asaas" and blocking.get("status") in ACCESS_STATUSES:
                return {
                    "error": "You already have an active Asaas subscription",
                    "code": "duplicate_subscription",
                }, 409
            plan = PlanModel.get_by_google_sku(sku)
            if not plan:
                return {"error": "Unknown Google Play SKU"}, 404
            expiry_ms = payload.get("expiryTimeMillis")
            expiry = datetime.fromtimestamp(int(expiry_ms) / 1000, tz=timezone.utc) if expiry_ms else utcnow() + timedelta(days=30)
            payment_state = str(payload.get("paymentState"))
            status = "active" if payment_state in ("1", "2") else "pending"
            if payload.get("autoRenewing") is False and expiry <= utcnow():
                status = "expired"
            subscription = SubscriptionModel.get_by_provider_id("google_play", token)
            if not subscription:
                subscription = SubscriptionModel.create({
                    "user_id": user._id,
                    "plan_id": plan["_id"],
                    "provider": "google_play",
                    "provider_subscription_id": token,
                    "status": status,
                    "billing_cycle": plan.get("cycle"),
                    "value": float(plan.get("price") or 0),
                    "original_value": float(plan.get("price") or 0),
                    "next_due_date": expiry,
                    "grace_until": compute_grace_until(expiry),
                    "current_period_end": expiry,
                    "metadata": {"sku": sku, "order_id": payload.get("orderId")},
                })
            else:
                subscription = SubscriptionModel.update(subscription["_id"], {
                    "status": status,
                    "next_due_date": expiry,
                    "grace_until": compute_grace_until(expiry),
                    "current_period_end": expiry,
                })
            PaymentModel.create({
                "user_id": user._id,
                "type": "subscription",
                "provider": "google_play",
                "provider_payment_id": payload.get("orderId") or token,
                "status": "confirmed" if status in ACCESS_STATUSES else "pending",
                "amount": plan.get("price") or 0,
                "product_type": "plan",
                "product_id": plan["_id"],
                "subscription_id": subscription["_id"],
                "paid_at": utcnow() if status in ACCESS_STATUSES else None,
            })
            if status in ACCESS_STATUSES:
                EntitlementService.grant_subscription_entitlements(user._id, plan, subscription["_id"])
            try:
                GooglePlay.acknowledge_subscription(sku, token)
            except GooglePlayError:
                pass
            return {"subscription": subscription, "provider": "google_play"}, 200

        product = BookModel.get_by_google_sku(sku) if product_type == "book" else BookBundleModel.get_by_google_sku(sku)
        if not product:
            return {"error": "Unknown Google Play SKU"}, 404
        payment = PaymentModel.create({
            "user_id": user._id,
            "type": product_type,
            "provider": "google_play",
            "provider_payment_id": token,
            "status": "confirmed",
            "amount": product.get("price") or 0,
            "product_type": product_type,
            "product_id": product["_id"],
            "paid_at": utcnow(),
            "metadata": {"sku": sku},
        })
        BillingService._fulfill_one_time(payment)
        try:
            GooglePlay.acknowledge_product(sku, token)
        except GooglePlayError:
            pass
        return {"payment": payment, "provider": "google_play"}, 200

    @staticmethod
    def handle_google_rtdn(body, token=None):
        if not GooglePlay.verify_rtdn_token(token):
            return {"error": "Invalid RTDN token"}, 401
        notification = GooglePlay.decode_rtdn(body)
        event_id = (notification.get("message") or {}).get("messageId") or notification.get("eventTimeMillis")
        if event_id and WebhookEventModel.already_processed("google_play_rtdn", event_id):
            return {"message": "already processed"}, 200
        if event_id:
            WebhookEventModel.record("google_play_rtdn", event_id, "RTDN", notification)
        sub_n = notification.get("subscriptionNotification") or {}
        one_n = notification.get("oneTimeProductNotification") or {}
        purchase_token = sub_n.get("purchaseToken") or one_n.get("purchaseToken")
        sku = sub_n.get("subscriptionId") or one_n.get("sku")
        ntype = sub_n.get("notificationType")
        if purchase_token and sku and ntype is not None:
            subscription = SubscriptionModel.get_by_provider_id("google_play", purchase_token)
            status_map = {
                2: "active",
                3: "canceled",
                4: "active",
                5: "overdue",
                6: "suspended",
                10: "paused",
                12: "expired",
                13: "expired",
            }
            mapped = status_map.get(int(ntype))
            if subscription and mapped:
                if mapped in ("canceled", "expired", "suspended"):
                    EntitlementService.revoke_subscription_entitlements(subscription["user_id"], subscription["_id"])
                    SubscriptionModel.update(subscription["_id"], {"status": mapped if mapped != "paused" else "suspended", "canceled_at": utcnow()})
                elif mapped == "active":
                    plan = PlanModel.get_by_id(subscription["plan_id"])
                    SubscriptionModel.update(subscription["_id"], {"status": "active"})
                    if plan:
                        EntitlementService.grant_subscription_entitlements(subscription["user_id"], plan, subscription["_id"])
                elif mapped == "overdue":
                    SubscriptionModel.update(subscription["_id"], {"status": "overdue"})
        return {"message": "ok"}, 200

    @staticmethod
    def reconcile():
        now = utcnow()
        for subscription in SubscriptionModel.query({"status": "active"}, limit=200)[0]:
            grace = parse_datetime(subscription.get("grace_until"))
            due = parse_datetime(subscription.get("next_due_date"))
            if due and now > due and grace and now > grace:
                SubscriptionModel.update(subscription["_id"], {"status": "overdue"})
            if subscription.get("provider") == "asaas" and subscription.get("provider_subscription_id") and Asaas.is_configured():
                try:
                    remote = Asaas.get_subscription(subscription["provider_subscription_id"])
                    BillingService._on_asaas_subscription_status(remote, None)
                except AsaasError:
                    continue
        return True
