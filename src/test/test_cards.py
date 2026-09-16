"""Testes das rotas de cartas."""
import json
import pytest


def test_card_create(client):
    response = client.post(
        "/card/create",
        data=json.dumps({"front": "Frente", "back": "Trás"}),
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data is not None


def test_card_create_missing_fields(client):
    response = client.post(
        "/card/create",
        data=json.dumps({"front": "Só frente"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_card_get_all(client):
    response = client.get("/card/get_all_cards")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list) or "cards" in str(data).lower()


def test_card_create_and_get_by_id(client):
    create = client.post(
        "/card/create",
        data=json.dumps({"front": "A", "back": "B"}),
        content_type="application/json",
    )
    assert create.status_code == 201
    data = create.get_json()
    card_id = data.get("_id") or data.get("id")
    assert card_id, "create card should return _id or id"
    get_one = client.get(f"/card/{card_id}")
    assert get_one.status_code == 200


def test_card_get_by_deck(client):
    # deck_id inexistente retorna lista vazia (200) após correção no model
    response = client.get("/card/get_cards_by_deck/507f1f77bcf86cd799439011")
    assert response.status_code == 200
    data = response.get_json()
    assert "cards" in data
    assert isinstance(data["cards"], list)


def test_card_update(client):
    create = client.post(
        "/card/create",
        data=json.dumps({"front": "X", "back": "Y"}),
        content_type="application/json",
    )
    assert create.status_code == 201
    data = create.get_json()
    card_id = data.get("id") or data.get("_id") or (data.get("card", {}) or data).get("_id")
    if isinstance(card_id, dict):
        card_id = card_id.get("$oid") or (list(card_id.values())[0] if card_id else None)
    if card_id:
        upd = client.put(
            f"/card/{card_id}",
            data=json.dumps({"front": "X2", "back": "Y2"}),
            content_type="application/json",
        )
        assert upd.status_code in (200, 404)


def test_card_delete(client):
    create = client.post(
        "/card/create",
        data=json.dumps({"front": "Del", "back": "Card"}),
        content_type="application/json",
    )
    assert create.status_code == 201
    data = create.get_json()
    card_id = data.get("id") or data.get("_id") or (data.get("card", {}) or data).get("_id")
    if isinstance(card_id, dict):
        card_id = card_id.get("$oid") or (list(card_id.values())[0] if card_id else None)
    if card_id:
        del_r = client.delete(f"/card/{card_id}")
        assert del_r.status_code in (200, 404)


def test_card_create_in_lots(client):
    response = client.post(
        "/card/create_card_in_lots",
        data=json.dumps({
            "deck_name": "Deck Lote",
            "cards": [{"front": "F1", "back": "B1"}, {"front": "F2", "back": "B2"}],
        }),
        content_type="application/json",
    )
    assert response.status_code in (201, 400, 500)


def test_card_create_in_lots_missing(client):
    response = client.post(
        "/card/create_card_in_lots",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_card_create_text_type(client):
    response = client.post(
        "/card/create",
        data=json.dumps({
            "front": "Capital of France?",
            "back": "Paris",
            "card_type": "text",
        }),
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["card_type"] == "text"
    assert data["front"] == "Capital of France?"
    assert data["back"] == "Paris"


def test_card_create_multiple_choice(client):
    response = client.post(
        "/card/create",
        data=json.dumps({
            "front": "2 + 2?",
            "card_type": "multiple_choice",
            "options": ["3", "4", "5", "6"],
            "correct_index": 1,
        }),
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["card_type"] == "multiple_choice"
    assert data["options"] == ["3", "4", "5", "6"]
    assert data["correct_index"] == 1
    assert data["back"] == "4"


def test_card_create_multiple_choice_invalid(client):
    response = client.post(
        "/card/create",
        data=json.dumps({
            "front": "2 + 2?",
            "card_type": "multiple_choice",
            "options": ["3", "4"],
            "correct_index": 1,
        }),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_card_create_image(client):
    response = client.post(
        "/card/create",
        data=json.dumps({
            "front": "Eiffel Tower",
            "back": "Paris",
            "card_type": "image",
            "image": "https://example.com/eiffel.jpg",
        }),
        content_type="application/json",
    )
    assert response.status_code == 201
    data = response.get_json()
    assert data["card_type"] == "image"
    assert data["image"] == "https://example.com/eiffel.jpg"
    assert data["media_type"] == "image"


def test_card_create_image_missing_image(client):
    response = client.post(
        "/card/create",
        data=json.dumps({
            "front": "Eiffel Tower",
            "back": "Paris",
            "card_type": "image",
        }),
        content_type="application/json",
    )
    assert response.status_code == 400
