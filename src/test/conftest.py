"""
Configuração global dos testes.
Usa MONGO_URI_TEST como banco de dados (nunca o banco oficial).
"""
import os
import sys

# Garantir uso do banco de TESTE antes de qualquer import do app
os.environ["TESTING"] = "1"

# Carregar .env para ter MONGO_URI_TEST disponível
from dotenv import load_dotenv
from os import path as os_path

_basedir = os_path.abspath(os_path.join(os_path.dirname(__file__), "../.."))
load_dotenv(os_path.join(_basedir, ".env"))

# Garantir que o src está no path
sys.path.insert(0, _basedir)

import pytest
from src.app import create_app
from src.app.database.mongo import mongo


def _drop_test_collections():
    try:
        for name in list(mongo.db.list_collection_names()):
            mongo.db[name].drop()
    except Exception:
        pass


@pytest.fixture(scope="session")
def app():
    """App Flask em modo teste, conectado ao banco MONGO_URI_TEST."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["MAIL_SUPPRESS_SEND"] = True
    with app.app_context():
        _drop_test_collections()
    yield app
    try:
        _drop_test_collections()
    except Exception:
        pass


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(client):
    """Registra um usuário, faz login e retorna headers com Bearer token."""
    user = {"name": "Test User", "email": "test@example.com", "password": "password123"}
    client.post("/auth/register", json=user)
    r = client.post("/auth/login", json={"email": user["email"], "password": user["password"]})
    data = r.get_json()
    token = data.get("token") or data.get("access_token")
    if not token and data.get("pending"):
        token = data["pending"][1] if len(data["pending"]) > 1 else None
    if not token:
        raise ValueError("Login did not return token")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
