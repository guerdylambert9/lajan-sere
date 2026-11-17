"""Command line interface. Run `trader --help` for the list of commands."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from trader import __version__
from trader.assets import fmt_price, fmt_qty

if TYPE_CHECKING:
    from trader.config import Settings
    from trader.services.context import AppContext

app = typer.Typer(
    help="Lajan Sere: backtests, gates, the nightly pipeline, execution and the dashboard API.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show debug logs.")] = False,
    env_file: Annotated[
        Path | None,
        typer.Option(
            "--env-file",
            help="Read settings from this file instead of .env, e.g. ../.env.b for paper account B.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
) -> None:
    if env_file is not None:
        from trader.config import ENV_FILE_VAR, get_settings

        os.environ[ENV_FILE_VAR] = str(env_file)
        get_settings.cache_clear()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "apscheduler", "urllib3", "trader.notify"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ------------------------------------------------------------------------- helpers


def _settings() -> Settings:
    """This book's settings with the dashboard's choices on top (stop-loss, pairs, short selling),
    so backtests and gates test what the book trades."""
    from trader.config import get_settings
    from trader.preferences import effective

    return effective(get_settings())


def _strategy(settings: Settings, name: str | None = None) -> Any:
    from trader.strategies import get_strategy

    chosen = name or settings.strategy
    return get_strategy(chosen, shorts=settings.allow_shorts and chosen == "trend")


def _context(settings: Settings | None = None) -> AppContext:
    from trader.db import DatabaseDriverError
    from trader.ledger import LedgerOwnerError
    from trader.services.context import build_context

    try:
        return build_context(settings)
    except (LedgerOwnerError, DatabaseDriverError) as exc:
        _fail(str(exc))


def _extra_settings(settings: Settings, crypto: bool = True, forex: bool = True) -> dict[str, Settings]:
    """The crypto and forex books that run beside this one: CRYPTO_ENV_FILE's and
    FOREX_ENV_FILE's, or the demo's."""
    from trader.services.context import extra_book_settings

    try:
        books = extra_book_settings(settings)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))
    wanted = {"crypto": crypto, "forex": forex}
    return {str(kind): book for kind, book in books.items() if wanted.get(str(kind), False)}


def _fail(message: str) -> NoReturn:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=1)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _today_ny() -> date:
    from trader.utils import NY

    return datetime.now(NY).date()


def _load_closes(settings: Settings, start: date, end: date, extra: tuple[str, ...] = ()) -> pd.DataFrame:
    from trader.data import get_bar_source

    symbols = list(dict.fromkeys([*settings.universe_list, *extra, settings.benchmark_symbol]))
    closes = get_bar_source(settings).get_closes(symbols, start, end)
    if closes.empty:
        _fail(f"No price data between {start} and {end}.")
    return closes


def _save_report(settings: Settings, name: str, payload: dict[str, Any]) -> Path:
    path = Path(settings.reports_dir) / f"{name}-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def _config(settings: Settings, cost_bps: float, **values: Any) -> Any:
    """Backtest settings: the cost per side, plus overnight financing for a forex book."""
    from trader.backtest import BacktestConfig

    return BacktestConfig(cost_bps=cost_bps, financing_bps_per_year=settings.financing_bps_per_year, **values)


def _development_backtest(
    settings: Settings,
    strategy: Any,
    start_day: date,
    end_day: date,
    lag: int,
    cost_bps: float,
    capital: float,
) -> tuple[Any, dict[str, Any]]:
    from trader.backtest import backtest_report, run_backtest
    from trader.risk.limits import RiskLimits

    closes = _load_closes(
        settings, start_day - timedelta(days=strategy.history_days()), end_day, strategy.extra_symbols()
    )
    limits = RiskLimits.from_settings(settings)
    result = run_backtest(
        closes,
        strategy,
        limits,
        _config(settings, cost_bps, initial_capital=capital, lag=lag),
        settings.universe_list,
    )
    report = backtest_report(
        result,
        closes,
        settings.benchmark_symbol,
        limits,
        start=pd.Timestamp(start_day),
        end=pd.Timestamp(end_day),
    )
    return result, report


def _checks_table(title: str, checks: list[Any]) -> Table:
    table = Table(title=title)
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Detail")
    for check in checks:
        table.add_row(check.name, "[green]PASS[/green]" if check.passed else "[red]FAIL[/red]", check.detail)
    return table


def _finish_gate(settings: Settings, name: str, report: Any) -> None:
    console.print(_checks_table(f"{name} checks", report.checks))
    console.print(
        f"[green]{name.upper()} PASSED[/green]" if report.passed else f"[red]{name.upper()} FAILED[/red]"
    )
    path = _save_report(settings, name.lower().replace(" ", ""), report.to_dict())
    console.print(f"Saved {path}")
    raise typer.Exit(code=0 if report.passed else 1)


def _print_json(payload: Any) -> None:
    console.print_json(json.dumps(payload, default=str))


def _performance_table(title: str, strategy: dict[str, Any], benchmark: dict[str, Any]) -> Table:
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Strategy", justify="right")
    table.add_column(benchmark.get("symbol", "Benchmark"), justify="right")
    rows = [
        ("Total return", "total_return", _pct),
        ("CAGR", "cagr", _pct),
        ("Volatility", "volatility", _pct),
        ("Sharpe", "sharpe", _num),
        ("Sortino", "sortino", _num),
        ("Max drawdown", "max_drawdown", _pct),
        ("Calmar (CAGR / max drawdown)", "calmar", _num),
    ]
    for label, key, fmt in rows:
        table.add_row(label, fmt(strategy.get(key)), fmt(benchmark.get(key)))
    return table


# ------------------------------------------------------------------------- commands


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"trader {__version__}")


@app.command("init-db")
def init_db() -> None:
    """Create the ledger tables (safe to run more than once)."""
    _context()
    console.print("Ledger tables are ready.")


@app.command()
def status() -> None:
    """Mode, kill switch and account at a glance."""
    from trader.services import killswitch
    from trader.services.account import load_account_state

    ctx = _context()
    settings = ctx.settings
    with ctx.session() as session:
        kill = killswitch.state(session)
        account = load_account_state(ctx, session)
    console.print(
        f"Mode: [bold]{settings.mode_label}[/bold]  book={settings.asset_class}  account={settings.account_label}  "
        f"broker={settings.broker}  dry_run={settings.dry_run}"
    )
    console.print(f"Strategy: {ctx.strategy.describe()}  universe={','.join(settings.universe_list)}")
    console.print(
        f"Kill switch: {'[red]ENGAGED[/red] ' + str(kill.get('reason')) if kill.get('engaged') else 'off'}"
    )
    console.print(
        f"Equity ${account.equity:,.2f}  cash ${account.cash:,.2f}  day {account.day_pnl_pct:+.2f}%  "
        f"drawdown {account.drawdown_pct:.2f}%  positions {len(account.held_symbols())}"
    )


@app.command("fetch-data")
def fetch_data(
    start: Annotated[str, typer.Option(help="First date to download.")] = "2016-01-01",
    out: Annotated[str | None, typer.Option(help="CSV path (default: CSV_PATH).")] = None,
) -> None:
    """Download daily closes (Alpaca, or OANDA for forex) into a CSV for offline backtests (DATA_SOURCE=csv)."""
    from trader.data import BarSource, save_closes

    settings = _settings()
    source: BarSource
    if settings.is_forex:
        from trader.data.oanda_source import OandaBarSource

        try:
            source = OandaBarSource(settings.oanda_api_token, live=settings.is_live)
        except ValueError as exc:
            _fail(str(exc))
    elif settings.is_crypto:
        from trader.data.alpaca_crypto_source import AlpacaCryptoBarSource

        source = AlpacaCryptoBarSource(settings.alpaca_api_key, settings.alpaca_secret_key)
    else:
        from trader.data.alpaca_source import AlpacaBarSource

        source = AlpacaBarSource(
            settings.alpaca_api_key, settings.alpaca_secret_key, settings.alpaca_data_feed
        )
    symbols = list(
        dict.fromkeys(
            [*settings.universe_list, *_strategy(settings).extra_symbols(), settings.benchmark_symbol]
        )
    )
    closes = source.get_closes(symbols, date.fromisoformat(start), _today_ny())
    if closes.empty:
        _fail(f"{'OANDA' if settings.is_forex else 'Alpaca'} returned no bars. Check your keys and symbols.")
    path = save_closes(closes, out or settings.csv_path)
    console.print(
        f"Saved {len(closes)} days x {len(closes.columns)} symbols "
        f"({closes.index[0].date()} to {closes.index[-1].date()}) to {path}"
    )


@app.command()
def backtest(
    strategy: Annotated[str | None, typer.Option(help="Strategy name (default: STRATEGY).")] = None,
    start: Annotated[str, typer.Option(help="First day of the test window.")] = "2016-01-01",
    end: Annotated[str, typer.Option(help="Last day; keep it before the holdout.")] = "2022-12-31",
    lag: Annotated[int, typer.Option(help="1 = trade at the signal's close, 2 = one day later.")] = 1,
    cost_bps: Annotated[
        float | None, typer.Option(help="Cost per side in basis points (default: COST_BPS).")
    ] = None,
    capital: Annotated[float, typer.Option(help="Starting capital.")] = 100_000.0,
) -> None:
    """Backtest on the development years only. The holdout stays untouched for Gate 1."""
    from trader.services.recommendations import save_track_record

    settings = _settings()
    cost_bps = settings.cost_bps if cost_bps is None else cost_bps
    chosen = _strategy(settings, strategy)
    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    result, report = _development_backtest(settings, chosen, start_day, end_day, lag, cost_bps, capital)

    window = report["window"]
    console.print(
        _performance_table(
            f"{chosen!r}  {window['start']} to {window['end']}  (lag {lag}, {cost_bps:g} bps per side)",
            report["performance"],
            report["benchmark"],
        )
    )
    trades = report["trades"]
    console.print(
        f"Closed trades {trades['round_trips']}  win rate {_pct(trades['win_rate'])}  "
        f"avg win {_num(trades['avg_win_pct'])}%  avg loss {_num(trades['avg_loss_pct'])}%  "
        f"stopped out {trades['stopped_out']}  average invested {report['avg_exposure']:.0%}"
    )
    checks = report["kill_switch_check"]
    console.print(
        f"The drawdown kill switch would have fired {checks['drawdown_limit_breaches']} time(s); "
        f"the daily loss limit on {checks['daily_loss_limit_days']} day(s)."
    )
    path = _save_report(settings, f"backtest-{chosen.name}", report)
    result.equity.loc[pd.Timestamp(start_day) :].to_csv(path.with_suffix(".equity.csv"))
    console.print(f"Saved {path}")
    with _context().session() as session:  # the dashboard shows this record on every call
        save_track_record(session, report, str(settings.data_source))


@app.command()
def gate1(
    strategy: Annotated[str | None, typer.Option(help="Strategy name (default: STRATEGY).")] = None,
    holdout_start: Annotated[str, typer.Option(help="First day of the held-out years.")] = "2023-01-01",
    start: Annotated[str, typer.Option(help="First day of data to use.")] = "2016-01-01",
    cost_bps: Annotated[
        float | None, typer.Option(help="Cost per side in basis points (default: COST_BPS).")
    ] = None,
    min_calmar_ratio: Annotated[
        float, typer.Option(help="Holdout Calmar must be at least this x the benchmark's.")
    ] = 1.0,
    max_drawdown: Annotated[float, typer.Option(help="Worst holdout drawdown allowed, in percent.")] = 25.0,
    min_trades: Annotated[int, typer.Option(help="Closed trades needed over the whole run.")] = 30,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Gate 1: test the strategy on the held-out years. Run it once per idea."""
    from trader.backtest import Gate1Criteria, evaluate_gate1, log_holdout_use
    from trader.risk.limits import RiskLimits

    settings = _settings()
    cost_bps = settings.cost_bps if cost_bps is None else cost_bps
    chosen = _strategy(settings, strategy)
    if not yes:
        typer.confirm(
            "Gate 1 looks at the holdout. Each extra look makes a pass less trustworthy. Run it now?",
            abort=True,
        )
    closes = _load_closes(
        settings,
        date.fromisoformat(start) - timedelta(days=chosen.history_days()),
        _today_ny(),
        chosen.extra_symbols(),
    )
    criteria = Gate1Criteria(min_calmar_ratio, max_drawdown, min_trades)
    report = evaluate_gate1(
        closes,
        chosen,
        RiskLimits.from_settings(settings),
        settings.benchmark_symbol,
        holdout_start,
        _config(settings, cost_bps),
        criteria,
        settings.universe_list,
    )
    earlier = log_holdout_use(settings.reports_dir, report)

    holdout = report.holdout
    console.print(
        _performance_table(
            f"Gate 1 holdout {holdout['start']} to {holdout['end']}: {chosen!r}",
            holdout["strategy"],
            holdout["benchmark"],
        )
    )
    console.print(_checks_table("Gate 1 checks", report.checks))
    if earlier:
        console.print(
            f"[yellow]Note: this is look #{earlier + 1} at the holdout for '{chosen.name}'. "
            "Treat a pass with extra suspicion.[/yellow]"
        )
    verdict = "[green]GATE 1 PASSED[/green]" if report.passed else "[red]GATE 1 FAILED[/red]"
    console.print(verdict)
    path = _save_report(settings, f"gate1-{chosen.name}", report.to_dict())
    console.print(f"Saved {path}")
    from trader.services.recommendations import save_gate1

    with _context().session() as session:
        save_gate1(session, report, _today_ny(), str(settings.data_source))
    raise typer.Exit(code=0 if report.passed else 1)


