"""Load and save mathem-pins.local.yaml (spec §6). Round-trips comments."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .shopping_list import normalize_key


@dataclass
class Pin:
    fixed: int | None = None
    approved: list[int] = field(default_factory=list)
    search: str | None = None


class Pins:
    def __init__(self, path: Path, data: CommentedMap):
        self.path = path
        self._data = data
        self._yaml = YAML()
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml.width = 4096

    def keys(self) -> list[str]:
        return [str(k) for k in self._data]

    def get(self, name: str) -> Pin | None:
        raw = self._data.get(normalize_key(name))
        if not raw:
            return None
        return Pin(fixed=int(raw["fast"]) if raw.get("fast") is not None else None,
                   approved=[int(x) for x in raw.get("godkända") or []],
                   search=str(raw["sök"]).strip() or None if raw.get("sök") else None)

    def _entry(self, name: str) -> CommentedMap:
        key = normalize_key(name)
        if not key:
            raise ValueError("tomt ingrediensnamn")
        if not isinstance(self._data.get(key), CommentedMap):
            self._data[key] = CommentedMap()
        return self._data[key]

    def approve(self, name: str, product_id: int) -> None:
        entry = self._entry(name)
        approved = entry.get("godkända")
        if approved is None:
            approved = CommentedSeq()
            approved.fa.set_flow_style()
            entry["godkända"] = approved
        if int(product_id) not in [int(x) for x in approved]:
            approved.append(int(product_id))

    def set_fixed(self, name: str, product_id: int) -> None:
        self._entry(name)["fast"] = int(product_id)

    def set_search(self, name: str, term: str) -> None:
        self._entry(name)["sök"] = term.strip()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".pins-", suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                self._yaml.dump(self._data, fh)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def load_pins(path: Path) -> Pins:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    data = YAML().load(text) if text.strip() else None
    if data is not None and not isinstance(data, CommentedMap):
        raise ValueError(f"{path}: pin-filen måste vara en mappning")
    if data is None:
        # comment-only (or missing) file: keep the leading comment block
        data = CommentedMap()
        header = [l[1:].removeprefix(" ") for l in text.splitlines() if l.startswith("#")]
        if header:
            data.yaml_set_start_comment("\n".join(header))
    data.fa.set_block_style()
    return Pins(path, data)
