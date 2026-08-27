#!/usr/bin/env python3
"""Offline near-miss analysis. Read-only. Never places orders.

Reads a paper run's ``nearmiss.jsonl`` (and an optional recorded ``books.jsonl``
tape for market categories) and reports how far walked YES+NO ask edges got
from completeness, bucketed by category and by hour of day.

Usage:
  uv run python scripts/analyze_nearmiss.py --nearmiss data/paper/nearmiss.jsonl
  uv run python scripts/analyze_nearmiss.py \
      --nearmiss data/paper/nearmiss.jsonl --tape data/paper/books.jsonl --top 10
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from arb.nearmiss_report import (
    analyze_nearmiss,
    condition_categories,
    parse_nearmiss_rows,
)
from arb.recorder import load_jsonl


def format_report(summary: dict) -> str:
    lines = [
        "near-miss analysis (paper, offline)",
        f"  considers: {summary['considers']}  walked: {summary['walked']}  thin: {summary['thin']}",
        f"  min_edge: {summary['min_edge']}",
        f"  best_edge: {summary['best_edge']}  distance_to_min_edge: {summary['best_distance_to_min_edge']}",
        f"  would_fire: {summary['would_fire']}",
        "  histogram (walked-edge buckets):",
    ]
    for bucket, count in sorted(summary["histogram"].items()):
        lines.append(f"    {bucket}: {count}")
    lines.append("  by category (best walked edge):")
    for cat, stats in sorted(
        summary["by_category"].items(),
        key=lambda kv: kv[1]["considers"],
        reverse=True,
    ):
        lines.append(
            f"    {cat}: considers={stats['considers']} best_edge={stats['best_edge']}"
        )
    lines.append("  by hour of day UTC (best walked edge):")
    for hour, stats in sorted(summary["by_hour"].items(), key=lambda kv: int(kv[0])):
        lines.append(
            f"    {hour:>2}: considers={stats['considers']} best_edge={stats['best_edge']}"
        )
    lines.append(f"  closest {len(summary['closest'])} pairs:")
    for row in summary["closest"]:
        lines.append(
            f"    {row['raw_edge']} (need {row['distance_to_min_edge']} more) "
            f"[{row['category']}] {row['condition_id']}"
        )
    if not summary["would_fire"]:
        lines.append(
            "  verdict: no walked edge reached min_edge. Do not loosen risk. Do not go live."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze recorded near-miss telemetry. Never places orders."
    )
    parser.add_argument("--nearmiss", default="data/paper/nearmiss.jsonl")
    parser.add_argument(
        "--tape",
        default="",
        help="Optional recorded books.jsonl for market categories.",
    )
    parser.add_argument("--min-edge", default="0.01")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Rejected. This analysis never places orders.",
    )
    args = parser.parse_args(argv)
    if args.place_orders:
        print("analyze_nearmiss: refuses to place orders", file=sys.stderr)
        return 2

    nearmiss_path = Path(args.nearmiss)
    if not nearmiss_path.is_file():
        print(f"analyze_nearmiss: no near-miss log at {nearmiss_path}", file=sys.stderr)
        return 1
    rows = parse_nearmiss_rows(load_jsonl(nearmiss_path))

    categories: dict[str, str] = {}
    if args.tape:
        tape_path = Path(args.tape)
        if tape_path.is_file():
            categories = condition_categories(load_jsonl(tape_path))

    summary = analyze_nearmiss(
        rows,
        categories=categories,
        min_edge=Decimal(str(args.min_edge)),
        top_n=int(args.top),
    )
    print(format_report(summary))
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
