"""Testes das regras principais de assinatura, cupons, entitlements e webhooks."""
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from src.app import mongo
from bson import ObjectId
from src.app.models.book_model import BookModel
from src.app.models.coupon_model import CouponModel
from src.app.models.entitlement_model import EntitlementModel
from src.app.models.plan_model import PlanModel
from src.app.models.subscription_model import SubscriptionModel
from src.app.models.user_model import UserModel
from src.app.services.billing_service import BillingService
from src.app.services.entitlement_service import EntitlementService
from werkzeug.security import check_password_hash
from src.app.utils.billing_utils import utcnow, invoice_description


def _auth_user(client, email, password="password123", name="User", admin=False):
    client.post(
        "/auth/register",
        json={"name": name, "email": email, "password": password},
        content_type="application/json",
    )
    roles = ["user", "admin"] if admin else ["user"]
    mongo.db.users.update_one(
        {"email": email},
        {"$set": {"is_confirmed": True, "roles": roles, "role": "admin" if admin else "user"}},
    )
    user = mongo.db.users.find_one({"email": email})
    UserModel.update_roles(str(user["_id"]), roles)
    login = client.post(
        "/auth/login",
        json={"email": email, "password": password},
        content_type="application/json",
    )
    data = login.get_json() or {}
    token = data.get("token") or (data.get("pending") or [None, None])[1]
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, str(user["_id"])


