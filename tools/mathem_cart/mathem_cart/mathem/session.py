"""HTTP session for the Mathem API: allowlist, User-Agent, rate limit, backoff, login.

Adapted from ha-mathem (MIT, Copyright (c) 2026 Marcus Forsberg), see
LICENSE-ha-mathem. Synchronous on httpx. Every outgoing request -- including
redirect hops -- passes check_allowed() before it is sent, and waits its turn
under the rate limit.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Mapping

import httpx

from .errors import ForbiddenEndpoint, MathemAuthError, MathemError, MathemProtocolError, MathemRequestError

_LOG = logging.getLogger(__name__)

HOST = "www.mathem.se"
ORIGIN = f"https://{HOST}"
BASE_URL = f"{ORIGIN}/api/v1"
LOGIN_PAGE_URL = f"{ORIGIN}/se/user/login/"
BANNED_IN_PATH = ("checkout", "slot", "order")
ALLOWED_QUERY_KEYS = frozenset({"q", "type", "page", "group-by"})
ALLOWED = (
    ("GET", re.compile(r"^/api/v1/search/mixed/$")),
    ("GET", re.compile(r"^/api/v1/products/\d+/$")),
    ("GET", re.compile(r"^/se/user/login/$")),
    ("POST", re.compile(r"^/api/v1/user/login/$")),
    ("GET", re.compile(r"^/api/v1/cart/$")),
    ("POST", re.compile(r"^/api/v1/cart/items/$")),
)
LOGIN_PATH = "/api/v1/user/login/"
CREDENTIAL_PATHS = (LOGIN_PATH,)
_AUTH_HINT = "kontrollera MATHEM_EMAIL och MATHEM_PASSWORD i .env"
MAX_RETRY_AFTER = 60.0   # longer waits abort instead of retrying early (spec §8.6)


def check_allowed(method: str, url: str) -> None:
    """Raise ForbiddenEndpoint unless ``method url`` is on the allowlist.

    The banned words apply to the path only (V3): query keys are allowlisted,
    query values are free so a search for "Slotts senap" works.
    """
    u = httpx.URL(url)
    if u.scheme != "https" or u.host != HOST or u.port not in (None, 443):
        raise ForbiddenEndpoint(f"otillåten värd: {u.scheme}://{u.host}")
    path = u.path
    if any(word in path.lower() for word in BANNED_IN_PATH):
        raise ForbiddenEndpoint(f"otillåten sökväg: {path}")
    verb = method.upper()
    if not any(m == verb and rx.match(path) for m, rx in ALLOWED):
        raise ForbiddenEndpoint(f"otillåtet anrop: {verb} {path}")
    unknown = set(u.params.keys()) - ALLOWED_QUERY_KEYS
    if unknown:
        raise ForbiddenEndpoint(f"otillåtna parametrar: {sorted(unknown)}")


class MathemSession:
    def __init__(self, contact: str, *, client: httpx.Client | None = None, min_interval: float = 1.0,
                 max_retries: int = 4, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        contact = (contact or "").strip()
        if not contact:
            raise ValueError("MATHEM_BOT_CONTACT saknas (kontaktuppgift i User-Agent)")
        self.user_agent = f"meal-prep-bot/0.1 (+{contact})"
        self._client = client or httpx.Client(timeout=20.0)
        self._client.follow_redirects = True
        # Replaces any hooks on an injected client: the guard must be the only gate.
        self._client.event_hooks = {"request": [self._guard], "response": []}
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._now = now
        self._last: float | None = None
        self._blocked_until: float | None = None   # clock() time a long Retry-After ends

    def __repr__(self) -> str:
        return f"MathemSession(user_agent={self.user_agent!r})"

    def __enter__(self) -> "MathemSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _guard(self, request: httpx.Request) -> None:
        # httpx runs request hooks for the first request and for every redirect hop.
        check_allowed(request.method, str(request.url))
        self._wait_turn()

    def _wait_turn(self) -> None:
        if self._last is not None:
            wait = self._last + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def _headers(self, method: str, camel: bool, accept: str) -> dict[str, str]:
        h = {"accept": accept, "user-agent": self.user_agent, "x-language": "sv", "x-country": "se",
             "origin": ORIGIN, "referer": f"{ORIGIN}/se/"}
        if camel:
            h.update({"x-requested-case": "camel", "x-client-app": "tienda-web",
                      "content-type": "application/json"})
        if method == "POST":
            token = self._client.cookies.get("csrftoken")
            if token:
                h["x-csrftoken"] = token
        return h

    def _retry_after(self, resp: httpx.Response) -> float | None:
        """Seconds the server asked us to wait (delta-seconds or HTTP-date), or None."""
        value = resp.headers.get("retry-after", "").strip()
        if not value:
            return None
        if value.isdigit():
            return float(value)
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - self._now()).total_seconds())

    def _rate_limited(self, method: str, path: str, seconds: float) -> MathemRequestError:
        return MathemRequestError(429, method, path,
                                  hint=f"Mathem ber oss vänta {seconds:.0f} s — försök igen senare")

    @staticmethod
    def _retryable(method: str, code: int) -> bool:
        # 429 means "not processed" and is always safe to retry. A 5xx on a POST may
        # already have been applied (cart quantities are deltas), so only GETs retry it.
        return code == 429 or (code >= 500 and method == "GET")

    def _send(self, method: str, url: str, *, params: Mapping[str, Any] | None = None, json: Any = None,
              camel: bool = False, accept: str = "application/json") -> httpx.Response:
        method = method.upper()
        full = httpx.URL(url, params=params) if params else httpx.URL(url)
        check_allowed(method, str(full))
        path = full.path
        if self._blocked_until is not None:
            left = self._blocked_until - self._clock()
            if left > 0:
                raise self._rate_limited(method, path, left)
            self._blocked_until = None
        for attempt in range(self._max_retries + 1):
            _LOG.debug("%s %s", method, path)   # never the body, never the query
            resp = self._client.request(method, full, json=json, headers=self._headers(method, camel, accept))
            code = resp.status_code
            if code == 429 or code >= 500:
                wait = self._retry_after(resp)
                if wait is not None and wait > MAX_RETRY_AFTER:
                    # Retrying before the server allows it is not honouring Retry-After.
                    self._blocked_until = self._clock() + wait
                    raise self._rate_limited(method, path, wait)
                if attempt == self._max_retries or not self._retryable(method, code):
                    raise MathemRequestError(code, method, path)
                self._sleep(wait if wait is not None else float(2 ** attempt))
                continue
            if code in (401, 403):
                raise MathemAuthError(f"{method} {path} -> HTTP {code}")
            if code >= 400:
                body = None if path in CREDENTIAL_PATHS else resp.text[:300]
                raise MathemRequestError(code, method, path, body)
            return resp
        raise AssertionError("unreachable")

    @staticmethod
    def _json(resp: httpx.Response, method: str) -> Any:
        ok = True
        try:
            data = resp.json()
        except ValueError:
            ok = False
        if not ok:   # raised outside the except so the body isn't kept in __context__
            raise MathemProtocolError(f"{method} {resp.request.url.path} svarade inte med JSON")
        return data

    def get_json(self, path: str, params: Mapping[str, Any] | None = None, *, camel: bool = False) -> Any:
        return self._json(self._send("GET", BASE_URL + path, params=params, camel=camel), "GET")

    def post_json(self, path: str, payload: Any, params: Mapping[str, Any] | None = None, *,
                  camel: bool = True) -> Any:
        return self._json(self._send("POST", BASE_URL + path, params=params, json=payload, camel=camel), "POST")

    def login(self, email: str, password: str) -> None:
        """GET the login page to seed ``csrftoken``, then POST the credentials as JSON.

        Credentials never reach a log line, an exception message or an exception's
        ``__cause__``/``__context__``: every failure is recorded as a flag and the
        error is raised outside the ``except`` block.
        """
        self._send("GET", LOGIN_PAGE_URL, accept="text/html,application/xhtml+xml")
        if not self._client.cookies.get("csrftoken"):
            raise MathemProtocolError("inloggningssidan satte ingen csrftoken-cookie")
        outcome = "ok"
        try:
            self._send("POST", BASE_URL + "/user/login/", json={"username": email, "password": password},
                       camel=True)
        except (MathemAuthError, MathemRequestError, MathemProtocolError):
            outcome = "rejected"
        except httpx.HTTPError:
            # httpx errors carry the request (and so the credential body) as an attribute.
            outcome = "network"
        if outcome == "network":
            raise MathemError(f"Nätverksfel vid inloggning (POST {LOGIN_PATH}) — försök igen senare")
        if outcome == "rejected" or not self._client.cookies.get("sessionid"):
            raise MathemAuthError(f"Inloggningen misslyckades — {_AUTH_HINT}")
