"""Willys provider: search parsing, allowlist, login, cart, and the CLI with --butik willys. Offline."""

import base64
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from mathem_cart import candidates, cli
from mathem_cart.answers import _is_id
from mathem_cart.ids import norm_id
from mathem_cart.mathem.errors import ForbiddenEndpoint, MathemAuthError, MathemProtocolError
from mathem_cart.packaging import parse_package, parse_pricing
from mathem_cart.pins import load_pins
from mathem_cart.plan_model import Plan
from mathem_cart.quantity import cost_for
from mathem_cart.rules import load_rules
from mathem_cart.willys.cart import WillysCart, cart_from_willys
from mathem_cart.willys.products import WillysProducts, parse_search, product_from_willys
from mathem_cart.willys.session import (ORIGIN, WillysSession, check_allowed, encrypt_field,
                                        normalize_username)

FIX = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIX / "willys-search.json").read_text(encoding="utf-8"))
CONTACT = "https://example.org/kontakt"
PKG = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def _mathem_names():
    yield
    candidates.use_store("mathem")   # the CLI points module state at a store; reset for other tests


def by_code(code):
    products, _ = parse_search(SEARCH)
    return next(p for p in products if p.id == code)


def session_with(handler):
    return WillysSession(CONTACT, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


# --- search parsing -----------------------------------------------------------------

def test_product_sold_per_kg_costs_one_piece():
    p = by_code("100149359_KG")   # Paprika Röd, 59,90 kr/kg, ca 200 g
    assert p.name_extra == "ca 200 g"
    assert p.gross_price == pytest.approx(11.98)
    assert (p.gross_unit_price, p.unit_price_unit) == (59.9, "kg")
    pkg = parse_package(p)
    assert pkg.size.value == 200 and pkg.size.dim == "g" and pkg.approximate and pkg.flags == ()


def test_ca_weight_for_one_kilo_pack():
    p = by_code("101203634_KG")   # Nötfärs 12 %, ca: 1kg, 152 kr/kg
    assert p.name_extra == "ca 1000 g" and p.gross_price == 152.0


def test_pack_sold_per_piece_reads_display_volume():
    p = by_code("100816299_ST")
    assert p.name_extra == "400g" and p.gross_price == 29.9
    assert parse_package(p).size.value == 400


def test_single_unit_member_promotion_is_price_with_limit():
    p = by_code("101106287_ST")   # Spara 9,00 kr/st, Max 3 köp, LOYALTY
    assert p.gross_price == 69.9
    pricing = parse_pricing(p)
    assert pricing.discount_limit == 3 and pricing.undiscounted_price == 78.9
    assert cost_for(4, p.gross_price, pricing.deals, pricing.discount_limit, pricing.undiscounted_price) == \
        pytest.approx(3 * 69.9 + 78.9)
    assert any("Willys Plus" in t for t in pricing.informational)


def test_multi_buy_promotion_is_a_deal():
    p = by_code("101667240_ST")   # Välj & blanda! 3 för 35,00
    deals = parse_pricing(p).deals
    assert [(d.count, d.price) for d in deals] == [(3, 35.0)]
    assert p.gross_price == 14.9


def test_labels_become_rule_labels():
    p = by_code("101106287_ST")
    assert "Från Sverige" in p.classifiers and "Kött från Sverige" in p.classifiers
    assert by_code("101203622_KG").classifiers == ()   # Irish mince: no Swedish label


def test_frozen_label_puts_fryst_in_name_and_stock_decides_availability():
    raw = {"code": "1_ST", "name": "Kycklingfilé", "priceValue": 99, "displayVolume": "1kg",
           "labels": ["frozen"], "outOfStock": True}
    p = product_from_willys(raw)
    assert p.full_name == "Kycklingfilé Fryst" and not p.available
    assert product_from_willys({**raw, "outOfStock": False}).available


def test_weighed_product_without_weight_is_unavailable():
    p = product_from_willys({"code": "2_KG", "name": "Lök", "priceValue": 10.9, "displayVolume": ""})
    assert p.gross_price is None and not p.available


def test_no_hits_and_paging():
    empty = {"results": None, "pagination": {"currentPage": 0, "numberOfPages": 0, "totalNumberOfResults": 0}}
    assert parse_search(empty) == ([], False)
    assert parse_search(SEARCH)[1] is True   # page 0 of 2
    with pytest.raises(MathemProtocolError):
        parse_search({"results": None, "pagination": {"totalNumberOfResults": 3}})
    with pytest.raises(MathemProtocolError):
        parse_search({"results": []})


def test_search_pages_and_caches(tmp_path):
    from mathem_cart.mathem.products import SearchCache
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=SEARCH)

    with session_with(handler) as s:
        client = WillysProducts(s, SearchCache(tmp_path))
        assert len(client.search("Paprika", limit=30)) == len(SEARCH["results"])
        client.search("paprika", limit=30)
    # Page 1 adds nothing new, so paging stops there; the second search comes from the cache.
    assert [r.url.params["page"] for r in seen] == ["0", "1"]
    assert seen[0].url.path == "/search" and dict(seen[0].url.params) == {"q": "paprika", "size": "30", "page": "0"}
    assert seen[0].headers["user-agent"] == f"meal-prep-bot/0.1 (+{CONTACT})"


