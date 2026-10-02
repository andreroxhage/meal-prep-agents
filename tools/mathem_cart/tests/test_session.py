import logging
from datetime import datetime, timezone

import httpx
import pytest

from mathem_cart.mathem.errors import ForbiddenEndpoint, MathemAuthError, MathemError, MathemRequestError
from mathem_cart.mathem.session import BASE_URL, LOGIN_PAGE_URL, MathemSession, check_allowed

CONTACT = "https://example.org/kontakt"


class Recorder:
    def __init__(self, responses=None):
        self.requests: list[httpx.Request] = []
        self.responses = list(responses or [])

    def __call__(self, request):
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(200, json={"items": []})


def make(recorder, **kw):
    fake_time = {"t": 0.0}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        fake_time["t"] += s

    session = MathemSession(CONTACT, client=httpx.Client(transport=httpx.MockTransport(recorder)),
                            sleep=sleep, clock=lambda: fake_time["t"], **kw)
    return session, sleeps


@pytest.mark.parametrize("method,url", [
    ("GET", f"{BASE_URL}/search/mixed/?q=gr%C3%A4dde&type=product&page=1"),
    ("GET", f"{BASE_URL}/products/6851/"),
    ("GET", LOGIN_PAGE_URL),
    ("POST", f"{BASE_URL}/user/login/"),
    ("GET", f"{BASE_URL}/cart/?group-by=recipes"),
    ("POST", f"{BASE_URL}/cart/items/?group-by=recipes"),
])
def test_allowlisted(method, url):
    check_allowed(method, url)


@pytest.mark.parametrize("method,url", [
    ("POST", f"{BASE_URL}/checkout/confirm/"),
    ("GET", f"{BASE_URL}/checkout/"),
    ("GET", f"{BASE_URL}/slots/"),
    ("GET", f"{BASE_URL}/delivery/slots/2026-09-25/"),
    ("GET", f"{BASE_URL}/orders/"),
    ("POST", f"{BASE_URL}/orders/123/"),
    ("DELETE", f"{BASE_URL}/cart/"),
    ("POST", f"{BASE_URL}/cart/"),
    ("GET", f"{BASE_URL}/cart/items/"),
    ("POST", f"{BASE_URL}/search/mixed/"),
    ("GET", f"{BASE_URL}/user/"),
    ("GET", "https://evil.example/api/v1/search/mixed/"),
    ("GET", "http://www.mathem.se/api/v1/search/mixed/"),
    ("GET", f"{BASE_URL}/search/mixed/?q=x&next=/checkout/confirm/"),   # unknown query key
    ("GET", f"{BASE_URL}/products/abc/"),
    ("GET", "https://www.mathem.se:8443/api/v1/search/mixed/"),
])
def test_forbidden(method, url):
    with pytest.raises(ForbiddenEndpoint):
        check_allowed(method, url)


def test_query_values_may_contain_banned_words():
    # Review Focus 1: "Slotts senap" is a real brand; the ban is on the path.
    check_allowed("GET", f"{BASE_URL}/search/mixed/?q=Slotts+senap&type=product&page=1")
    check_allowed("GET", f"{BASE_URL}/search/mixed/?q=order&type=product&page=1")


def test_forbidden_raises_before_any_request():
    rec = Recorder()
    session, _ = make(rec)
    for path in ("/checkout/confirm/", "/slots/", "/orders/"):
        with pytest.raises(ForbiddenEndpoint):
            session.get_json(path)
        with pytest.raises(ForbiddenEndpoint):
            session.post_json(path, {})
    assert rec.requests == []


def test_redirect_into_forbidden_path_is_blocked():
    rec = Recorder([httpx.Response(302, headers={"location": f"{BASE_URL}/checkout/confirm/"})])
    session, _ = make(rec)
    with pytest.raises(ForbiddenEndpoint):
        session.get_json("/search/mixed/", {"q": "mjölk", "type": "product", "page": 1})
    assert len(rec.requests) == 1


def test_user_agent_and_no_contact_in_code():
    rec = Recorder()
    session, _ = make(rec)
    session.get_json("/search/mixed/", {"q": "mjölk", "type": "product", "page": 1})
    assert rec.requests[0].headers["user-agent"] == f"meal-prep-bot/0.1 (+{CONTACT})"
    assert "x-requested-case" not in rec.requests[0].headers


def test_empty_contact_is_rejected():
    with pytest.raises(ValueError):
        MathemSession("  ")


def test_rate_limit_one_per_second():
    rec = Recorder()
    session, sleeps = make(rec)
    for _ in range(3):
        session.get_json("/search/mixed/", {"q": "mjölk", "type": "product", "page": 1})
    assert sleeps == [1.0, 1.0]


def test_backoff_honours_retry_after_then_succeeds():
    rec = Recorder([httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(503),
                    httpx.Response(200, json={"ok": True})])
    session, sleeps = make(rec)
    assert session.get_json("/products/1/") == {"ok": True}
    assert 7 in sleeps and 2 in sleeps      # Retry-After, then 2**1


def test_backoff_gives_up():
    rec = Recorder([httpx.Response(500)] * 10)
    session, _ = make(rec, max_retries=2)
    with pytest.raises(MathemRequestError):
        session.get_json("/products/1/")
    assert len(rec.requests) == 3


def test_401_is_auth_error():
    session, _ = make(Recorder([httpx.Response(401)]))
    with pytest.raises(MathemAuthError):
        session.get_json("/cart/", {"group-by": "recipes"}, camel=True)


