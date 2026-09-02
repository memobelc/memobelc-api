"""Self-service profile and admin coin grants."""

from src.app.models.badge_model import BadgeModel
from src.app.models.coin_ledger_model import CoinLedgerModel
from src.app.models.mission_model import MissionModel
from src.app.models.user_model import ADDRESS_FIELDS, UserModel
from src.app.utils.billing_utils import to_object_id


def _digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def normalize_cpf_cnpj(value):
    digits = _digits_only(value)
    if len(digits) in (11, 14):
        return digits
    return None


def empty_address():
    return {field: "" for field in ADDRESS_FIELDS}


def serialize_profile(user_id, include_rewards=True):
    doc = UserModel.get_document(user_id)
    if not doc:
        return None
    roles = UserModel.normalize_roles(role=doc.get("role"), roles=doc.get("roles"))
    address = doc.get("address") if isinstance(doc.get("address"), dict) else {}
    payload = {
        "_id": str(doc["_id"]),
        "name": doc.get("name") or "",
        "email": doc.get("email") or "",
        "image": doc.get("image"),
        "cpf_cnpj": doc.get("cpf_cnpj") or None,
        "address": {**empty_address(), **{
            field: str(address.get(field) or "") for field in ADDRESS_FIELDS
        }},
        "coins": int(doc.get("coins") or 0),
        "role": UserModel.primary_role(roles),
        "roles": roles,
    }
    if include_rewards:
        MissionModel.complete_eligible_streak_missions(user_id)
        refreshed = UserModel.get_document(user_id) or doc
        payload["coins"] = int(refreshed.get("coins") or 0)
        payload["badges"] = BadgeModel.list_for_user(user_id)
        payload["missions"] = MissionModel.list_for_user(user_id)
    return payload


class ProfileService:
    @staticmethod
    def get_me(user_id):
        return serialize_profile(user_id, include_rewards=True)

    @staticmethod
    def update_me(user_id, data):
        updates = {}
        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                raise ValueError("Name is required")
            updates["name"] = name
        if "image" in data:
            image = (data.get("image") or "").strip()
            updates["image"] = image or None
        if "cpf_cnpj" in data:
            raw = data.get("cpf_cnpj")
            if raw in (None, ""):
                updates["cpf_cnpj"] = None
            else:
                normalized = normalize_cpf_cnpj(raw)
                if not normalized:
                    raise ValueError("Informe um CPF ou CNPJ válido")
                updates["cpf_cnpj"] = normalized
        if "address" in data:
            updates["address"] = UserModel.normalize_address(data.get("address"))
        if not updates:
            return serialize_profile(user_id)
        updated = UserModel.update_profile(user_id, updates)
        if not updated:
            return None
        return serialize_profile(user_id)

    @staticmethod
    def grant_coins(user_id, amount, reason, admin_id):
        try:
            to_object_id(user_id)
        except Exception:
            return None
        amount = int(amount)
        if amount <= 0:
            raise ValueError("amount must be greater than zero")
        if not UserModel.find_by_id(user_id):
            return None
        balance = UserModel.increment_coins(user_id, amount)
        CoinLedgerModel.record(
            user_id,
            amount,
            "grant",
            reason=reason,
            admin_id=admin_id,
        )
        return {"coins": balance, "amount": amount}