@app.command()
def gate2(
    days: Annotated[int, typer.Option(help="Weekdays in a row that need a clean broker check.")] = 10,
) -> None:
    """Gate 2: clean broker checks on paper for ten weekdays, and the kill switch tested."""
    from trader.services.gates import Gate2Criteria, evaluate_gate2

    settings = _settings()
    ctx = _context()
    with ctx.session() as session:
        report = evaluate_gate2(session, settings, ctx.today(), Gate2Criteria(days=days))
    _finish_gate(settings, "Gate 2", report)


@app.command()
def gate4(
    weeks: Annotated[int, typer.Option(help="Weeks of paper results to judge.")] = 12,
    start: Annotated[str, typer.Option(help="First day of backtest data for the ranges.")] = "2016-01-01",
    cost_bps: Annotated[
        float | None, typer.Option(help="Cost per side in basis points (default: COST_BPS).")
    ] = None,
) -> None:
    """Gate 4: are the last twelve weeks of paper results inside the backtest's ranges?"""
    from trader.risk.limits import RiskLimits
    from trader.services.gates import Gate4Criteria, evaluate_gate4

    settings = _settings()
    cost_bps = settings.cost_bps if cost_bps is None else cost_bps
    chosen = _strategy(settings)
    first = date.fromisoformat(start) - timedelta(days=chosen.history_days())
    ctx = _context()
    with ctx.session() as session:
        report = evaluate_gate4(
            session,
            settings,
            lambda end: _load_closes(settings, first, end, chosen.extra_symbols()),
            chosen,
            RiskLimits.from_settings(settings),
            Gate4Criteria(weeks=weeks),
            _config(settings, cost_bps),
        )
    _finish_gate(settings, "Gate 4", report)


