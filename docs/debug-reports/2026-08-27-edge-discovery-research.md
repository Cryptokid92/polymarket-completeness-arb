# Edge-discovery research — 27 Aug 2026

Paper only. No `ALLOW_LIVE`. No live orders. Not financial advice.

Track A of the research plan: build the evidence needed to decide whether any
realizable completeness edge exists, given the earlier hour found `gaps=0` and
a best walked edge of `-0.001`
([2026-08-27-paper-evidence.md](2026-08-27-paper-evidence.md)). No hunt/risk cap
was changed. Task 12 stays dark.

## What was built

- **Tape metadata (Phase 1).** `market_meta()` records `category`, `tags`,
  `slug`, close time, and the event grouping (`event_slug` / `event_title`).
  `book_to_event()` nests it under `meta`. Diagnostic only; `frames_from_events`
  ignores it and money never comes from it.
- **Near-miss analyzer (Phase 2).** `src/arb/nearmiss_report.py` +
  `scripts/analyze_nearmiss.py` bucket walked-edge distributions by
  classification label and by UTC hour, with closest-N pairs and
  distance-to-`min_edge`. Read-only; rejects `--place-orders`.
- **Maker-rest fill study (Phase 3).** `estimate_maker_fill()` posts a passive
  completeness bid at each deciding frame's best bid (no lookahead) and checks
  whether a later frame within `maker_rest_ms` has an ask crossing down to it.
  It reports per-leg and joint fill rates, gross both-fill edge, and a net EV
  that debits an approximate hedge cost for naked one-leg fills.
  `summarize_tape_paths()` / `backtest_tape.py` now run taker + maker + study.
- **Aggregator (Phase 4).** `scripts/aggregate_evidence.py` pools several run
  data dirs and reruns the near-miss and maker-fill studies across sessions.

## SDK classification finding

The installed `polymarket-client` 0.7.0 listing (`gamma.Market`) does **not**
populate `category` or `tags`, and exposes no close time on the market or its
`trading` block. Across 300 sampled open markets, `category` was `None` and
`tags` empty for all of them. The `slug` and the `events` grouping
(`events[0].title` / `.slug`) **are** populated, so the analyzer falls back to
the event grouping as its classification label. Category/tag bucketing will
light up automatically if a future client populates those fields.

## Evidence (paper, public client only)

All data dirs are gitignored and not committed.

### Full universe, one cycle — `data/evi-all`

```bash
uv run python scripts/paper_run.py --once --all-markets --record-books --data-dir data/evi-all
uv run python scripts/aggregate_evidence.py data/evi-all
```

```text
markets_listed=5000  universe=1546  gaps=0  intents=0
nearmiss_considers=48821   best_edge=-0.001
pooled edge histogram: lt_-0.05=47907  -0.05_-0.02=469  -0.02_-0.01=66  -0.01_0=280  none=99
positive-edge buckets: 0
maker-fill: both_fill_rate=0  net_ev=-47.85  verdict=non_positive
```

Not one of 48,821 walked considers reached completeness. The closest walked
edge was `-0.001` (a tenth of a cent short of `1`, still `0.011` below the
`0.01` min edge). Zero buckets were at or above `0`.

### Two moderate sessions — `data/evi-a`, `data/evi-b`

```bash
uv run python scripts/aggregate_evidence.py data/evi-a data/evi-b
```

```text
sessions=2  markets_listed=1000  universe=114  gaps=0  intents=0
near-miss best_edge=-0.1057...  would_fire=False
maker-fill: both_fill_rate=0  net_ev=-3.45  verdict=non_positive
```

Near-miss buckets by event grouping (e.g. "Israel and Saudi Arabia normalize
relations before 2027?", "Xi Jinping out before 2027?"); every bucket's best
walked edge is deeply negative.

### Maker-rest study, single tape — `data/evi-a`

```text
probes=167  window_ms=400  size=5
fill rate  yes=0.126  no=0.066  both=0
both fills=0   one-leg (naked)=32
net_ev=-1.60   verdict=non_positive
```

Even resting passive completeness bids, **both legs never filled jointly**
within the rest window; only single legs filled, which is exactly the naked-leg
risk the risk agent exists to avoid. A half-filled arb is worse than no trade.

## Conclusion

Both the taker and the maker paths are `non_positive` on live-shaped data, by
wide margins. There is no realizable completeness edge in this evidence.

**Stop.** Do not loosen `min_edge`, `max_gap`, `stale_ms`, `WATCH_PAIRS`, or
`LIST_SAFETY_CAP`. Do not build or enable Task 12. Agents did not create
`ALLOW_LIVE`. Task 12 stays dark.

Tests: `uv run pytest -q` — 241 passed.
