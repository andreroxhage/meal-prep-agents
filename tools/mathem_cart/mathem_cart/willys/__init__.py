"""Willys client: search, product, login and cart. Never the till, delivery times or payment.

The HTTP contract (routes, login encryption, cart payload) is taken from cartway
(https://github.com/oscarthroedsson/cartway, MIT, Copyright (c) 2026 Oscar Throedsson),
rewritten in Python on the same session, allowlist and rate limit as the Mathem client.
See LICENSE-cartway and docs/design/varukorg-butiker.md.
"""