def _create_plan(admin_headers, client, **overrides):
    payload = {
        "name": "Pro",
        "description": "Full access",
        "price": 49.9,
        "cycle": "MONTHLY",
        "trial_days": 0,
        "included_service_keys": ["talk_to_me", "books"],
        "is_active": True,
        "is_public": True,
        "google_play_product_id": "memobelc_pro_monthly",
    }
    payload.update(overrides)
    response = client.post("/plans/admin", headers=admin_headers, data=json.dumps(payload))
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def test_public_plans_and_admin_crud(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_{suffix}@example.com", admin=True)
    plan = _create_plan(admin_headers, client, name=f"Plan {suffix}")
    listed = client.get("/plans/public")
    assert listed.status_code == 200
    assert any(item["_id"] == plan["_id"] for item in listed.get_json()["plans"])
    updated = client.put(
        f"/plans/admin/{plan['_id']}",
        headers=admin_headers,
        data=json.dumps({"price": 79.9, "is_active": True}),
    )
    assert updated.status_code == 200
    assert updated.get_json()["price"] == 79.9


def test_coupon_validation_rules(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_c_{suffix}@example.com", admin=True)
    user_headers, _ = _auth_user(client, f"user_c_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"Coupon plan {suffix}")
    created = client.post(
        "/coupons/admin",
        headers=admin_headers,
        data=json.dumps({
            "code": f"SAVE{suffix[:4]}",
            "discount_type": "percent",
            "value": 10,
            "duration": "once",
            "max_uses": 1,
            "applicable_product_types": ["plan"],
            "applicable_plan_ids": [plan["_id"]],
        }),
    )
    assert created.status_code == 201, created.get_json()
    code = created.get_json()["code"]
    ok = client.post(
        "/coupons/validate",
        headers=user_headers,
        data=json.dumps({"code": code, "amount": 100, "product_type": "plan", "product_id": plan["_id"]}),
    )
    assert ok.status_code == 200
    assert ok.get_json()["final_amount"] == 90
    other_plan = _create_plan(admin_headers, client, name=f"Other {suffix}")
    denied = client.post(
        "/coupons/validate",
        headers=user_headers,
        data=json.dumps({"code": code, "amount": 100, "product_type": "plan", "product_id": other_plan["_id"]}),
    )
    assert denied.status_code == 400
    CouponModel.record_redemption(created.get_json()["_id"], "user")
    exhausted = client.post(
        "/coupons/validate",
        headers=user_headers,
        data=json.dumps({"code": code, "amount": 100, "product_type": "plan", "product_id": plan["_id"]}),
    )
    assert exhausted.status_code == 400


def test_duplicate_subscription_blocked(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_d_{suffix}@example.com", admin=True)
    user_headers, user_id = _auth_user(client, f"user_d_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"Dup {suffix}")
    SubscriptionModel.create({
        "user_id": user_id,
        "plan_id": plan["_id"],
        "provider": "asaas",
        "status": "active",
        "value": 49.9,
        "provider_subscription_id": f"sub_{suffix}",
    })
    response = client.post(
        "/billing/checkout",
        headers=user_headers,
        data=json.dumps({
            "product_type": "plan",
            "product_id": plan["_id"],
            "platform": "web",
            "billing_type": "PIX",
            "cpf_cnpj": "52998224725",
        }),
    )
    assert response.status_code == 409


def test_checkout_requires_pix_or_card(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_bt_{suffix}@example.com", admin=True)
    user_headers, _ = _auth_user(client, f"user_bt_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"BT {suffix}")
    response = client.post(
        "/billing/checkout",
        headers=user_headers,
        data=json.dumps({
            "product_type": "plan",
            "product_id": plan["_id"],
            "cpf_cnpj": "52998224725",
        }),
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "billing_type_required"


@patch("src.app.services.billing_service.Asaas.get_pix_qr_code", return_value={"encodedImage": "aaa==", "payload": "00020126", "expirationDate": "2026-08-28 23:59:59"})
@patch("src.app.services.billing_service.Asaas.list_subscription_payments", return_value={"data": [{"id": "pay_1", "status": "PENDING", "invoiceUrl": "https://asaas.test/pay"}]})
@patch("src.app.services.billing_service.Asaas.create_customer", return_value={"id": "cus_1"})
@patch("src.app.services.billing_service.Asaas.create_subscription", return_value={"id": "sub_1", "invoiceUrl": "https://asaas.test/pay"})
def test_asaas_checkout_creates_pending_subscription(mock_sub, mock_cus, mock_list, mock_pix, client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_a_{suffix}@example.com", admin=True)
    user_headers, user_id = _auth_user(client, f"user_a_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"Asaas {suffix}")
    response = client.post(
        "/billing/checkout",
        headers=user_headers,
        data=json.dumps({
            "product_type": "plan",
            "product_id": plan["_id"],
            "platform": "web",
            "billing_type": "PIX",
            "cpf_cnpj": "52998224725",
        }),
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["provider"] == "asaas"
    assert body["billing_type"] == "PIX"
    assert body["pix"]["payload"] == "00020126"
    assert body["payment"]["status"] == "pending"
    stored = SubscriptionModel.get_active_for_user(user_id)
    assert stored is not None
    assert stored["provider_subscription_id"] == "sub_1"
    pix = client.get(f"/billing/payments/{body['payment']['_id']}/pix", headers=user_headers)
    assert pix.status_code == 200
    assert pix.get_json()["pix"]["payload"] == "00020126"


def test_webhook_idempotency_and_entitlements(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_w_{suffix}@example.com", admin=True)
    _, user_id = _auth_user(client, f"user_w_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"Hook {suffix}")
    subscription = SubscriptionModel.create({
        "user_id": user_id,
        "plan_id": plan["_id"],
        "provider": "asaas",
        "status": "pending",
        "value": 49.9,
        "provider_subscription_id": f"sub_hook_{suffix}",
    })
    payload = {
        "id": f"evt_{suffix}",
        "event": "PAYMENT_CONFIRMED",
        "payment": {
            "id": f"pay_{suffix}",
            "subscription": f"sub_hook_{suffix}",
            "value": 49.9,
            "billingType": "PIX",
            "invoiceUrl": "https://asaas.test/pay",
        },
    }
    first = client.post("/billing/asaas/webhook", json=payload)
    second = client.post("/billing/asaas/webhook", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    updated = SubscriptionModel.get_by_id(subscription["_id"])
    assert updated["status"] == "active"
    books = EntitlementService.user_book_ids(user_id)
    entitlements = EntitlementModel.list_active_for_user(user_id)
    assert any(item["type"] == "plan" for item in entitlements)


def test_manual_grant_and_revoke(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_g_{suffix}@example.com", admin=True)
    _, user_id = _auth_user(client, f"user_g_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"Grant {suffix}")
    granted = client.post(
        "/admin/billing/grants",
        headers=admin_headers,
        data=json.dumps({"user_id": user_id, "type": "plan", "resource_id": plan["_id"]}),
    )
    assert granted.status_code == 200, granted.get_json()
    entitlements = client.get(f"/admin/billing/users/{user_id}/entitlements", headers=admin_headers)
    items = entitlements.get_json()["entitlements"]
    plan_ent = next(item for item in items if item["type"] == "plan" and not item.get("revoked_at"))
    revoked = client.delete(f"/admin/billing/grants/{plan_ent['_id']}", headers=admin_headers)
    assert revoked.status_code == 200
    assert revoked.get_json()["entitlement"]["revoked_at"]


def test_external_sale_creates_user(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_e_{suffix}@example.com", admin=True)
    plan = _create_plan(admin_headers, client, name=f"Ext {suffix}")
    email = f"newbuyer_{suffix}@example.com"
    with patch("src.app.services.billing_service.mail.send"):
        response = client.post(
            "/admin/billing/external-sales",
            headers=admin_headers,
            data=json.dumps({
                "email": email,
                "name": "Buyer",
                "product_type": "plan",
                "product_ids": [plan["_id"]],
                "amount": 10,
            }),
        )
    assert response.status_code == 201, response.get_json()
    assert response.get_json()["user_created"] is True
    assert UserModel.find_by_email(email) is not None


def test_grace_period_keeps_access():
    plan = PlanModel.create({
        "name": "Grace",
        "price": 10,
        "cycle": "MONTHLY",
        "included_service_keys": ["talk_to_me"],
    })
    user_id = str(mongo.db.users.insert_one({
        "name": "Grace User",
        "email": f"grace_{uuid.uuid4().hex[:8]}@example.com",
        "password": "x",
        "roles": ["user"],
        "role": "user",
        "is_confirmed": True,
        "collections": [],
    }).inserted_id)
    SubscriptionModel.create({
        "user_id": user_id,
        "plan_id": plan["_id"],
        "provider": "asaas",
        "status": "overdue",
        "value": 10,
        "grace_until": utcnow() + timedelta(hours=12),
        "provider_subscription_id": f"grace_{user_id}",
    })
    user = UserModel.find_by_id(user_id)
    assert EntitlementService.is_subscriber(user_id) is True
    allowed, _ = EntitlementService.can_access_service(user, "talk_to_me")
    assert allowed is True


def _set_service_action(client, admin_headers, service_key, action):
    updated = client.put(
        f"/admin/billing/access/{service_key}",
        headers=admin_headers,
        data=json.dumps({
            "rules": [{"audience": "everyone", "action": action, "plan_ids": []}],
        }),
    )
    assert updated.status_code == 200, updated.get_json()


def test_service_middleware_blocks_when_hidden(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_m_{suffix}@example.com", admin=True)
    user_headers, _ = _auth_user(client, f"user_m_{suffix}@example.com")
    _set_service_action(client, admin_headers, "talk_to_me", "hide")
    blocked = client.post(
        "/chat/talk_to_me",
        headers=user_headers,
        data=json.dumps({"message": "hi", "history": [], "settings": {}}),
    )
    assert blocked.status_code == 403
    assert blocked.get_json().get("action") == "hide"
    _set_service_action(client, admin_headers, "talk_to_me", "allow")


def test_disabled_service_stays_blocked_for_subscriber(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_dis_{suffix}@example.com", admin=True)
    _, user_id = _auth_user(client, f"user_dis_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"Dis {suffix}", included_service_keys=["talk_to_me"])
    SubscriptionModel.create({
        "user_id": user_id,
        "plan_id": plan["_id"],
        "provider": "asaas",
        "status": "active",
        "value": 49.9,
        "provider_subscription_id": f"sub_dis_{suffix}",
    })
    _set_service_action(client, admin_headers, "talk_to_me", "disabled")
    user = UserModel.find_by_id(user_id)
    action, _ = EntitlementService.service_action(user, "talk_to_me")
    allowed, payload = EntitlementService.can_access_service(user, "talk_to_me")
    assert action == "disabled"
    assert allowed is False
    assert payload["action"] == "disabled"
    _set_service_action(client, admin_headers, "talk_to_me", "allow")


def test_allow_is_visible_without_subscription(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_allow_{suffix}@example.com", admin=True)
    _, user_id = _auth_user(client, f"user_allow_{suffix}@example.com")
    mongo.db.service_access_rules.update_one(
        {"service_key": "talk_to_me"},
        {"$set": {"rules": [
            {"audience": "non_subscribers", "action": "disabled_upgrade", "plan_ids": []},
            {"audience": "everyone", "action": "allow", "plan_ids": []},
        ]}},
        upsert=True,
    )
    user = UserModel.find_by_id(user_id)
    action, _ = EntitlementService.service_action(user, "talk_to_me")
    allowed, _ = EntitlementService.can_access_service(user, "talk_to_me")
    assert action == "allow"
    assert allowed is True
    resolved = EntitlementService.resolve(user)
    assert resolved["services"]["talk_to_me"]["configured"] == "allow"
    _set_service_action(client, admin_headers, "talk_to_me", "allow")


def test_gated_service_unlocks_for_active_subscriber(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_gate_{suffix}@example.com", admin=True)
    _, user_id = _auth_user(client, f"user_gate_{suffix}@example.com")
    _set_service_action(client, admin_headers, "talk_to_me", "disabled_upgrade")
    user = UserModel.find_by_id(user_id)
    action, _ = EntitlementService.service_action(user, "talk_to_me")
    allowed, _ = EntitlementService.can_access_service(user, "talk_to_me")
    assert action == "disabled_upgrade"
    assert allowed is False
    assert EntitlementService.resolve(user)["services"]["talk_to_me"]["configured"] == "disabled_upgrade"

    plan = _create_plan(
        admin_headers, client, name=f"Any {suffix}", included_service_keys=["books"]
    )
    SubscriptionModel.create({
        "user_id": user_id,
        "plan_id": plan["_id"],
        "provider": "asaas",
        "status": "active",
        "value": 49.9,
        "provider_subscription_id": f"sub_gate_ok_{suffix}",
    })
    user = UserModel.find_by_id(user_id)
    action, _ = EntitlementService.service_action(user, "talk_to_me")
    allowed, _ = EntitlementService.can_access_service(user, "talk_to_me")
    assert action == "allow"
    assert allowed is True
    resolved = EntitlementService.resolve(user)
    assert resolved["services"]["talk_to_me"]["configured"] == "disabled_upgrade"
    assert resolved["services"]["talk_to_me"]["action"] == "allow"
    _set_service_action(client, admin_headers, "talk_to_me", "allow")


def test_hide_stays_hidden_for_subscriber_admin_can_access(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, admin_id = _auth_user(client, f"admin_hide_{suffix}@example.com", admin=True)
    _, user_id = _auth_user(client, f"user_hide_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"Hide {suffix}", included_service_keys=["talk_to_me"])
    SubscriptionModel.create({
        "user_id": user_id,
        "plan_id": plan["_id"],
        "provider": "asaas",
        "status": "active",
        "value": 49.9,
        "provider_subscription_id": f"sub_hide_{suffix}",
    })
    _set_service_action(client, admin_headers, "talk_to_me", "hide")
    user = UserModel.find_by_id(user_id)
    action, _ = EntitlementService.service_action(user, "talk_to_me")
    allowed, _ = EntitlementService.can_access_service(user, "talk_to_me")
    assert action == "hide"
    assert allowed is False

    admin = UserModel.find_by_id(admin_id)
    admin_action, _ = EntitlementService.service_action(admin, "talk_to_me")
    admin_allowed, _ = EntitlementService.can_access_service(admin, "talk_to_me")
    assert admin_action == "hide"
    assert admin_allowed is True
    _set_service_action(client, admin_headers, "talk_to_me", "allow")


def test_redirect_plans_alias_maps_to_gated(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_redir_{suffix}@example.com", admin=True)
    _, user_id = _auth_user(client, f"user_redir_{suffix}@example.com")
    _set_service_action(client, admin_headers, "talk_to_me", "redirect_plans")
    user = UserModel.find_by_id(user_id)
    action, _ = EntitlementService.service_action(user, "talk_to_me")
    assert action == "disabled_upgrade"
    _set_service_action(client, admin_headers, "talk_to_me", "allow")


def test_google_verify_invalid_token(client):
    suffix = uuid.uuid4().hex[:8]
    user_headers, _ = _auth_user(client, f"user_p_{suffix}@example.com")
    with patch("src.app.services.billing_service.GooglePlay.verify_subscription", side_effect=Exception("no")):
        from src.app.provider.google_play import GooglePlayError
        with patch("src.app.services.billing_service.GooglePlay.verify_subscription", side_effect=GooglePlayError("invalid", 400)):
            response = client.post(
                "/billing/google/verify",
                headers=user_headers,
                data=json.dumps({"sku": "x", "purchase_token": "bad", "product_type": "plan"}),
            )
    assert response.status_code == 400


def test_entitlements_me_default_allow(client, auth_headers):
    response = client.get("/entitlements/me", headers=auth_headers)
    assert response.status_code == 200
    services = response.get_json()["services"]
    assert services["home"]["action"] == "allow"


@patch("src.app.services.billing_service.Asaas.get_pix_qr_code", return_value={"encodedImage": "aaa==", "payload": "00020126", "expirationDate": "2026-08-28 23:59:59"})
@patch("src.app.services.billing_service.Asaas.list_subscription_payments")
@patch("src.app.services.billing_service.Asaas.create_customer", return_value={"id": "cus_ios"})
@patch("src.app.services.billing_service.Asaas.create_subscription")
def test_ios_and_android_checkout_use_asaas(mock_sub, mock_cus, mock_list, mock_pix, client):
    mock_sub.side_effect = lambda payload: {"id": f"sub_{uuid.uuid4().hex[:8]}", "invoiceUrl": "https://asaas.test/pay"}
    mock_list.side_effect = lambda sub_id: {"data": [{"id": f"pay_{uuid.uuid4().hex[:8]}", "status": "PENDING", "invoiceUrl": "https://asaas.test/pay"}]}
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_i_{suffix}@example.com", admin=True)
    plan = _create_plan(admin_headers, client, name=f"iOS {suffix}")
    for platform in ("ios", "android"):
        other_headers, _ = _auth_user(client, f"user_{platform}_{suffix}@example.com")
        response = client.post(
            "/billing/checkout",
            headers=other_headers,
            data=json.dumps({
                "product_type": "plan",
                "product_id": plan["_id"],
                "platform": platform,
                "billing_type": "PIX",
                "cpf_cnpj": "52998224725",
            }),
        )
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert body["provider"] == "asaas"
        assert body.get("sku") is None
        assert body["pix"]["payload"] == "00020126"


_CARD = {
    "holder_name": "Ada Lovelace",
    "number": "4111111111111111",
    "expiry_month": "12",
    "expiry_year": "2030",
    "ccv": "123",
    "postal_code": "01310100",
    "address_number": "100",
    "phone": "11999999999",
}


@patch("src.app.services.billing_service.Asaas.list_subscription_payments", return_value={"data": [{"id": "pay_card", "status": "PENDING", "invoiceUrl": "https://asaas.test/card"}]})
@patch("src.app.services.billing_service.Asaas.create_customer", return_value={"id": "cus_card"})
@patch("src.app.services.billing_service.Asaas.create_subscription", return_value={"id": "sub_card", "status": "PENDING", "invoiceUrl": "https://asaas.test/card"})
def test_card_checkout_returns_asaas_hosted_url(mock_sub, mock_cus, mock_list, client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_card_{suffix}@example.com", admin=True)
    user_headers, user_id = _auth_user(client, f"user_card_{suffix}@example.com")
    plan = _create_plan(admin_headers, client, name=f"Card {suffix}")
    response = client.post(
        "/billing/checkout",
        headers=user_headers,
        data=json.dumps({
            "product_type": "plan",
            "product_id": plan["_id"],
            "platform": "web",
            "billing_type": "CREDIT_CARD",
            "cpf_cnpj": "52998224725",
        }),
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["provider"] == "asaas"
    assert body["granted"] is False
    assert body["checkout_url"] == "https://asaas.test/card"
    entitlements = EntitlementModel.list_active_for_user(user_id)
    assert not any(item["type"] == "plan" for item in entitlements)


def _create_paid_book(**overrides):
    payload = {
        "titulo": "Aventuras no Brasil",
        "autor": "Maria Silva",
        "idioma": "pt",
        "nivel": "basico",
        "genero": "ficcao",
        "is_free": False,
        "price": 19.9,
        "sale_mode": "separate",
        "is_published": True,
        "chapters": [{"titulo": "Capítulo 1", "ordem": 1}, {"titulo": "Capítulo 2", "ordem": 2}],
    }
    payload.update(overrides)
    book = BookModel(**payload)
    book.save_to_db()
    return book.to_dict()


def test_invoice_description_includes_book_fields():
    book = {
        "_id": "abc123",
        "titulo": "Aventuras no Brasil",
        "autor": "Maria Silva",
        "idioma": "pt",
        "nivel": "basico",
        "genero": "ficcao",
        "chapters": [{"titulo": "Capítulo 1"}],
    }
    text = invoice_description("book", book)
    assert "Aventuras no Brasil" in text
    assert "Maria Silva" in text
    assert "pt" in text
    assert "Capítulo 1" in text
    assert "abc123" in text


@patch("src.app.services.billing_service.Asaas.verify_webhook", return_value=True)
@patch("src.app.services.billing_service.Asaas.get_pix_qr_code", return_value={"encodedImage": "bbb==", "payload": "00020199", "expirationDate": "2026-08-28 23:59:59"})
@patch("src.app.services.billing_service.Asaas.create_customer", return_value={"id": "cus_book"})
@patch("src.app.services.billing_service.Asaas.create_payment", return_value={"id": "pay_book_1", "status": "PENDING", "invoiceUrl": "https://asaas.test/book"})
def test_book_asaas_checkout_and_webhook_grants_access(mock_pay, mock_cus, mock_pix, mock_wh, client):
    suffix = uuid.uuid4().hex[:8]
    user_headers, user_id = _auth_user(client, f"user_book_{suffix}@example.com")
    book = _create_paid_book(titulo=f"Livro {suffix}")
    response = client.post(
        "/billing/checkout",
        headers=user_headers,
        data=json.dumps({
            "product_type": "book",
            "product_id": book["_id"],
            "platform": "web",
            "billing_type": "PIX",
            "cpf_cnpj": "52998224725",
        }),
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["provider"] == "asaas"
    assert body["pix"]["payload"] == "00020199"
    sent = mock_pay.call_args[0][0]
    assert book["titulo"] in sent["description"]
    assert "Autor:" in sent["description"] or book.get("autor", "Maria Silva") in sent["description"]
    payment_id = body["payment"]["_id"]

    webhook = client.post("/billing/asaas/webhook", json={
        "id": f"evt_book_{suffix}",
        "event": "PAYMENT_CONFIRMED",
        "payment": {
            "id": "pay_book_1",
            "value": 19.9,
            "billingType": "PIX",
            "invoiceUrl": "https://asaas.test/book",
            "externalReference": f"book:{user_id}:{book['_id']}",
        },
    })
    assert webhook.status_code == 200
    user = UserModel.find_by_id(user_id)
    allowed, _ = EntitlementService.can_access_book(user, book["_id"])
    assert allowed is True
    listed = client.get("/books/list", headers=user_headers)
    my_ids = [item["_id"] for item in listed.get_json()["my_books"]]
    assert book["_id"] in my_ids

    synced = client.post(f"/billing/payments/{payment_id}/sync", headers=user_headers)
    assert synced.status_code == 200
    assert synced.get_json()["granted"] is True


def _create_sellable_classroom(teacher_id, **overrides):
    from bson import ObjectId
    from src.app.models.course_model import CourseModel

    collection_id = mongo.db.collections.insert_one({
        "name": "Course collection",
        "decks": [],
        "user_id": ObjectId(teacher_id),
    }).inserted_id
    payload = {
        "name": "Turma checkout",
        "teacher": ObjectId(teacher_id),
        "collection": collection_id,
        "students": [],
        "guests": [],
        "checkout_allowed": True,
        "checkout_enabled": True,
        "price": 97.0,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    payload.update(overrides)
    classroom_id = mongo.db.classrooms.insert_one(payload).inserted_id
    course = CourseModel(
        name="Curso da turma",
        description="Conteúdo",
        classroom_id=str(classroom_id),
        teacher_id=teacher_id,
    )
    course.save_to_db()
    from src.app.models.classroom_model import ClassroomModel
    classroom = ClassroomModel.get_by_id(str(classroom_id))
    classroom["course_id"] = course._id
    return classroom


def test_teacher_cannot_enable_checkout_without_admin(client):
    suffix = uuid.uuid4().hex[:8]
    teacher_headers, teacher_id = _auth_user(client, f"teacher_deny_{suffix}@example.com")
    mongo.db.users.update_one({"_id": __import__("bson").ObjectId(teacher_id)}, {"$set": {"roles": ["user", "teacher"], "role": "teacher"}})
    classroom = _create_sellable_classroom(teacher_id, checkout_allowed=False, checkout_enabled=False, price=None)
    denied = client.put(
        f"/classroom/{classroom['_id']}",
        headers=teacher_headers,
        data=json.dumps({"checkout_enabled": True, "price": 120}),
    )
    assert denied.status_code == 403
    missing = client.get(f"/classroom/public/{classroom['_id']}")
    assert missing.status_code == 404


def test_admin_allows_classroom_checkout_and_teacher_enables(client):
    suffix = uuid.uuid4().hex[:8]
    admin_headers, _ = _auth_user(client, f"admin_ck_{suffix}@example.com", admin=True)
    teacher_headers, teacher_id = _auth_user(client, f"teacher_ok_{suffix}@example.com")
    mongo.db.users.update_one({"_id": __import__("bson").ObjectId(teacher_id)}, {"$set": {"roles": ["user", "teacher"], "role": "teacher"}})
    classroom = _create_sellable_classroom(teacher_id, checkout_allowed=False, checkout_enabled=False, price=None)
    allowed = client.put(
        f"/admin/billing/classrooms/{classroom['_id']}",
        headers=admin_headers,
        data=json.dumps({"checkout_allowed": True}),
    )
    assert allowed.status_code == 200, allowed.get_json()
    enabled = client.put(
        f"/classroom/{classroom['_id']}",
        headers=teacher_headers,
        data=json.dumps({"checkout_enabled": True, "price": 120}),
    )
    assert enabled.status_code == 200, enabled.get_json()
    public = client.get(f"/classroom/public/{classroom['_id']}")
    assert public.status_code == 200
    body = public.get_json()
    assert body["price"] == 120
    assert body["checkout_url"].endswith(f"/checkout/{classroom['_id']}")


def test_authenticated_classroom_checkout_rejected_when_disabled(client):
    suffix = uuid.uuid4().hex[:8]
    _, teacher_id = _auth_user(client, f"teacher_off_{suffix}@example.com")
    user_headers, _ = _auth_user(client, f"buyer_off_{suffix}@example.com")
    classroom = _create_sellable_classroom(teacher_id, checkout_enabled=False)
    response = client.post(
        "/billing/checkout",
        headers=user_headers,
        data=json.dumps({
            "product_type": "classroom",
            "product_id": classroom["_id"],
            "billing_type": "PIX",
            "cpf_cnpj": "52998224725",
        }),
    )
    assert response.status_code == 400


@patch("src.app.services.billing_service.mail.send")
@patch("src.app.services.billing_service.Asaas.verify_webhook", return_value=True)
@patch("src.app.services.billing_service.Asaas.get_pix_qr_code", return_value={"encodedImage": "ccc==", "payload": "000201class", "expirationDate": "2026-08-28 23:59:59"})
@patch("src.app.services.billing_service.Asaas.create_customer", return_value={"id": "cus_class"})
@patch("src.app.services.billing_service.Asaas.create_payment", return_value={"id": "pay_class_1", "status": "PENDING", "invoiceUrl": "https://asaas.test/class"})
def test_public_classroom_checkout_enrolls_student_and_sends_receipt(mock_pay, mock_cus, mock_pix, mock_wh, mock_mail, client):
    suffix = uuid.uuid4().hex[:8]
    _, teacher_id = _auth_user(client, f"teacher_ck_{suffix}@example.com")
    classroom = _create_sellable_classroom(teacher_id, name=f"Turma {suffix}", price=97.0)
    from bson import ObjectId
    module_id = mongo.db.course_modules.insert_one({
        "name": "Módulo 1",
        "order": 0,
        "course_id": ObjectId(classroom["course_id"]),
        "scheduled_at": None,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }).inserted_id
    mongo.db.lessons.insert_one({
        "title": "Aula 1",
        "video_url": "",
        "video_type": "youtube",
        "description": "",
        "order": 0,
        "module_id": module_id,
        "course_id": ObjectId(classroom["course_id"]),
        "visible": True,
        "scheduled_at": None,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    })
    email = f"buyer_ck_{suffix}@example.com"
    response = client.post(
        "/billing/public/checkout",
        data=json.dumps({
            "product_type": "classroom",
            "product_id": classroom["_id"],
            "name": "Aluno Novo",
            "email": email,
            "billing_type": "PIX",
            "cpf_cnpj": "52998224725",
        }),
        content_type="application/json",
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["token"]
    assert body["user_created"] is True
    assert body["pix"]["payload"] == "000201class"
    buyer = UserModel.find_by_email(email)
    assert buyer is not None
    assert buyer.must_change_password is True
    assert check_password_hash(buyer.password, "52998224725")
    payment_id = body["payment"]["_id"]

    webhook = client.post("/billing/asaas/webhook", json={
        "id": f"evt_class_{suffix}",
        "event": "PAYMENT_CONFIRMED",
        "payment": {
            "id": "pay_class_1",
            "value": 97.0,
            "billingType": "PIX",
            "invoiceUrl": "https://asaas.test/class",
            "externalReference": f"classroom:{buyer._id}:{classroom['_id']}",
        },
    })
    assert webhook.status_code == 200
    from src.app.models.classroom_model import ClassroomModel
    assert ClassroomModel.is_student(classroom["_id"], buyer._id)
    entitlements = EntitlementModel.list_active_for_user(buyer._id)
    assert any(item["type"] == "classroom" and item["resource_id"] == classroom["_id"] for item in entitlements)
    assert UserModel.verify_is_confirmed(email) is True
    assert mock_mail.called
    sent_body = mock_mail.call_args[0][0].body
    assert payment_id in sent_body
    assert "Bem-vindo" in sent_body
    assert "CPF" in sent_body

    token = body["token"]
    rejected = client.put(
        "/auth/change_password",
        data=json.dumps({
            "current_password": "52998224725",
            "new_password": "52998224725",
        }),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rejected.status_code == 400
    changed = client.put(
        "/auth/change_password",
        data=json.dumps({
            "current_password": "52998224725",
            "new_password": "newpass123",
        }),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert changed.status_code == 200, changed.get_json()
    assert changed.get_json()["must_change_password"] is False
    buyer = UserModel.find_by_email(email)
    assert buyer.must_change_password is False
    assert check_password_hash(buyer.password, "newpass123")

    mine = client.get("/course/mine", headers={"Authorization": f"Bearer {token}"})
    assert mine.status_code == 200
    courses = mine.get_json().get("courses") or []
    assert any(item["_id"] == classroom["course_id"] for item in courses)


@patch("src.app.services.billing_service.Asaas.verify_webhook", return_value=True)
@patch("src.app.services.billing_service.Asaas.get_pix_qr_code", return_value={"encodedImage": "ccc==", "payload": "000201class", "expirationDate": "2026-08-28 23:59:59"})
@patch("src.app.services.billing_service.Asaas.create_customer", return_value={"id": "cus_class_exist"})
@patch("src.app.services.billing_service.Asaas.create_payment", return_value={"id": "pay_class_exist", "status": "PENDING", "invoiceUrl": "https://asaas.test/class"})
def test_public_checkout_links_existing_profile_without_password(mock_pay, mock_cus, mock_pix, mock_wh, client):
    suffix = uuid.uuid4().hex[:8]
    _, teacher_id = _auth_user(client, f"teacher_exist_{suffix}@example.com")
    classroom = _create_sellable_classroom(teacher_id, name=f"Turma exist {suffix}", price=80.0)
    email = f"already_{suffix}@example.com"
    _, user_id = _auth_user(client, email, password="keep-this-password")
    mongo.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"cpf_cnpj": "52998224725"}})
    response = client.post(
        "/billing/public/checkout",
        data=json.dumps({
            "product_type": "classroom",
            "product_id": classroom["_id"],
            "name": "Nome ignorado",
            "email": email,
            "billing_type": "PIX",
            "cpf_cnpj": "52998224725",
        }),
        content_type="application/json",
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["user_created"] is False
    buyer = UserModel.find_by_email(email)
    assert str(buyer._id) == user_id
    assert check_password_hash(buyer.password, "keep-this-password")
    assert buyer.must_change_password is False
    sync = client.post(
        f"/billing/public/payments/{body['payment']['_id']}/sync",
        data=json.dumps({"email": email, "cpf_cnpj": "52998224725"}),
        content_type="application/json",
    )
    assert sync.status_code == 200
