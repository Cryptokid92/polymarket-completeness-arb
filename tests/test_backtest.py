from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path

from arb.adversary import detect_lookahead, detect_mid_fill
from arb.backtest import (
    BacktestConfig,
    estimate_maker_fill,
    run_backtest,
    summarize_tape,
    summarize_tape_paths,
    walk_bids,
)
from arb.books import Level
from arb.fees import pair_taker_fees
from arb.money import d
from arb.recorder import load_jsonl

RECORDED = Path(__file__).parent / "fixtures" / "recorded" / "gap_persist.jsonl"
MAKER_FILL = Path(__file__).parent / "fixtures" / "recorded" / "maker_fill.jsonl"


def _honest_cfg(**overrides: object) -> BacktestConfig:
    values: dict[str, object] = dict(
        path="taker_fak",
        p_miss=d("0"),
        latency_ms=100,
        hedge_slippage=d("0.01"),
        fee_rate_yes=d("0"),
        fee_rate_no=d("0"),
        min_edge=d("0.01"),
        min_size=d("5"),
        max_shares=d("80"),
        starting_capital=d("100"),
        rng_seed=1,
    )
    values.update(overrides)
    return BacktestConfig(**values)  # type: ignore[arg-type]


def test_honest_replay_completes_pair_on_ask_vwap_not_mid() -> None:
    events = load_jsonl(RECORDED)
    result = run_backtest(events, _honest_cfg())
    assert result.completed_pairs >= 1
    assert result.trades >= 1
    assert result.net_pnl > Decimal("0")
    assert result.capital_turns > Decimal("0")
    buys = [fill for fill in result.fills if fill.kind != "hedge"]
    assert buys
    for fill in buys:
        assert fill.fill_source == "ask"
        mid = (fill.best_bid + fill.best_ask) / Decimal("2")
        assert fill.price == fill.ask_vwap
        assert fill.price != mid
    detect_mid_fill(result)
    detect_lookahead(result)


def test_p_miss_one_makes_second_fak_fail_naked() -> None:
    events = load_jsonl(RECORDED)
    result = run_backtest(events, _honest_cfg(p_miss=d("1")))
    assert result.completed_pairs == 0
    assert result.naked_incidents >= 1
    sides = {fill.side for fill in result.fills if fill.kind != "hedge"}
    assert sides == {"YES"}
    hedges = [fill for fill in result.fills if fill.kind == "hedge"]
    assert hedges
    assert hedges[0].fill_source == "bid"
    assert hedges[0].price == d("0.54") - d("0.01")


def test_taker_fees_are_subtracted() -> None:
    events = load_jsonl(RECORDED)
    free = run_backtest(events, _honest_cfg())
    taxed = run_backtest(
        events,
        _honest_cfg(fee_rate_yes=d("0.07"), fee_rate_no=d("0.07")),
    )
    assert taxed.completed_pairs == free.completed_pairs
    assert taxed.completed_pairs >= 1
    assert taxed.net_pnl < free.net_pnl
    expected_fees = pair_taker_fees(
        d("80"), d("0.55"), d("80"), d("0.42"), d("0.07"), d("0.07")
    )
    assert free.net_pnl - taxed.net_pnl == expected_fees * taxed.completed_pairs


def test_walk_bids_uses_depth_not_mid() -> None:
    bids = [Level(price=d("0.54"), size=d("10")), Level(price=d("0.50"), size=d("10"))]
    vwap, filled = walk_bids(bids, d("20"))
    assert filled == d("20")
    assert vwap == (d("0.54") * d("10") + d("0.50") * d("10")) / d("20")
    assert vwap != (d("0.54") + d("0.55")) / d("2")


def test_reports_required_fields() -> None:
    result = run_backtest(load_jsonl(RECORDED), _honest_cfg())
    for name in (
        "trades",
        "completed_pairs",
        "naked_incidents",
        "net_pnl",
        "capital_turns",
    ):
        assert hasattr(result, name)


def test_record_books_script_uses_official_public_client_only() -> None:
    source = Path("scripts/record_books.py").read_text(encoding="utf-8")
    assert "refuses to place orders" in source
    assert "AsyncSecureClient" not in source
    assert "from polymarket import AsyncPublicClient" in source
    assert "import urllib" not in source
    assert "import httpx" not in source
    assert "import requests" not in source

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "record_books_cli", Path("scripts/record_books.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--place-orders"]) == 2


def test_summarize_tape_empty_is_no_tape() -> None:
    summary = summarize_tape([])
    assert summary["verdict"] == "no_tape"
    assert summary["events"] == 0


def test_summarize_tape_gap_persist_is_positive() -> None:
    summary = summarize_tape(load_jsonl(RECORDED), _honest_cfg())
    assert summary["events"] >= 1
    assert int(summary["completed_pairs"]) >= 1
    assert summary["verdict"] == "positive"


def test_backtest_public_api_has_no_float_literals() -> None:
    source = inspect.getsource(run_backtest)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) is float:
            raise AssertionError("run_backtest must not use float literals")


def test_maker_independent_rest_fills_when_touch_holds() -> None:
    events = load_jsonl(RECORDED)
    result = run_backtest(
        events,
        _honest_cfg(path="maker_gtc", maker_rest_ms=400, latency_ms=0),
    )
    assert result.completed_pairs >= 1
    for fill in result.fills:
        if fill.kind == "maker_gtc":
            assert fill.fill_source == "ask"


def test_estimate_maker_fill_counts_joint_and_naked_fills() -> None:
    study = estimate_maker_fill(load_jsonl(MAKER_FILL))
    assert study["probes"] == 6
    assert study["both_fills"] == 1
    assert study["one_leg_fills"] == 2
    assert study["best_edge"] == "0.05"
    assert study["gross_edge_sum"] == "0.25"
    assert study["naked_hedge_cost"] == "0.10"
    assert study["net_ev"] == "0.15"
    assert study["verdict"] == "positive"


def test_estimate_maker_fill_zero_window_never_fills() -> None:
    study = estimate_maker_fill(
        load_jsonl(MAKER_FILL),
        BacktestConfig(path="maker_gtc", maker_rest_ms=0),
    )
    assert study["probes"] == 6
    assert study["both_fills"] == 0
    assert study["one_leg_fills"] == 0
    assert Decimal(str(study["net_ev"])) == Decimal("0")
    assert study["verdict"] == "non_positive"


def test_estimate_maker_fill_empty_tape_has_no_probes() -> None:
    study = estimate_maker_fill([])
    assert study["probes"] == 0
    assert study["verdict"] == "no_probes"


def test_summarize_tape_paths_reports_both_sides() -> None:
    paths = summarize_tape_paths(load_jsonl(RECORDED))
    assert set(paths) == {"taker", "maker", "maker_fill"}
    assert paths["taker"]["verdict"] == "positive"
    assert "verdict" in paths["maker"]
    assert "both_fill_rate" in paths["maker_fill"]


def test_maker_fill_limits_use_only_deciding_frame() -> None:
    # Posting at the deciding frame's best bid must never fill from that same
    # frame (ask is above bid), so joint fills require a genuine later cross.
    study = estimate_maker_fill(load_jsonl(MAKER_FILL))
    assert study["both_fills"] <= study["probes"]
    assert study["both_fills"] >= 1
