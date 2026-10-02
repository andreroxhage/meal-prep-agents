"""Render `06-mathem-varukorg.md` from a Plan (and optionally an ApplyResult).

Depends only on `plan_model`. All text is Swedish, numbers use decimal comma.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .plan_model import ApplyResult, Need, Plan, PlanLine, Undecided

SOURCES = ("pin", "fast", "haiku", "sonnet")
REASON_WIDTH = 80


def fmt_num(x: float) -> str:
    """1.2 -> "1,2", 300.0 -> "300"."""
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",") if x % 1 else str(int(x))


def fmt_kr(x: float | None) -> str:
    """27.2 -> "27,20 kr", None -> "—"."""
    return "—" if x is None else f"{x:.2f} kr".replace(".", ",")


def fmt_need(need: Need) -> str:
    """1200 g -> "1,2 kg", 1500 ml -> "1,5 l", 300 ml -> "300 ml", None -> "okänt"."""
    if need.amount is None or need.unit is None:
        return "okänt"
    amount, unit = need.amount, need.unit
    if unit == "g" and amount >= 1000:
        amount, unit = amount / 1000, "kg"
    elif unit == "ml" and amount >= 1000:
        amount, unit = amount / 1000, "l"
    return f"{fmt_num(amount)} {unit}"


def fmt_unit_price(s: str | None) -> str:
    """"54.40 kr/l" -> "54,40 kr/l", None -> "—"."""
    return "—" if not s else s.replace(".", ",")


def fmt_flags(line: PlanLine) -> str:
    """"överköp" -> "överköp 67 %" (from line.overshoot); others verbatim; empty -> "—"."""
    parts = []
    for flag in line.flags:
        if flag == "överköp":
            parts.append(f"överköp {fmt_num(round(line.overshoot * 100))} %")
        else:
            parts.append(flag)
    return ", ".join(parts) if parts else "—"


def source_counts(lines: Sequence[PlanLine]) -> dict[str, int]:
    """Lines per decision source: every SOURCES key (even 0), then any other decision."""
    counts = {source: 0 for source in SOURCES}
    for line in lines:
        counts[line.decision] = counts.get(line.decision, 0) + 1
    return counts


def reason_counts(undecided: Sequence[Undecided]) -> dict[str, int]:
    """Undecided items per reason, in first-seen order."""
    counts: dict[str, int] = {}
    for u in undecided:
        counts[u.reason] = counts.get(u.reason, 0) + 1
    return counts


def fmt_counts(counts: Mapping[str, int]) -> str:
    """{"pin": 3, "haiku": 40} -> "pin 3 · haiku 40"."""
    return " · ".join(f"{key} {value}" for key, value in counts.items())


def _short(text: str | None, width: int = REASON_WIDTH) -> str:
    """Collapse whitespace and cut to `width` characters with a trailing "…"."""
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 1] + "…"


def _cell(s: str) -> str:
    """Keep a table cell on one line and stop a `|` from splitting it."""
    return s.replace("\n", " ").replace("|", "\\|")


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def render_report(plan: Plan, result: ApplyResult | None = None) -> str:
    out: list[str] = [
        "# Steg 6 — Mathem-varukorg (experimentell)",
        "",
        f"> Vecka {plan.week} · plan skapad {plan.created:%Y-%m-%d %H:%M}",
        "> **Ingen beställning görs.** Kontrollera varukorgen och beställ själv i Mathem-appen.",
        "",
        f"**{len(plan.lines)} rader · totalt {fmt_kr(plan.total_kr)} · "
        f"{len(plan.undecided)} behöver beslut · {len(plan.skipped)} hoppade över**",
        "",
        f"Beslut: {fmt_counts(source_counts(plan.lines))}",
    ]
    if plan.undecided:
        out.append(f"Oavgjorda: {fmt_counts(reason_counts(plan.undecided))}")
    out += [
        "",
        "## I varukorgen",
        "",
        "| Vara | Behov | Produkt | Förp. | Antal | Kostnad | Jämförpris | Kampanj | Beslut | Motivering | Flaggor |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for line in plan.lines:
        out.append(_row([
            line.item,
            fmt_need(line.need),
            f"{line.name} ({line.product_id})",
            line.package,
            str(line.count),
            fmt_kr(line.cost_kr),
            fmt_unit_price(line.unit_price),
            line.deal or "—",
            line.decision,
            _short(line.reason),
            fmt_flags(line),
        ]))

    if plan.undecided:
        out += ["", "## Behöver beslut"]
        for u in plan.undecided:
            out += ["", f"### {u.item} — {fmt_need(u.need)} ({u.reason})"]
            if u.note:
                out.append(f"Modellen: {_short(u.note, 160)}")
            for i, c in enumerate(u.candidates, 1):
                out.append(
                    f"{i}. {c.name} (id {c.product_id}) · {c.package} · {fmt_kr(c.price)} · "
                    f"{fmt_unit_price(c.unit_price)} · {c.deal or '—'}"
                )
            out.append(f'Svara med `mathem-cart pin "{u.item}" <id>` eller kör `/mathem-cart`.')

    for heading, items in (
        ("Hoppade över", plan.skipped),
        ("Ej med", plan.excluded),
        ("Varningar", plan.warnings),
    ):
        if items:
            out += ["", f"## {heading}"] + [f"- {x}" for x in items]

    if result is not None:
        out += ["", f"## Resultat i varukorgen (apply {result.applied_at:%Y-%m-%d %H:%M})"]
        if result.ok:
            out.append(f"✅ Alla {len(result.expected)} rader finns i varukorgen med rätt antal.")
        else:
            if result.differences:
                out.append(f"⚠️ {len(result.differences)} avvikelser:")
                out += [f"- {d}" for d in result.differences]
            else:
                out.append("⚠️ Apply blev inte klar.")
            if result.error:
                out.append(f"**Fel:** {result.error}")
        out.append("Töm varukorgen i Mathem-appen och kör `apply` igen om något blev fel.")

    return "\n".join(out) + "\n"
