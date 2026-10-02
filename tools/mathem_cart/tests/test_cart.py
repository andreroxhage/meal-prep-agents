import json

import httpx
import pytest

from mathem_cart.mathem.cart import CartClient
from mathem_cart.mathem.models import Cart
from mathem_cart.mathem.session import MathemSession

CART = {"id": 1, "groups": [{"items": [
    {"itemId": 10, "quantity": 2, "product": {"id": 6851, "fullName": "Garant Vispgrädde 36%"},
     "availability": {"isAvailable": True}},
    {"itemId": 11, "quantity": 1, "product": {"id": 7, "fullName": "Slut"}, "availability": {"isAvailable": False}},
]}]}


def test_cart_from_api():
    cart = Cart.from_api(CART)
    assert not cart.is_empty
    assert cart.quantity_of(6851) == 2 and cart.quantity_of(1) == 0
    assert cart.lines[1].available is False


def test_empty_cart():
    assert Cart.from_api({"groups": []}).is_empty


def test_cart_without_groups_is_protocol_error():
    from mathem_cart.mathem.errors import MathemProtocolError
    with pytest.raises(MathemProtocolError, match="groups"):
        Cart.from_api({"id": 1})


def recording_client(responses):
    seen = []

    def handler(request):
        seen.append(request)
        return responses.pop(0)

    session = MathemSession("https://example.org", sleep=lambda s: None,
                            client=httpx.Client(transport=httpx.MockTransport(handler)))
    return CartClient(session), seen


def test_add_posts_positive_delta():
    client, seen = recording_client([httpx.Response(200, json=CART)])
    client.add(6851, 2)
    req = seen[0]
    assert req.method == "POST" and req.url.path == "/api/v1/cart/items/"
    assert req.url.params["group-by"] == "recipes"
    assert json.loads(req.content) == {"items": [{"productId": 6851, "quantity": 2}]}


def test_add_rejects_non_positive():
    client, _ = recording_client([])
    with pytest.raises(ValueError):
        client.add(1, 0)


def test_set_quantity_sends_difference():
    client, seen = recording_client([httpx.Response(200, json=CART), httpx.Response(200, json=CART)])
    client.set_quantity(6851, 5)
    assert json.loads(seen[1].content) == {"items": [{"productId": 6851, "quantity": 3}]}


@pytest.mark.parametrize("group", [
    {"recipe": {"id": 3}, "products": [{"id": 1, "quantity": 1}]},   # lines under another key
    {"recipe": {"id": 3}},                                            # no `items` at all
    {"items": None, "lines": [{"product": {"id": 1}, "quantity": 1}]},
    {"items": [], "products": [{"id": 1, "quantity": 1}]},            # empty items, lines elsewhere
    {"items": {"product": {"id": 1}}},                                # items is not a list
])
def test_unexpected_group_shape_fails_closed(group):
    # S3: the empty-cart check (D7) must never read an unknown shape as "empty".
    from mathem_cart.mathem.errors import MathemProtocolError
    with pytest.raises(MathemProtocolError):
        Cart.from_api({"groups": [group]})


def test_group_with_empty_items_is_empty():
    assert Cart.from_api({"groups": [{"recipe": None, "items": [], "tags": []}]}).is_empty