@app.command()
def gate5(
    paper: Annotated[str, typer.Option(help="Database URL of the paper account running the same rules.")],
    paper_label: Annotated[str, typer.Option(help="ACCOUNT_LABEL used by the paper account.")] = "A",
    min_days: Annotated[
        int | None,
        typer.Option(help="Shared days needed (default about 3 months: 63 weekdays, or 91 days for crypto)."),
    ] = None,
) -> None:
    """Gate 5: run with the live settings; does live track paper closely enough to add money?"""
    from trader.services.gates import Gate5Criteria, evaluate_gate5

    settings = _settings()
    min_days = min_days or (91 if settings.is_crypto else 63)
    report = evaluate_gate5(settings, paper, paper_label, Gate5Criteria(min_days=min_days))
    _finish_gate(settings, "Gate 5", report)


@app.command()
def scan() -> None:
    """Rank the watchlist now and show the ideas. Ideas only: they never become orders by themselves."""
    from trader.services.scanner import run_scan

    result = run_scan(_context())
    if not result["rows"]:
        _fail("No prices for the watchlist. Check WATCHLIST and DATA_SOURCE.")
    table = Table(title=f"Watchlist scan for {result['as_of']} (untested ideas)")
    for column in ("Rank", "Symbol", "Idea", "12-1 return", "vs 200-day", "Entry", "Stop", "Shares"):
        table.add_column(column)
    labels = {"buy_idea": "Buy idea", "watch": "Watch", "skip": "Skip", "no_data": "No data"}
    for row in result["rows"]:
        table.add_row(
            str(row.get("rank") or "-"),
            row["symbol"],
            labels[row["label"]],
            _pct(row.get("momentum")),
            _pct(row.get("trend_gap")),
            _num(row.get("entry")),
            _num(row.get("stop")),
            str(row.get("qty", "-")),
        )
    console.print(table)
    console.print(result["how_to_test"])