def _login_responses(ok=True):
    page = httpx.Response(200, text="<html>", headers={"set-cookie": "csrftoken=tok123; Path=/"})
    if ok:
        post = httpx.Response(200, json={"id": 1}, headers={"set-cookie": "sessionid=s3cr; Path=/"})
    else:
        post = httpx.Response(400, json={"detail": "Fel lösenord för hemlig@example.org"})
    return [page, post]


def test_login_flow_sends_csrf_and_camel_headers():
    rec = Recorder(_login_responses())
    session, _ = make(rec)
    session.login("hemlig@example.org", "pw-123-hemligt")
    page, post = rec.requests
    assert str(page.url) == LOGIN_PAGE_URL and page.headers["accept"].startswith("text/html")
    assert post.method == "POST" and post.headers["x-csrftoken"] == "tok123"
    assert post.headers["x-requested-case"] == "camel"


def test_credentials_never_leak(caplog):
    caplog.set_level(logging.DEBUG)
    rec = Recorder(_login_responses(ok=False))
    session, _ = make(rec)
    with pytest.raises(MathemAuthError) as err:
        session.login("hemlig@example.org", "pw-123-hemligt")
    text = str(err.value) + repr(err.value) + caplog.text + repr(session)
    assert "hemlig@example.org" not in text and "pw-123-hemligt" not in text
    assert err.value.__cause__ is None and err.value.__context__ is None
    assert ".env" in str(err.value)


def test_login_without_sessionid_is_auth_error():
    page = httpx.Response(200, text="<html>", headers={"set-cookie": "csrftoken=tok; Path=/"})
    rec = Recorder([page, httpx.Response(200, json={})])
    session, _ = make(rec)
    with pytest.raises(MathemAuthError):
        session.login("a@b.se", "x")


def test_redirect_to_other_host_is_blocked():
    rec = Recorder([httpx.Response(301, headers={"location": "https://evil.example/api/v1/search/mixed/"})])
    session, _ = make(rec)
    with pytest.raises(ForbiddenEndpoint):
        session.get_json("/products/1/")
    assert len(rec.requests) == 1


def test_allowed_redirect_hop_is_rate_limited():
    rec = Recorder([httpx.Response(302, headers={"location": f"{BASE_URL}/products/2/"}),
                    httpx.Response(200, json={"ok": True})])
    session, sleeps = make(rec)
    assert session.get_json("/products/1/") == {"ok": True}
    assert [str(r.url) for r in rec.requests] == [f"{BASE_URL}/products/1/", f"{BASE_URL}/products/2/"]
    assert sleeps == [1.0]


def test_post_5xx_is_not_retried():
    # Cart quantities are deltas: a 5xx may already have been applied, so retrying could double it.
    rec = Recorder([httpx.Response(502), httpx.Response(200, json={"groups": []})])
    session, _ = make(rec)
    with pytest.raises(MathemRequestError):
        session.post_json("/cart/items/", {"items": [{"productId": 1, "quantity": 1}]}, {"group-by": "recipes"})
    assert len(rec.requests) == 1


def test_post_429_is_retried():
    rec = Recorder([httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(200, json={"groups": []})])
    session, sleeps = make(rec)
    assert session.post_json("/cart/items/", {"items": []}, {"group-by": "recipes"}) == {"groups": []}
    assert 3 in sleeps and len(rec.requests) == 2


def test_login_network_error_does_not_leak(caplog):
    caplog.set_level(logging.DEBUG)
    page = httpx.Response(200, text="<html>", headers={"set-cookie": "csrftoken=tok; Path=/"})

    def handler(request):
        if request.method == "GET":
            return page
        raise httpx.ConnectError("anslutningen bröts", request=request)

    session, _ = make(handler)
    with pytest.raises(MathemError) as err:
        session.login("hemlig@example.org", "pw-123-hemligt")
    assert not isinstance(err.value, httpx.HTTPError)
    text = str(err.value) + repr(err.value) + caplog.text
    assert "hemlig@example.org" not in text and "pw-123-hemligt" not in text
    assert err.value.__cause__ is None and err.value.__context__ is None


WALL = datetime(2026, 10, 21, 7, 27, 30, tzinfo=timezone.utc)


def test_retry_after_http_date_is_honoured():
    # S2: "Wed, 21 Oct 2026 07:28:00 GMT" is 30 s after WALL, not the 1 s fallback.
    rec = Recorder([httpx.Response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}),
                    httpx.Response(200, json={"ok": True})])
    session, sleeps = make(rec, now=lambda: WALL)
    assert session.get_json("/products/1/") == {"ok": True}
    assert sleeps[0] == pytest.approx(30.0)


@pytest.mark.parametrize("value", ["300", "Wed, 21 Oct 2026 07:37:30 GMT"])
def test_retry_after_beyond_cap_stops_instead_of_retrying_early(value):
    rec = Recorder([httpx.Response(429, headers={"retry-after": value})] + [httpx.Response(200, json={})] * 3)
    session, sleeps = make(rec, now=lambda: WALL)
    with pytest.raises(MathemRequestError, match="försök igen senare") as exc:
        session.get_json("/products/1/")
    assert exc.value.status == 429
    assert len(rec.requests) == 1 and sleeps == []
    # The server asked to be left alone: later calls must not send anything either.
    with pytest.raises(MathemRequestError, match="försök igen senare"):
        session.get_json("/products/2/")
    assert len(rec.requests) == 1
