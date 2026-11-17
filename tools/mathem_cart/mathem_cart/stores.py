"""The stores the cart flow supports, and what differs between them (docs/design/varukorg-butiker.md §1).

Everything else (shopping list, rules, planner, agents, decide, applier, report) is shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .mathem.cart import CartClient
from .mathem.products import ProductsClient, SearchCache
from .willys.cart import WillysCart
from .willys.products import WillysProducts

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Store:
    name: str                                  # "mathem", used in file names and --butik
    label: str                                 # "Mathem", in messages and the report
    site: str                                  # where the user empties the cart
    login_vars: tuple[str, str]                # (user, password) in .env, read only by apply
    products: Callable[[Any, SearchCache | None], Any]   # session, cache -> .search() / .product()
    cart: Callable[[Any], Any]                            # session -> .get() / .add()

    @property
    def rules_file(self) -> Path:
        return PACKAGE_ROOT / f"{self.name}-regler.yaml"

    @property
    def pins_file(self) -> Path:
        # Pins are personal choices, so they live in a gitignored file (see mathem-pins.example.yaml).
        return PACKAGE_ROOT / f"{self.name}-pins.local.yaml"

    @property
    def plan_file(self) -> str:
        return f"06-{self.name}-plan.json"

    @property
    def report_file(self) -> str:
        return f"06-{self.name}-varukorg.md"

    @property
    def cache_dir(self) -> str:
        return f".{self.name}-cache"


MATHEM = Store("mathem", "Mathem", "mathem.se", ("MATHEM_EMAIL", "MATHEM_PASSWORD"), ProductsClient, CartClient)
WILLYS = Store("willys", "Willys", "willys.se", ("WILLYS_USERNAME", "WILLYS_PASSWORD"), WillysProducts, WillysCart)
STORES = {s.name: s for s in (MATHEM, WILLYS)}


def store_named(name: str | None) -> Store:
    return STORES[(name or MATHEM.name).strip().casefold()]
