# Lajan Sere (the Trading Platform): plan summary

The living plan is the doc [Lajan Sere — Game Plan](https://claude.ai/artifact/KZgVmMfuucbSNsPRVFHkxD), written Nov 11, 2026 (titled "Trading Platform — Game Plan" until Nov 16). This is a short summary so later chats in this project start from it. Where the two differ, the doc wins. On Nov 16 the user named the app **Lajan Sere** (see Name, at the end).

## Scope (assumed)
- The user's own account first, US stocks and ETFs, daily bars, positions held for days to weeks. Crypto joins in Phase 6 (added Nov 15) and forex in Phase 7 (added Nov 15–16). Forex short selling, the standard/exotic pair choice and the dashboard settings were added Nov 16.
- Selling it to other people is a separate, later decision that needs a regulatory and licensing review.

## Core decisions
- Broker: Alpaca for stocks and crypto. The app places orders in code through alpaca-py. The Alpaca MCP server (v2, paper trading by default) is only a chat window. On live keys, set `ALPACA_TOOLSETS` without `trading`.
- Forex broker: OANDA (Alpaca has no currency trading; its Local Currency Trading only buys US stocks in other currencies). The app calls OANDA's v20 REST API directly over httpx with a personal access token; the practice server for paper, the live server for live.
- Principle: AI proposes, code decides. Flow: data → rules engine / AI research desk → signal ledger → risk engine → human approval → execution → broker → nightly reconciliation and dashboard.
- The app recommends trades from tested rules, explains each one, and teaches the ideas behind it (decided Nov 14); the user decides what gets sent.
- Short selling (decided Nov 16, the user chose "Forex only"): forex only, off by default, switched on by the user after a warning. Stocks stay long-only (margin, no ceiling on the loss); Alpaca can't short crypto.
- Real money runs through the same app: once a book passes Gates 0–4 on paper, its own live settings file sets the real broker, `TRADING_MODE=live` and `LIVE_TRADING_CONFIRMED=true`. There is deliberately no dashboard button for going live.
- Tools:
  - Use alpaca-mcp-server now. The official TradingView MCP is optional (Essential plan or higher).
  - Add OpenBB ODP and TradingAgents in Phase 3.
  - Skip ai-hedge-fund, daily_stock_analysis and FinceptTerminal, but borrow their ideas.
- Stack: Python (FastAPI, Postgres, a scheduler, vectorbt), a React + Vite dashboard, Telegram approvals.

## Phases and gates
0. Set up (week 1). Gate 0: the code places, reads back and cancels a paper order.
1. One rules strategy (weeks 2–4). Gate 1: beats SPY on the held-out years (2023 to now) after costs, and still holds when parameters change a little.
2. Build the app (weeks 5–8), including explained recommendations, the watchlist scanner and the Learn section. Gate 2: 10 paper days with zero reconciliation errors, and the kill switch tested.
3. AI A/B test on paper account B (weeks 9–20). Gate 3: the AI goes live only if it beats rules-only after its LLM costs.
4. Paper forward test on account A (weeks 9–20). Gate 4: 12 weeks within the backtest's ranges.
5. Live with small money (week 21 on). Gate 5: three live months track paper before scaling up.
6. Crypto (week 34 on, only after stocks pass Gate 5; added Nov 15). A second book on its own paper account, labeled C: the trend rule on BTC/USD and ETH/USD, judged against holding bitcoin, with Gates 0, 1, 2, 4 and 5 repeated. Live crypto needs its own account too, or a decision on sharing one, before its Gate 5.
7. Forex (week 47 on, once crypto passes its Gate 4, or after stocks' Gate 5 if crypto is skipped; added Nov 15–16). A third book, labeled F, on an OANDA practice account: the trend rule on the standard pairs (the seven majors) or the exotic ones (the dollar against six emerging-market currencies), judged against holding EUR/USD (USD/MXN for exotic), short selling only if switched on, with Gates 0, 1, 2, 4 and 5 repeated. A changed stop, pair set or short-selling switch means running Gate 1 again before real money.

## Risk defaults
- Risk per trade: 0.5–1% of equity.
- Position size: at most 10% of equity in one name.
- Open positions: 5–10 at most.
- Daily loss: down 2% means no new orders that day.
- Drawdown: down 10% from the peak triggers the kill switch.
- Orders: bracket orders with the stop held at Alpaca; limit orders, nothing in the first or last 15 minutes.
- Unique client order ID per signal; at most 10 orders a day.
- Crypto book: a stop-limit 15% below each buy with its limit 5% lower (19.25% worst fill), so the 1% risk rule caps each coin at about 5% of the account; 2 positions at most; 0.35% per side in backtests.
- Forex book: no leverage (buying power = equity minus what's held or on order, shorts fully paid for too); every pair has the dollar on one side (crosses refused). Standard pairs: recommended stop 3% from the entry, at most 14% per pair and seven pairs (a stop-out costs about 0.42%), 0.03% per side plus 2.5% a year of financing in backtests. Exotic pairs (USD/MXN, USD/ZAR, USD/PLN, USD/HUF, USD/CZK, USD/SGD; the Turkish lira left out for its carry cost): 5% stop, 10% per pair, six pairs (about 0.5%), 0.15% per side and 6% a year. No orders 4:45–5:15 pm ET.
- Stop-loss choice (every book): the recommended stop is 8% stocks, 15% crypto, 3% standard forex, 5% exotic. The user can set 1% up to 3 times the recommended (30% at most). A wider stop shows warnings (cost per stop-out, smaller positions once the 1% limit bites, all-slots loss, gaps, open positions keep their stops, re-run Gate 1) and needs confirming; so do exotic pairs and switching shorts on.

## Facts checked
- Nov 11: The pattern day trader rule is gone (FINRA Regulatory Notice 26-10, effective June 4, 2026), and Alpaca has implemented the change.
- Nov 11: Alpaca's Basic data plan is free (real-time IEX, history since 2016). Algo Trader Plus costs $99 a month.
- Nov 11: Alpaca allows 3 paper accounts per owner, which makes the A/B test possible.
- Nov 11: LLM backtests suffer from look-ahead bias built into the model, so AI signals are judged only on results logged going forward.
- Nov 14–15, crypto at Alpaca: trades 24/7; market, limit and stop-limit orders with GTC or IOC, no OTO; no margin or shorting; fees 0.15% maker and 0.25% taker on the lowest tier, taken from the asset received; open only in some US states; positions are listed as BTCUSD while orders use BTC/USD; daily bars run midnight to midnight Chicago time.
- Nov 14–15, crypto taxes: digital assets are property; Form 1099-DA reports gross proceeds from 2025 and basis for covered assets from 2026; the wash sale rule typically doesn't apply to coins (it does to spot crypto ETFs), but a bill that cleared House Ways and Means in September 2026 would apply it to crypto sold after Sept 14, 2026.
- Nov 15–16, forex: about $9.6 trillion a day in April 2025, up 28% from 2022, the dollar on one side of about 89% of trades (BIS, WEF); the CFTC lists six registered retail forex dealers (OANDA is one) and says about two of three retail forex traders lose money each quarter; US dealers must collect 2% of notional on major pairs and 5% on others (17 CFR 5.9), so leverage up to 50:1 and 20:1; NFA Rule 2-43(b): FIFO and no hedging; OANDA's market runs Sunday ~5 pm to Friday 5 pm New York and books financing on positions open at 5 pm ET (interest differential plus a fee); spot forex is taxed under Section 988 as ordinary income unless a Section 1256 election (60/40) is in place by January 1.
- Nov 15–16, OANDA v20 API: practice https://api-fxpractice.oanda.com, live https://api-fxtrade.oanda.com; LIMIT orders take units (negative to sell), price, timeInForce, positionFill (OPEN_ONLY, REDUCE_ONLY), clientExtensions and stopLossOnFill (with its own clientExtensions); a STOP_LOSS order carries only a tradeID, no pair or units; daily candles align to 17:00 America/New_York, at most 5,000 a page; order fill prices come from the ORDER_FILL transaction (fullVWAP).
- Nov 16, shorting: in forex a short is an ordinary trade with nothing to borrow (IG); a stock short at Alpaca needs margin and at least $2,000 of equity; Alpaca says crypto isn't shortable.
- Nov 16, exotic pairs: 30-day realized volatility over roughly 2021–23 was about 12.9% for USD/ZAR, 9.2% USD/MXN, 6.6% EUR/USD, 3.9% USD/SGD (tastyfx, Dec 2023); exotics have wider spreads and jump on local news (FxPro). Turkey cut its policy rate to 36% on Oct 22, 2026 (Trading Economics); the Fed held 3.75–4% on Oct 28, 2026; the lira hit a record low near 50 per dollar in Nov 2026. Which exotics an OANDA US account offers wasn't confirmed (OANDA's pages render by script); the app relies on OANDA refusing orders for pairs it doesn't offer.

## Codebase (built Nov 13, extended Nov 14–16, 2026)
Delivered as `lajan-sere.zip` (top folder `lajan-sere/`; it was `trading-platform.zip` until Nov 16) for the user to push to their own private GitHub repo (`gh repo create lajan-sere --private`). Layout: `backend/` (Python package `trader`, CLI `trader`), `frontend/` (React 19 + Vite 8 dashboard; lessons in `src/learn/`), `docs/` (ARCHITECTURE.md, GATES.md, MCP configs), CI on GitHub Actions, Docker Compose with Postgres.

- Safe defaults: fake broker, synthetic prices, paper mode, every order needs approval. Live needs the book's real broker (`BROKER=alpaca` for stocks and crypto, `BROKER=oanda` for forex), `TRADING_MODE=live` and `LIVE_TRADING_CONFIRMED=true`. Settings refuse a book on the wrong broker or price feed.
- Strategies: trend (200-day average, equal weight; with `shorts=True` it targets -1/N below the average) and momentum (12-1 month, top 3, monthly; long-only) on a 10-ETF universe.
- Recommendations: a Buy, Sell, Hold or Stay out call per symbol (forex with shorts on adds Sell short, Hold short, Buy to cover) with the rule's reason, limit, stop, size, dollars at risk, backtest record, Gate 1 status and account record (`trader recommendations`, dashboard).
- Watchlist scanner: ranks `WATCHLIST` (11 sector ETFs by default) by 12-1 momentum; ideas are labeled untested and can't be sent until a strategy covering the list passes Gate 1 (`trader scan`). Stocks only.
- Crypto book (Nov 15): `ASSET_CLASS=crypto` in its own settings file (`.env.crypto.example`), run beside the stock book with `CRYPTO_ENV_FILE` (dashboard Crypto tab, API under `/api/crypto`) or alone with `--env-file`. It reads only its own file. Fractional sizes rounded to each pair's steps; GTC limit entries, then a GTC stop-limit placed as soon as the buy fills; a protect job every 5 minutes places missing stops, cancels orders unfilled after 60 minutes and warns when a price falls below a stop's limit; daily jobs at 1:05 and 1:15 am ET; each book sees only its own asset class at Alpaca; one Telegram bot serves every book. The demo fills a Crypto tab on made-up prices (`backend/crypto-demo.db`).
- Forex book (Nov 15–16): `ASSET_CLASS=forex` in its own file (`.env.forex.example`: `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, `DATA_SOURCE=oanda`, `PAIR_SET`, `ALLOW_SHORTS`), run beside the others with `FOREX_ENV_FILE` (dashboard Forex tab, API under `/api/forex`). `broker/oanda_broker.py` and `data/oanda_source.py`; `forex.py` holds the clock. Entries are GTC limit orders with stopLossOnFill and OPEN_ONLY (a sell for a short, its stop above); exits are REDUCE_ONLY on the other side and don't cancel the stop first; client IDs end in `-buy`, `-sell`, `-short` or `-cover`, and OANDA orders carry the tag `lajan-sere`; the 5:05 pm ET broker check cancels unfilled entries and exits and wants a stop on the right side of every position; jobs on weekdays: send 9:50 am, broker check 5:05 pm, signals 5:15 pm ET. A long whose signal turns short closes first; the short opens another day. Short entries re-check the gap downward; the AI veto is mirrored for shorts.
- Money model (Nov 16, `money.py`): every value in dollars; a pair with the dollar first (USD/MXN) has $1 units and its P&L converted at the current price; positions are fully paid for, shorts too (value = dollars set aside + P&L). The planner also caps an entry so its dollar loss at the stop stays within the 1% risk limit. Pair price steps: 0.001 for JPY/HUF/THB, 0.0001 CZK, else 0.00001.
- Dashboard settings (Nov 16, `preferences.py`): GET/PUT `/preferences` per book and `trader settings` (`--stop`, `--recommended-stop`, `--pairs`, `--shorts/--no-shorts`, `--yes`). Stored in each book's ledger and applied over its settings file; riskier choices return 409 with warnings until confirmed; a change expires waiting proposals, audits and notifies; a pair-set switch is blocked while positions are open in pairs leaving the set; backtests and gates (CLI) read the choices. The dashboard has a "Your settings" panel with an amber warning box and a tick-to-confirm.
- Learn section: 24 beginner lessons in 7 modules (Forex adds "Standard or exotic pairs" and "Selling short", Nov 16), 33 quiz questions, a glossary and tap-to-explain dashboard terms; progress saved in the ledger. Currency prices show the pair's own decimals.
- Every gate has a command: `smoke-test` (0), `gate1`, `gate2`, `compare-ab` (3), `gate4`, `gate5`; the crypto and forex books run them with `--env-file ../.env.crypto` or `../.env.forex`.
- One database per account: a ledger records its mode and account on first use and refuses other settings. The demo uses `backend/demo.db` by default. Second accounts run with `trader --env-file ../.env.b ...`.
- Differences from the doc's stack, decided while building: an in-house backtester on the live order planner instead of vectorbt (exact live/backtest parity; vectorbt adds the Commons Clause); stock entries are one-triggers-other orders (limit buy plus stop, no take-profit) rather than full brackets; whole shares only for stocks, so small live accounts can't buy the pricier ETFs.
- Verified Nov 16: 199 tests pass on Python 3.11 and 3.13 from a clean unzip; ruff clean; the dashboard builds. On made-up prices, the two-sided trend rule on the standard pairs traded a lot (357 round trips, 2016–22) and lost a little, so whether shorts help is for Gate 1 on real OANDA data to decide.

## Name (chosen Nov 16)
- The app is **Lajan Sere**, from the Haitian proverb "Lajan sere se lajan ou fè" (money saved is money earned). The user picked it over Mache Mapou, which Claude had preferred, flagging the mapou's Vodou association and the "poo" sound for English speakers.
- Where it shows: the dashboard's top band and browser title, the token screen, the README (title, tagline, repo name `lajan-sere`), the API title, the CLI help, the package description and the npm package (`lajan-sere-dashboard`). The CLI command and Python package stay `trader`, and client order IDs keep their `tp` prefix.
- The Game Plan doc was renamed "Lajan Sere — Game Plan" on Nov 16, at the user's request: its name and heading changed, the link didn't. Its entry in the claude.ai Artifacts list still showed the old title afterwards, and Claude's tools couldn't change that entry.
- Other ideas offered: English (Trendkeeper, Second Look, Ledgerline), Haitian Creole (Piti Piti, Kenbe, Mache Dousman, Konbit), Swahili (Pole Pole, Dira, Imara, Busara), Sankofa (Akan), Ndank Ndank (Wolof), Díẹ̀díẹ̀ (Yoruba), Kancane (Zulu), Qes Be Qes (Amharic). "Haba Haba" is already Kenya's NSSF micro-pension scheme.
- Still to do: trademark and domain checks.
