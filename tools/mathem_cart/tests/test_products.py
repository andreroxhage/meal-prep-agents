import json

import httpx

from mathem_cart.mathem.products import ProductsClient, SearchCache, parse_search
from mathem_cart.mathem.session import MathemSession


def prod(pid, name="Vara"):
    return {"type": "product", "attributes": {"id": pid, "full_name": name, "name_extra": "1 st",
                                              "gross_price": "10.00",
                                              "availability": {"is_available": True, "code": "available"}}}


def page(items, more):
    return {"type": "search", "attributes": {"items": len(items), "page": 1, "has_more_items": more}, "items": items}


def test_parse_search_flattens_and_puts_previously_bought_first():
    data = page([prod(1), {"type": "product_list", "attributes": {"id": "prev_bought_products"},
                           "items": [prod(2)]}, prod(2), {"type": "recipe", "attributes": {}}], False)
    products, more = parse_search(data)
    assert [p.id for p in products] == [2, 1]
    assert products[0].previously_bought is True and more is False


def test_parse_search_camel_paging_key():
    _, more = parse_search({"attributes": {"hasMoreItems": True}, "items": []})
    assert more is True


def test_parse_search_missing_items_is_protocol_error():
    import pytest
    from mathem_cart.mathem.errors import MathemProtocolError
    with pytest.raises(MathemProtocolError, match="items"):
        parse_search({"attributes": {}})


def client_with(pages, tmp_path=None, clock=None):
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=pages[int(request.url.params["page"]) - 1])

    session = MathemSession("https://example.org", client=httpx.Client(transport=httpx.MockTransport(handler)),
                            sleep=lambda s: None)
    cache = SearchCache(tmp_path, clock=clock) if tmp_path else None
    return ProductsClient(session, cache), calls


def test_search_pages_until_limit():
    pages = [page([prod(i) for i in range(1, 31)], True), page([prod(i) for i in range(31, 61)], False)]
    client, calls = client_with(pages)
    assert [p.id for p in client.search("mjölk", limit=40)] == list(range(1, 41))
    assert [c["page"] for c in calls] == ["1", "2"]
    assert calls[0] == {"q": "mjölk", "type": "product", "page": "1"}


def test_search_uses_cache_within_ttl(tmp_path):
    now = {"t": 1000.0}
    pages = [page([prod(1)], False)]
    client, calls = client_with(pages, tmp_path, clock=lambda: now["t"])
    client.search("mjölk")
    client.search("Mjölk ")            # same normalised term
    assert len(calls) == 1
    now["t"] += 25 * 3600
    client.search("mjölk")
    assert len(calls) == 2
    cached = list(tmp_path.glob("*.json"))
    assert cached and json.loads(cached[0].read_text(encoding="utf-8"))["term"] == "mjölk"


def test_product_404_is_none():
    session = MathemSession("https://example.org", sleep=lambda s: None, client=httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    assert ProductsClient(session).product(999) is None
