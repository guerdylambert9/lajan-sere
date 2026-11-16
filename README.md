# Lajan Sere

*Lajan sere se lajan ou fè*: money saved is money earned, as the Haitian proverb goes.

A trading app you run yourself. After each market close it recommends trades: a Buy, Sell, Hold or Stay out call on every symbol (the forex book can also sell short, once you switch that on), each with its reason, its price levels and the dollars at risk. It checks every order against hard risk limits and waits for your approval, then places the orders with Alpaca (stocks and crypto) or OANDA (forex). A Learn section teaches what every recommendation rests on. Backtests and a series of gates tell you, with numbers, when the app has earned the next step from demo to paper to live money.

One rule runs through all of it: **AI proposes, code decides.** Rules (and later an optional AI research desk) can suggest trades. Only code with fixed risk limits, plus your approval, can send them. The AI can veto an entry; it can never add or enlarge one.

> Out of the box it runs a fake broker on made-up prices. It cannot touch real money unless you set three things on purpose: `BROKER=alpaca` (or `BROKER=oanda` for the forex book), `TRADING_MODE=live` and `LIVE_TRADING_CONFIRMED=true`. This is a personal tool, not investment advice.

## What it does

- **Signals.** Two rules strategies on a basket of ETFs: trend following (hold what trades above its 200-day average) and momentum (the top 3 by 12-month return, skipping the last month, rebalanced monthly).
- **Recommendations.** Every evening each symbol gets a call (Buy, Sell, Hold or Stay out) with the rule's reason in plain words, the limit, the stop, the shares, the dollars at risk, and the rule's track record. A Buy that got no order says why.
- **Watchlist scanner.** Ranks a list you choose (the 11 sector ETFs to start) the way the momentum rule would, with entry, stop and size. Ideas stay labeled untested, and can't be sent, until a strategy covering the list passes Gate 1.
- **Learn section.** 24 short lessons for beginners in seven modules, crypto and forex included (short selling and the exotic pairs too), with quizzes, a glossary, and tap-to-explain terms on the dashboard. Progress is saved in the ledger.
- **Your settings.** Each book's tab sets its stop-loss, and the forex tab picks standard or exotic pairs and switches short selling on or off. Riskier choices show plain warnings and wait for your OK.
- **Risk checks.** Every order is checked when it is planned and again right before it is sent: size, risk per trade, open positions, daily loss, drawdown, daily order cap, trading window, duplicates, buying power, and no short selling (the forex book can sell short only once you switch it on).
- **Approvals.** From the dashboard, the command line or Telegram buttons. Nothing goes out without you unless you turn on `AUTO_APPROVE`.
- **Execution.** Limit orders through the official `alpaca-py` SDK. Every entry carries a protective stop held at Alpaca, so it protects you even when this app is off.
- **Broker check.** Every afternoon the ledger is compared with Alpaca: unfilled entries are canceled, equity is recorded, and the kill switch engages by itself at the drawdown limit.
- **Kill switch.** One button cancels pending entries and blocks new orders. Protective stops stay in place.
- **Backtests and gates.** The backtester uses the same order planner as live trading, so a backtest trades exactly the way the app would. Gates 0 to 5 decide each step forward.
- **AI research desk (optional, phase 3).** TradingAgents reviews entries on a second paper account, and Gate 3 decides whether it earns its LLM costs.
- **Crypto book (Phase 6).** Bitcoin and ether on their own account and ledger, with the same planner, risk checks and approvals. It trades around the clock in slices of a coin, places a stop-limit under each position as soon as the buy fills, and charges Alpaca's crypto fee in backtests. It appears as a Crypto tab beside the stock desk.
- **Forex book (Phase 7).** Four currency pairs (EUR/USD, GBP/USD, AUD/USD, NZD/USD) at OANDA, since Alpaca doesn't trade currencies. Same planner, risk checks and approvals; whole units of currency, a stop-loss attached to every buy, no borrowed money, and overnight financing charged in backtests. It appears as a Forex tab.

## Try the demo (no accounts needed)

You need Python 3.11 or newer and Node.js 22.12 or newer (20.19+ also works).

```bash
# Terminal 1: the backend
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
trader demo                        # replays the last 120 trading days with a fake broker
trader serve                       # the API, on http://127.0.0.1:8000
```

