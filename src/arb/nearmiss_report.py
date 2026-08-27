"""Offline analysis of recorded near-miss telemetry. Pure and read-only.

This never places orders, never touches the network, and never changes hunt
or risk caps. It only summarizes how far walked YES+NO ask edges got from
completeness, bucketed by market category and by hour of day, so a human can
decide whether any realizable edge exists.

Money stays ``Decimal``. Category comes from the recorded tape's ``meta``
(see :func:`arb.recorder.book_to_event`); rows without a category map to
``"unknown"``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from arb.books import _reject_float
from arb.nearmiss import edge_bucket

__all__ = [
    "NearMissRow",
    "parse_nearmiss_rows",
    "condition_categories",
    "analyze_nearmiss",
]

_UNKNOWN = "unknown"
_DEFAULT_MIN_EDGE = Decimal("0.01")


@dataclass(frozen=True)
class NearMissRow:
    condition_id: str
    raw_edge: Decimal | None
    fillable_shares: Decimal | None
    book_age_ms: int | None
    ts_ms: int | None
    in_watch: bool | None
    thin: bool


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return _reject_float(value, "nearmiss_row")


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def parse_nearmiss_rows(rows: Iterable[dict[str, Any]]) -> list[NearMissRow]:
    """Parse raw ``nearmiss.jsonl`` dicts. Decimal-only for edge/size."""
    parsed: list[NearMissRow] = []
    for row in rows:
        parsed.append(
            NearMissRow(
                condition_id=str(row.get("condition_id") or ""),
                raw_edge=_optional_decimal(row.get("raw_edge")),
                fillable_shares=_optional_decimal(row.get("fillable_shares")),
                book_age_ms=_optional_int(row.get("book_age_ms")),
                ts_ms=_optional_int(row.get("ts_ms")),
                in_watch=row.get("in_watch"),
                thin=bool(row.get("thin", False)),
            )
        )
    return parsed


def condition_categories(tape_events: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Map condition_id -> category from recorded tape ``meta``.

    Later rows win, so a market keeps whatever category the tape last carried.
    Rows without ``meta.category`` are skipped (they stay ``unknown``).
    """
    mapping: dict[str, str] = {}
    for event in tape_events:
        cid = str(event.get("condition_id") or "")
        if not cid:
            continue
        meta = event.get("meta")
        if not isinstance(meta, dict):
            continue
        category = meta.get("category")
        if category:
            mapping[cid] = str(category)
    return mapping


def _hour_of_day(ts_ms: int | None) -> int | None:
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour


@dataclass
class _Bucket:
    considers: int = 0
    thin: int = 0
    best_edge: Decimal | None = None
    histogram: dict[str, int] = field(default_factory=dict)

    def observe(self, row: NearMissRow) -> None:
        self.considers += 1
        if row.thin:
            self.thin += 1
        self.histogram[edge_bucket(row.raw_edge)] = (
            self.histogram.get(edge_bucket(row.raw_edge), 0) + 1
        )
        if row.raw_edge is not None and (
            self.best_edge is None or row.raw_edge > self.best_edge
        ):
            self.best_edge = row.raw_edge

    def summary(self) -> dict[str, Any]:
        return {
            "considers": self.considers,
            "thin": self.thin,
            "best_edge": str(self.best_edge) if self.best_edge is not None else None,
            "histogram": dict(self.histogram),
        }


def analyze_nearmiss(
    rows: Sequence[NearMissRow],
    *,
    categories: dict[str, str] | None = None,
    min_edge: Decimal = _DEFAULT_MIN_EDGE,
    top_n: int = 10,
) -> dict[str, Any]:
    """Summarize near-miss rows overall, by category, and by hour of day.

    ``min_edge`` is only used to report how far the closest walked edges are
    from firing a gap. It does not change any live threshold.
    """
    min_edge = _reject_float(min_edge, "min_edge")
    categories = categories or {}

    overall = _Bucket()
    by_category: dict[str, _Bucket] = {}
    by_hour: dict[int, _Bucket] = {}

    for row in rows:
        overall.observe(row)
        cat = categories.get(row.condition_id, _UNKNOWN)
        by_category.setdefault(cat, _Bucket()).observe(row)
        hour = _hour_of_day(row.ts_ms)
        if hour is not None:
            by_hour.setdefault(hour, _Bucket()).observe(row)

    walked = [row for row in rows if row.raw_edge is not None]
    walked.sort(key=lambda r: r.raw_edge, reverse=True)  # type: ignore[arg-type,return-value]
    closest: list[dict[str, Any]] = []
    for row in walked[: max(0, int(top_n))]:
        assert row.raw_edge is not None
        closest.append(
            {
                "condition_id": row.condition_id,
                "category": categories.get(row.condition_id, _UNKNOWN),
                "raw_edge": str(row.raw_edge),
                "distance_to_min_edge": str(min_edge - row.raw_edge),
                "fillable_shares": (
                    str(row.fillable_shares)
                    if row.fillable_shares is not None
                    else None
                ),
                "in_watch": row.in_watch,
                "ts_ms": row.ts_ms,
            }
        )

    best_edge = overall.best_edge
    return {
        "min_edge": str(min_edge),
        "considers": overall.considers,
        "thin": overall.thin,
        "walked": len(walked),
        "best_edge": str(best_edge) if best_edge is not None else None,
        "best_distance_to_min_edge": (
            str(min_edge - best_edge) if best_edge is not None else None
        ),
        "would_fire": bool(best_edge is not None and best_edge >= min_edge),
        "histogram": dict(overall.histogram),
        "by_category": {cat: bucket.summary() for cat, bucket in by_category.items()},
        "by_hour": {str(hour): bucket.summary() for hour, bucket in by_hour.items()},
        "closest": closest,
    }
