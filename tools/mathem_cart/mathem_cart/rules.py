"""Load mathem-regler.yaml and filter search candidates per category (spec §6–§7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from ruamel.yaml import YAML

from .mathem.models import Product
from .quantity import StockUp
from .shopping_list import _parse_amount
from .units import Amount, Conversions, to_base

REQUIRE_PREFIXES = ("märkning:", "namn:")


MATCHING_REMOVED = ("matchning.läge och matchning.tröskel används inte längre (Laya är borttaget; "
                    "matchningen görs av agenter) — ta bort blocket matchning ur mathem-regler.yaml")


class RulesError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CategoryRule:
    frysbar: bool = False
    max_overshoot: float = 0.25
    require_any: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    prefer_any: tuple[str, ...] = ()   # like require_any, but falls back when nothing qualifies
    storpack: bool = False             # worth having at home: bigger pack by jämförpris (quantity.StockUp)

    def overshoot_cap(self) -> float | None:
        return None if self.frysbar else self.max_overshoot


@dataclass(frozen=True, slots=True)
class Rules:
    max_count_per_line: int = 10
    plan_max_age_h: float = 24.0
    default_max_overshoot: float = 0.25
    categories: Mapping[str, CategoryRule] = field(default_factory=dict)
    conversions: Conversions = field(default_factory=Conversions)
    warnings: tuple[str, ...] = ()   # load warnings (e.g. an old matchning block), printed by the CLI
    elsewhere: Mapping[str, tuple[str, ...]] = field(default_factory=dict)   # place -> words (köps_inte_på_mathem)
    stock_up: StockUp = field(default_factory=StockUp)                       # storpack limits
    stock_up_words: tuple[str, ...] = ()                                     # storpack_varor
    frozen_ok_words: tuple[str, ...] = ()                                    # tillåt_fryst
    staples: Mapping[str, StockUp] = field(default_factory=dict)             # basvaror: head noun -> limits
    staple_exceptions: tuple[str, ...] = ()                                  # basvaror.utom, casefolded

    def bought_elsewhere(self, item_name: str) -> str | None:
        """The place an item is bought instead of Mathem, when its head noun is a listed word.

        The head noun is the last word before any comma ("torrt vitt vin", "vin, torrt vitt"),
        so "sherry vinäger" and "cider-vinäger" stay vinegar and are bought on Mathem.
        """
        head = head_noun(item_name)
        for place, words in self.elsewhere.items():
            if head in {w.casefold() for w in words}:
                return place
        return None

    def rule_for(self, item_name: str, category: str) -> CategoryRule:
        """The category rule for one item: an item in `tillåt_fryst` drops "fryst" from `uteslut`.

        Frozen chicken and fish are what gets bought most weeks, but frozen stays excluded for
        the rest of the category. A list that asks for "färsk" still gets fresh: the matcher
        treats it as a requirement.
        """
        rule = self.for_category(category)
        if head_noun(item_name) in {w.casefold() for w in self.frozen_ok_words}:
            return replace(rule, exclude=tuple(x for x in rule.exclude if x.casefold() != "fryst"))
        return rule

    def stock_up_for(self, item_name: str, category: str) -> StockUp | None:
        """Basvaror limits when the item's head noun is in `basvaror.varor` and no word of its name
        is in `basvaror.utom` ("färsk pasta" stays fresh); else storpack limits when the item's
        category is `storpack: ja` or its head noun is in `storpack_varor`."""
        head = head_noun(item_name)
        staple = self.staples.get(head)
        if staple is not None and not set(re.split(r"[\s,-]+", item_name.casefold())) & set(self.staple_exceptions):
            return staple
        if self.for_category(category).storpack or head in {w.casefold() for w in self.stock_up_words}:
            return self.stock_up
        return None

    def for_category(self, name: str) -> CategoryRule:
        for key, rule in self.categories.items():
            if key.casefold() == name.casefold():
                return rule
        return CategoryRule(max_overshoot=self.default_max_overshoot)


def head_noun(item_name: str) -> str:
    """Last word before any comma, casefolded: "osaltat smör" and "smör, osaltat" -> "smör"."""
    words = re.split(r"[\s-]+", item_name.split(",")[0].strip().casefold())
    return words[-1] if words else ""


_TRUE = {"ja", "yes", "true", "1"}
_FALSE = {"nej", "no", "false", "0", ""}


def _truthy(value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise RulesError(f"{where} måste vara ja eller nej, inte {value!r}")


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool):
        raise RulesError(f"{where} måste vara ett tal, inte {value!r}")
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        raise RulesError(f"{where} måste vara ett tal, inte {value!r}") from None


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RulesError(f"{where} måste vara en mappning")
    return value


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        raise RulesError(f"{where} måste vara en lista")
    return tuple(str(x) for x in value)


STAPLE_KEYS = {"max_merkostnad_kr", "min_besparing", "max_gånger_behovet", "utom", "varor"}
DEFAULT_STAPLE_EXCEPTIONS = ("färsk", "färska", "färskt", "picklad", "picklade", "inlagd", "inlagda",
                             "syltad", "syltade", "rostad", "rostade", "friterad", "friterade")


def _amount(value: Any, where: str) -> Amount:
    """"5 kg", "2,5 l", "12 st": the shopping list's own amount parser, with a unit required."""
    text = str(value).strip()
    amount, unit, rest = _parse_amount(text) if isinstance(value, str) else (None, None, text)
    base = to_base(amount, unit) if amount is not None and unit and not rest.strip() \
        and re.search(r"[^\d\s.,]", text) else None
    if base is None or base.value <= 0 or base.dim == "förp":
        raise RulesError(f"{where} måste vara en mängd som \"5 kg\", \"2 l\" eller \"12 st\", inte {value!r}")
    return base


