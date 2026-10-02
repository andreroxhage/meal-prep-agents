"""`mathem-cart` — the command line (base spec §9, matching spec §8).

`plan` searches, applies the rules and the pins and, when items need matching, writes the
candidate file for the matcher agents and exits 4. `decide` validates the agents' answers
and writes the plan. Neither ever logs in, touches the cart or calls a model. `apply`
executes a saved plan verbatim after the safety checks (base spec §8). This is the only
module that reads the environment (`.env` via python-dotenv).

Exit codes: 0 ok, 2 plan has undecided items, 3 safety abort, 4 matching needed, 1 other errors.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from .answers import label
from .applier import SafetyAbort, apply_plan, check_safety
from .candidates import (CANDIDATE_FILE, build_candidate_file, clear_matching, drop_warnings, part_path, parts_of,
                         read_round, write_round)
from .decider import DecideDeps, DecideError, DecideResult, decide
from .mathem.cart import CartClient
from .mathem.errors import MathemError
from .mathem.products import ProductsClient, SearchCache
from .mathem.session import MathemSession
from .pins import Pins, load_pins
from .plan_model import Candidate, Need, Plan, PlanLine, Undecided
from .planner import (SHOWN_CANDIDATES, Answer, Planner, PlannerDeps, Settled, candidate_view, need_for,
                      settle_all)
from .report import fmt_counts, fmt_kr, fmt_need, fmt_unit_price, reason_counts, render_report, source_counts
from .rules import Rules, RulesError, load_rules
from .shopping_list import Item, ShoppingList, load_shopping_list, normalize_key

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = PACKAGE_ROOT / "mathem-regler.yaml"
# Pins are personal choices, so they live in a gitignored file; mathem-pins.example.yaml documents the format.
DEFAULT_PINS = PACKAGE_ROOT / "mathem-pins.local.yaml"
SHOPPING_LIST = "03-handlingslista.md"
PLAN_FILE = "06-mathem-plan.json"
REPORT_FILE = "06-mathem-varukorg.md"
CACHE_DIR = ".mathem-cache"
WEEK_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEARCH_LIMIT = 10
EXIT_OK, EXIT_ERROR, EXIT_UNDECIDED, EXIT_SAFETY, EXIT_MATCHING = 0, 1, 2, 3, 4

CONTACT_MISSING = ("MATHEM_BOT_CONTACT saknas — sätt en kontaktadress (e-post eller URL) i .env; "
                   "den skickas i User-Agent till Mathem")


class CliError(Exception):
    """A user-facing error: the message goes to stderr and the exit code is 1."""


# --- factories the tests monkeypatch ------------------------------------------------

def make_session(contact: str) -> MathemSession:
    return MathemSession(contact)


# --- paths and environment ---------------------------------------------------------

def find_root(start: Path) -> Path:
    """Walk up from ``start`` until ``tools/mathem_cart/pyproject.toml`` exists."""
    start = Path(start).resolve()
    for folder in (start, *start.parents):
        if (folder / "tools" / "mathem_cart" / "pyproject.toml").is_file():
            return folder
    raise CliError(f"hittar inte repo-roten (tools/mathem_cart/pyproject.toml) ovanför {start} — ange --root")


def latest_week(root: Path) -> Path:
    """The lexicographically last ``YYYY-MM-DD`` folder in ``root``."""
    weeks = sorted(p for p in Path(root).iterdir() if p.is_dir() and WEEK_RE.match(p.name))
    if not weeks:
        raise CliError(f"ingen veckomapp (ÅÅÅÅ-MM-DD) i {root}")
    return weeks[-1]


def _root(args: argparse.Namespace) -> Path:
    if args.root:
        return Path(args.root)
    env = os.environ.get("MATHEM_CART_ROOT")
    return Path(env) if env else find_root(Path.cwd())


def _week(root: Path, name: str | None) -> Path:
    if not name:
        return latest_week(root)
    week = root / name
    if not week.is_dir():
        raise CliError(f"veckomappen finns inte: {week}")
    return week


def _load_env(root: Path) -> None:
    # Explicit path: never search upwards from cwd; never override the real environment.
    load_dotenv(root / ".env", override=False)


def _contact() -> str:
    contact = (os.environ.get("MATHEM_BOT_CONTACT") or "").strip()
    if not contact:
        raise CliError(CONTACT_MISSING)
    return contact


def _warn(message: str) -> None:
    print(f"Varning: {message}", file=sys.stderr)


def _rules(args: argparse.Namespace) -> Rules:
    rules = load_rules(Path(args.regler))
    for warning in rules.warnings:
        _warn(warning)
    return rules


# --- interactive questions -----------------------------------------------------------

def format_candidate(i: int, c: Candidate) -> str:
    return (f"{i}) {c.name} · {c.package or '—'} · {fmt_kr(c.price)} · {fmt_unit_price(c.unit_price)} · "
            f"{c.deal or '—'}")


class TerminalAsker:
    """Asks about one undecided item on the terminal (spec §6 "Asking")."""

    def ask(self, item: Item, candidates: Sequence[Candidate]) -> Answer:
        shown = list(candidates)[:SHOWN_CANDIDATES]
        need = need_for(item)
        amount = fmt_need(Need(need.value, need.dim)) if need else "okänd mängd"
        print(f"\n{item.name} — {amount} ({item.category})")
        for i, c in enumerate(shown, 1):
            print(format_candidate(i, c))
        if not shown:
            print("Inga kandidater.")
        choices = f"1–{len(shown)} = godkänn, f<n> = fast, " if shown else ""
        prompt = f"{choices}s = ny sökterm, h = hoppa över denna vecka: "
        while True:
            try:
                reply = input(prompt).strip().lower()
            except EOFError:
                return Answer("stop")   # not a usable answer: the item stays undecided
            fixed = reply.startswith("f")
            digits = reply[1:] if fixed else reply
            if digits.isdigit() and 1 <= int(digits) <= len(shown):
                return Answer("fixed" if fixed else "accept", shown[int(digits) - 1].product_id)
            if reply == "s":
                try:
                    term = input("Ny sökterm: ").strip()
                except EOFError:
                    return Answer("stop")
                if term:
                    return Answer("search", term=term)
            elif reply == "h":
                return Answer("skip")


# --- commands ------------------------------------------------------------------------

def _planner(session: MathemSession, week: Path, rules: Rules, pins: Pins) -> Planner:
    products = ProductsClient(session, SearchCache(week / CACHE_DIR))
    return Planner(PlannerDeps(search=products.search, lookup=products.product, rules=rules, pins=pins,
                               warn=_warn))


def _write_plan(week: Path, plan: Plan) -> int:
    plan.write(week / PLAN_FILE)
    report = week / REPORT_FILE
    report.write_text(render_report(plan), encoding="utf-8")
    print(f"Beslut: {fmt_counts(source_counts(plan.lines))}")
    if plan.undecided:
        print(f"Oavgjorda: {fmt_counts(reason_counts(plan.undecided))}")
    print(f"{len(plan.lines)} rader · {fmt_kr(plan.total_kr)} · {len(plan.undecided)} behöver beslut → {report}")
    return EXIT_UNDECIDED if plan.undecided else EXIT_OK


def _ask_all(planner: Planner, settled: Settled, outcomes: dict[str, PlanLine | Undecided], skipped: list[str],
             asker: TerminalAsker) -> None:
    for vid in settled.order:
        result = outcomes.get(vid)
        if isinstance(result, Undecided):
            answer = planner.ask(settled.items[vid], vid, result, asker)
            if answer is None:
                skipped.append(settled.items[vid].name)
                del outcomes[vid]
            else:
                outcomes[vid] = answer


def _print_parts(week: Path, file: dict) -> None:
    """One line per part: the small file its agent reads → the answer file it writes (K17)."""
    for pid, part in parts_of(file):
        print(f"  {label(pid)}: {week / part_path(file['omgång'], pid)} → {week / part['svarsfil']}")


def _print_round(week: Path, result: DecideResult) -> int:
    if result.status == "skicka om":
        for r in result.resend:
            print(f"Skicka om: {label(r.part)} → {r.path} ({r.problem})", file=sys.stderr)
        print(f"Omgång {result.round_no}: {len(result.resend)} svar behöver skickas om → {week / CANDIDATE_FILE}")
    else:
        file = read_round(week)
        review = len(file["granskning"]["varor"]) if file["granskning"] else 0
        print(f"Omgång 2 behövs: {len(file['batcher'])} batcher, granskning {review} varor → {result.candidate_file}")
        _print_parts(week, file)
    return EXIT_MATCHING


@dataclass
class _Run:
    """What `plan` and `decide` both need before they search: the week, its list and the config."""

    contact: str
    week: Path
    rules: Rules
    pins: Pins
    shopping: ShoppingList
    now: datetime


def _prepare(args: argparse.Namespace) -> _Run:
    root = _root(args)
    _load_env(root)
    contact = _contact()
    week = _week(root, args.vecka)
    return _Run(contact=contact, week=week, rules=_rules(args), pins=load_pins(Path(args.pins)),
                shopping=load_shopping_list(week / SHOPPING_LIST), now=datetime.now().astimezone())


def cmd_plan(args: argparse.Namespace) -> int:
    run = _prepare(args)
    week, shopping, now = run.week, run.shopping, run.now
    with make_session(run.contact) as session:
        planner = _planner(session, week, run.rules, run.pins)
        settled = settle_all(shopping, planner, args.hoppa)
    clear_matching(week)                                       # K11: old answers never leak
    if settled.pending:
        (week / PLAN_FILE).unlink(missing_ok=True)
        file, dropped = build_candidate_file(week.name, 1, settled.pending, now=now)
        path = write_round(week, file)
        for warning in drop_warnings(settled.pending, dropped):
            _warn(warning)
        print(f"{len(settled.pending)} varor behöver matchning · omgång 1 · {len(file['batcher'])} batcher → {path}")
        _print_parts(week, file)
        return EXIT_MATCHING
    plan = planner.finish(week=week.name, now=now, outcomes=[settled.decided[v] for v in settled.order],
                          skipped=settled.skipped, excluded=[*shopping.excluded, *settled.excluded])
    return _write_plan(week, plan)


def cmd_decide(args: argparse.Namespace) -> int:
    run = _prepare(args)
    week, shopping, now = run.week, run.shopping, run.now
    asker = TerminalAsker() if sys.stdin.isatty() and not args.no_input else None
    with make_session(run.contact) as session:
        planner = _planner(session, week, run.rules, run.pins)
        settled = settle_all(shopping, planner, args.hoppa)
        outcomes: dict[str, PlanLine | Undecided] = dict(settled.decided)
        if settled.pending:
            if not (week / CANDIDATE_FILE).is_file():
                raise CliError(f"hittar inte {week / CANDIDATE_FILE} — kör plan först")
            try:
                result = decide(DecideDeps(week_dir=week, week=week.name, now=now, pending=settled.pending,
                                           candidates_for=planner.candidates_for, line_for=planner.line_for,
                                           undecided_for=planner.undecided_for))
            except DecideError as err:
                raise CliError(str(err)) from None
            for warning in result.warnings:
                planner.warn(warning)
            if result.status != "klar":
                (week / PLAN_FILE).unlink(missing_ok=True)
                return _print_round(week, result)
            outcomes.update(result.outcomes)
        skipped = list(settled.skipped)
        if asker is not None:
            _ask_all(planner, settled, outcomes, skipped, asker)
    plan = planner.finish(week=week.name, now=now, outcomes=[outcomes[v] for v in settled.order if v in outcomes],
                          skipped=skipped, excluded=[*shopping.excluded, *settled.excluded])
    return _write_plan(week, plan)


def cmd_apply(args: argparse.Namespace) -> int:
    root = _root(args)
    week = _week(root, args.vecka)
    path = week / PLAN_FILE
    if not path.is_file():
        raise CliError(f"hittar inte planen: {path} — kör plan först")
    try:
        plan = Plan.read(path)
    except (ValueError, KeyError, TypeError) as err:
        raise CliError(f"kunde inte läsa planen {path}: {err} — kör plan igen") from None
    if not plan.lines:
        print("Inget att lägga i varukorgen.")
        return EXIT_OK
    rules = _rules(args)
    check_safety(plan, rules, datetime.now(timezone.utc))   # before any network or login
    if plan.undecided:
        _warn(f"{len(plan.undecided)} varor behöver fortfarande beslut och läggs inte i varukorgen")
    _load_env(root)
    missing = [var for var in ("MATHEM_EMAIL", "MATHEM_PASSWORD") if not os.environ.get(var)]
    if missing:
        raise CliError(f"{' och '.join(missing)} saknas i miljön — lägg in i .env")
    email, password = os.environ["MATHEM_EMAIL"], os.environ["MATHEM_PASSWORD"]
    contact = _contact()
    with make_session(contact) as session:
        session.login(email, password)
        result = apply_plan(plan, CartClient(session), rules, now=datetime.now(timezone.utc),
                            relogin=lambda: session.login(email, password))
    report = week / REPORT_FILE
    report.write_text(render_report(plan, result), encoding="utf-8")
    for difference in result.differences:
        print(f"Avvikelse: {difference}", file=sys.stderr)
    if result.error:
        print(f"Fel: {result.error}", file=sys.stderr)
        print(f"Se {report}. Töm varukorgen på mathem.se och kör apply igen.", file=sys.stderr)
        return EXIT_ERROR
    in_cart = sum(result.actual.values())
    print(f"{in_cart} st av {len(result.actual)} produkter i varukorgen · {len(result.differences)} avvikelser → {report}")
    print("Ingen beställning är gjord — kontrollera varukorgen och beställ själv i Mathem-appen.")
    return EXIT_OK


def cmd_pin(args: argparse.Namespace) -> int:
    if args.produkt_id is None and not args.sok:
        raise CliError("ange ett produkt-id och/eller --sök TERM")
    if args.fast and args.produkt_id is None:
        raise CliError("--fast kräver ett produkt-id")
    key = normalize_key(args.ingrediens)
    if not key:
        raise CliError("tomt ingrediensnamn")
    pins = load_pins(Path(args.pins))
    saved = []
    if args.produkt_id is not None:
        if args.fast:
            pins.set_fixed(key, args.produkt_id)
            saved.append(f"fast {args.produkt_id}")
        else:
            pins.approve(key, args.produkt_id)
            saved.append(f"godkänd {args.produkt_id}")
    if args.sok:
        pins.set_search(key, args.sok)
        saved.append(f"sökterm “{args.sok.strip()}”")
    pins.save()
    print(f"Sparat för {key}: {', '.join(saved)} ({pins.path})")
    return EXIT_OK


def cmd_sok(args: argparse.Namespace) -> int:
    root = _root(args)
    _load_env(root)
    contact = _contact()
    with make_session(contact) as session:
        results = ProductsClient(session).search(args.term, limit=SEARCH_LIMIT)
    if not results:
        print(f"Inga träffar för “{args.term}”.")
        return EXIT_OK
    print("id  namn  förpackning  pris  jämförpris  kampanj")
    for p in results:
        c = candidate_view(p)
        print("  ".join([str(c.product_id), c.name, c.package or "—", fmt_kr(c.price),
                         fmt_unit_price(c.unit_price), c.deal or "—"]))
    return EXIT_OK


# --- argument parsing ----------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    """Usage errors exit 1: exit code 2 means "plan has undecided items"."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: fel: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    shared = _Parser(add_help=False)
    shared.add_argument("--root", help="repo-roten (standard: sök uppåt, eller MATHEM_CART_ROOT)")
    shared.add_argument("--regler", default=str(DEFAULT_RULES), help="regelfil (mathem-regler.yaml)")
    shared.add_argument("--pins", default=str(DEFAULT_PINS), help="pin-fil (mathem-pins.local.yaml)")

    parser = _Parser(prog="mathem-cart",
                     description="Fyll Mathem-varukorgen från veckans handlingslista. Lägger aldrig en beställning.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="kommando", parser_class=_Parser)

    p = sub.add_parser("plan", parents=[shared], help="gör en plan (loggar aldrig in)")
    p.add_argument("vecka", nargs="?", help="veckomapp ÅÅÅÅ-MM-DD (standard: senaste)")
    p.add_argument("--no-input", action="store_true", help="ignoreras (kvar för skript); plan frågar aldrig")
    p.add_argument("--hoppa", action="append", default=[], metavar="VARA", help="hoppa över en vara (upprepas)")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("decide", parents=[shared], help="gör planen av agenternas svar (loggar aldrig in)")
    p.add_argument("vecka", nargs="?", help="veckomapp ÅÅÅÅ-MM-DD (standard: senaste)")
    p.add_argument("--no-input", action="store_true", help="fråga inte; oavgjorda varor hamnar i planen")
    p.add_argument("--hoppa", action="append", default=[], metavar="VARA", help="hoppa över en vara (upprepas)")
    p.set_defaults(func=cmd_decide)

    p = sub.add_parser("apply", parents=[shared], help="lägg en sparad plan i varukorgen")
    p.add_argument("vecka", nargs="?", help="veckomapp ÅÅÅÅ-MM-DD (standard: senaste)")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("pin", parents=[shared], help="spara en produkt eller sökterm för en ingrediens")
    p.add_argument("ingrediens")
    p.add_argument("produkt_id", nargs="?", type=int)
    p.add_argument("--fast", action="store_true", help="alltid exakt den här produkten")
    p.add_argument("--sök", "--sok", dest="sok", metavar="TERM", help="egen sökterm")
    p.set_defaults(func=cmd_pin)

    p = sub.add_parser("sök", aliases=["sok"], parents=[shared], help="visa de 10 första sökträffarna")
    p.add_argument("term")
    p.set_defaults(func=cmd_sok)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as err:   # usage error (exit 1) or --help (exit 0): return the code, don't raise
        return err.code if isinstance(err.code, int) else EXIT_ERROR
    try:
        return args.func(args)
    except SafetyAbort as err:
        print(f"Avbrutet av säkerhetsskäl: {err}", file=sys.stderr)
        return EXIT_SAFETY
    except (CliError, MathemError, FileNotFoundError, RulesError) as err:
        print(f"Fel: {err}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