def test_unknown_product_code_is_none():
    with session_with(lambda r: httpx.Response(400, json={})) as s:
        assert WillysProducts(s).product("999_ST") is None


def test_non_willys_code_is_none_without_a_request():
    def handler(request):
        raise AssertionError("no request expected")
    with session_with(handler) as s:
        for pin in (12345, "abc", "1_ST/../checkout"):
            assert WillysProducts(s).product(pin) is None


def test_lowercase_code_is_upper_cased():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(400, json={})
    with session_with(handler) as s:
        WillysProducts(s).product("101106287_st")
    assert seen == ["/axfood/rest/p/101106287_ST"]


def test_reward_label_ending_in_kr_is_not_doubled():
    raw = {"code": "1_ST", "name": "X", "priceValue": 30, "displayVolume": "1 st",
           "potentialPromotions": [{"qualifyingCount": 2, "rewardLabel": "50,00 kr", "conditionLabel": "2 för"}]}
    assert product_from_willys(raw).promotions == ("2 för 50,00 kr",)


# --- allowlist ----------------------------------------------------------------------

@pytest.mark.parametrize("method,url", [
    ("GET", f"{ORIGIN}/search?q=gr%C3%A4dde&size=30&page=0"),
    ("GET", f"{ORIGIN}/axfood/rest/p/101106287_ST"),
    ("GET", f"{ORIGIN}/anvandare/inloggning"),
    ("POST", f"{ORIGIN}/login"),
    ("GET", f"{ORIGIN}/axfood/rest/csrf-token"),
    ("GET", f"{ORIGIN}/axfood/rest/cart"),
    ("POST", f"{ORIGIN}/axfood/rest/cart/addProducts"),
])
def test_allowlisted(method, url):
    check_allowed(method, url)


@pytest.mark.parametrize("method,url", [
    ("GET", f"{ORIGIN}/axfood/rest/tms/delivery-slots"),
    ("GET", f"{ORIGIN}/axfood/rest/pickup-slots"),
    ("POST", f"{ORIGIN}/axfood/rest/checkout/placeOrder"),
    ("GET", f"{ORIGIN}/axfood/rest/account/orders"),
    ("GET", f"{ORIGIN}/axfood/rest/orderdata?q=1"),
    ("GET", f"{ORIGIN}/axfood/rest/customer"),          # carries the personnummer; never read
    ("POST", f"{ORIGIN}/axfood/rest/payment"),
    ("GET", f"{ORIGIN}/kassa"),
    ("POST", f"{ORIGIN}/search"),
    ("GET", f"{ORIGIN}/search?q=x&sort=price"),
    ("GET", "https://www.hemkop.se/search?q=x"),
    ("GET", "http://www.willys.se/search?q=x"),
    ("GET", f"{ORIGIN}/axfood/rest/p/1_ST%0A"),          # $ alone would match before a newline
])
def test_forbidden(method, url):
    with pytest.raises(ForbiddenEndpoint):
        check_allowed(method, url)


