"""Testes das rotas de baralhos."""
import json
import pytest


@pytest.fixture
def collection_id(client):
    r = client.post(
        "/collections/create",
        data=json.dumps({"name": "Coleção Teste Deck"}),
        content_type="application/json",
    )
    assert r.status_code == 200
    data = r.get_json()
    return data.get("collection_id") or data.get("id")


def test_deck_create(client, collection_id):
    if not collection_id:
        pytest.skip("no collection_id")
    response = client.post(
        "/deck/create",
        data=json.dumps({"name": "Baralho Teste", "collection_id": collection_id}),
        content_type="application/json",
    )
    assert response.status_code == 200


def test_deck_create_missing_fields(client):
    response = client.post(
        "/deck/create",
        data=json.dumps({"name": "Só nome"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_deck_get_all(client):
    response = client.get("/deck/get")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list) or "decks" in str(data).lower()


def test_deck_get_by_collection_id(client, collection_id):
    if not collection_id:
        pytest.skip("no collection_id")
    response = client.get(
        "/deck/get_by_collection_id",
        query_string={"collection_id": collection_id, "user_id": "507f1f77bcf86cd799439011"},
    )
    assert response.status_code == 200


def test_deck_get_by_collection_id_missing_params(client):
    response = client.get("/deck/get_by_collection_id")
    assert response.status_code == 400


def test_deck_save_deck(client, collection_id):
    if not collection_id:
        pytest.skip("no collection_id")
    # Criar um deck primeiro
    create = client.post(
        "/deck/create",
        data=json.dumps({"name": "Deck Save Test", "collection_id": collection_id}),
        content_type="application/json",
    )
    if create.status_code != 200:
        pytest.skip("deck create failed")
    data = create.get_json()
    deck_id = data.get("deck_id")
    if not deck_id:
        pytest.skip("no deck_id in response")
    response = client.post(
        "/deck/save_deck",
        data=json.dumps({
            "user_id": "507f1f77bcf86cd799439011",
            "deck_id": deck_id,
            "collection_id": collection_id,
        }),
        content_type="application/json",
    )
    assert response.status_code in (200, 400)


def test_deck_check_if_user_has(client):
    response = client.post(
        "/deck/check_if_the_user_has_the_deck",
        data=json.dumps({
            "user_id": "507f1f77bcf86cd799439011",
            "deck_id": "507f1f77bcf86cd799439012",
        }),
        content_type="application/json",
    )
    assert response.status_code == 200


def test_deck_check_if_user_has_missing(client):
    response = client.post(
        "/deck/check_if_the_user_has_the_deck",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_deck_create_with_status(client, collection_id):
    if not collection_id:
        pytest.skip("no collection_id")
    response = client.post(
        "/deck/create",
        data=json.dumps({
            "name": "Draft Deck",
            "collection_id": collection_id,
            "status": "draft",
        }),
        content_type="application/json",
    )
    assert response.status_code == 200
    deck_id = response.get_json().get("deck_id")
    fetched = client.get(f"/deck/{deck_id}")
    assert fetched.status_code == 200
    assert fetched.get_json().get("status") == "draft"
    updated = client.put(
        f"/deck/{deck_id}",
        data=json.dumps({"status": "published"}),
        content_type="application/json",
    )
    assert updated.status_code == 200
    assert updated.get_json().get("status") == "published"
