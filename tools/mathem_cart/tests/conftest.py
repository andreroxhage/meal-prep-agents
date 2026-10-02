import httpx
import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Unit tests never touch the network; use httpx.MockTransport instead."""

    def refuse(self, request):
        raise RuntimeError(f"nätverk avstängt i test: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
