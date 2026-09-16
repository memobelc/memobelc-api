"""Coupon validation."""

from src.app.models.coupon_model import CouponModel
from src.app.utils.billing_utils import apply_discount, parse_datetime, utcnow


class CouponService:
    @staticmethod
    def validate(code, product_type=None, product_id=None):
        coupon = CouponModel.get_by_code(code)
        if not coupon:
            return None, "Invalid coupon"
        if not coupon.get("is_active"):
            return None, "Coupon is inactive"
        now = utcnow()
        starts = parse_datetime(coupon.get("starts_at"))
        expires = parse_datetime(coupon.get("expires_at"))
        if starts and now < starts:
            return None, "Coupon is not active yet"
        if expires and now > expires:
            return None, "Coupon has expired"
        max_uses = coupon.get("max_uses")
        if max_uses is not None and int(coupon.get("used_count") or 0) >= int(max_uses):
            return None, "Coupon usage limit reached"
        types = coupon.get("applicable_product_types") or []
        if types and product_type and product_type not in types:
            return None, "Coupon does not apply to this product"
        plan_ids = coupon.get("applicable_plan_ids") or []
        product_ids = coupon.get("applicable_product_ids") or []
        allowed_ids = set(plan_ids + product_ids)
        if allowed_ids and product_id and str(product_id) not in allowed_ids:
            return None, "Coupon does not apply to this product"
        return coupon, None

    @staticmethod
    def quote(amount, code, product_type=None, product_id=None):
        coupon, error = CouponService.validate(code, product_type, product_id)
        if error:
            return None, error
        return {
            "coupon": coupon,
            "original_amount": float(amount or 0),
            "final_amount": apply_discount(amount, coupon),
        }, None