def test_redirect_into_checkout_is_blocked():
    sent = []

    def handler(request):
        sent.append(request.url.path)
        return httpx.Response(302, headers={"location": f"{ORIGIN}/checkout"})

    with session_with(handler) as s, pytest.raises(ForbiddenEndpoint):
        s.get_json("/search", {"q": "mjölk", "size": 30, "page": 0})
    assert sent == ["/search"]


# --- login --------------------------------------------------------------------------

def decrypt(packed, key):
    iv_hex, salt_hex, cipher_b64 = base64.b64decode(packed).decode().split("::")
    aes = hashlib.pbkdf2_hmac("sha1", key.encode(), bytes.fromhex(salt_hex), 1000, 16)
    dec = Cipher(algorithms.AES(aes), modes.CBC(bytes.fromhex(iv_hex))).decryptor()
    unpad = padding.PKCS7(128).unpadder()
    return (unpad.update(dec.update(base64.b64decode(cipher_b64)) + dec.finalize()) + unpad.finalize()).decode()


def test_encrypt_field_round_trips():
    packed, key = encrypt_field("hemligt-lösen")
    assert len(key) == 16 and key.isdigit()
    assert decrypt(packed, key) == "hemligt-lösen"


def test_normalize_username():
    assert normalize_username("8112189876", date(2026, 1, 1)) == "198112189876"
    assert normalize_username("0503031234", date(2026, 1, 1)) == "200503031234"
    assert normalize_username("198112189876") == "198112189876"


def login_handler(success=True, sent=None, flag="true"):
    def handler(request):
        if sent is not None:
            sent.append(request)
        if request.url.path == "/anvandare/inloggning":
            return httpx.Response(200, text="<html>", headers={"set-cookie": "JSESSIONID=anon; Path=/"})
        if request.url.path == "/login":
            body = {"login_successful": flag} if success else {"login_successful": "false",
                                                                  "message": "Bad credentials"}
            return httpx.Response(200, json=body, headers={"set-cookie": "JSESSIONID=auth; Path=/"})
        return httpx.Response(404)
    return handler


def test_login_accepts_a_json_boolean():
    with session_with(login_handler(flag=True)) as s:
        s.login("user@example.com", "pw")


def test_login_sends_encrypted_fields():
    sent = []
    with session_with(login_handler(sent=sent)) as s:
        s.login("8112189876", "hemligt-lösen")
    body = json.loads(sent[-1].content)
    assert decrypt(body["j_username"], body["j_username_key"]).endswith("8112189876")
    assert decrypt(body["j_password"], body["j_password_key"]) == "hemligt-lösen"
    assert b"hemligt" not in sent[-1].content


def test_rejected_login_does_not_leak(caplog):
    caplog.set_level(logging.DEBUG)
    with session_with(login_handler(success=False)) as s, pytest.raises(MathemAuthError) as exc:
        s.login("8112189876", "hemligt-lösen")
    text = str(exc.value) + repr(exc.value.__context__) + repr(exc.value.__cause__) + caplog.text
    assert "hemligt" not in text and "8112189876" not in text and "WILLYS_PASSWORD" in str(exc.value)


# --- cart ---------------------------------------------------------------------------

def test_cart_parse_fails_closed():
    assert cart_from_willys({"products": [], "totalItems": 0}).is_empty
    assert cart_from_willys({"products": None, "totalItems": 0}).is_empty
    for bad in ({}, {"products": [], "totalItems": 2}, {"products": [{"name": "x", "quantity": 1}]},
                {"products": [{"code": "1_ST"}]}, {"products": "x"},
                {"products": None}, {"products": None, "totalItems": None}, {"products": None, "totalItems": False}):
        with pytest.raises(MathemProtocolError):
            cart_from_willys(bad)


