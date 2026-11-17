"""Product ids for every store. No dependencies, so plan_model and the clients can share it."""

from __future__ import annotations

ProductId = int | str


def norm_id(value: object) -> ProductId:
    """A product id as stored: Mathem ids are ints, Willys codes strings (``101106287_ST``).

    Digits-only strings become ints so a Mathem id read back from YAML or JSON compares equal.
    """
    if isinstance(value, bool):
        raise ValueError(f"ogiltigt produkt-id: {value!r}")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    if not text or not text.replace("_", "").isalnum():
        raise ValueError(f"ogiltigt produkt-id: {value!r}")
    return text
