"""Typed views over Mathem API JSON.

Adapted from ha-mathem (MIT, Copyright (c) 2026 Marcus Forsberg), see
LICENSE-ha-mathem. Keys are normalised camelCase -> snake_case so responses with
and without the ``x-requested-case: camel`` header parse the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import MathemProtocolError

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def snake(key: str) -> str:
    return _CAMEL.sub("_", key).lower()


def normalise(data: Mapping[str, Any]) -> dict[str, Any]:
    return {snake(k): v for k, v in data.items()}


def parse_price(value: Any) -> float | None:
    """'15.95' / '19 kr' / 15.95 -> float; missing or unparseable -> None (never 0)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).lower().replace("kr", "").replace("\xa0", " ").replace(",", ".").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    full_name: str
    brand: str | None
    name_extra: str | None
    gross_price: float | None
    gross_unit_price: float | None
    unit_price_unit: str | None
    classifiers: tuple[str, ...]
    promotions: tuple[str, ...]
    discount: dict[str, Any] | None
    available: bool
    availability_code: str | None
    previously_bought: bool = False
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_api(cls, attrs: Mapping[str, Any], *, previously_bought: bool = False) -> "Product":
        a = normalise(attrs)
        for name in ("id", "full_name"):
            if a.get(name) in (None, ""):
                raise MathemProtocolError(f"produkt saknar fältet {name!r}")
        avail = a.get("availability")
        available, code = False, None  # fail closed
        if isinstance(avail, Mapping):
            av = normalise(avail)
            available, code = bool(av.get("is_available", False)), av.get("code")
        discount = a.get("discount")
        return cls(
            id=int(a["id"]),
            full_name=str(a["full_name"]),
            brand=a.get("brand"),
            name_extra=a.get("name_extra"),
            gross_price=parse_price(a.get("gross_price")),
            gross_unit_price=parse_price(a.get("gross_unit_price")),
            unit_price_unit=a.get("unit_price_quantity_abbreviation"),
            classifiers=tuple(str(c["name"]) for c in a.get("client_classifiers") or []
                              if isinstance(c, Mapping) and c.get("name")),
            promotions=tuple(str(normalise(p)["title"]) for p in a.get("promotions") or []
                             if isinstance(p, Mapping) and p.get("title")),
            discount=normalise(discount) if isinstance(discount, Mapping) else None,
            available=available,
            availability_code=code,
            previously_bought=previously_bought,
            raw=dict(attrs),
        )


@dataclass(frozen=True, slots=True)
class CartLine:
    product_id: int
    name: str
    quantity: int
    available: bool | None


@dataclass(frozen=True, slots=True)
class Cart:
    lines: tuple[CartLine, ...]

    @property
    def is_empty(self) -> bool:
        return not self.lines

    def quantity_of(self, product_id: int) -> int:
        return sum(line.quantity for line in self.lines if line.product_id == int(product_id))

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "Cart":
        if not isinstance(data, Mapping) or not isinstance(data.get("groups"), list):
            raise MathemProtocolError("GET /cart/ saknar fältet 'groups'")
        lines: list[CartLine] = []
        for group in data["groups"]:
            if not isinstance(group, Mapping):
                raise MathemProtocolError("GET /cart/: en grupp i 'groups' är inte ett objekt")
            # Fail closed: this parse feeds the empty-cart check (D7), so a shape we don't
            # know must raise rather than count as zero lines.
            items = group.get("items")
            if not isinstance(items, list):
                raise MathemProtocolError("GET /cart/: en grupp saknar listan 'items'")
            if not items:
                other = sorted(str(k) for k, v in group.items() if isinstance(v, list) and v)
                if other:
                    raise MathemProtocolError(f"GET /cart/: tom 'items' men rader under {other}")
            for raw in items:
                if not isinstance(raw, Mapping):
                    raise MathemProtocolError("GET /cart/: en rad i 'items' är inte ett objekt")
                item = normalise(raw)
                prod = item.get("product")
                if not isinstance(prod, Mapping):
                    raise MathemProtocolError("varukorgsrad saknar fältet 'product'")
                p = normalise(prod)
                if p.get("id") in (None, ""):
                    raise MathemProtocolError("varukorgsrad saknar fältet 'product.id'")
                avail = item.get("availability")
                available = normalise(avail).get("is_available") if isinstance(avail, Mapping) else None
                lines.append(CartLine(int(p["id"]), str(p.get("full_name") or p.get("name") or ""),
                                      int(item.get("quantity") or 0),
                                      None if available is None else bool(available)))
        return cls(tuple(lines))
