"""Willys search and product detail, mapped onto the shared ``Product``.

Field meanings are from cartway (MIT, see LICENSE-cartway) and checked against live
search responses on 2026-11-17 (docs/design/varukorg-butiker.md §2).
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ..mathem.errors import MathemProtocolError, MathemRequestError
from ..mathem.models import Product, parse_price
from ..mathem.products import SearchCache, _norm_term
from .session import WillysSession

PAGE_SIZE = 30
# Willys label -> the Swedish label the rule files use (märkning:…), so one rule set fits both stores.
LABELS = {
    "swedish_flag": "Från Sverige", "from_sweden": "Från Sverige", "meat_from_sweden": "Kött från Sverige",
    "swedish_bird": "Svensk Fågel", "milk_from_sweden": "Mjölk från Sverige", "laktosfree": "Lactose free",
    "ecological": "Ekologisk", "eu_ecological": "EU-ekologisk", "krav": "KRAV", "keyhole": "Nyckelhål",
    "frozen": "Fryst",
}
_REDEEM_RE = re.compile(r"max\s+(\d+)", re.IGNORECASE)


def _price_value(promo: Mapping[str, Any]) -> float | None:
    price = promo.get("price")
    return parse_price(price.get("value")) if isinstance(price, Mapping) else None


def product_from_willys(raw: Mapping[str, Any]) -> Product:
    """One ``results[]`` entry (or a ``/axfood/rest/p/<code>`` body) as a Product.

    ``_KG`` goods are priced per kg; one piece costs ``priceValue × averageWeight`` and its
    size is ``ca <averageWeight> g``. A single-unit promotion ("Spara 9,00 kr/st") becomes the
    price, with the ordinary price and "Max N köp" as the discount limit; a multi-buy
    ("Välj & blanda! 3 för 35,00") becomes "3 för 35,00 kr".
    """
    if not isinstance(raw, Mapping):
        raise MathemProtocolError("Willys-produkt är inte ett objekt")
    for name in ("code", "name"):
        if raw.get(name) in (None, ""):
            raise MathemProtocolError(f"Willys-produkt saknar fältet {name!r}")
    code, name = str(raw["code"]), str(raw["name"])
    weighed = code.upper().endswith("_KG")
    weight_kg = parse_price(raw.get("averageWeight"))
    volume = str(raw.get("displayVolume") or "").replace("ca:", "ca ").strip()
    if weighed:
        size = f"ca {round(weight_kg * 1000):g} g" if weight_kg and weight_kg > 0 else volume
        factor = weight_kg if weight_kg and weight_kg > 0 else None   # no weight: no piece price
    else:
        size, factor = volume, 1.0
    if isinstance(raw.get("maxOrderQuantity"), int) and raw["maxOrderQuantity"] > 0:
        size = f"Max {raw['maxOrderQuantity']} per kund, {size}"

    def piece(value: float | None) -> float | None:
        return None if value is None or factor is None else round(value * factor, 2)

    regular = parse_price(raw.get("priceValue"))
    price, unit_price = piece(regular), parse_price(raw.get("comparePrice"))
    titles: list[str] = []
    discount: dict[str, Any] | None = None
    for promo in raw.get("potentialPromotions") or []:
        if not isinstance(promo, Mapping):
            continue
        count = promo.get("qualifyingCount")
        label = " ".join(str(promo.get("conditionLabel") or "").split())
        member = " (Willys Plus)" if promo.get("campaignType") == "LOYALTY" else ""
        promo_price = _price_value(promo)
        if isinstance(count, int) and count > 1 and promo.get("rewardLabel"):
            titles.append(f"{count} för {promo['rewardLabel']} kr")
            if member:
                titles.append(f"{label} {promo['rewardLabel']}{member}")
        elif count == 1 and promo_price is not None and discount is None and regular is not None:
            limit = _REDEEM_RE.search(str(promo.get("redeemLimitLabel") or ""))
            discount = {"undiscounted_gross_price": piece(regular),
                        "maximum_quantity": int(limit.group(1)) if limit else None}
            price = piece(promo_price)
            unit_price = parse_price(promo.get("comparePrice")) or unit_price
            titles.append(f"{label} (ingår i priset){member}")
        elif label:
            titles.append(f"{label}{member}")
    labels = tuple(dict.fromkeys(LABELS.get(str(x), str(x)) for x in raw.get("labels") or []))
    if "Fryst" in labels and "fryst" not in name.casefold():
        name = f"{name} Fryst"   # the rule files exclude frozen goods by name (uteslut: [fryst])
    available = not raw.get("outOfStock") and not raw.get("addToCartDisabled") and raw.get("online") is not False
    return Product(
        id=code, full_name=name, brand=raw.get("manufacturer") or None, name_extra=size or None,
        gross_price=price, gross_unit_price=unit_price,
        unit_price_unit=(str(raw.get("comparePriceUnit") or "").strip() or None),
        classifiers=labels, promotions=tuple(titles), discount=discount,
        available=available and price is not None, availability_code=None, raw=dict(raw))


def parse_search(data: Mapping[str, Any]) -> tuple[list[Product], bool]:
    """A ``/search`` page: products in Willys' order, and whether another page exists."""
    if not isinstance(data, Mapping) or not isinstance(data.get("pagination"), Mapping):
        raise MathemProtocolError("GET /search saknar fältet 'pagination'")
    results = data.get("results")
    if results is None and data["pagination"].get("totalNumberOfResults") == 0:
        results = []   # no hits: Willys answers results: null
    if not isinstance(results, list):
        raise MathemProtocolError("GET /search saknar fältet 'results'")
    products: list[Product] = []
    seen: set[str] = set()
    for raw in results:
        p = product_from_willys(raw)
        if p.id not in seen:
            seen.add(p.id)
            products.append(p)
    page = data["pagination"]
    current, pages = page.get("currentPage"), page.get("numberOfPages")
    more = isinstance(current, int) and isinstance(pages, int) and current + 1 < pages
    return products, more


class WillysProducts:
    """Same interface as the Mathem ProductsClient: ``search`` and ``product``."""

    def __init__(self, session: WillysSession, cache: SearchCache | None = None):
        self._session = session
        self._cache = cache

    def _page(self, term: str, page: int) -> dict:
        if self._cache and (hit := self._cache.get(term, page)) is not None:
            return hit
        data = self._session.get_json("/search", {"q": _norm_term(term), "size": PAGE_SIZE, "page": page})
        if self._cache:
            self._cache.put(term, page, data)
        return data

    def search(self, term: str, limit: int = PAGE_SIZE, max_pages: int = 3) -> list[Product]:
        out: list[Product] = []
        seen: set[str] = set()
        for page in range(max_pages):
            products, more = parse_search(self._page(term, page))
            added = 0
            for p in products:
                if p.id not in seen:
                    seen.add(p.id)
                    out.append(p)
                    added += 1
            if len(out) >= limit or not more or added == 0:
                break
        return out[:limit]

    def product(self, product_id: int | str) -> Product | None:
        """Product detail; ``None`` when Willys answers 400/404 (an unknown code is a 400)."""
        missing = False
        try:
            data = self._session.get_json(f"/axfood/rest/p/{product_id}")
        except MathemRequestError as err:
            if err.status not in (400, 404):
                raise
            missing = True
        if missing:
            return None
        return product_from_willys(data)