def _staples(data: Any) -> tuple[dict[str, StockUp], tuple[str, ...]]:
    """`basvaror`: staples bought in bulk, and the qualifier words that make an item not one.

    Kronor cap only (no share), a minimum saving, a max multiple of the need, and an
    optional max amount per item (`potatis: 5 kg`; `ja` or nothing = no max, `nej` = not a
    staple after all).
    """
    data = _mapping(data, "basvaror")
    unknown = sorted(set(map(str, data)) - STAPLE_KEYS)
    if unknown:
        raise RulesError(f"basvaror: okänd nyckel {', '.join(unknown)} (giltiga: {', '.join(sorted(STAPLE_KEYS))})")
    extra_kr = _number(data.get("max_merkostnad_kr", 150), "basvaror.max_merkostnad_kr")
    saving = _number(data.get("min_besparing", 0.15), "basvaror.min_besparing")
    multiple = _number(data.get("max_gånger_behovet", 20), "basvaror.max_gånger_behovet")
    if extra_kr < 0 or not 0 <= saving < 1 or multiple < 1:
        raise RulesError("basvaror: max_merkostnad_kr får inte vara negativ, min_besparing ska vara 0–0,99 "
                         "och max_gånger_behovet minst 1")
    raw = data.get("varor")
    items = {str(w): None for w in _strings(raw, "basvaror.varor")} if isinstance(raw, (list, tuple, str)) \
        else _mapping(raw, "basvaror.varor")
    staples: dict[str, StockUp] = {}
    for word, cap in items.items():
        where = f"basvaror.varor.{word}"
        if isinstance(cap, str) and not cap.strip():
            cap = None
        elif isinstance(cap, bool) or (isinstance(cap, str) and cap.strip().casefold() in _TRUE | _FALSE):
            if not _truthy(cap, where):
                continue
            cap = None
        staples[str(word).casefold()] = StockUp(max_extra_share=None, max_extra_kr=extra_kr, min_saving=saving,
                                                max_amount=None if cap is None else _amount(cap, where),
                                                max_multiple=multiple)
    exceptions = _strings(data["utom"], "basvaror.utom") if "utom" in data else DEFAULT_STAPLE_EXCEPTIONS
    return staples, tuple(w.casefold() for w in exceptions)


