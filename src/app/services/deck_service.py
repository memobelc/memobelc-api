# src/app/services/deck_service.py

from src.app.models.deck_model import DeckModel
from src.app.models.card_model import CardModel
from src.app.models.user_progress_model import UserProgressModel
from src.app.models.publish_status import (
    DEFAULT_STATUS,
    validate_status_payload,
)


class DeckService:
    @staticmethod
    def create_deck(name, collection_id, image=None, cards=None, status=None, scheduled_at=None, init_progress=True):
        """Cria um novo deck e o salva no banco de dados"""
        if status is not None or scheduled_at is not None:
            status, scheduled_at = validate_status_payload(
                status or DEFAULT_STATUS, scheduled_at
            )
        else:
            status = DEFAULT_STATUS
            scheduled_at = None

        deck = DeckModel(
            name=name,
            collection_id=collection_id,
            image=image,
            status=status,
            scheduled_at=scheduled_at,
        )
        deck_id = deck.save_to_db()

        if cards is not None:
            card_ids = []
            for card in cards:
                card_data = CardModel.from_dict(card)
                card_id = card_data.save_to_db()
                card_ids.append(card_id)

            DeckModel.add_cards_to_deck(deck_id, card_ids)

            if init_progress:
                users = CardModel.get_user_by_deck(deck_id)
                from src.app.models.lesson_deck_model import ContentVisibility

                for user_id in users:
                    for card_id in card_ids:
                        if ContentVisibility.student_should_get_progress(user_id, deck_id, card_id):
                            UserProgressModel.create_or_update(user_id, deck_id, card_id)

        return {"message": "Deck criado com sucesso", "deck_id": deck_id}

    @staticmethod
    def clone_deck(source_deck_id, target_collection_id):
        """Clone a deck and its cards into another collection."""
        deck = DeckModel.get_by_id(source_deck_id)
        if not deck:
            return None

        cards_payload = []
        source_card_ids = [str(card_id) for card_id in (deck.get('cards') or [])]
        for card_id in source_card_ids:
            card = CardModel.get_by_id(card_id)
            if not card:
                continue
            card_dict = card.to_dict()
            card_dict.pop('_id', None)
            cards_payload.append(card_dict)

        created = DeckService.create_deck(
            deck.get('name') or 'Deck',
            target_collection_id,
            image=deck.get('image'),
            cards=cards_payload if cards_payload else None,
            status=deck.get('status'),
            scheduled_at=deck.get('scheduled_at'),
            init_progress=False,
        )
        new_deck_id = created['deck_id']
        new_deck = DeckModel.get_by_id(new_deck_id)
        new_card_ids = [str(card_id) for card_id in (new_deck.get('cards') or [])]
        card_id_map = {}
        for old_id, new_id in zip(source_card_ids, new_card_ids):
            card_id_map[old_id] = new_id

        return {'deck_id': new_deck_id, 'card_id_map': card_id_map}


    @staticmethod
    def get_all_decks():
        return DeckModel.get_all_decks()

    @staticmethod
    def get_decks_by_collection_id(collection_id, user_id):
        """This method returns all deck in collection"""

        return DeckModel.get_decks_by_collection_id(collection_id, user_id)
    
    @staticmethod
    def save_deck(user_id, deck_id, collection_id):
        """This method is responsible for save deck in user"""
    
        return DeckModel.save_deck(user_id, deck_id, collection_id)
    
    @staticmethod
    def check_if_the_user_has_the_deck(user_id, deck_id):
        """This method is responsible for verify if the deck has the user"""
        
        return DeckModel.check_if_the_user_has_the_deck(user_id, deck_id)

    @staticmethod
    def update_deck(deck_id, data):
        result = DeckModel.update_deck(deck_id, data)
        if result:
            DeckService._sync_progress_for_deck(deck_id)
        return result

    @staticmethod
    def delete_deck(deck_id):
        return DeckModel.delete_deck(deck_id)

    @staticmethod
    def get_deck(deck_id):
        return DeckModel.get_by_id(deck_id)

    @staticmethod
    def _sync_progress_for_deck(deck_id):
        from src.app.models.lesson_deck_model import ContentVisibility, LessonDeckModel
        from src.app.models.publish_status import is_released

        deck = DeckModel.get_by_id(deck_id)
        if not deck or not is_released(deck.get('status'), deck.get('scheduled_at')):
            return
        if LessonDeckModel.is_deck_linked(deck_id):
            users = CardModel.get_user_by_deck(deck_id)
            for user_id in users:
                filtered = ContentVisibility.filter_deck_for_user(deck, user_id)
                if not filtered:
                    continue
                for card_id in filtered.get('cards') or []:
                    UserProgressModel.create_or_update(user_id, deck_id, card_id)
            return
        users = CardModel.get_user_by_deck(deck_id)
        for user_id in users:
            for card_id in deck.get('cards') or []:
                if ContentVisibility.student_should_get_progress(user_id, deck_id, card_id):
                    UserProgressModel.create_or_update(user_id, deck_id, card_id)
