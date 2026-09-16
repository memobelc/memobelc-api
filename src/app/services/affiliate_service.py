"""Affiliate program business logic."""

from pymongo.errors import DuplicateKeyError

from src.app.models.affiliate_application_model import AffiliateApplicationModel
from src.app.models.affiliate_commission_model import AffiliateCommissionModel
from src.app.models.affiliate_model import AffiliateClickModel, AffiliateModel, AffiliateSettingsModel
from src.app.models.affiliate_product_model import AffiliateProductModel
from src.app.models.affiliate_withdrawal_model import AffiliateWithdrawalModel
from src.app.models.coupon_model import CouponModel
from src.app.models.user_model import UserModel
from src.app.utils.billing_utils import utcnow


class AffiliateError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


# #region agent log
def _dbg(hypothesis_id, location, message, data=None):
    try:
        import json
        import time
        with open(r"e:\Usuários\cleby\Music\MEMOBELC\memobelc-api\debug-75e675.log", "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "75e675",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data or {},
                "timestamp": int(time.time() * 1000),
            }, default=str) + "\n")
    except Exception:
        pass
# #endregion


def _share_url(product, referral_code):
    base = (product.get("checkout_url") or "").strip()
    if not base:
        return None
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}ref={referral_code}"


def _current_percent(product, affiliate_id):
    count = AffiliateCommissionModel.count_credited(affiliate_id, product["_id"]) + 1
    tier = AffiliateProductModel.match_tier(product, count)
    if not tier:
        return 0.0, count
    return float(tier.get("percent") or 0), count


