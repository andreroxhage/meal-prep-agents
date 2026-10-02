"""Structural guarantees: no path to checkout, slots or orders; one network module; no model client."""

import ast
import re
from pathlib import Path

import pytest

PKG = Path(__file__).parents[1] / "mathem_cart"
FILES = {p.relative_to(PKG).as_posix(): p.read_text(encoding="utf-8") for p in PKG.rglob("*.py")}


def imported_modules(text):
    """Top-level names of every module the source imports, including dynamic imports by literal name."""
    names = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if called in ("import_module", "__import__") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names.add(arg.value.split(".")[0])
    return names


IMPORTS = {n: imported_modules(t) for n, t in FILES.items()}


def test_only_session_imports_httpx():
    assert sorted(n for n, mods in IMPORTS.items() if "httpx" in mods) == ["mathem/session.py"]


def test_banned_words_only_in_session_ban_list():
    offenders = [n for n, t in FILES.items() if n != "mathem/session.py"
                 and re.search(r"checkout|/slots?/|/orders?/", t, re.I)]
    assert offenders == []


def test_no_other_http_clients():
    for name, mods in IMPORTS.items():
        assert not mods & {"requests", "urllib", "urllib3", "aiohttp"}, name


def test_environment_only_read_in_cli():
    readers = [n for n, t in FILES.items() if re.search(r"\benviron\b|getenv|load_dotenv|dotenv_values", t)]
    assert readers == ["cli.py"]


CART_OR_LOGIN = {"login", "CartClient", "apply_plan", "post_json"}
CART_OR_LOGIN_HOMES = {"mathem/session.py", "mathem/cart.py", "applier.py"}


def cart_or_login_calls(name, text):
    """(file, enclosing top-level function) for every call to a cart/login name, aliases resolved."""
    tree = ast.parse(text)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name.split(".")[-1]
    records = set()
    for top in tree.body:
        owner = getattr(top, "name", "<module>") if isinstance(
            top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else "<module>"
        for node in ast.walk(top):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                called = aliases.get(func.id, func.id)
            elif isinstance(func, ast.Attribute):
                called = func.attr
            else:
                continue
            if called in CART_OR_LOGIN:
                records.add((name, owner))
    return records


def test_only_cmd_apply_touches_cart_or_login():
    # plan/decide (and every helper they call) never log in or touch the cart.
    records = set()
    for name, text in FILES.items():
        if name not in CART_OR_LOGIN_HOMES:
            records |= cart_or_login_calls(name, text)
    assert records == {("cli.py", "cmd_apply")}


def test_model_side_modules_never_see_pins():
    # M3: model picks are never saved as pins.
    for name in ("decider.py", "answers.py", "candidates.py"):
        assert not re.search(r"^\s*from \.pins|^\s*import .*pins", FILES[name], re.M), name


MODEL_CLIENTS = {"laya", "anthropic", "openai", "claude_agent_sdk", "transformers", "torch"}


def test_no_model_clients():
    # M1: the CLI never calls a model and needs no API key.
    assert [n for n, mods in IMPORTS.items() if mods & MODEL_CLIENTS] == []
    assert not any("ANTHROPIC" in t for t in FILES.values())
    pyproject = (PKG.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert [c for c in sorted(MODEL_CLIENTS) if c in pyproject] == []
