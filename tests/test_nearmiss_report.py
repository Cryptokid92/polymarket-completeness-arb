"""Offline near-miss analyzer. Read-only. No orders. No caps changed."""

from __future__ import annotations

import ast
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from arb.money import d
from arb.nearmiss_report import (
    analyze_nearmiss,
    condition_categories,
    parse_nearmiss_rows,
)
from arb.recorder import load_jsonl

_FIXTURES = Path("tests/fixtures/nearmiss_report")


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "analyze_nearmiss_cli", Path("scripts/analyze_nearmiss.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rows():
    return parse_nearmiss_rows(load_jsonl(_FIXTURES / "nearmiss.jsonl"))


def _categories():
    return condition_categories(load_jsonl(_FIXTURES / "books.jsonl"))


def test_parse_handles_null_raw_edge_and_thin() -> None:
    rows = _rows()
    assert len(rows) == 4
    thin = [row for row in rows if row.thin]
    assert len(thin) == 1
    assert thin[0].raw_edge is None
    assert rows[0].raw_edge == d("-0.001")


def test_condition_categories_from_tape_meta() -> None:
    cats = _categories()
    assert cats == {"c1": "Politics", "c2": "Sports", "c3": "Politics"}


def test_condition_categories_falls_back_to_event_grouping() -> None:
    events = [
        {
            "condition_id": "e1",
            "meta": {"category": None, "event_title": "World Cup Final"},
        },
        {"condition_id": "e2", "meta": {"category": None, "event_slug": "us-cpi"}},
        {"condition_id": "e3", "meta": {"category": None}},
    ]
    cats = condition_categories(events)
    assert cats == {"e1": "World Cup Final", "e2": "us-cpi"}


def test_analyze_overall_best_and_would_not_fire() -> None:
    summary = analyze_nearmiss(_rows(), categories=_categories(), min_edge=d("0.01"))
    assert summary["considers"] == 4
    assert summary["thin"] == 1
    assert summary["walked"] == 3
    assert summary["best_edge"] == "-0.001"
    # -0.001 is 0.011 short of the 0.01 min edge.
    assert summary["best_distance_to_min_edge"] == "0.011"
    assert summary["would_fire"] is False


def test_analyze_buckets_by_category_and_hour() -> None:
    summary = analyze_nearmiss(_rows(), categories=_categories(), min_edge=d("0.01"))
    politics = summary["by_category"]["Politics"]
    assert politics["considers"] == 2  # c1 and c3
    assert politics["best_edge"] == "-0.001"
    assert summary["by_category"]["Sports"]["considers"] == 1
    # c4 has no tape category.
    assert summary["by_category"]["unknown"]["considers"] == 1
    # Hours 0 (c1), 1 (c2, c3), 2 (c4 thin).
    assert summary["by_hour"]["0"]["considers"] == 1
    assert summary["by_hour"]["1"]["considers"] == 2
    assert summary["by_hour"]["2"]["considers"] == 1


def test_closest_sorted_desc_with_category() -> None:
    summary = analyze_nearmiss(_rows(), categories=_categories(), min_edge=d("0.01"))
    closest = summary["closest"]
    assert [row["raw_edge"] for row in closest] == ["-0.001", "-0.02", "-0.05"]
    assert closest[0]["category"] == "Politics"
    assert closest[0]["condition_id"] == "c1"


def test_analyze_rejects_float_min_edge() -> None:
    with pytest.raises(Exception):
        analyze_nearmiss(_rows(), min_edge=0.01)  # type: ignore[arg-type]


def test_cli_runs_on_fixtures_and_refuses_place_orders() -> None:
    module = _load_script()
    assert module.main(["--place-orders"]) == 2
    rc = module.main(
        [
            "--nearmiss",
            str(_FIXTURES / "nearmiss.jsonl"),
            "--tape",
            str(_FIXTURES / "books.jsonl"),
        ]
    )
    assert rc == 0
    source = Path("scripts/analyze_nearmiss.py").read_text(encoding="utf-8")
    assert "AsyncSecureClient" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "AsyncSecureClient"


def test_cli_missing_nearmiss_returns_error(tmp_path: Path) -> None:
    module = _load_script()
    assert module.main(["--nearmiss", str(tmp_path / "missing.jsonl")]) == 1
