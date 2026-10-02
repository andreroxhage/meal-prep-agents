"""Cart read and mutation. Quantities are deltas (spec §3).

Adapted from ha-mathem (MIT, Copyright (c) 2026 Marcus Forsberg), see LICENSE-ha-mathem.
"""

from __future__ import annotations

from .models import Cart
from .session import MathemSession

_PARAMS = {"group-by": "recipes"}


class CartClient:
    def __init__(self, session: MathemSession):
        self._session = session

    def get(self) -> Cart:
        return Cart.from_api(self._session.get_json("/cart/", _PARAMS, camel=True))

    def _adjust(self, product_id: int, delta: int) -> Cart:
        payload = {"items": [{"productId": int(product_id), "quantity": int(delta)}]}
        return Cart.from_api(self._session.post_json("/cart/items/", payload, _PARAMS))

    def add(self, product_id: int, quantity: int) -> Cart:
        if int(quantity) <= 0:
            raise ValueError("antal måste vara positivt")
        return self._adjust(product_id, quantity)

    def set_quantity(self, product_id: int, quantity: int) -> Cart:
        if int(quantity) < 0:
            raise ValueError("antal får inte vara negativt")
        cart = self.get()
        delta = int(quantity) - cart.quantity_of(product_id)
        return cart if delta == 0 else self._adjust(product_id, delta)