@app.command("settings")
def settings_command(
    stop: Annotated[
        float | None, typer.Option(help="Stop-loss in percent below the entry (above it for a short).")
    ] = None,
    recommended_stop: Annotated[
        bool, typer.Option("--recommended-stop", help="Go back to the recommended stop-loss.")
    ] = False,
    pairs: Annotated[str | None, typer.Option(help="Forex: the standard or the exotic pairs.")] = None,
    shorts: Annotated[
        bool | None, typer.Option("--shorts/--no-shorts", help="Forex: allow short selling.")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Accept the warnings without asking.")] = False,
) -> None:
    """Show or change the dashboard's choices: the stop-loss, and for forex the pairs and short
    selling. Pass --env-file to pick the book (for example ../.env.forex)."""
    from trader import preferences

    ctx = _context()
    changes: dict[str, Any] = {}
    if recommended_stop:
        changes["stop_loss_pct"] = None
    elif stop is not None:
        changes["stop_loss_pct"] = stop
    if pairs is not None:
        changes["pair_set"] = pairs.lower()
    if shorts is not None:
        changes["allow_shorts"] = shorts

    def show_notices(notices: list[Any]) -> None:
        for notice in notices:
            colour = "yellow" if notice.level == "warning" else "cyan"
            console.print(f"[{colour}]{notice.title}[/{colour}]")
            for line in notice.lines:
                console.print(f"  - {line}")

    if changes:
        result = preferences.update(ctx, changes)
        if result.status == "needs_confirm":
            show_notices(result.notices)
            if not yes and not typer.confirm("Make the change?", default=False):
                _fail("Nothing changed.")
            result = preferences.update(ctx, changes, confirm=True)
        if result.status in ("invalid", "blocked"):
            _fail(result.message)
        if result.status == "applied":
            show_notices([n for n in result.notices if n.level == "info"])
        console.print(result.message)

    data = preferences.view(ctx)
    allowed = f"allowed {data['stop_range'][0]:g}-{data['stop_range'][1]:g}%"
    if data["stop_source"] == "recommended":
        where = f"the recommended stop; {allowed}"
    else:
        origin = "set on the dashboard" if data["stop_source"] == "dashboard" else "from the settings file"
        where = f"{origin}; recommended {data['recommended_stop_loss_pct']:g}%, {allowed}"
    console.print(
        f"[bold]{data['book'].capitalize()} book[/bold]: stop-loss {data['stop_loss_pct']:g}% ({where}). "
        f"A full stop-out costs about {data['max_loss_per_position_pct']:.2f}% of the account."
    )
    forex = data["forex"]
    if forex:
        console.print(
            f"Pairs: {forex['pair_set']} ({', '.join(forex['pairs'])}). "
            f"Short selling: {'on' if forex['allow_shorts'] else 'off'}."
        )
    if not changes:
        show_notices([preferences.Notice(**n) for n in data["notes"]])


CALL_LABELS = {
    "buy": "Buy",
    "sell": "Sell",
    "hold": "Hold",
    "stay_out": "Stay out",
    "short": "Sell short",
    "hold_short": "Hold short",
    "cover": "Buy to cover",
}


@app.command()
def recommendations() -> None:
    """Show today's call on every symbol: buy, sell, hold or stay out (forex with short selling on:
    sell short, hold short or buy to cover), with the reason."""
    from trader.services.recommendations import build_recommendations

    ctx = _context()
    with ctx.session() as session:
        data = build_recommendations(ctx, session)
    if not data["items"]:
        _fail("No recommendations yet. Run `trader run-nightly` after the close.")
    console.print(f"[bold]Recommendations for {data['as_of']}[/bold]: {data['rule']}")
    table = Table()
    for column in ("Call", "Symbol", "Reason", "Order or note"):
        table.add_column(column)
    for item in data["items"]:
        proposal = item["proposal"]
        note = item["detail"] or ""
        symbol = item["symbol"]
        if proposal and not note:
            note = (
                f"#{proposal['id']} {proposal['action']} {fmt_qty(proposal['qty'])} @ "
                f"{fmt_price(proposal['limit_price'], symbol)} ({proposal['status']})"
            )
        elif item["position"] and item["position"]["stop_price"]:
            note = note or f"stop {fmt_price(item['position']['stop_price'], symbol)}"
        table.add_row(CALL_LABELS[item["call"]], item["symbol"], item["reason"], note)
    console.print(table)


@app.command("run-nightly")
def run_nightly_command(
    as_of: Annotated[str | None, typer.Option(help="Signal date (default: today).")] = None,
    force: Annotated[
        bool, typer.Option(help="Run even if today's bar is missing or it already ran.")
    ] = False,
) -> None:
    """Compute today's signals and create proposals for your approval."""
    from trader.services.pipeline import run_nightly

    result = run_nightly(_context(), date.fromisoformat(as_of) if as_of else None, force=force)
    _print_json(asdict(result))


@app.command()
def submit() -> None:
    """Send approved proposals to the broker (stocks: only inside the trading window)."""
    from trader.services.execution import submit_approved

    _print_json(asdict(submit_approved(_context())))


@app.command()
def protect() -> None:
    """Crypto: put a stop-limit under each new position and cancel orders that sat unfilled.
    (Stock and forex entries carry their stops with them.)"""
    from trader.services.protect import protect as run_protect

    _print_json(asdict(run_protect(_context())))


@app.command()
def reconcile() -> None:
    """Compare the ledger with the broker, record equity, check the drawdown limit."""
    from trader.services.reconcile import reconcile as run_reconcile

    _print_json(asdict(run_reconcile(_context())))


@app.command()
def proposals(status: Annotated[str, typer.Option(help="Filter by status.")] = "pending") -> None:
    """List proposals (pending by default)."""
    from trader import ledger
    from trader.models import action_of

    ctx = _context()
    with ctx.session() as session:
        rows = ledger.list_proposals(session, ctx.label, status=status or None)
        table = Table(title=f"Proposals ({status or 'all'})")
        for column in ("ID", "Date", "Side", "Qty", "Symbol", "Limit", "Stop", "Status", "Notes"):
            table.add_column(column)
        for row in rows:
            notes = ", ".join(v.get("code", "") for v in row.violations or []) or row.reason
            table.add_row(
                str(row.id),
                str(row.as_of),
                action_of(row.side, row.kind),
                fmt_qty(row.qty),
                row.symbol,
                fmt_price(row.limit_price, row.symbol),
                fmt_price(row.stop_price, row.symbol) if row.stop_price else "-",
                row.status,
                notes,
            )
    console.print(table)


def _decide(proposal_id: int, approve: bool) -> None:
    from trader.services.approvals import InvalidTransitionError, ProposalNotFoundError, decide_proposal

    ctx = _context()
    with ctx.session() as session:
        try:
            row = decide_proposal(session, proposal_id, approve, by="cli", label=ctx.label, at=ctx.now())
        except (ProposalNotFoundError, InvalidTransitionError) as exc:
            _fail(str(exc))
            return
        console.print(f"Proposal #{row.id} is now {row.status}.")


@app.command()
def approve(proposal_id: int) -> None:
    """Approve a pending proposal."""
    _decide(proposal_id, True)


@app.command()
def reject(proposal_id: int) -> None:
    """Reject a pending proposal."""
    _decide(proposal_id, False)


@app.command("kill-switch")
def kill_switch(
    action: Annotated[str, typer.Argument(help="engage or release")],
    reason: Annotated[str, typer.Option(help="Why you are engaging it.")] = "Engaged from the CLI",
) -> None:
    """Engage (cancel pending entries, block new orders) or release the kill switch."""
    from trader.services import killswitch

    ctx = _context()
    with ctx.session() as session:
        if action == "engage":
            canceled = killswitch.engage(ctx, session, reason, by="cli")
            console.print(
                f"[red]Kill switch engaged.[/red] Canceled {canceled} open order(s); protective stops kept."
            )
        elif action == "release":
            typer.confirm("Release the kill switch and allow new orders?", abort=True)
            killswitch.release(ctx, session, by="cli")
            console.print("Kill switch released.")
        else:
            _fail("Use `engage` or `release`.")


@app.command("smoke-test")
def smoke_test() -> None:
    """Gate 0: place, read back and cancel one paper order through your own code."""
    from trader.assets import AssetRules
    from trader.broker import get_broker
    from trader.config import REAL_BROKER
    from trader.models import IntentKind, OrderIntent, Side

    settings = _settings()
    real = REAL_BROKER[settings.asset_class]
    if settings.broker != real or settings.is_live:
        account = "OANDA practice" if settings.is_forex else "Alpaca PAPER"
        _fail(f"Gate 0 runs against the {account} account: set BROKER={real} and TRADING_MODE=paper.")
    broker = get_broker(settings)
    steps: list[tuple[str, bool, str]] = []

    account = broker.get_account()
    steps.append(("Read the account", True, f"equity ${account.equity:,.2f}"))
    clock = broker.clock()
    steps.append(("Read the market clock", True, f"market open: {clock.is_open}"))
    symbol = settings.benchmark_symbol
    price = broker.latest_price(symbol)
    steps.append(("Read the latest price", price > 0, f"{symbol} {fmt_price(price, symbol)}"))

    lots = getattr(broker, "lots", None)
    paired = settings.is_crypto or settings.is_forex
    rules = AssetRules(
        crypto=settings.is_crypto, forex=settings.is_forex, lots=lots([symbol]) if paired and lots else {}
    )
    qty = rules.lot(symbol).min_qty  # 1 share, the smallest crypto order, or 1 unit of a currency
    # Far below the market, so it cannot fill (a currency moves less, so 10% is far enough).
    limit = rules.price_down(symbol, price * (0.9 if settings.is_forex else 0.5))
    client_id = f"{settings.client_order_prefix}-smoke-{datetime.now(UTC):%Y%m%d%H%M%S}"
    intent = OrderIntent(
        symbol=symbol,
        side=Side.BUY,
        kind=IntentKind.ENTRY,
        qty=qty,
        limit_price=limit,
        client_order_id=client_id,
        reason="Gate 0 smoke test",
    )
    order = broker.submit_limit_order(intent)
    steps.append(
        (
            "Place a paper limit order",
            True,
            f"{fmt_qty(qty)} {symbol} @ {fmt_price(limit, symbol)}, status {order.status}",
        )
    )
    found = broker.get_order_by_client_id(client_id)
    steps.append(
        (
            "Read it back by client order ID",
            found is not None and found.id == order.id,
            found.status if found else "missing",
        )
    )
    broker.cancel_order(order.id)
    final = found
    for _ in range(20):
        final = broker.get_order_by_client_id(client_id)
        if final is not None and final.status == "canceled":
            break
        time.sleep(0.5)
    canceled = final is not None and final.status == "canceled"
    steps.append(("Cancel it", canceled, final.status if final else "missing"))

    table = Table(title="Gate 0 smoke test (paper)")
    table.add_column("Step")
    table.add_column("Result")
    table.add_column("Detail")
    for name, ok, detail in steps:
        table.add_row(name, "[green]PASS[/green]" if ok else "[red]FAIL[/red]", detail)
    console.print(table)
    passed = all(ok for _, ok, _ in steps)
    console.print("[green]GATE 0 PASSED[/green]" if passed else "[red]GATE 0 FAILED[/red]")
    raise typer.Exit(code=0 if passed else 1)


def _reset_demo_state(settings: Settings) -> None:
    from sqlalchemy.engine import make_url

    from trader.ledger import ledger_owner

    if settings.database_url.startswith("sqlite"):
        database = make_url(settings.database_url).database
        if database and database != ":memory:" and Path(database).exists():
            owner = ledger_owner(settings.database_url)
            if owner and owner.get("mode") != "DEMO":
                _fail(
                    f"{database} holds the {owner.get('mode')} ledger of account {owner.get('account')}. "
                    "The demo won't reset it; point DATABASE_URL somewhere else or leave it unset."
                )
            Path(database).unlink()
    if settings.fake_broker_state:
        Path(settings.fake_broker_state).unlink(missing_ok=True)


def _run_demo(settings: Settings, days: int, fresh: bool) -> None:
    from trader.services.recommendations import save_track_record
    from trader.services.replay import replay

    if fresh:
        _reset_demo_state(settings)
    ctx = _context(settings)
    book = "stock" if settings.asset_class == "stocks" else str(settings.asset_class)
    end = ctx.bar_date()
    probe = ctx.bars.get_closes([settings.benchmark_symbol], end - timedelta(days=int(days * 1.6) + 10), end)
    sessions = [ts.date() for ts in probe.index if ts.date() <= end]
    if not sessions:
        _fail("No prices are available for the demo window.")
    start = sessions[-min(days, len(sessions))]
    with console.status(f"Replaying {days} days of the {book} demo..."):
        result = replay(ctx, start, end, approve_all=True, leave_last_pending=True)
    console.print(
        f"{book.capitalize()} demo: replayed {result.days} days ({result.start} to {result.end}), "
        f"{result.submitted} orders submitted, {result.stops_filled} stops hit, final equity ${result.final_equity:,.2f}."
    )
    with console.status(f"Backtesting the {book} demo strategy for its track record..."):
        _, report = _development_backtest(
            settings,
            ctx.strategy,
            date(2016, 1, 1),
            date(2022, 12, 31),
            lag=1,
            cost_bps=settings.cost_bps,
            capital=100_000.0,
        )
    with ctx.session() as session:
        save_track_record(session, report, str(settings.data_source))


@app.command()
def demo(
    days: Annotated[int, typer.Option(help="Days to replay.")] = 120,
    fresh: Annotated[bool, typer.Option(help="Start from an empty demo ledger.")] = True,
    crypto: Annotated[
        bool, typer.Option("--crypto/--no-crypto", help="Also fill the Crypto tab, on made-up coin prices.")
    ] = True,
    forex: Annotated[
        bool,
        typer.Option("--forex/--no-forex", help="Also fill the Forex tab, on made-up currency prices."),
    ] = True,
) -> None:
    """Replay the live jobs on synthetic prices with the fake broker, to fill the dashboard."""
    from trader.config import BrokerKind, get_settings

    settings = get_settings()  # each book adds its own dashboard choices (a fresh demo has none)
    if settings.broker != BrokerKind.FAKE:
        _fail("The demo only runs with BROKER=fake.")
    _run_demo(settings, days, fresh)
    for extra in _extra_settings(settings, crypto=crypto, forex=forex).values():
        if extra.broker == BrokerKind.FAKE:
            _run_demo(extra, days, fresh)
    console.print(
        "Next: `trader serve`, then open the dashboard (see README). The last day's proposals wait for you."
    )


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port.")] = 8000,
    scheduler: Annotated[
        bool | None,
        typer.Option(
            "--scheduler/--no-scheduler", help="Run scheduled jobs here (default: ENABLE_SCHEDULER)."
        ),
    ] = None,
    crypto: Annotated[
        bool,
        typer.Option(
            "--crypto/--no-crypto", help="Also run the crypto book (CRYPTO_ENV_FILE, or the demo's)."
        ),
    ] = True,
    forex: Annotated[
        bool,
        typer.Option("--forex/--no-forex", help="Also run the forex book (FOREX_ENV_FILE, or the demo's)."),
    ] = True,
) -> None:
    """Run the dashboard API (and the built dashboard, if present)."""
    import uvicorn

    from trader.api.app import create_app

    ctx = _context()
    extra = {kind: _context(book) for kind, book in _extra_settings(ctx.settings, crypto, forex).items()}
    app_ = create_app(
        ctx, start_background=scheduler, crypto_ctx=extra.get("crypto"), forex_ctx=extra.get("forex")
    )
    uvicorn.run(app_, host=host, port=port, log_level="info")


