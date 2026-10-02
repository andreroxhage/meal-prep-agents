"""Search (paged, flattened, previously bought first) and product detail.

Adapted from ha-mathem (MIT, Copyright (c) 2026 Marcus Forsberg), see LICENSE-ha-mathem.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .errors import MathemProtocolError, MathemRequestError
from .models import Product, normalise
from .session import MathemSession

PAGE_SIZE = 30
PREV_BOUGHT_LIST_ID = "prev_bought_products"


def _norm_term(term: str) -> str:
    return re.sub(r"\s+", " ", term).strip().casefold()


class SearchCache:
    """Search responses on disk, one file per (normalised term, page), valid ``ttl_h`` hours."""

    def __init__(self, directory: Path, ttl_h: float = 24.0, clock: Callable[[], float] = time.time):
        self.directory = Path(directory)
        self.ttl_s = ttl_h * 3600
        self.clock = clock

    def _path(self, term: str, page: int) -> Path:
        digest = hashlib.sha1(f"{_norm_term(term)}|{page}".encode()).hexdigest()[:16]
        return self.directory / f"{digest}.json"

    def get(self, term: str, page: int) -> dict | None:
        path = self._path(term, page)
        if not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            saved, data = float(entry["saved"]), entry["data"]
        except (ValueError, KeyError, TypeError):
            return None   # a corrupt cache file is a miss, not a crash
        if self.clock() - saved > self.ttl_s:
            return None
        return data

    def put(self, term: str, page: int, data: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        entry = {"term": _norm_term(term), "page": page, "saved": self.clock(), "data": data}
        self._path(term, page).write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")


def parse_search(data: Mapping[str, Any]) -> tuple[list[Product], bool]:
    """Flatten a ``/search/mixed/`` page: previously bought first, deduplicated; plus has_more."""
    if not isinstance(data, Mapping) or not isinstance(data.get("items"), list):
        raise MathemProtocolError("GET /search/mixed/ saknar fältet 'items'")
    attrs = normalise(data.get("attributes") or {})
    flat: list[Product] = []
    prev: list[Product] = []
    for item in data["items"]:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if kind == "product" and item.get("attributes"):
            flat.append(Product.from_api(item["attributes"]))
        elif kind == "product_list":
            is_prev = (item.get("attributes") or {}).get("id") == PREV_BOUGHT_LIST_ID
            for nested in item.get("items") or []:
                if isinstance(nested, Mapping) and nested.get("type") == "product" and nested.get("attributes"):
                    p = Product.from_api(nested["attributes"], previously_bought=is_prev)
                    (prev if is_prev else flat).append(p)
    seen: set[int] = set()
    products: list[Product] = []
    for p in prev + flat:
        if p.id not in seen:
            seen.add(p.id)
            products.append(p)
    return products, bool(attrs.get("has_more_items"))


class ProductsClient:
    def __init__(self, session: MathemSession, cache: SearchCache | None = None):
        self._session = session
        self._cache = cache

    def _page(self, term: str, page: int) -> dict:
        if self._cache and (hit := self._cache.get(term, page)) is not None:
            return hit
        data = self._session.get_json("/search/mixed/", {"q": _norm_term(term), "type": "product", "page": page})
        if self._cache:
            self._cache.put(term, page, data)
        return data

    def search(self, term: str, limit: int = PAGE_SIZE, max_pages: int = 5) -> list[Product]:
        out: list[Product] = []
        seen: set[int] = set()
        for page in range(1, max_pages + 1):
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

    def product(self, product_id: int) -> Product | None:
        """Product detail; ``None`` when Mathem answers 404."""
        missing = False
        try:
            data = self._session.get_json(f"/products/{int(product_id)}/")
        except MathemRequestError as err:
            if err.status != 404:
                raise
            missing = True
        if missing:
            return None
        return Product.from_api(data)