```bash
# Terminal 2: the dashboard
cd frontend
npm install
npm run dev                        # open http://localhost:5173
```

The dashboard shows the demo account, its equity against SPY, today's recommendations and the watchlist ideas. Approve the order waiting for you, then press **Send approved orders**. The **Crypto** and **Forex** tabs run their own demos on made-up coin and currency prices, and the **Learn** tab holds the lessons. The demo market never closes, so this works at any hour. The demo keeps its records in `backend/demo.db`, `backend/crypto-demo.db` and `backend/forex-demo.db`, apart from any real account; `trader demo --no-crypto` or `--no-forex` skips one.

To run everything from one process and one port, build the dashboard once with `npm run build`; `trader serve` then serves it at http://127.0.0.1:8000.

## How a trading day runs

Times are New York time on weekdays. With the scheduler on (`ENABLE_SCHEDULER=true` or `trader serve --scheduler`) the jobs run by themselves. You can also press them in the dashboard or run them from the command line.

| When | Job | What happens |
|---|---|---|
| 5:15 pm | Signals (`trader run-nightly`) | Reads the day's closes, makes today's recommendations, plans whole-share orders, runs the risk checks, posts proposals to the dashboard and Telegram, and scans the watchlist. |
| Evening | You | Approve or reject each proposal. |
| 9:50 am next trading day | Send (`trader submit`) | Re-prices each approved order at the latest price, skips entries that gapped up too far, re-checks the limits, and sends limit orders. Entries carry a stop 8% below; exits cancel that stop first. |
| 4:30 pm | Broker check (`trader reconcile`) | Compares the ledger with Alpaca, cancels entries that didn't fill, records equity, and engages the kill switch at 10% below the peak. |

## The road to live trading

Each gate is a command that prints its checks and exits with 0 on a pass and 1 on a fail. [docs/GATES.md](docs/GATES.md) explains every check and why it is there.

| Phase | Weeks | What you do | Gate to pass | Command |
|---|---|---|---|---|
| 0. Set up | 1 | Open Alpaca, put paper keys in `.env` | Your code places, reads back and cancels a paper order | `trader smoke-test` |
| 1. One strategy | 2 to 4 | Backtest 2016 to 2022 on real prices | Beats SPY on the held-out years (2023 to now) after costs, and holds up when parameters move or trades come a day late | `trader gate1` |
| 2. The app on paper | 5 to 8 | Run the scheduler on paper, approve daily, drill the kill switch | Ten weekdays of clean broker checks, kill switch tested | `trader gate2` |
| 3. AI A/B test | 9 to 20 | Paper account B runs the same rules plus the AI veto | B beats A after its LLM costs | `trader compare-ab` |
| 4. Paper forward test | 9 to 20 | Account A keeps trading on paper | Twelve weeks inside the backtest's ranges | `trader gate4` |
| 5. Live, small | 21 on | Live keys, small size, paper still running | Three live months track paper before you add money | `trader gate5` |

### Phase 0: connect Alpaca paper trading