@app.command("compare-ab")
def compare_ab_command(
    a: Annotated[str, typer.Option(help="Database URL of paper account A (rules only).")],
    b: Annotated[str, typer.Option(help="Database URL of paper account B (rules + AI).")],
    label_a: Annotated[str, typer.Option(help="ACCOUNT_LABEL used by A.")] = "A",
    label_b: Annotated[str, typer.Option(help="ACCOUNT_LABEL used by B.")] = "B",
    min_days: Annotated[int, typer.Option(help="Shared trading days needed (60 is about 12 weeks).")] = 60,
) -> None:
    """Gate 3: does the AI layer beat rules-only after its own costs?"""
    from trader.services.ab_compare import compare_ab

    try:
        result = compare_ab(a, b, label_a, label_b, min_days)
    except ValueError as exc:
        _fail(str(exc))
    console.print(
        _performance_table(
            f"Gate 3: {result['start']} to {result['end']} ({result['days']} days)",
            result["rules_plus_ai"],
            result["rules_only"] | {"symbol": "Rules only (A)"},
        )
    )
    console.print(
        f"AI cost ${result['rules_plus_ai']['ai_cost_usd']:,.2f}, vetoes {result['rules_plus_ai']['ai_vetoes']}. "
        f"Rule: {result['rule']}"
    )
    if not result["enough_days"]:
        console.print(
            f"[yellow]Only {result['days']} shared trading days so far; keep both accounts running.[/yellow]"
        )
    console.print("[green]GATE 3 PASSED[/green]" if result["passed"] else "[red]GATE 3 FAILED[/red]")
    raise typer.Exit(code=0 if result["passed"] else 1)


if __name__ == "__main__":
    app()
