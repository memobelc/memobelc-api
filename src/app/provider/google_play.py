"""Google Play Developer API client for purchase verification and RTDN."""

import json
import base64

import requests

from src.app.config import Config


class GooglePlayError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


class GooglePlay:
    TOKEN_URI = "https://oauth2.googleapis.com/token"
    PUBLISHER_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"

    @staticmethod
    def is_configured():
        return bool(
            Config.GOOGLE_PLAY_PACKAGE_NAME
            and (Config.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON or Config.GOOGLE_PLAY_SERVICE_ACCOUNT_FILE)
        )

    @staticmethod
    def _service_account_info():
        if Config.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON:
            return json.loads(Config.GOOGLE_PLAY_SERVICE_ACCOUNT_JSON)
        if Config.GOOGLE_PLAY_SERVICE_ACCOUNT_FILE:
            with open(Config.GOOGLE_PLAY_SERVICE_ACCOUNT_FILE, "r", encoding="utf-8") as handle:
                return json.load(handle)
        return None

    @staticmethod
    def _access_token():
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise GooglePlayError("google-auth is not installed", 503) from exc
        info = GooglePlay._service_account_info()
        if not info:
            raise GooglePlayError("Google Play is not configured", 503)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/androidpublisher"],
        )
        credentials.refresh(Request())
        return credentials.token

    @staticmethod
    def _get(path):
        token = GooglePlay._access_token()
        response = requests.get(
            f"{GooglePlay.PUBLISHER_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            raise GooglePlayError(payload.get("error", {}).get("message") or str(payload), response.status_code)
        return payload

    @staticmethod
    def _post(path, json_body=None):
        token = GooglePlay._access_token()
        response = requests.post(
            f"{GooglePlay.PUBLISHER_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=json_body or {},
            timeout=30,
        )
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            raise GooglePlayError(payload.get("error", {}).get("message") or str(payload), response.status_code)
        return payload

    @staticmethod
    def verify_subscription(sku, purchase_token):
        package = Config.GOOGLE_PLAY_PACKAGE_NAME
        return GooglePlay._get(
            f"/applications/{package}/purchases/subscriptions/{sku}/tokens/{purchase_token}"
        )

    @staticmethod
    def verify_product(sku, purchase_token):
        package = Config.GOOGLE_PLAY_PACKAGE_NAME
        return GooglePlay._get(
            f"/applications/{package}/purchases/products/{sku}/tokens/{purchase_token}"
        )

    @staticmethod
    def acknowledge_subscription(sku, purchase_token):
        package = Config.GOOGLE_PLAY_PACKAGE_NAME
        return GooglePlay._post(
            f"/applications/{package}/purchases/subscriptions/{sku}/tokens/{purchase_token}:acknowledge"
        )

    @staticmethod
    def acknowledge_product(sku, purchase_token):
        package = Config.GOOGLE_PLAY_PACKAGE_NAME
        return GooglePlay._post(
            f"/applications/{package}/purchases/products/{sku}/tokens/{purchase_token}:acknowledge"
        )

    @staticmethod
    def verify_rtdn_token(request_token):
        expected = Config.GOOGLE_PLAY_RTDN_TOKEN
        if not expected:
            return True
        return request_token == expected

    @staticmethod
    def decode_rtdn(body):
        """Decode Pub/Sub push payload into a Play notification dict."""
        message = (body or {}).get("message") or {}
        data = message.get("data")
        if not data:
            return body
        try:
            decoded = base64.b64decode(data).decode("utf-8")
            return json.loads(decoded)
        except Exception:
            return body
