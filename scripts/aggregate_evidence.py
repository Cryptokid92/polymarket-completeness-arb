#!/usr/bin/env python3
"""Aggregate several paper-run data dirs into one edge summary. Read-only.

Never places orders. Pools per-session stats.json, joins recorded books.jsonl
categories, and reruns the near-miss and maker-fill studies across all
sessions.

Usage:
  uv run python scripts/aggregate_evidence.py data/paper-a data/paper-b
  uv run python scripts/aggregate_evidence.py --min-edge 0.01 --top 10 data/run1 data/run2
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from arb.evidence import aggregate_sessions


def format_report(summary: dict) -> str:
    totals = summary["totals"]
    nm = summary["nearmiss"]
    mf = summary["maker_fill"]
    lines = [
        "edge-discovery aggregate (paper, offline)",
        f"  sessions: {summary['sessions']}",
        f"  markets_listed: {totals['markets_listed']}  universe: {totals['universe']}",
        f"  gaps: {totals['gaps']}  intents: {totals['intents']}"
        f"  nearmiss_considers: {totals['nearmiss_considers']}",
        f"  best_edge across sessions: {summary['best_edge']}",
        "  pooled edge histogram:",
    ]
    for bucket, count in sorted(summary["pooled_edge_histogram"].items()):
        lines.append(f"    {bucket}: {count}")
    lines.append("  pooled reject reasons:")
    for reason, count in sorted(
        summary["pooled_reject_reasons"].items(), key=lambda kv: kv[1], reverse=True
    ):
        lines.append(f"    {reason}: {count}")
    lines.append(
        f"  near-miss best_edge: {nm['best_edge']} would_fire: {nm['would_fire']}"
    )
    lines.append("  near-miss best by category:")
    for cat, stats in sorted(
        nm["by_category"].items(), key=lambda kv: kv[1]["considers"], reverse=True
    ):
        lines.append(
            f"    {cat}: considers={stats['considers']} best_edge={stats['best_edge']}"
        )
    lines.append(
        "  maker-fill: "
        f"both_fill_rate={mf['both_fill_rate']} net_ev={mf['net_ev']} "
        f"verdict={mf['verdict']}"
    )
    if not nm["would_fire"] and mf["verdict"] != "positive":
        lines.append(
            "  verdict: no realizable edge in this evidence. Do not loosen risk. Do not go live."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate paper-run evidence. Never places orders."
    )
    parser.add_argument("dirs", nargs="*", help="Paper run data dirs to pool.")
    parser.add_argument("--min-edge", default="0.01")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument(
        "--place-orders",
        action="store_true",
        help="Rejected. This aggregation never places orders.",
    )
    args = parser.parse_args(argv)
    if args.place_orders:
        print("aggregate_evidence: refuses to place orders", file=sys.stderr)
        return 2
    if not args.dirs:
        print("aggregate_evidence: pass at least one data dir", file=sys.stderr)
        return 1

    summary = aggregate_sessions(
        [Path(d) for d in args.dirs],
        min_edge=Decimal(str(args.min_edge)),
        top_n=int(args.top),
    )
    print(format_report(summary))
    print(json.dumps(summary, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
