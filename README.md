# polymarket-completeness-arb

Paper-first completeness arbitrage bot for [Polymarket](https://polymarket.com).

This repository scaffolds a **paper-mode** specialist team that looks for completeness (YES + NO) mispricings. It is research and software infrastructure only. Paper bankroll is **$500** and is **not real money**.

**Not financial advice.** Nothing here is an offer, solicitation, or recommendation to trade. There is **no guaranteed PnL**. Markets can gap, quotes can go stale, and a half-filled arb is worse than no trade.

## Hard rules

- Default mode is paper (`ARB_MODE=paper`). Live trading is not enabled in this repo.
- Secrets never belong in this public repository. Copy `.env.example` to a local `.env` that stays gitignored.
- Official SDK only: [`polymarket-client`](https://pypi.org/project/polymarket-client/) (`from polymarket import AsyncPublicClient, AsyncSecureClient`). Do not use unofficial clients.
- Money uses `Decimal`. Do not put an LLM in the hot path.
- Do not create `ALLOW_LIVE`. Do not place live orders.
