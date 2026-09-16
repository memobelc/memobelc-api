"""Asaas HTTP client (sandbox or production)."""

from datetime import timedelta, timezone

import requests

from src.app.config import Config
from src.app.utils.billing_utils import utcnow


class AsaasError(Exception):
    def __init__(self, message, status_code=400, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class Asaas:
    @staticmethod
    def is_configured():
        return bool(Config.ASAAS_API_KEY)

    @staticmethod
    def _headers():
        if not Asaas.is_configured():
            raise AsaasError("Asaas is not configured", 503)
        return {
            "Content-Type": "application/json",
            "access_token": Config.ASAAS_API_KEY,
        }

    @staticmethod
    def _url(path):
        base = (Config.ASAAS_API_URL or "https://api-sandbox.asaas.com/v3").rstrip("/")
        return f"{base}{path}"

    @staticmethod
    def _request(method, path, json=None, params=None):
        try:
            response = requests.request(
                method,
                Asaas._url(path),
                headers=Asaas._headers(),
                json=json,
                params=params,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise AsaasError(str(exc), 502)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400:
            errors = payload.get("errors") or payload.get("message") or payload
            raise AsaasError(str(errors), response.status_code, payload)
        return payload

    @staticmethod
    def verify_webhook(headers):
        expected = Config.ASAAS_WEBHOOK_TOKEN
        if not expected:
            return True
        token = headers.get("asaas-access-token") or headers.get("Asaas-Access-Token")
        return token == expected

    @staticmethod
    def create_customer(name, email, external_reference=None, cpf_cnpj=None):
        payload = {
            "name": name or email,
            "email": email,
            "externalReference": external_reference,
        }
        if cpf_cnpj:
            payload["cpfCnpj"] = cpf_cnpj
        return Asaas._request("POST", "/customers", json=payload)

    @staticmethod
    def update_customer(customer_id, payload):
        return Asaas._request("PUT", f"/customers/{customer_id}", json=payload)

    @staticmethod
    def get_customer(customer_id):
        return Asaas._request("GET", f"/customers/{customer_id}")

    @staticmethod
    def create_subscription(payload):
        return Asaas._request("POST", "/subscriptions", json=payload)

    @staticmethod
    def update_subscription(subscription_id, payload):
        return Asaas._request("PUT", f"/subscriptions/{subscription_id}", json=payload)

    @staticmethod
    def get_subscription(subscription_id):
        return Asaas._request("GET", f"/subscriptions/{subscription_id}")

    @staticmethod
    def cancel_subscription(subscription_id):
        return Asaas._request("DELETE", f"/subscriptions/{subscription_id}")

    @staticmethod
    def list_subscription_payments(subscription_id):
        return Asaas._request("GET", f"/subscriptions/{subscription_id}/payments")

    @staticmethod
    def create_payment(payload):
        return Asaas._request("POST", "/payments", json=payload)

    @staticmethod
    def get_payment(payment_id):
        return Asaas._request("GET", f"/payments/{payment_id}")

    @staticmethod
    def refund_payment(payment_id, value=None):
        body = {}
        if value is not None:
            body["value"] = value
        return Asaas._request("POST", f"/payments/{payment_id}/refund", json=body or None)

    @staticmethod
    def get_pix_qr_code(payment_id):
        return Asaas._request("GET", f"/payments/{payment_id}/pixQrCode")

    @staticmethod
    def tokenize_credit_card(customer_id, credit_card, credit_card_holder, remote_ip=None):
        payload = {
            "customer": customer_id,
            "creditCard": credit_card,
            "creditCardHolderInfo": credit_card_holder,
        }
        if remote_ip:
            payload["remoteIp"] = remote_ip
        return Asaas._request("POST", "/creditCard/tokenizeCreditCard", json=payload)

    @staticmethod
    def update_subscription_credit_card(
        subscription_id,
        credit_card=None,
        credit_card_holder=None,
        remote_ip=None,
        credit_card_token=None,
    ):
        payload = {}
        if credit_card_holder:
            payload["creditCardHolderInfo"] = credit_card_holder
        if credit_card_token:
            payload["creditCardToken"] = credit_card_token
        elif credit_card:
            payload["creditCard"] = credit_card
        if remote_ip:
            payload["remoteIp"] = remote_ip
        return Asaas._request("PUT", f"/subscriptions/{subscription_id}", json=payload)

    @staticmethod
    def due_date_today():
        sao_paulo = timezone(timedelta(hours=-3))
        return utcnow().astimezone(sao_paulo).strftime("%Y-%m-%d")

    @staticmethod
    def default_next_due_date(trial_days=0):
        days = max(int(trial_days or 0), 0)
        if days == 0:
            days = 1
        sao_paulo = timezone(timedelta(hours=-3))
        return (utcnow().astimezone(sao_paulo) + timedelta(days=days)).strftime("%Y-%m-%d")
