"""Fernet helpers for system setting secrets."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.app.config import Config


def _fernet():
    secret = getattr(Config, "SETTINGS_ENCRYPTION_KEY", None) or Config.SECRET_KEY
    digest = hashlib.sha256(str(secret).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_value(plaintext):
    if plaintext is None:
        return ""
    text = str(plaintext)
    if text == "":
        return ""
    return _fernet().encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_value(stored):
    if stored is None:
        return ""
    text = str(stored)
    if text == "":
        return ""
    try:
        return _fernet().decrypt(text.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return text


def mask_value(value):
    if not value:
        return ""
    text = str(value)
    if len(text) <= 4:
        return "****"
    return f"****{text[-4:]}"