1. Open an account at [alpaca.markets](https://alpaca.markets). In the dashboard, switch to your paper account and generate API keys.
2. Copy the settings file and fill it in (from the repository root):

   ```bash
   cp .env.example .env
   ```

   ```ini
   BROKER=alpaca
   ALPACA_API_KEY=your-paper-key
   ALPACA_SECRET_KEY=your-paper-secret
   DATA_SOURCE=alpaca
   ```

3. From `backend/`, run `trader smoke-test`. It places a one-share limit buy far below the market (it can't fill), reads it back by its client order ID, and cancels it.

### Phase 1: test a strategy on real prices

```bash
trader backtest --strategy trend        # 2016 to 2022 only
trader backtest --strategy momentum
trader gate1 --strategy trend           # 2023 to today; run it once per idea
```

Write down what would count as a pass before you run `gate1`. Every run is logged in `reports/holdout_log.jsonl`, because each extra look at the held-out years makes a pass less trustworthy. If an idea fails, change the idea, not the test. `trader fetch-data` saves the prices to `data/closes.csv` so you can backtest offline with `DATA_SOURCE=csv`.

With `DATA_SOURCE=synthetic` these commands run, but the prices are random, so the results mean nothing. Gate 1 usually fails on them, as it should.

### Phase 2: run it on paper

1. Set `ENABLE_SCHEDULER=true` and run `trader serve` on a computer that stays on, or use Docker on a small server (see below).
2. Optionally set up Telegram approvals (see below).
3. Each evening, approve or reject the proposals. Each day, glance at the broker check on the dashboard.
4. Drill the kill switch once: engage it, confirm that pending entries were canceled and the stops stayed, then release it.
5. After ten weekdays, run `trader gate2`.

### Phase 3: the AI A/B test on paper account B

Alpaca lets you open up to three paper accounts. Open a second one for account B.

1. Install TradingAgents into the backend's environment and set up its LLM provider keys as its README describes:

   ```bash
   pip install git+https://github.com/TauricResearch/TradingAgents.git
   ```

2. Copy your settings to `.env.b` and change these lines:

   ```ini
   ACCOUNT_LABEL=B
   ALPACA_API_KEY=account-b-paper-key
   ALPACA_SECRET_KEY=account-b-paper-secret
   DATABASE_URL=sqlite:///./trader-b.db
   AI_MODE=veto
   AI_RESEARCHER=tradingagents
   AI_COST_PER_CALL_USD=0.50
   ```

   Set `AI_COST_PER_CALL_USD` to what a research call really costs you, so Gate 3 charges it against B.

3. Run B next to A: `trader --env-file ../.env.b serve --port 8001`. With the dashboard built, B's dashboard is at http://127.0.0.1:8001.
4. After twelve weeks, compare: `trader compare-ab --a sqlite:///./trader.db --b sqlite:///./trader-b.db`.

The AI is judged only on results logged going forward. Backtesting an LLM is unreliable, because the model may already know what happened next.

### Phase 4: the paper forward test

Account A keeps trading on paper with the rules alone. After twelve weeks, `trader gate4` checks that its return and drawdown sit inside the range the backtest produced over twelve-week windows. Don't reset the paper account during the test: a reset breaks the equity history.

### Phase 5: live, with small money

Give the live account its own settings file, `.env.live`, with its own database:

```ini
TRADING_MODE=live
LIVE_TRADING_CONFIRMED=true
BROKER=alpaca
ACCOUNT_LABEL=L
ALPACA_API_KEY=your-live-key
ALPACA_SECRET_KEY=your-live-secret
DATABASE_URL=sqlite:///./trader-live.db
ENABLE_SCHEDULER=true
```

Run it next to paper account A with `trader --env-file ../.env.live serve --port 8002`. Start with an amount you can afford to lose. The dashboard's top band turns into hazard stripes in live mode. After three months, run `trader --env-file ../.env.live gate5 --paper sqlite:///./trader.db` before adding money.

The app buys whole shares, and a new position starts at no more than 10% of equity. In a small account that rules out the pricier ETFs: with $5,000, 10% is $500, which buys no SPY. For a fair comparison, give the paper account the same cash as live (use your third paper account, or reset A's balance after Gate 4), or choose a universe of cheaper ETFs.

### Phase 6: crypto, after Gate 5

Crypto comes last, once the stock rules have passed Gate 5 with real money. It runs as a second book with its own Alpaca account, ledger and schedule; the dashboard shows it as a Crypto tab. Alpaca offers crypto only in [some US states](https://alpaca.markets/support/what-regions-support-cryptocurrency-trading), so check yours first. If it isn't listed, spot bitcoin and ether ETFs trade in the stock account under the stock rules instead.

1. Pick a paper account you no longer need (B once the AI test is over, or your third) and reset it to the cash you plan to use. Copy [.env.crypto.example](.env.crypto.example) to `.env.crypto` in the repository root and add that account's paper keys; the book labels it C.
2. In `.env`, set `CRYPTO_ENV_FILE=../.env.crypto` (relative to `backend/`). `trader serve` then runs both books, and the Crypto tab appears. To run crypto on its own instead: `trader --env-file ../.env.crypto serve --port 8003`.
3. Repeat the gates with the crypto settings: `trader --env-file ../.env.crypto smoke-test`, then `fetch-data`, `backtest`, `gate1`, `gate2`, `gate4` and `gate5` the same way. Gate 3 applies only if you add AI. Alpaca's crypto history may not reach back to 2016; if `backtest` finds no data, pass a later `--start`, or load daily closes from another source as a CSV with `DATA_SOURCE=csv`.

The crypto book keeps its own clock, because crypto never closes and Alpaca's crypto day ends at midnight Chicago time:

| When (New York time) | Job | What happens |
|---|---|---|
| 1:05 am daily | Broker check (`reconcile`) | Places any missing stop, compares the ledger with Alpaca, records the day's equity |
| 1:15 am daily | Signals (`run-nightly`) | Reads the day that just ended, makes the calls, proposes orders; yesterday's unsent proposals expire |
| Every 5 minutes | Send (`submit`) | Sends approved orders at any hour; each buy gets its stop-limit as soon as it fills |
| Every 5 minutes | Protect (`protect`) | Puts a stop-limit under any position without one, cancels orders unfilled after 60 minutes, warns when a price falls below a stop's limit |

Its starting values (each can be changed in `.env.crypto`): BTC/USD and ETH/USD against holding bitcoin; a stop 15% below each buy with its limit 5% lower; at most 5% of the account per coin, which the 1% risk limit allows with a 19.25% worst-case fill; 0.35% per side in backtests for Alpaca's 0.25% taker fee plus the spread.

Two things differ from stocks. Alpaca's crypto desk takes no one-triggers-other orders, so the app places each stop itself; and a stop-limit never sells below its limit, so in a straight-down crash it can stay unfilled. When that happens the protect job warns you, and you decide whether to sell. Fees come out of the coins you receive, so the app sizes each stop from the coins actually held.

For live crypto, give it its own live account if Alpaca allows you one: each book only sees its own asset class at Alpaca, but sharing the stock account would mix the two books' equity in the risk limits.

The crypto book reads only its own file: nothing in `.env` or the environment leaks into it. In Docker, mount the file into the app (add `- ./.env.crypto:/app/.env.crypto:ro` under the app's `volumes`), set `CRYPTO_ENV_FILE=../.env.crypto` in `.env`, and give the book its own database, such as `DATABASE_URL=sqlite:///./data/crypto.db` in the app's data volume.

### Phase 7: forex, at OANDA

Forex comes after crypto has cleared its own paper forward test (or after stocks pass Gate 5, if you skip crypto). Alpaca doesn't trade currencies: its [Local Currency Trading](https://alpaca.markets/docs/local-currency-trading-lct) only lets people buy US stocks in other currencies. So the forex book runs at OANDA, one of the [six CFTC-registered retail forex dealers](https://www.cftc.gov/LearnAndProtect/forexfrauds), through its v20 REST API. It runs as a third book with its own account, ledger and schedule; the dashboard shows it as a Forex tab.

1. Open a free OANDA practice account, and in its account settings create a personal access token ("Manage API Access"). Copy [.env.forex.example](.env.forex.example) to `.env.forex` in the repository root and add the token and the v20 account ID (it looks like `101-001-1234567-001`); the book labels it F.
2. In `.env`, set `FOREX_ENV_FILE=../.env.forex`. `trader serve` then runs it beside the other books, and the Forex tab appears. On its own: `trader --env-file ../.env.forex serve --port 8004`.
3. Repeat the gates with the forex settings: `trader --env-file ../.env.forex smoke-test`, then `fetch-data` (OANDA's daily candles, back to 2016), `backtest`, `gate1`, `gate2`, `gate4` and `gate5`. Gate 3 applies only if you add AI.

The forex book keeps New York time. The market runs from Sunday 5 pm to Friday 5 pm, and each forex day ends at 5 pm:

| When (New York time) | Job | What happens |
|---|---|---|
| 9:50 am weekdays | Send (`submit`) | Sends approved orders while London and New York both trade; never between 4:45 and 5:15 pm |
| 5:05 pm weekdays | Broker check (`reconcile`) | Compares the ledger with OANDA, records the day's equity, cancels entries and exits that didn't fill (stops stay) |
| 5:15 pm weekdays | Signals (`run-nightly`) | Reads the day that just closed, makes the calls, proposes orders |

It trades one of two pair sets (`PAIR_SET`, or pick it on the dashboard), each with risk settings to match. Every pair has the US dollar on one side, so every size and loss is counted in dollars; in a pair with the dollar first, like USD/MXN, a unit is one dollar and the profit, in pesos, is counted back into dollars.

| | `standard` (the default) | `exotic` |
|---|---|---|
| Pairs | EUR/USD, GBP/USD, USD/JPY, USD/CHF, USD/CAD, AUD/USD, NZD/USD | USD/MXN, USD/ZAR, USD/PLN, USD/HUF, USD/CZK, USD/SGD |
| Benchmark | EUR/USD | USD/MXN |
| Recommended stop | 3% from the entry | 5% |
| Per pair, open pairs | at most 14%, seven | at most 10%, six |
| A full stop-out costs | about 0.42% of the account | about 0.5% |
| Backtest costs | 0.03% per side, 2.5% a year of financing | 0.15% per side, 6% a year |

The exotic currencies trade less and most of them swing more than the majors, so their spreads are wider and the stop needs more room. The Turkish lira is left out on purpose: its interest rate is so far above the dollar's that holding the dollar against it would cost a large share of the position in financing every year. OANDA refuses orders for any pair your account doesn't offer, and the dashboard shows the refusal.

Four things differ from stocks:

- **No leverage.** US rules let OANDA lend up to 50 times the deposit on the major pairs. The app never uses it: buying power is equity minus what's held or on order, and a short is paid for in full like a long. Financing comes out of the same money, so with every slot filled, the free cash can slip a little below zero; then no new position starts until there's room.
- **The stop rides with the trade.** Each entry is a limit order with a stop-loss on fill, and each exit is a reduce-only order that can't open a position on the other side. Closing a trade cancels its stop, so the app doesn't cancel the stop first: the position stays protected until the exit fills.
- **Financing every night.** A position open at 5 pm ET is charged or credited the interest gap between its two currencies plus OANDA's fee. It can be a credit, but backtests always charge it, long or short, and the benchmark line doesn't pay it, so Gate 1 is a little harder for forex than it looks.
- **Short selling, if you switch it on.** It's off by default (`ALLOW_SHORTS=false`). On, the trend rule becomes two-sided: a pair that closes below its 200-day average is sold short, with its stop above the entry, and bought back when the signal ends. A long whose signal turns short closes first; the short opens on a later day. Every short still needs your approval. Stocks never sell short here (that takes a margin account and the loss has no ceiling), and Alpaca doesn't short crypto.

US accounts close trades oldest first and can't hold a long and a short in one pair; the book holds one trade per pair, long or short, so neither rule gets in its way. For live forex, open a live OANDA account, put its token in `.env.forex`, and pass Gate 5 for this book before you scale.

The forex book reads only its own file, like the crypto book. In Docker, mount it (`- ./.env.forex:/app/.env.forex:ro`), set `FOREX_ENV_FILE=../.env.forex` in `.env`, and give it its own database, such as `DATABASE_URL=sqlite:///./data/forex.db`.

## Your settings on the dashboard

Each book's tab has a **Your settings** panel: the stop-loss for every book, and for forex the pair set and short selling. Each shows the value the app recommends (8% for stocks, 15% for crypto, 3% for the standard pairs and 5% for the exotic ones).

- **A riskier choice asks first.** A stop wider than recommended, the exotic pairs, or short selling comes back with plain warnings (how much a stop-out could cost, how much smaller positions get once the 1% limit per trade bites, what can go wrong), and only takes effect once you tick that you've read them. A tighter stop, the standard pairs, or switching shorts off just goes through, with a note.
- **What changes.** New orders use the new settings at once. Positions already open keep their stops, and proposals still waiting expire, so the next nightly plan sizes them again. The pair set won't change while you hold pairs that aren't in the new set: close those first.
- **Where it's kept.** In the book's own ledger, so it survives restarts and wins over the settings file. Every change is in the audit log, and Telegram gets a one-line note.
- **Test before real money.** `trader backtest` and `trader gate1` read these choices too, so run Gate 1 again after a change, before you trade real money with it.

The same from the command line: `trader --env-file ../.env.forex settings` shows the choices, and for example `trader --env-file ../.env.forex settings --stop 4 --shorts` changes them, printing the warnings and asking you to confirm (`--yes` skips the question; `--recommended-stop` goes back to the recommendation; `--pairs exotic` picks the pair set).

## Approvals on your phone (Telegram)

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`, and put the token it gives you in `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message, then open `https://api.telegram.org/bot<token>/getUpdates` and copy the number after `"chat":{"id":` into `TELEGRAM_CHAT_ID`.
3. Restart `trader serve` with the scheduler on. Each proposal arrives with Approve and Reject buttons, and only your chat can use them. One bot can serve every book: each button names its account.

## Talk to your account in Claude (optional)

The [Alpaca MCP server](https://github.com/alpacahq/alpaca-mcp-server) lets Claude read your account and market data in a chat. It is a window onto the account, not the trading engine: this app's orders go through its own code and risk checks. Two example configs are in [docs/mcp](docs/mcp):

- `claude_desktop_config.paper.json`: paper keys, every tool.
- `claude_desktop_config.live-readonly.json`: live keys with the `trading` toolset left out, so Claude can look but not trade.

Run the MCP server only on your own computer. Never expose it to the internet.

## Commands

Run these from `backend/` with the virtual environment active. `trader --help` lists them all, and `trader <command> --help` shows each one's options.

| Command | What it does |
|---|---|
| `trader demo` | Replays recent days on made-up prices with the fake broker, for the stock, crypto and forex books |
| `trader serve` | Runs the API and the built dashboard (add `--scheduler` to run the daily jobs) |
| `trader status` | Mode, account, kill switch and equity at a glance |
| `trader run-nightly` | Computes today's signals, recommendations and proposals, and scans the watchlist |
| `trader recommendations` | Shows today's call on every symbol, with its reason |
| `trader scan` | Ranks the watchlist again and shows the ideas |
| `trader proposals`, `trader approve ID`, `trader reject ID` | Reviews and decides proposals |
| `trader submit` | Sends approved proposals (stocks: only inside the trading window) |
| `trader protect` | Crypto: puts a stop-limit under any position without one and cancels stale orders (stock and forex stops travel with the entry) |
| `trader reconcile` | Runs the broker check, records equity, applies the drawdown limit |
| `trader kill-switch engage --reason "..."`, `trader kill-switch release` | Stops or resumes new orders |
| `trader settings` | Shows or changes the dashboard's choices: `--stop`, and for forex `--pairs` and `--shorts/--no-shorts` (riskier choices ask first) |
| `trader fetch-data` | Saves daily closes to a CSV: adjusted closes from Alpaca, or OANDA's candles for forex |
| `trader backtest` | Backtests on the development years, 2016 to 2022 |
| `trader smoke-test`, `gate1`, `gate2`, `compare-ab`, `gate4`, `gate5` | Gates 0 to 5 |
| `trader --env-file ../.env.b <command>` | Runs any command with another account's settings, such as `../.env.crypto` or `../.env.forex` |

## Settings

Settings come from environment variables or a `.env` file in the repository root or in `backend/`. [.env.example](.env.example) lists every setting with its safe default. Relative paths (the SQLite file, `data/`, `reports/`) resolve from `backend/`, so run commands from there.

To scan different symbols, set `WATCHLIST`, for example `WATCHLIST=XLK,XLE,AAPL,MSFT`. `ASSET_CLASS=crypto` turns a settings file into a crypto book with its own defaults ([.env.crypto.example](.env.crypto.example)), and `CRYPTO_ENV_FILE` runs that book beside the stock one. `ASSET_CLASS=forex` and `FOREX_ENV_FILE` do the same for the forex book ([.env.forex.example](.env.forex.example)). The lessons live in `frontend/src/learn/lessons/` as Markdown files, so you can edit or add to them.

Each account keeps its own database. The first time the app opens a database, it records which mode and account it belongs to, and from then on it refuses to open it with other settings. Demo, paper and live records can't mix.

## Safety

- **Safe defaults.** Fake broker, made-up prices, paper mode, and every order waits for your approval.
- **Live needs three deliberate settings.** The app refuses to start with `TRADING_MODE=live` unless `LIVE_TRADING_CONFIRMED=true` and the book's real broker is set: `BROKER=alpaca` for stocks and crypto, `BROKER=oanda` for forex. A stock or crypto book can't point at OANDA, nor the forex book at Alpaca.
- **Limits in code.** At most 1% of equity at risk per trade, a stop 8% below each entry, no new position over 10% of equity, at most 8 open positions and 10 orders a day, no new entries after a 2% daily loss, the kill switch at 10% below the peak, and no orders in the first or last 15 minutes of the session. The crypto book uses the same checks with its own values (a 15% stop, 5% per coin, no session window), and so does the forex book (a 3% stop and 14% per pair on the standard pairs, a 5% stop and 10% on the exotic ones, no borrowed money, no orders around the 5 pm ET close).
- **Short selling is forex only, and off until you switch it on.** The risk engine refuses a short entry while it's off, every short needs a stop above its entry, and an exit can never open a position on the other side.
- **Stops live at the broker.** Stock entries are sent as one-triggers-other orders, so the stop exists at Alpaca as soon as the entry fills. Crypto entries get a stop-limit seconds after they fill, and a job checks every 5 minutes that each position has one. Forex entries carry a stop-loss that OANDA attaches to the trade as it opens.
- **Separate ledgers.** Each database belongs to one mode and account, so demo, paper and live records never mix.
- **No double orders.** Each signal gets a unique client order ID (for example `tpA-20261113-SPY-buy`, `tpC-20261113-BTCUSD-buy` or `tpF-20261113-EURUSD-buy`), and the broker check flags any order the ledger doesn't know.
- **Kill switch.** On the dashboard, on the command line, and automatic at the drawdown limit. Releasing it takes a deliberate confirmation (typing RELEASE on the dashboard).
- **The AI can only say no.** In veto mode it can block an entry; it can never create or enlarge an order.
- **Keys stay local.** They live only in `.env`, which git ignores. Set `API_TOKEN` before the API is reachable from any other machine.

## Run it on a server (Docker)

```bash
cp .env.example .env               # set BROKER, your keys and API_TOKEN
docker compose up -d --build
docker compose exec app trader status
```

This starts Postgres and the app with the scheduler on. The dashboard is at http://127.0.0.1:8000 on that machine. To reach it from elsewhere, put it behind an HTTPS reverse proxy such as Caddy or nginx, and set `API_TOKEN`.

Set `BROKER` and your keys before the first start, and set `POSTGRES_PASSWORD` in `.env` too. The database remembers which account it belongs to, so switching from the demo to Alpaca later means starting a fresh database: `docker compose down -v` deletes all the app's data.

## Project layout

```
backend/
  src/trader/
    strategies/   trend and momentum rules, pure functions of prices
    planner.py    target weights to orders, shared by live trading and backtests
    assets.py     whole shares for stocks, each crypto pair's order sizes and price steps, currency units
    forex.py      forex hours (Sunday to Friday, 5 pm New York) and OANDA's pair names
    risk/         the limits and the order checks
    broker/       Alpaca (alpaca-py), OANDA (its v20 REST API) and the fake demo broker
    data/         daily closes from Alpaca (stocks and crypto), OANDA (forex), a CSV, or made-up prices
    backtest/     backtester, metrics and Gate 1
    services/     signals, recommendations, scanner, sending, crypto stops, broker check, kill switch, approvals, Learn progress, gates
    ai/           the optional AI research desk (TradingAgents adapter)
    notify/       Telegram approvals
    api/          the FastAPI routes behind the dashboard
    cli.py        the trader command
  tests/          unit, end-to-end and live-versus-backtest parity tests
frontend/         React + Vite dashboard; the Learn lessons are in src/learn/
docs/             architecture, gates and MCP configs
```

## Development

```bash
cd backend && pytest && ruff check . && ruff format --check .
cd frontend && npm run build        # type-checks, then builds
```

`make check` runs the same steps. GitHub Actions runs them on every push to `main` and on every pull request. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains how the pieces fit together.

## Put it on GitHub

```bash
cd lajan-sere
git init -b main
git add .
git commit -m "Initial commit"
gh repo create lajan-sere --private --source . --push
```

Without the GitHub CLI, create an empty private repository on github.com, then run `git remote add origin https://github.com/<you>/lajan-sere.git` and `git push -u origin main`. Keep the repository private: it describes your strategy and risk settings. The `.gitignore` already keeps `.env`, databases and reports out.

## Disclaimer

Trading carries a risk of loss, and backtested or paper results don't guarantee live results. This software is for managing your own account and is not investment advice. Offering it to other people is a separate decision that needs a regulatory and licensing review first.