class AffiliateService:
    @staticmethod
    def ensure_indexes():
        AffiliateModel.ensure_indexes()
        AffiliateSettingsModel.get()

    @staticmethod
    def wallet(affiliate_id):
        pending = AffiliateCommissionModel.sum_by_status(affiliate_id, "pending")
        credited = AffiliateCommissionModel.sum_by_status(affiliate_id, "available")
        reserved = AffiliateWithdrawalModel.sum_reserved(affiliate_id)
        withdrawn = AffiliateWithdrawalModel.sum_paid(affiliate_id)
        available = round(max(credited - reserved, 0), 2)
        return {
            "pending": pending,
            "available": available,
            "withdrawn": withdrawn,
            "credited": credited,
        }

    @staticmethod
    def _enrich_affiliate(affiliate):
        if not affiliate:
            return None
        user = UserModel.find_by_id(affiliate["user_id"])
        wallet = AffiliateService.wallet(affiliate["_id"])
        sales_count = len(AffiliateCommissionModel.list_for_affiliate(affiliate["_id"], limit=5000))
        return {
            **affiliate,
            "user_name": user.name if user else None,
            "user_email": user.email if user else None,
            "wallet": wallet,
            "sales_count": sales_count,
        }

    @staticmethod
    def add_affiliate(user_id, admin_id=None):
        user = UserModel.find_by_id(user_id)
        if not user:
            raise AffiliateError("User not found", 404)
        roles = user.get_roles()
        if "affiliate" not in roles:
            roles.append("affiliate")
            if "user" not in roles:
                roles.append("user")
            UserModel.update_roles(user_id, roles)
        affiliate = AffiliateModel.create(user_id, created_by=admin_id)
        return AffiliateService._enrich_affiliate(affiliate)

    @staticmethod
    def sync_role(user_id, roles, admin_id=None):
        has_affiliate = "affiliate" in (roles or [])
        existing = AffiliateModel.find_by_user_id(user_id)
        if has_affiliate:
            AffiliateService.add_affiliate(user_id, admin_id=admin_id)
        elif existing and existing.get("status") == "active":
            AffiliateModel.update(existing["_id"], {"status": "suspended"})

    @staticmethod
    def require_affiliate(user):
        if not user or not user.has_role("affiliate"):
            raise AffiliateError("Unauthorized", 403)
        affiliate = AffiliateModel.find_by_user_id(user._id)
        if not affiliate:
            affiliate = AffiliateModel.create(user._id)
        if affiliate.get("status") != "active":
            raise AffiliateError("Affiliate account is suspended", 403)
        return affiliate

    @staticmethod
    def get_me(user):
        affiliate = AffiliateService.require_affiliate(user)
        return AffiliateService._enrich_affiliate(affiliate)

    @staticmethod
    def list_affiliates(status=None):
        return [AffiliateService._enrich_affiliate(item) for item in AffiliateModel.list_affiliates(status=status)]

    @staticmethod
    def set_status(affiliate_id, status, admin_id=None):
        affiliate = AffiliateModel.get_by_id(affiliate_id)
        if not affiliate:
            raise AffiliateError("Affiliate not found", 404)
        updated = AffiliateModel.update(affiliate_id, {"status": status})
        if status == "suspended":
            user = UserModel.find_by_id(affiliate["user_id"])
            if user:
                roles = [role for role in user.get_roles() if role != "affiliate"] or ["user"]
                UserModel.update_roles(affiliate["user_id"], roles)
        elif status == "active":
            AffiliateService.add_affiliate(affiliate["user_id"], admin_id=admin_id)
        return AffiliateService._enrich_affiliate(updated)

    @staticmethod
    def list_affiliate_products(user):
        affiliate = AffiliateService.require_affiliate(user)
        applications = {
            item["product_id"]: item
            for item in AffiliateApplicationModel.list_for_affiliate(affiliate["_id"])
        }
        resellable = []
        available = []
        for product in AffiliateProductModel.list_products(active_only=True):
            app = applications.get(product["_id"])
            payload = AffiliateService._product_payload(product, affiliate, app)
            if app and app.get("status") == "approved":
                resellable.append(payload)
            elif product.get("show_in_catalog") and product.get("affiliate_enabled"):
                if not app or app.get("status") in ("pending", "rejected"):
                    available.append(payload)
        return {"resellable": resellable, "available": available}

    @staticmethod
    def get_affiliate_product(user, product_id):
        affiliate = AffiliateService.require_affiliate(user)
        product = AffiliateProductModel.get_by_id(product_id)
        if not product or not product.get("is_active"):
            raise AffiliateError("Product not found", 404)
        app = AffiliateApplicationModel.find(affiliate["_id"], product_id)
        if not (app and app.get("status") == "approved"):
            if not product.get("show_in_catalog") or not product.get("affiliate_enabled"):
                raise AffiliateError("Product not found", 404)
        return AffiliateService._product_payload(product, affiliate, app, include_terms=True)

    @staticmethod
    def _product_payload(product, affiliate, application=None, include_terms=False):
        percent, sale_count = _current_percent(product, affiliate["_id"])
        coupon = CouponModel.find_by_affiliate(affiliate["_id"], product["_id"]) or CouponModel.find_by_affiliate(
            affiliate["_id"]
        )
        approved = bool(application and application.get("status") == "approved")
        payload = {
            **product,
            "application": application,
            "current_percent": percent,
            "sale_count": max(sale_count - 1, 0),
            "share_url": _share_url(product, affiliate.get("referral_code")) if approved else None,
            "referral_code": affiliate.get("referral_code") if approved else None,
            "coupon_code": coupon.get("code") if coupon and approved else None,
        }
        if not include_terms:
            payload.pop("terms", None)
        return payload

    @staticmethod
    def apply_to_product(user, product_id, accepted_terms):
        affiliate = AffiliateService.require_affiliate(user)
        if not accepted_terms:
            raise AffiliateError("You must accept the affiliate terms", 400)
        product = AffiliateProductModel.get_by_id(product_id)
        if not product or not product.get("is_active") or not product.get("affiliate_enabled"):
            raise AffiliateError("Product is not available for affiliation", 400)
        existing = AffiliateApplicationModel.find(affiliate["_id"], product_id)
        if existing and existing.get("status") == "approved":
            raise AffiliateError("You are already an affiliate of this product", 400)
        if existing and existing.get("status") == "pending":
            raise AffiliateError("Affiliation request is already under review", 400)
        application = AffiliateApplicationModel.create(
            affiliate["_id"],
            user._id,
            product_id,
            terms_accepted_at=utcnow(),
        )
        AffiliateService._notify_application(user, product, application)
        return application

    @staticmethod
    def review_application(application_id, status, admin_id, notes=""):
        application = AffiliateApplicationModel.get_by_id(application_id)
        if not application:
            raise AffiliateError("Application not found", 404)
        if status not in ("approved", "rejected"):
            raise AffiliateError("status must be approved or rejected", 400)
        updated = AffiliateApplicationModel.update(application_id, {
            "status": status,
            "reviewed_by": admin_id,
            "reviewed_at": utcnow(),
            "notes": notes,
        })
        return updated

    @staticmethod
    def resolve_attribution(affiliate_code=None, coupon=None, product_type=None, product_id=None):
        affiliate = None
        affiliate_product = None
        if coupon and coupon.get("affiliate_id"):
            affiliate = AffiliateModel.get_by_id(coupon["affiliate_id"])
            if coupon.get("affiliate_product_id"):
                affiliate_product = AffiliateProductModel.get_by_id(coupon["affiliate_product_id"])
        if not affiliate and affiliate_code:
            affiliate = AffiliateModel.find_by_code(affiliate_code)
        if not affiliate or affiliate.get("status") != "active":
            # #region agent log
            _dbg("A", "affiliate_service.py:resolve_attribution", "attribution failed: affiliate", {
                "has_code": bool(affiliate_code),
                "has_coupon_affiliate": bool(coupon and coupon.get("affiliate_id")),
                "has_affiliate": bool(affiliate),
                "affiliate_status": (affiliate or {}).get("status"),
                "product_type": product_type,
                "product_id": str(product_id) if product_id else None,
            })
            # #endregion
            return None
        if not affiliate_product:
            related = AffiliateProductModel.find_platform_products_for_sale(product_type, product_id)
            approved_related = [
                item for item in related
                if AffiliateApplicationModel.is_approved(affiliate["_id"], item["_id"])
            ]
            affiliate_product = (approved_related or related or [None])[0]
        if not affiliate_product:
            sale_keys = set(AffiliateProductModel.related_sale_keys(product_type, product_id))
            fallback_products = []
            for application in AffiliateApplicationModel.list_for_affiliate(affiliate["_id"]):
                if application.get("status") != "approved":
                    continue
                candidate = AffiliateProductModel.get_by_id(application.get("product_id"))
                if not candidate or not candidate.get("is_active") or not candidate.get("affiliate_enabled"):
                    continue
                if candidate.get("source") == "platform":
                    key = (str(candidate.get("product_type") or ""), str(candidate.get("product_id") or ""))
                    if key in sale_keys:
                        affiliate_product = candidate
                        break
                    continue
                fallback_products.append(candidate)
            if not affiliate_product and len(fallback_products) == 1:
                affiliate_product = fallback_products[0]
        if not affiliate_product:
            # #region agent log
            _dbg("A", "affiliate_service.py:resolve_attribution", "attribution failed: product", {
                "affiliate_id": str(affiliate.get("_id")),
                "product_type": product_type,
                "product_id": str(product_id) if product_id else None,
                "related_keys": AffiliateProductModel.related_sale_keys(product_type, product_id),
            })
            # #endregion
            return None
        if not AffiliateApplicationModel.is_approved(affiliate["_id"], affiliate_product["_id"]):
            # #region agent log
            _dbg("A", "affiliate_service.py:resolve_attribution", "attribution failed: application not approved", {
                "affiliate_id": str(affiliate.get("_id")),
                "affiliate_product_id": str(affiliate_product.get("_id")),
            })
            # #endregion
            return None
        result = {
            "affiliate_id": affiliate["_id"],
            "affiliate_code": affiliate.get("referral_code"),
            "affiliate_product_id": affiliate_product["_id"],
        }
        # #region agent log
        _dbg("A", "affiliate_service.py:resolve_attribution", "attribution ok", {
            "affiliate_id": str(result["affiliate_id"]),
            "affiliate_product_id": str(result["affiliate_product_id"]),
        })
        # #endregion
        return result

    @staticmethod
    def attribution_metadata(data, coupon, product_type, product_id):
        affiliate_code = data.get("affiliate_code") or data.get("ref")
        attribution = AffiliateService.resolve_attribution(
            affiliate_code=affiliate_code,
            coupon=coupon,
            product_type=product_type,
            product_id=product_id,
        )
        if attribution:
            return attribution
        if affiliate_code:
            return {"affiliate_code": affiliate_code}
        return {}

    @staticmethod
    def accrue_from_payment(payment, subscription=None):
        if not payment:
            # #region agent log
            _dbg("E", "affiliate_service.py:accrue_from_payment", "no payment", {})
            # #endregion
            return None
        metadata = dict(payment.get("metadata") or {})
        if subscription:
            metadata.update(subscription.get("metadata") or {})
        affiliate_id = metadata.get("affiliate_id")
        product_id = metadata.get("affiliate_product_id")
        # #region agent log
        _dbg("E", "affiliate_service.py:accrue_from_payment", "accrue start", {
            "payment_id": str(payment.get("_id")) if payment.get("_id") else None,
            "payment_status": payment.get("status"),
            "product_type": payment.get("product_type"),
            "product_id": str(payment.get("product_id")) if payment.get("product_id") else None,
            "has_affiliate_id": bool(affiliate_id),
            "has_affiliate_product_id": bool(product_id),
            "has_affiliate_code": bool(metadata.get("affiliate_code")),
            "meta_keys": list(metadata.keys()),
        })
        # #endregion
        if not affiliate_id:
            attribution = AffiliateService.resolve_attribution(
                affiliate_code=metadata.get("affiliate_code"),
                coupon=CouponModel.get_by_id(payment.get("coupon_id")) if payment.get("coupon_id") else None,
                product_type=payment.get("product_type"),
                product_id=payment.get("product_id"),
            )
            if not attribution:
                # #region agent log
                _dbg("A", "affiliate_service.py:accrue_from_payment", "accrue aborted: no attribution", {
                    "payment_id": str(payment.get("_id")) if payment.get("_id") else None,
                })
                # #endregion
                return None
            affiliate_id = attribution["affiliate_id"]
            product_id = attribution["affiliate_product_id"]
        return AffiliateService._create_commission(
            affiliate_id=affiliate_id,
            product_id=product_id,
            sale_amount=float(payment.get("amount") or 0),
            payment_id=payment.get("_id"),
            buyer_user_id=payment.get("user_id"),
        )

    @staticmethod
    def cancel_from_payment(payment):
        if not payment:
            return None
        commission = AffiliateCommissionModel.find_by_payment(payment.get("_id"))
        if not commission or commission.get("status") == "cancelled":
            return commission
        return AffiliateCommissionModel.update(commission["_id"], {
            "status": "cancelled",
            "notes": "payment refunded",
        })

    @staticmethod
    def register_external_sale(admin, data):
        affiliate = None
        if data.get("affiliate_id"):
            affiliate = AffiliateModel.get_by_id(data.get("affiliate_id"))
        elif data.get("referral_code") or data.get("affiliate_code"):
            affiliate = AffiliateModel.find_by_code(data.get("referral_code") or data.get("affiliate_code"))
        if not affiliate:
            raise AffiliateError("Affiliate not found", 404)
        if affiliate.get("status") != "active":
            raise AffiliateError("Affiliate is not active", 400)
        product = AffiliateProductModel.get_by_id(data.get("product_id"))
        if not product:
            raise AffiliateError("Affiliate product not found", 404)
        if not AffiliateApplicationModel.is_approved(affiliate["_id"], product["_id"]):
            raise AffiliateError("Affiliate is not approved for this product", 400)
        amount = float(data.get("amount") or 0)
        if amount <= 0:
            raise AffiliateError("amount must be greater than 0", 400)
        external_sale_id = data.get("external_sale_id") or f"manual:{utcnow().isoformat()}:{affiliate['_id']}"
        return AffiliateService._create_commission(
            affiliate_id=affiliate["_id"],
            product_id=product["_id"],
            sale_amount=amount,
            external_sale_id=str(external_sale_id),
            buyer_user_id=data.get("buyer_user_id"),
            notes=data.get("notes") or "external sale",
        )

    @staticmethod
    def _create_commission(
        affiliate_id,
        product_id,
        sale_amount,
        payment_id=None,
        external_sale_id=None,
        buyer_user_id=None,
        notes="",
    ):
        # #region agent log
        _dbg("B", "affiliate_service.py:_create_commission", "create start", {
            "has_payment_id": bool(payment_id),
            "affiliate_id": str(affiliate_id) if affiliate_id else None,
            "product_id": str(product_id) if product_id else None,
        })
        # #endregion
        if payment_id:
            existing = AffiliateCommissionModel.find_by_payment(payment_id)
            if existing:
                # #region agent log
                _dbg("B", "affiliate_service.py:_create_commission", "existing commission by payment", {
                    "commission_id": str(existing.get("_id")),
                    "status": existing.get("status"),
                })
                # #endregion
                return existing
        if external_sale_id:
            existing = AffiliateCommissionModel.find_by_external_sale(external_sale_id)
            if existing:
                # #region agent log
                _dbg("B", "affiliate_service.py:_create_commission", "existing commission by external sale", {
                    "commission_id": str(existing.get("_id")),
                    "status": existing.get("status"),
                })
                # #endregion
                return existing
        affiliate = AffiliateModel.get_by_id(affiliate_id)
        product = AffiliateProductModel.get_by_id(product_id)
        if not affiliate or not product:
            # #region agent log
            _dbg("B", "affiliate_service.py:_create_commission", "missing affiliate or product", {
                "has_affiliate": bool(affiliate),
                "has_product": bool(product),
                "affiliate_id": str(affiliate_id) if affiliate_id else None,
                "product_id": str(product_id) if product_id else None,
            })
            # #endregion
            return None
        if affiliate.get("status") != "active":
            # #region agent log
            _dbg("B", "affiliate_service.py:_create_commission", "affiliate not active", {
                "affiliate_id": str(affiliate_id),
                "status": affiliate.get("status"),
            })
            # #endregion
            return None
        if not AffiliateApplicationModel.is_approved(affiliate_id, product_id):
            # #region agent log
            _dbg("B", "affiliate_service.py:_create_commission", "application not approved", {
                "affiliate_id": str(affiliate_id),
                "product_id": str(product_id),
            })
            # #endregion
            return None
        sale_count = AffiliateCommissionModel.count_credited(affiliate_id, product_id) + 1
        tier = AffiliateProductModel.match_tier(product, sale_count)
        percent = float((tier or {}).get("percent") or 0)
        amount = round(float(sale_amount or 0) * percent / 100.0, 2)
        try:
            commission = AffiliateCommissionModel.create({
                "affiliate_id": affiliate_id,
                "user_id": affiliate.get("user_id"),
                "product_id": product_id,
                "payment_id": payment_id,
                "external_sale_id": external_sale_id,
                "buyer_user_id": buyer_user_id,
                "sale_amount": sale_amount,
                "percent": percent,
                "amount": amount,
                "sale_count_at": sale_count,
                "notes": notes,
            })
        except DuplicateKeyError:
            if payment_id:
                return AffiliateCommissionModel.find_by_payment(payment_id)
            return AffiliateCommissionModel.find_by_external_sale(external_sale_id)
        # #region agent log
        _dbg("B", "affiliate_service.py:_create_commission", "commission created", {
            "commission_id": str(commission.get("_id")),
            "status": commission.get("status"),
            "amount": commission.get("amount"),
            "affiliate_user_id": str(affiliate.get("user_id")) if affiliate.get("user_id") else None,
        })
        # #endregion
        AffiliateService._notify_sale(affiliate, product, commission)
        return commission

    @staticmethod
    def review_commission(commission_id, status, admin_id, notes=""):
        commission = AffiliateCommissionModel.get_by_id(commission_id)
        if not commission:
            raise AffiliateError("Commission not found", 404)
        if commission.get("status") not in ("pending", "available"):
            raise AffiliateError("Commission cannot be updated", 400)
        if status not in ("available", "cancelled"):
            raise AffiliateError("status must be available or cancelled", 400)
        return AffiliateCommissionModel.update(commission_id, {
            "status": status,
            "approved_by": admin_id if status == "available" else None,
            "approved_at": utcnow() if status == "available" else None,
            "notes": notes or commission.get("notes") or "",
        })

    @staticmethod
    def list_sales(user):
        affiliate = AffiliateService.require_affiliate(user)
        commissions = AffiliateCommissionModel.list_for_affiliate(affiliate["_id"])
        products = {item["_id"]: item for item in AffiliateProductModel.list_products()}
        return [
            {
                **item,
                "product_name": (products.get(item.get("product_id")) or {}).get("name"),
            }
            for item in commissions
        ]

    @staticmethod
    def get_wallet(user):
        affiliate = AffiliateService.require_affiliate(user)
        return {
            **AffiliateService._enrich_affiliate(affiliate),
            "commissions": AffiliateService.list_sales(user),
            "withdrawals": AffiliateWithdrawalModel.list_for_affiliate(affiliate["_id"]),
            "settings": AffiliateSettingsModel.get(),
        }

    @staticmethod
    def request_withdrawal(user, data):
        affiliate = AffiliateService.require_affiliate(user)
        settings = AffiliateSettingsModel.get()
        if not settings.get("withdrawals_enabled"):
            raise AffiliateError("Withdrawals are not enabled", 400)
        amount = round(float(data.get("amount") or 0), 2)
        if amount <= 0:
            raise AffiliateError("amount must be greater than 0", 400)
        min_amount = float(settings.get("min_withdrawal_amount") or 0)
        if amount < min_amount:
            raise AffiliateError(f"Minimum withdrawal is {min_amount:.2f}", 400)
        wallet = AffiliateService.wallet(affiliate["_id"])
        if amount > wallet["available"] + 0.001:
            raise AffiliateError("Insufficient available balance", 400)
        pix_key = (data.get("pix_key") or "").strip()
        full_name = (data.get("full_name") or "").strip()
        cpf = _digits(data.get("cpf"))
        if settings.get("pix_required") and len(pix_key) < 5:
            raise AffiliateError("pix_key is required", 400)
        if len(full_name) < 3:
            raise AffiliateError("full_name is required", 400)
        if len(cpf) not in (11, 14):
            raise AffiliateError("Inform a valid CPF or CNPJ", 400)
        withdrawal = AffiliateWithdrawalModel.create({
            "affiliate_id": affiliate["_id"],
            "user_id": user._id,
            "amount": amount,
            "pix_key": pix_key,
            "full_name": full_name,
            "cpf": cpf,
            "bank": data.get("bank"),
        })
        AffiliateService._notify_withdrawal(user, affiliate, withdrawal)
        return withdrawal

    @staticmethod
    def review_withdrawal(withdrawal_id, status, admin_id, notes=""):
        withdrawal = AffiliateWithdrawalModel.get_by_id(withdrawal_id)
        if not withdrawal:
            raise AffiliateError("Withdrawal not found", 404)
        if withdrawal.get("status") != "processing":
            raise AffiliateError("Withdrawal is not processing", 400)
        if status not in ("paid", "rejected"):
            raise AffiliateError("status must be paid or rejected", 400)
        return AffiliateWithdrawalModel.update(withdrawal_id, {
            "status": status,
            "reviewed_by": admin_id,
            "reviewed_at": utcnow(),
            "notes": notes,
        })

    @staticmethod
    def record_click(referral_code, product_slug=None):
        code = (referral_code or "").strip().upper()
        if not code:
            raise AffiliateError("referral_code is required", 400)
        affiliate = AffiliateModel.find_by_code(code)
        if not affiliate:
            raise AffiliateError("Invalid referral code", 404)
        return AffiliateClickModel.record(code, product_slug=product_slug)

    @staticmethod
    def _notify_application(user, product, application):
        name = user.name or user.email or "Usuário"
        body = (
            f"{name} solicitou afiliação no produto {product.get('name')}. "
            "Pedido em análise."
        )
        AffiliateService._alert_admins(
            title="Solicitação de afiliação",
            body=body,
            kind="application",
            extra={"application_id": application["_id"], "user_id": user._id, "product_id": product["_id"]},
            support_user_id=user._id,
            support_body=body,
        )

    @staticmethod
    def _notify_sale(affiliate, product, commission):
        user = UserModel.find_by_id(affiliate.get("user_id"))
        name = (user.name if user else None) or "Afiliado"
        sale_body = (
            f"{name} fez uma venda de {product.get('name')} e recebeu "
            f"R$ {commission.get('amount'):.2f} de comissão ({commission.get('percent')}%)."
        )
        pending_body = (
            f"{name} tem saldo pendente de comissão: R$ {commission.get('amount'):.2f} "
            f"({product.get('name')})."
        )
        AffiliateService._notify_affiliate_sale(affiliate, product, commission)
        AffiliateService._alert_admins(
            title="Venda de afiliado",
            body=sale_body,
            kind="sale",
            extra={
                "commission_id": commission["_id"],
                "user_id": affiliate.get("user_id"),
                "product_id": product["_id"],
            },
            support_user_id=None,
        )
        AffiliateService._alert_admins(
            title="Saldo pendente de afiliado",
            body=pending_body,
            kind="pending_balance",
            extra={
                "commission_id": commission["_id"],
                "user_id": affiliate.get("user_id"),
                "product_id": product["_id"],
            },
            support_user_id=affiliate.get("user_id"),
            support_body=pending_body,
        )

    @staticmethod
    def _notify_affiliate_sale(affiliate, product, commission):
        user_id = affiliate.get("user_id")
        if not user_id:
            # #region agent log
            _dbg("C", "affiliate_service.py:_notify_affiliate_sale", "no affiliate user_id", {
                "affiliate_id": str(affiliate.get("_id")) if affiliate.get("_id") else None,
            })
            # #endregion
            return
        amount = float(commission.get("amount") or 0)
        percent = commission.get("percent")
        product_name = product.get("name") or "produto"
        title = "Você fez uma venda!"
        body = (
            f"Sua venda de {product_name} gerou R$ {amount:.2f} de comissão ({percent}%). "
            "O valor foi creditado como saldo em análise."
        )
        try:
            from src.app.services.notification_service import NotificationService

            # #region agent log
            _dbg("C", "affiliate_service.py:_notify_affiliate_sale", "notify_affiliate_sale start", {
                "user_id": str(user_id),
                "amount": amount,
            })
            # #endregion
            NotificationService.notify_affiliate_sale(
                user_id=str(user_id),
                title=title,
                body=body,
                extra_data={
                    "kind": "sale",
                    "commission_id": commission.get("_id"),
                    "product_id": product.get("_id"),
                    "amount": amount,
                    "percent": percent,
                    "sale_amount": commission.get("sale_amount"),
                },
            )
            # #region agent log
            _dbg("C", "affiliate_service.py:_notify_affiliate_sale", "notify_affiliate_sale called", {
                "user_id": str(user_id),
                "amount": amount,
            })
            # #endregion
        except Exception as exc:
            # #region agent log
            _dbg("C", "affiliate_service.py:_notify_affiliate_sale", "notify exception", {
                "error": type(exc).__name__,
            })
            # #endregion
            pass

    @staticmethod
    def _notify_withdrawal(user, affiliate, withdrawal):
        name = user.name or user.email or "Afiliado"
        body = (
            f"{name} solicitou saque de R$ {withdrawal.get('amount'):.2f}. "
            f"PIX: {withdrawal.get('pix_key')}."
        )
        AffiliateService._alert_admins(
            title="Saque de afiliado",
            body=body,
            kind="withdrawal",
            extra={
                "withdrawal_id": withdrawal["_id"],
                "user_id": user._id,
                "affiliate_id": affiliate["_id"],
            },
            support_user_id=user._id,
            support_body=body,
        )

    @staticmethod
    def _alert_admins(title, body, kind, extra=None, support_user_id=None, support_body=None):
        try:
            from src.app.services.notification_service import NotificationService

            NotificationService.notify_admins_affiliate(
                title=title,
                body=body,
                kind=kind,
                extra_data=extra or {},
            )
        except Exception:
            pass
        if support_user_id and support_body:
            try:
                from src.app.services.support_service import SupportService

                SupportService.post_system_message(support_user_id, support_body)
            except Exception:
                pass
