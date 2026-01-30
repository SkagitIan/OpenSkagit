from typing import List

from .models import Card


def get_active_cards_payload() -> List[dict]:
    active_cards = Card.objects.filter(is_active=True).order_by("direction", "order", "id")
    payload = []
    for card in active_cards:
        payload.append(
            {
                "id": card.id,
                "type": card.card_type,
                "direction": card.direction,
                "title": card.title,
                "slug": card.slug,
                "assets": card.assets(),
                "config": card.config or {},
            }
        )
    return payload
