"""Amounts and unit conversion (spec §7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Amount:
    value: float
    dim: str  # "g" | "ml" | "st" | "förp"


@dataclass(frozen=True, slots=True)
class Conversions:
    piece_weight_g: Mapping[str, float] = field(default_factory=dict)
    density_g_per_dl: Mapping[str, float] = field(default_factory=dict)


MASS = {"g": 1.0, "kg": 1000.0}
VOLUME = {"ml": 1.0, "cl": 10.0, "dl": 100.0, "l": 1000.0, "msk": 15.0, "tsk": 5.0, "krm": 1.0}
COUNT = {"st": 1.0}
# V5: package-like units mean "number of packages", whatever the size.
PACKAGES = {"förp": 1.0, "knippe": 1.0, "burk": 1.0, "paket": 1.0,
            "kruka": 1.0, "flaska": 1.0, "limpa": 1.0, "påse": 1.0, "tub": 1.0}
SPOON_UNITS = frozenset({"msk", "tsk", "krm"})
_TABLES = (("g", MASS), ("ml", VOLUME), ("st", COUNT), ("förp", PACKAGES))


def to_base(value: float, unit: str) -> Amount | None:
    """Convert to the base unit of its dimension; unknown unit -> None."""
    unit = unit.lower()
    for dim, table in _TABLES:
        if unit in table:
            return Amount(value * table[unit], dim)
    return None


def _noun_singulars(word: str) -> list[str]:
    """Simple Swedish singular guesses: "klyftor" → "klyfta", "lökar" → "lök", "citroner" → "citron",
    "morötter" → "morot"."""
    out = []
    if word.endswith("ötter"):
        out.append(word[:-5] + "ot")
    if word.endswith("or"):
        out.append(word[:-2] + "a")
    if word.endswith("ar"):
        out += [word[:-2], word[:-2] + "e"]
    if word.endswith("er"):
        out.append(word[:-2])
    return out


def _adjective_singular(word: str) -> str:
    """ "gula" → "gul"; other words unchanged."""
    return word[:-1] if len(word) > 2 and word.endswith("a") else word


def _singulars(key: str) -> list[str]:
    """Singular guesses for a plural list key, most literal first.

    Only the last word is the noun; earlier words are adjectives and lose a plural -a.
    """
    words = key.split()
    if not words:
        return []
    *adjectives, noun = words
    heads = " ".join(_adjective_singular(a) for a in adjectives)
    out: list[str] = []
    for n in (noun, *_noun_singulars(noun)):
        for prefix in (" ".join(adjectives), heads):
            variant = f"{prefix} {n}".strip()
            if variant != key and variant not in out:
                out.append(variant)
    return out


def _tokens(name: str) -> set[str]:
    """Words of a product name plus their singular guesses, in any order."""
    words = re.findall(r"\w+", name.casefold())
    out = set(words)
    for w in words:
        out.update(_noun_singulars(w))
        out.add(_adjective_singular(w))
    return out


def _named_key(table: Mapping[str, float], name: str) -> str | None:
    """The longest table key whose every word appears in the product name."""
    tokens = _tokens(name)
    for candidate in sorted(table, key=len, reverse=True):
        if set(candidate.casefold().split()) <= tokens:
            return candidate
    return None


def _match(table: Mapping[str, float], key: str) -> str | None:
    if key in table:
        return key
    for candidate in sorted(table, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(candidate.casefold())}(?!\w)", key):
            return candidate
    return None


def lookup_key(table: Mapping[str, float], key: str) -> str | None:
    """The table key that ``key`` matches (see `lookup`), or None."""
    key = key.casefold()
    for variant in (key, *_singulars(key)):
        found = _match(table, variant)
        if found is not None:
            return found
    return None


def lookup(table: Mapping[str, float], key: str) -> float | None:
    """Exact match, else the longest table key found as a whole word in ``key``.

    A plural list key ("citroner") falls back to its singular guesses (Q2).
    """
    found = lookup_key(table, key)
    return None if found is None else table[found]


def _pieces_to_pieces(amount: Amount, key: str, product: str, conv: Conversions) -> Amount | None:
    """"st" counts different things when the item has a piece weight the product doesn't share.

    3 st vitlöksklyftor against "Vitlök, 1 st" is 3 cloves, not 3 heads: go through
    grams when the product has a piece weight too, otherwise there is no path (Q1).
    """
    table = conv.piece_weight_g
    item_key = lookup_key(table, key)
    if item_key is None:
        return amount                        # nothing says the counts differ
    if set(item_key.split()) <= _tokens(product):
        return amount                        # "Citroner 4-pack" counts lemons too
    product_key = _named_key(table, product)
    if product_key is None:
        return None
    return Amount(amount.value * table[item_key] / table[product_key], "st")


def convert(amount: Amount, dim: str, key: str, conv: Conversions,
            product: str | None = None, package: Amount | None = None) -> Amount | None:
    """Convert ``amount`` to ``dim`` via grams, using piece weights and densities for ``key``.

    ``product`` is the product name; with it, pieces are only matched one for one when
    they count the same thing. ``package`` is the offer's package size: a package sold by
    weight counts as that weight in whole pieces, at least one ("Gurka, 270 g" is one
    cucumber even though the table says 300 g). Returns None when there is no conversion
    path (the item is then undecided).
    """
    if amount.dim == dim:
        if dim == "st" and product is not None:
            return _pieces_to_pieces(amount, key, product, conv)
        return amount
    if "förp" in (amount.dim, dim):
        return None
    piece = lookup(conv.piece_weight_g, key)
    density = lookup(conv.density_g_per_dl, key)  # g per 100 ml
    grams: float | None = None
    if amount.dim == "g":
        grams = amount.value
    elif amount.dim == "st" and piece:
        if dim == "g" and package is not None and package.dim == "g" and package.value > 0:
            piece = package.value / max(1, round(package.value / piece))
        grams = amount.value * piece
    elif amount.dim == "ml" and density:
        grams = amount.value * density / 100
    if grams is None:
        return None
    if dim == "g":
        return Amount(grams, "g")
    if dim == "st" and piece:
        return Amount(grams / piece, "st")
    if dim == "ml" and density:
        return Amount(grams * 100 / density, "ml")
    return None
