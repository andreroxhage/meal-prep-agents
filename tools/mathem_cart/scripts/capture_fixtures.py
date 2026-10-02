"""Capture raw search responses as test fixtures. Search only, via MathemSession (1 req/s).

Usage: MATHEM_BOT_CONTACT=<url or email> uv run --project tools/mathem_cart \
       python tools/mathem_cart/scripts/capture_fixtures.py [--force]

Existing fixtures are kept: without --force the script makes no request when every
fixture file is already on disk, so an accidental re-run never touches the network.
"""

import json
import os
import sys
from pathlib import Path

from mathem_cart.mathem.session import MathemSession

TERMS = {"search-vispgradde.json": "vispgrädde", "search-kycklingfile.json": "kycklingfilé"}
OUT = Path(__file__).parents[1] / "tests" / "fixtures"


def _strip_images(items: list) -> None:
    """Drop image URLs (large, irrelevant to tests), also inside nested product lists."""
    for item in items:
        if not isinstance(item, dict):
            continue
        (item.get("attributes") or {}).pop("images", None)
        _strip_images(item.get("items") or [])


def main() -> None:
    force = "--force" in sys.argv[1:]
    todo = {f: t for f, t in TERMS.items() if force or not (OUT / f).exists()}
    if not todo:
        print("Alla fixturer finns redan — inget anrop gjort (använd --force för att hämta om).")
        return
    with MathemSession(os.environ["MATHEM_BOT_CONTACT"]) as session:
        for filename, term in todo.items():
            data = session.get_json("/search/mixed/", {"q": term, "type": "product", "page": 1})
            _strip_images(data.get("items", []))
            (OUT / filename).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(filename, len(data.get("items", [])), "träffar")


if __name__ == "__main__":
    main()