def test_add_sets_current_plus_delta_with_csrf():
    state = {"101106287_ST": 1}
    posts = []

    def handler(request):
        path = request.url.path
        if path == "/axfood/rest/csrf-token":
            return httpx.Response(200, json="tok-1")
        if path == "/axfood/rest/cart":
            assert request.headers["x-csrf-token"] == "tok-1"
            return httpx.Response(200, json={"totalItems": sum(state.values()), "products": [
                {"code": c, "name": "Nötfärs", "quantity": q} for c, q in state.items()]})
        if path == "/axfood/rest/cart/addProducts":
            posts.append(request)
            item = json.loads(request.content)["products"][0]
            state[item["productCodePost"]] = item["qty"]
            return httpx.Response(200, text="ok")
        return httpx.Response(404)

    with session_with(handler) as s:
        cart = WillysCart(s).add("101106287_ST", 2)
    assert cart.quantity_of("101106287_ST") == 3
    item = json.loads(posts[0].content)["products"][0]
    assert item == {"productCodePost": "101106287_ST", "qty": 3, "pickUnit": "pieces",
                    "hideDiscountToolTip": False, "noReplacementFlag": False}
    assert posts[0].headers["x-csrf-token"] == "tok-1"


# --- ids, answers, rules ------------------------------------------------------------

def test_ids_and_answers_accept_willys_codes():
    assert norm_id("101106287_ST") == "101106287_ST" and norm_id("6851") == 6851 and norm_id(6851) == 6851
    with pytest.raises(ValueError):
        norm_id("1; rm")
    assert _is_id("101106287_ST") and _is_id(6851) and not _is_id(True) and not _is_id("abc")


def test_pins_keep_willys_codes(tmp_path):
    pins = load_pins(tmp_path / "willys-pins.local.yaml")
    pins.approve("nötfärs", "101106287_ST")
    pins.set_fixed("gul lök", "100269139_KG")
    pins.save()
    again = load_pins(tmp_path / "willys-pins.local.yaml")
    assert again.get("nötfärs").approved == ["101106287_ST"] and again.get("gul lök").fixed == "100269139_KG"


def test_willys_rules_load_and_read_the_new_key():
    rules = load_rules(PKG / "willys-regler.yaml")
    assert rules.bought_elsewhere("torrt vitt vin") == "Systembolaget"


