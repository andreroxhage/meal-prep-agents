"""HTTP session for willys.se: allowlist, User-Agent, rate limit, backoff, login, CSRF.

Reuses MathemSession's request loop (rate limit, Retry-After, no POST retry on 5xx);
only the allowlist, headers and login differ. Routes and the login encryption come from
cartway (MIT, Copyright (c) 2026 Oscar Throedsson), see LICENSE-cartway.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from datetime import date

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..mathem.errors import ForbiddenEndpoint, MathemAuthError, MathemError, MathemProtocolError, MathemRequestError
from ..mathem.session import MathemSession

HOST = "www.willys.se"
ORIGIN = f"https://{HOST}"
LOGIN_PAGE_PATH = "/anvandare/inloggning"
LOGIN_PATH = "/login"
CSRF_PATH = "/axfood/rest/csrf-token"
BANNED_IN_PATH = ("checkout", "slot", "order", "payment", "kassa", "betal")
ALLOWED_QUERY_KEYS = frozenset({"q", "size", "page"})
ALLOWED = (
    ("GET", re.compile(r"^/search$")),
    ("GET", re.compile(r"^/axfood/rest/p/\d+_[A-Z]+$")),
    ("GET", re.compile(rf"^{LOGIN_PAGE_PATH}$")),
    ("POST", re.compile(rf"^{LOGIN_PATH}$")),
    ("GET", re.compile(rf"^{CSRF_PATH}$")),
    ("GET", re.compile(r"^/axfood/rest/cart$")),
    ("POST", re.compile(r"^/axfood/rest/cart/addProducts$")),
)
_AUTH_HINT = "kontrollera WILLYS_USERNAME och WILLYS_PASSWORD i .env"


def check_allowed(method: str, url: str) -> None:
    """Raise ForbiddenEndpoint unless ``method url`` is on the Willys allowlist."""
    u = httpx.URL(url)
    if u.scheme != "https" or u.host != HOST or u.port not in (None, 443):
        raise ForbiddenEndpoint(f"otillåten värd: {u.scheme}://{u.host}")
    path = u.path
    if any(word in path.lower() for word in BANNED_IN_PATH):
        raise ForbiddenEndpoint(f"otillåten sökväg: {path}")
    verb = method.upper()
    if not any(m == verb and rx.fullmatch(path) for m, rx in ALLOWED):
        raise ForbiddenEndpoint(f"otillåtet anrop: {verb} {path}")
    unknown = set(u.params.keys()) - ALLOWED_QUERY_KEYS
    if unknown:
        raise ForbiddenEndpoint(f"otillåtna parametrar: {sorted(unknown)}")


def normalize_username(username: str, today: date | None = None) -> str:
    """A 10-digit personnummer gets its century, as the login form does; others pass through."""
    if len(username) != 10 or not username.isdigit():
        return username
    yy = int(username[:2])
    century = "19" if yy > (today or date.today()).year % 100 else "20"
    return century + username


def encrypt_field(plain: str) -> tuple[str, str]:
    """The login form's field encryption: (packed value, key).

    A 16-digit key, PBKDF2-SHA1 1000 rounds into AES-128-CBC, packed as
    base64("ivHex::saltHex::base64(ciphertext)"). The key travels with the value, so this is
    obfuscation the server requires, not secrecy.
    """
    key = "".join(str(secrets.randbelow(10)) for _ in range(16))
    iv, salt = secrets.token_bytes(16), secrets.token_bytes(16)
    aes_key = hashlib.pbkdf2_hmac("sha1", key.encode(), salt, 1000, 16)
    padder = padding.PKCS7(128).padder()
    data = padder.update(plain.encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).encryptor()
    cipher = enc.update(data) + enc.finalize()
    packed = f"{iv.hex()}::{salt.hex()}::{base64.b64encode(cipher).decode()}"
    return base64.b64encode(packed.encode()).decode(), key


class WillysSession(MathemSession):
    check = staticmethod(check_allowed)
    base_url = ORIGIN
    origin = ORIGIN
    label = "Willys"
    credential_paths = (LOGIN_PATH,)

    def __init__(self, contact: str, **kwargs):
        super().__init__(contact, **kwargs)
        self._csrf: str | None = None

    def __repr__(self) -> str:
        return f"WillysSession(user_agent={self.user_agent!r})"

    def _headers(self, method: str, camel: bool, accept: str) -> dict[str, str]:
        h = {"accept": accept, "user-agent": self.user_agent, "accept-language": "sv-SE",
             "origin": ORIGIN, "referer": f"{ORIGIN}/"}
        if method == "POST":
            h["content-type"] = "application/json"
        if self._csrf:
            h["x-csrf-token"] = self._csrf
        return h

    def refresh_csrf(self) -> None:
        """Fetch the CSRF token the cart routes need; it is bound to the session cookie."""
        resp = self._send("GET", ORIGIN + CSRF_PATH)
        try:
            data = resp.json()
        except ValueError:
            data = resp.text.strip()
        token = data if isinstance(data, str) else data.get("token") if isinstance(data, dict) else None
        if not token or not isinstance(token, str):
            raise MathemProtocolError(f"GET {CSRF_PATH} gav ingen CSRF-token")
        self._csrf = token

    def login(self, username: str, password: str) -> None:
        """GET the login page for its cookies, then POST the encrypted fields as JSON.

        Same rule as the Mathem login: no credential (plain or encrypted) reaches a log line,
        an exception message or an exception's ``__cause__``/``__context__``.
        """
        self._send("GET", ORIGIN + LOGIN_PAGE_PATH, accept="text/html,application/xhtml+xml")
        outcome = "ok"
        try:
            user, user_key = encrypt_field(normalize_username(username.strip()))
            pw, pw_key = encrypt_field(password)
            resp = self._send("POST", ORIGIN + LOGIN_PATH, json={
                "j_username": user, "j_username_key": user_key, "j_password": pw, "j_password_key": pw_key,
                "j_remember_me": False})
            body = resp.json()
            if not isinstance(body, dict) or body.get("login_successful") not in ("true", True):
                outcome = "rejected"
        except (MathemAuthError, MathemRequestError, MathemProtocolError, ValueError):
            outcome = "rejected"
        except httpx.HTTPError:
            outcome = "network"   # httpx errors carry the request, and so the body
        if outcome == "network":
            raise MathemError(f"Nätverksfel vid inloggning (POST {LOGIN_PATH}) — försök igen senare")
        if outcome == "rejected" or not self._client.cookies.get("JSESSIONID"):
            raise MathemAuthError(f"Inloggningen hos Willys misslyckades — {_AUTH_HINT}")
        self._csrf = None   # a new session needs a new token
