"""Multi-session evidence aggregator. Read-only. No orders. No caps changed."""

from __future__ import annotations

import ast
import importlib.util
from decimal import Decimal
from pathlib import Path

from arb.evidence import aggregate_sessions
from arb.money import d

_FIX = Path("tests/fixtures/evidence")
_SESSIONS = [_FIX / "session1", _FIX / "session2"]


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "aggregate_evidence_cli", Path("scripts/aggregate_evidence.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_aggregate_pools_totals_and_maps() -> None:
    summary = aggregate_sessions(_SESSIONS, min_edge=d("0.01"))
    assert summary["sessions"] == 2
    totals = summary["totals"]
    assert totals["markets_listed"] == 300
    assert totals["universe"] == 30
    assert totals["gaps"] == 0
    assert totals["nearmiss_considers"] == 11
    assert summary["pooled_edge_histogram"] == {"lt_-0.05": 8, "-0.01_0": 3}
    assert summary["pooled_reject_reasons"] == {"neg_risk": 270, "seconds_delay": 5}
    # Best edge is the max across sessions.
    assert summary["best_edge"] == "-0.001"


def test_aggregate_reruns_nearmiss_across_sessions() -> None:
    summary = aggregate_sessions(_SESSIONS, min_edge=d("0.01"))
    nm = summary["nearmiss"]
    assert nm["considers"] == 3  # c1, c2, c3 near-miss rows
    assert nm["best_edge"] == "-0.001"
    assert nm["would_fire"] is False
    # Categories join through the recorded tapes, prefixed per session.
    assert nm["by_category"]["Politics"]["considers"] == 2  # c1 + c3
    assert nm["by_category"]["Sports"]["considers"] == 1


def test_aggregate_includes_maker_fill_study() -> None:
    summary = aggregate_sessions(_SESSIONS, min_edge=d("0.01"))
    assert "both_fill_rate" in summary["maker_fill"]
    assert "verdict" in summary["maker_fill"]


def test_sessions_are_kept_separate_by_prefix() -> None:
    # Same condition id in two sessions must not collide in the category map.
    summary = aggregate_sessions([_FIX / "session1", _FIX / "session1"])
    # Two copies double the considers rather than overwriting.
    assert summary["nearmiss"]["considers"] == 4
    assert summary["totals"]["markets_listed"] == 200


def test_cli_runs_and_refuses_place_orders() -> None:
    module = _load_script()
    assert module.main(["--place-orders"]) == 2
    assert module.main([]) == 1
    rc = module.main([str(_SESSIONS[0]), str(_SESSIONS[1])])
    assert rc == 0
    source = Path("scripts/aggregate_evidence.py").read_text(encoding="utf-8")
    assert "AsyncSecureClient" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "AsyncSecureClient"