def parse_rules(data: Mapping[str, Any]) -> Rules:
    data = _mapping(data, "regelfilen")
    matching = _mapping(data.get("matchning"), "matchning")
    warnings = (MATCHING_REMOVED,) if any(k in matching for k in ("läge", "tröskel")) else ()
    safety = _mapping(data.get("säkerhet"), "säkerhet")
    default_cap = _number(_mapping(data.get("standard"), "standard").get("max_överköp", 0.25),
                          "standard.max_överköp")
    if default_cap < 0:
        raise RulesError(f"standard.max_överköp får inte vara negativ, inte {default_cap}")
    standard = _mapping(data.get("standard"), "standard")
    stock_up = StockUp(
        max_extra_share=_number(standard.get("storpack_max_merkostnad", 0.5), "standard.storpack_max_merkostnad"),
        max_extra_kr=_number(standard.get("storpack_max_merkostnad_kr", 100), "standard.storpack_max_merkostnad_kr"))
    if stock_up.max_extra_share < 0 or stock_up.max_extra_kr < 0:
        raise RulesError("standard.storpack_max_merkostnad och storpack_max_merkostnad_kr får inte vara negativa")
    categories: dict[str, CategoryRule] = {}
    for name, raw in _mapping(data.get("kategorier"), "kategorier").items():
        raw = _mapping(raw, f"kategorier.{name}")
        require = _strings(raw.get("kräv_någon_av"), f"{name}.kräv_någon_av")
        prefer = _strings(raw.get("föredra_någon_av"), f"{name}.föredra_någon_av")
        for r in require + prefer:
            if not r.startswith(REQUIRE_PREFIXES):
                raise RulesError(f"{name}: okänt krav {r!r} (använd märkning: eller namn:)")
        cap = _number(raw.get("max_överköp", default_cap), f"{name}.max_överköp")
        if cap < 0:
            raise RulesError(f"{name}.max_överköp får inte vara negativ, inte {cap}")
        categories[str(name)] = CategoryRule(
            frysbar=_truthy(raw.get("frysbar", False), f"{name}.frysbar"),
            max_overshoot=cap,
            require_any=require,
            exclude=_strings(raw.get("uteslut"), f"{name}.uteslut"),
            prefer_any=prefer,
            storpack=_truthy(raw.get("storpack", False), f"{name}.storpack"),
        )
    staples, staple_exceptions = _staples(data.get("basvaror"))
    conv = _mapping(data.get("omräkning"), "omräkning")
    piece = _mapping(conv.get("styckvikt_g"), "omräkning.styckvikt_g")
    density = _mapping(conv.get("densitet_g_per_dl"), "omräkning.densitet_g_per_dl")
    max_count = _number(safety.get("max_antal_per_rad", 10), "säkerhet.max_antal_per_rad")
    if max_count != int(max_count) or max_count < 1:
        raise RulesError(f"säkerhet.max_antal_per_rad måste vara ett positivt heltal, inte {max_count}")
    return Rules(
        max_count_per_line=int(max_count),
        plan_max_age_h=_number(safety.get("plan_max_ålder_h", 24), "säkerhet.plan_max_ålder_h"),
        default_max_overshoot=default_cap,
        categories=categories,
        conversions=Conversions(
            piece_weight_g={str(k).casefold(): _number(v, f"styckvikt_g.{k}") for k, v in piece.items()},
            density_g_per_dl={str(k).casefold(): _number(v, f"densitet_g_per_dl.{k}") for k, v in density.items()},
        ),
        warnings=warnings,
        stock_up=stock_up,
        stock_up_words=_strings(data.get("storpack_varor"), "storpack_varor"),
        frozen_ok_words=_strings(data.get("tillåt_fryst"), "tillåt_fryst"),
        staples=staples,
        staple_exceptions=staple_exceptions,
        elsewhere={str(place): _strings(words, f"köps_inte_på_mathem.{place}")
                   for place, words in _mapping(data.get("köps_inte_på_mathem"), "köps_inte_på_mathem").items()},
    )


def load_rules(path: Path) -> Rules:
    if not path.is_file():
        raise FileNotFoundError(f"Hittar inte regelfilen: {path}")
    raw = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}
    safety = raw.get("säkerhet") if isinstance(raw, dict) else None
    for key in ("max_antal_per_rad", "plan_max_ålder_h"):
        if not isinstance(safety, dict) or key not in safety:
            raise RulesError(f"säkerhet.{key} saknas i {path}")
    return parse_rules(raw)


def _requirement_holds(req: str, p: Product) -> bool:
    kind, _, value = req.partition(":")
    value = value.strip().casefold()
    if kind == "märkning":
        return any(c.strip().casefold() == value for c in p.classifiers)
    return value in p.full_name.casefold()


def filter_candidates(products: Sequence[Product], rule: CategoryRule) -> tuple[list[Product], list[tuple[Product, str]]]:
    kept: list[Product] = []
    dropped: list[tuple[Product, str]] = []
    for p in products:
        if not p.available:
            dropped.append((p, "ej tillgänglig"))
            continue
        haystack = f"{p.full_name} {p.name_extra or ''}".casefold()
        hit = next((x for x in rule.exclude if x.casefold() in haystack), None)
        if hit:
            dropped.append((p, f"utesluten: {hit}"))
            continue
        if rule.require_any and not any(_requirement_holds(r, p) for r in rule.require_any):
            dropped.append((p, "uppfyller inget krav: " + ", ".join(rule.require_any)))
            continue
        kept.append(p)
    if rule.prefer_any:
        preferred = [p for p in kept if meets_preference(p, rule)]
        if preferred:  # otherwise fall back to what is available
            reason = "föredraget alternativ finns: " + ", ".join(rule.prefer_any)
            dropped.extend((p, reason) for p in kept if p not in preferred)
            kept = preferred
    return kept, dropped


def meets_preference(p: Product, rule: CategoryRule) -> bool:
    return not rule.prefer_any or any(_requirement_holds(r, p) for r in rule.prefer_any)