# --- CLI ----------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "tools" / "mathem_cart").mkdir(parents=True)
    (tmp_path / "tools" / "mathem_cart" / "pyproject.toml").write_text("")
    week = tmp_path / "2026-11-23"
    week.mkdir()
    (week / "03-handlingslista.md").write_text("## Grönsaker\n- 2 röda paprikor\n", encoding="utf-8")
    monkeypatch.setenv("MATHEM_CART_ROOT", str(tmp_path))
    monkeypatch.delenv("MATHEM_BOT_CONTACT", raising=False)
    monkeypatch.setenv("BOT_CONTACT", CONTACT)
    for var in ("WILLYS_USERNAME", "WILLYS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path, week, ["--butik", "willys", "--pins", str(tmp_path / "pins.yaml")]


def test_plan_writes_willys_files(repo, monkeypatch):
    root, week, extra = repo
    monkeypatch.setattr(cli, "make_session", lambda c: pytest.fail("Mathem session for --butik willys"))
    monkeypatch.setattr(cli, "make_willys_session", lambda c: session_with(lambda r: httpx.Response(200, json=SEARCH)))
    assert cli.main(["plan", "2026-11-23", "--no-input", *extra]) == 4
    assert (week / "06-willys-kandidater.json").is_file() and (week / ".willys-matchning").is_dir()
    assert (week / ".willys-cache").is_dir()
    assert not (week / "06-mathem-kandidater.json").exists() and not (week / ".mathem-cache").exists()
    file = json.loads((week / "06-willys-kandidater.json").read_text(encoding="utf-8"))
    shown = file["batcher"][0]["varor"][0]["kandidater"]
    assert {"produkt_id", "namn", "förpackning", "märkning"} == set(shown[0])   # agents never see prices
    assert any(c["produkt_id"] == "100149359_KG" for c in shown)


def write_plan(week, store, created):
    row = {"vara": "nötfärs", "behov": {"mängd": 1000, "enhet": "g"}, "kategori": "Kött & Fisk",
           "produkt_id": "101106287_ST", "namn": "Nötfärs 12% Sverige", "förpackning": "500g", "antal": 2,
           "kostnad_kr": 139.8, "jämförpris": "139.8 kr/kg", "kampanj": None, "överköp": 0.0,
           "beslut": "pin", "flaggor": []}
    (week / f"06-{store}-plan.json").write_text(json.dumps({
        "vecka": week.name, "butik": "willys", "skapad": created.isoformat(), "rader": [row], "undecided": [],
        "hoppade": [], "ej_med": [], "varningar": [], "total_kr": 139.8}), encoding="utf-8")


def test_apply_needs_willys_credentials_and_never_opens_a_session(repo, monkeypatch, capsys):
    root, week, extra = repo
    write_plan(week, "willys", datetime.now(timezone.utc))
    monkeypatch.setattr(cli, "make_willys_session", lambda c: pytest.fail("no session without credentials"))
    assert cli.main(["apply", "2026-11-23", *extra]) == 1
    assert "WILLYS_USERNAME och WILLYS_PASSWORD saknas" in capsys.readouterr().err


def test_apply_stale_willys_plan_is_a_safety_stop(repo, monkeypatch):
    root, week, extra = repo
    write_plan(week, "willys", datetime.now(timezone.utc) - timedelta(days=2))
    monkeypatch.setattr(cli, "make_willys_session", lambda c: pytest.fail("no session for a stale plan"))
    assert cli.main(["apply", "2026-11-23", *extra]) == 3


def test_apply_refuses_a_plan_made_for_another_store(repo, monkeypatch, capsys):
    root, week, extra = repo
    write_plan(week, "mathem", datetime.now(timezone.utc))   # a Willys plan saved under the Mathem name
    monkeypatch.setattr(cli, "make_session", lambda c: pytest.fail("no session"))
    assert cli.main(["apply", "2026-11-23", "--pins", str(root / "p.yaml")]) == 1
    assert "gjord för willys, inte mathem" in capsys.readouterr().err


def test_apply_end_to_end_with_mock_willys(repo, monkeypatch, capsys):
    root, week, extra = repo
    write_plan(week, "willys", datetime.now(timezone.utc))
    monkeypatch.setenv("WILLYS_USERNAME", "8112189876")
    monkeypatch.setenv("WILLYS_PASSWORD", "hemligt-lösen")
    cart: dict[str, int] = {}
    login = login_handler()

    def handler(request):
        path = request.url.path
        if path in ("/anvandare/inloggning", "/login"):
            return login(request)
        if path == "/axfood/rest/csrf-token":
            return httpx.Response(200, json={"token": "t"})
        if path == "/axfood/rest/cart":
            return httpx.Response(200, json={"totalItems": sum(cart.values()), "products": [
                {"code": c, "name": "Nötfärs 12% Sverige", "quantity": q} for c, q in cart.items()]})
        if path == "/axfood/rest/cart/addProducts":
            item = json.loads(request.content)["products"][0]
            cart[item["productCodePost"]] = item["qty"]
            return httpx.Response(200, json={})
        return httpx.Response(404)

    monkeypatch.setattr(cli, "make_willys_session", lambda c: session_with(handler))
    assert cli.main(["apply", "2026-11-23", *extra]) == 0
    out = capsys.readouterr()
    assert cart == {"101106287_ST": 2}
    assert "beställ själv hos Willys" in out.out and "hemligt" not in out.out + out.err
    report = (week / "06-willys-varukorg.md").read_text(encoding="utf-8")
    assert report.startswith("# Steg 6 — Willys-varukorg") and "Alla 1 rader finns i varukorgen" in report
