"""Willys cart read and add. ``addProducts`` SETS a line's quantity (cartway, MIT).

So ``add`` reads the cart and sends current + delta, which keeps the Mathem contract
(``add`` adds) that the applier relies on.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..ids import ProductId, norm_id
from ..mathem.errors import MathemProtocolError
from ..mathem.models import Cart, CartLine
from .session import WillysSession

CART_PATH = "/axfood/rest/cart"
ADD_PATH = "/axfood/rest/cart/addProducts"


def cart_from_willys(data: Mapping[str, Any]) -> Cart:
    """Fail closed: this parse feeds the empty-cart check, so an unknown shape raises."""
    if not isinstance(data, Mapping) or "products" not in data:
        raise MathemProtocolError(f"GET {CART_PATH} saknar fältet 'products'")
    products = data["products"] or []
    if not isinstance(products, list):
        raise MathemProtocolError(f"GET {CART_PATH}: 'products' är inte en lista")
    total = data.get("totalItems")
    if not products and isinstance(total, (int, float)) and total > 0:
        raise MathemProtocolError(f"GET {CART_PATH}: tom 'products' men totalItems={total}")
    lines: list[CartLine] = []
    for raw in products:
        if not isinstance(raw, Mapping) or not raw.get("code"):
            raise MathemProtocolError(f"GET {CART_PATH}: en rad saknar 'code'")
        qty = raw.get("quantity")
        if not isinstance(qty, (int, float)) or isinstance(qty, bool):
            raise MathemProtocolError(f"GET {CART_PATH}: raden {raw['code']} saknar 'quantity'")
        # shortcut: _KG lines may report grams, not pieces (open item 2 in the design note); a
        # mismatch shows up as a difference in the apply report, never as a silent pass.
        lines.append(CartLine(norm_id(raw["code"]), str(raw.get("name") or ""), int(qty),
                              None if raw.get("outOfStock") is None else not raw["outOfStock"]))
    return Cart(tuple(lines))


class WillysCart:
    def __init__(self, session: WillysSession):
        self._session = session

    def get(self) -> Cart:
        self._session.refresh_csrf()
        return cart_from_willys(self._session.get_json(CART_PATH))

    def add(self, product_id: ProductId, quantity: int) -> Cart:
        if int(quantity) <= 0:
            raise ValueError("antal måste vara positivt")
        target = self.get().quantity_of(product_id) + int(quantity)
        self._session.refresh_csrf()
        # The answer's shape is not relied on (it may not be JSON): the cart is read back instead.
        self._session._send("POST", self._session.base_url + ADD_PATH, json={"products": [{
            "productCodePost": str(product_id), "qty": target, "pickUnit": "pieces",
            "hideDiscountToolTip": False, "noReplacementFlag": False}]})
        return self.get()
