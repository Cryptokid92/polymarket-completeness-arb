"""Aggregate several paper-run sessions into one edge-discovery summary.

Pure and read-only. It never places orders, never touches the network, and
never changes hunt or risk caps. It pools per-session ``stats.json`` counts,
joins recorded ``books.jsonl`` categories, and reruns the near-miss and
maker-fill studies across all sessions so a human can judge whether any
realizable edge exists.

Sessions are kept separate by prefixing each condition_id with the session
index, so the same market seen in two sessions is never mixed within a single
maker-fill window.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from arb.backtest import estimate_maker_fill
from arb.nearmiss_report import (
    analyze_nearmiss,
    condition_categories,
    parse_nearmiss_rows,
)
from arb.recorder import load_jsonl

__all__ = ["aggregate_sessions"]

_DEFAULT_MIN_EDGE = Decimal("0.01")


def _read_stats(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return load_jsonl(path)


def _sum_int_map(target: dict[str, int], source: object) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        target[str(key)] = target.get(str(key), 0) + int(value)


def _prefix_cid(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    out = dict(row)
    out["condition_id"] = f"{prefix}:{row.get('condition_id', '')}"
    return out


def aggregate_sessions(
    session_dirs: Sequence[Path],
    *,
    min_edge: Decimal = _DEFAULT_MIN_EDGE,
    top_n: int = 10,
) -> dict[str, Any]:
    """Pool per-session stats and rerun near-miss / maker-fill studies."""
    sessions: list[dict[str, Any]] = []
    total_listed = 0
    total_universe = 0
    total_gaps = 0
    total_intents = 0
    total_considers = 0
    pooled_hist: dict[str, int] = {}
    pooled_rejects: dict[str, int] = {}
    best_edge: Decimal | None = None

    all_nm_rows: list[dict[str, Any]] = []
    all_categories: dict[str, str] = {}
    all_tape_events: list[dict[str, Any]] = []

    for idx, raw_dir in enumerate(session_dirs):
        session_dir = Path(raw_dir)
        prefix = str(idx)
        stats = _read_stats(session_dir / "stats.json")
        listed = int(stats.get("markets_listed", 0) or 0)
        universe = int(stats.get("universe", 0) or 0)
        gaps = int(stats.get("gaps", 0) or 0)
        intents = int(stats.get("intents", 0) or 0)
        considers = int(stats.get("nearmiss_considers", 0) or 0)
        total_listed += listed
        total_universe += universe
        total_gaps += gaps
        total_intents += intents
        total_considers += considers
        _sum_int_map(pooled_hist, stats.get("edge_histogram"))
        _sum_int_map(pooled_rejects, stats.get("reject_reasons"))
        raw_best = stats.get("best_edge")
        if raw_best not in (None, ""):
            edge = Decimal(str(raw_best))
            if best_edge is None or edge > best_edge:
                best_edge = edge

        nm_rows = _load_rows(session_dir / "nearmiss.jsonl")
        tape_events = _load_rows(session_dir / "books.jsonl")
        for row in nm_rows:
            all_nm_rows.append(_prefix_cid(row, prefix))
        for event in tape_events:
            all_tape_events.append(_prefix_cid(event, prefix))
        for cid, category in condition_categories(tape_events).items():
            all_categories[f"{prefix}:{cid}"] = category

        sessions.append(
            {
                "dir": str(session_dir),
                "markets_listed": listed,
                "universe": universe,
                "gaps": gaps,
                "intents": intents,
                "nearmiss_considers": considers,
                "best_edge": str(raw_best) if raw_best not in (None, "") else None,
            }
        )

    nearmiss_summary = analyze_nearmiss(
        parse_nearmiss_rows(all_nm_rows),
        categories=all_categories,
        min_edge=min_edge,
        top_n=top_n,
    )
    maker_fill = estimate_maker_fill(all_tape_events)

    return {
        "sessions": len(sessions),
        "session_details": sessions,
        "totals": {
            "markets_listed": total_listed,
            "universe": total_universe,
            "gaps": total_gaps,
            "intents": total_intents,
            "nearmiss_considers": total_considers,
        },
        "pooled_edge_histogram": dict(pooled_hist),
        "pooled_reject_reasons": dict(pooled_rejects),
        "best_edge": str(best_edge) if best_edge is not None else None,
        "nearmiss": nearmiss_summary,
        "maker_fill": maker_fill,
    }
