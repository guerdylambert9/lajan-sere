"""Settings, read from environment variables or a .env file.

Safe defaults: paper trading, the in-memory fake broker and synthetic prices. Nothing touches
a real account until you change those settings on purpose, and live trading needs two
explicit flags (TRADING_MODE=live and LIVE_TRADING_CONFIRMED=true).
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trader.assets import is_forex_symbol, split_pair

DEFAULT_UNIVERSE = "SPY,QQQ,IWM,EFA,EEM,TLT,IEF,GLD,DBC,VNQ"
# The 11 Select Sector SPDR ETFs: a fixed list, so a backtest of it has no survivorship bias.
DEFAULT_WATCHLIST = "XLB,XLC,XLE,XLF,XLI,XLK,XLP,XLRE,XLU,XLV,XLY"
# The stock paper desk, used only when STRATEGY is unset. One fully invested position: SPY while
# its close is above its 200-day average, and BIL otherwise. Crypto and forex keep trend.
STOCK_DEFAULTS: dict[str, Any] = {
    "strategy": "spy-trend",
}
# Point this at another settings file to run a second account, e.g. TRADER_ENV_FILE=../.env.b
ENV_FILE_VAR = "TRADER_ENV_FILE"
# The demo's made-up trades go to their own file unless DATABASE_URL is set.
DEMO_DATABASE_URL = "sqlite:///./demo.db"
CRYPTO_DEMO_DATABASE_URL = "sqlite:///./crypto-demo.db"

# Starting values for ASSET_CLASS=crypto (Phase 6). Anything you set yourself wins. The stop
# sits 15% below the entry and its limit 5% below that, so with a 1% loss limit per trade each
# coin gets about 5% of the account.
CRYPTO_DEFAULTS: dict[str, Any] = {
    "account_label": "C",
    "universe": "BTC/USD,ETH/USD",
    "benchmark": "BTC/USD",
    "watchlist": "",
    "stop_loss_pct": 15.0,
    "stop_limit_band_pct": 5.0,
    "max_position_pct": 5.0,
    "max_open_positions": 2,
    "entry_limit_buffer_pct": 0.5,
    "max_gap_pct": 5.0,
    "cost_bps": 35.0,
    "database_url": "sqlite:///./crypto.db",
    "fake_broker_state": "data/fake_broker_crypto.json",
    "csv_path": "data/crypto_closes.csv",
}

FOREX_DEMO_DATABASE_URL = "sqlite:///./forex-demo.db"
# Starting values for ASSET_CLASS=forex (Phase 7). The pairs and their risk settings come from
# the pair set (PAIR_SET, below); anything you set yourself wins.
FOREX_DEFAULTS: dict[str, Any] = {
    "account_label": "F",
    "watchlist": "",
    "database_url": "sqlite:///./forex.db",
    "fake_broker_state": "data/fake_broker_forex.json",
    "csv_path": "data/forex_closes.csv",
}


class PairSet(StrEnum):
    STANDARD = "standard"
    EXOTIC = "exotic"


# The forex book's two ready-made pair sets, each with risk settings to match. Positions are
# fully paid for (no leverage) in both, so each set's slots add up to no more than the account.
#
# standard: the seven majors, the dollar against the euro, pound, yen, Swiss franc and the
# Canadian, Australian and New Zealand dollars. The most traded pairs, with the tightest
# spreads; they move far less than stocks, so the stop sits 3% from the entry and each pair may
# take up to 14% of the account (a stop-out costs about 0.4%).
#
# exotic: the dollar against six emerging-market currencies (Mexican peso, South African rand,
# Polish zloty, Hungarian forint, Czech koruna, Singapore dollar). They swing about twice as
# much, cost more to trade and to hold overnight, and can jump on local news, so the stop is
# wider (5%), each pair gets less (10%), and backtests charge more. The Turkish lira is left
# out: its interest rate is so far above the dollar's that holding the dollar against it costs
# a large share of the position in financing every year, and the lira's long slide keeps a
# trend rule on that side almost all the time.
#
# Financing is the interest a position pays each night; backtests charge a flat yearly rate
# as a cautious stand-in for the real charge, which follows the two currencies' interest rates.
PAIR_SETS: dict[str, dict[str, Any]] = {
    PairSet.STANDARD: {
        "universe": "EUR/USD,GBP/USD,USD/JPY,USD/CHF,USD/CAD,AUD/USD,NZD/USD",
        "benchmark": "EUR/USD",
        "stop_loss_pct": 3.0,
        "max_position_pct": 14.0,
        "max_open_positions": 7,
        "entry_limit_buffer_pct": 0.1,
        "max_gap_pct": 1.0,
        "cost_bps": 3.0,
        "financing_bps_per_year": 250.0,
    },
    PairSet.EXOTIC: {
        "universe": "USD/MXN,USD/ZAR,USD/PLN,USD/HUF,USD/CZK,USD/SGD",
        "benchmark": "USD/MXN",
        "stop_loss_pct": 5.0,
        "max_position_pct": 10.0,
        "max_open_positions": 6,
        "entry_limit_buffer_pct": 0.3,
        "max_gap_pct": 2.0,
        "cost_bps": 15.0,
        "financing_bps_per_year": 600.0,
    },
}
PAIR_SET_FIELDS = frozenset(PAIR_SETS[PairSet.STANDARD])


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class AssetClass(StrEnum):
    STOCKS = "stocks"
    CRYPTO = "crypto"
    FOREX = "forex"


class BrokerKind(StrEnum):
    FAKE = "fake"
    ALPACA = "alpaca"
    OANDA = "oanda"


class DataSourceKind(StrEnum):
    SYNTHETIC = "synthetic"
    CSV = "csv"
    ALPACA = "alpaca"
    OANDA = "oanda"


# Alpaca trades stocks and crypto; forex goes through OANDA (Alpaca has no currency trading).
REAL_BROKER = {
    AssetClass.STOCKS: BrokerKind.ALPACA,
    AssetClass.CRYPTO: BrokerKind.ALPACA,
    AssetClass.FOREX: BrokerKind.OANDA,
}


class AIMode(StrEnum):
    OFF = "off"
    LOG_ONLY = "log_only"
    VETO = "veto"


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _dollar_pair(symbol: str) -> bool:
    """A currency pair with the US dollar on one side: EUR/USD or USD/MXN, not EUR/GBP."""
    pair = split_pair(symbol)
    return is_forex_symbol(symbol) and pair is not None and pair[0] != pair[1] and "USD" in pair


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # What this book trades: stocks and ETFs, crypto pairs or currency pairs (own account and ledger)
    asset_class: AssetClass = AssetClass.STOCKS
    # Run a crypto or forex book next to this one, each from its own settings file (the
    # dashboard's Crypto and Forex tabs)
    crypto_env_file: str = ""
    forex_env_file: str = ""

    # Where orders go
    trading_mode: TradingMode = TradingMode.PAPER
    live_trading_confirmed: bool = False
    dry_run: bool = False
    broker: BrokerKind = BrokerKind.FAKE
    account_label: str = "A"

    # Alpaca
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_data_feed: str = "sip"
    alpaca_latest_feed: str = "iex"

    # OANDA (the forex book): a personal access token and the v20 account ID. TRADING_MODE=paper
    # uses the practice server, live the live one.
    oanda_api_token: str = ""
    oanda_account_id: str = ""
    # Forex only: the pairs it trades (standard or exotic, see PAIR_SETS) and whether it may sell
    # a pair short. Both can also be changed on the dashboard, which wins over this file.
    pair_set: PairSet = PairSet.STANDARD
    allow_shorts: bool = False

    # Data and storage (relative paths resolve from the backend/ folder)
    data_source: DataSourceKind = DataSourceKind.SYNTHETIC
    csv_path: str = "data/closes.csv"
    database_url: str = "sqlite:///./trader.db"  # demo.db when BROKER=fake and this isn't set
    fake_broker_state: str = "data/fake_broker.json"
    reports_dir: str = "reports"
    frontend_dist: str = "../frontend/dist"

    # Strategy. Unset, the stock book uses spy-trend (STOCK_DEFAULTS). Crypto and forex keep
    # trend unless their own file sets STRATEGY. Naming trend, momentum or trend-bil leaves that rule.
    strategy: str = "trend"
    universe: str = DEFAULT_UNIVERSE
    watchlist: str = DEFAULT_WATCHLIST  # the scanner ranks these; ideas only, never orders
    scan_top_n: int = 3
    benchmark: str = "SPY"

    # Risk limits (percentages are 0-100)
    risk_per_trade_pct: float = 1.0
    stop_loss_pct: float = 8.0
    max_position_pct: float = 10.0
    max_open_positions: int = 8
    daily_loss_limit_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    max_orders_per_day: int = 10
    no_trade_after_open_min: int = 15
    no_trade_before_close_min: int = 15
    entry_limit_buffer_pct: float = 0.2
    max_gap_pct: float = 2.0
    stop_limit_band_pct: float = 0.0  # crypto stops are stop-limits: the limit sits this far below the stop
    entry_ttl_minutes: int = 60  # crypto never closes, so unfilled entries are canceled after this
    auto_approve: bool = False

    # Backtests: cost per side in basis points (spread, slippage and fees), and for forex the
    # overnight financing charged on what's held, in basis points a year
    cost_bps: float = 5.0
    financing_bps_per_year: float = 0.0

    # AI research layer (Phase 3)
    ai_mode: AIMode = AIMode.OFF
    ai_researcher: str = "null"
    ai_veto_ratings: str = "underweight,sell"
    ai_max_calls_per_day: int = 5
    ai_cost_per_call_usd: float = 0.0

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # API and scheduler
    api_token: str = ""
    cors_origins: str = "http://localhost:5173"
    enable_scheduler: bool = False
    timezone: str = "America/New_York"

    _provided: frozenset[str] = PrivateAttr(default_factory=frozenset)

    @model_validator(mode="after")
    def _check_live_safety(self) -> Settings:
        if self.trading_mode == TradingMode.LIVE:
            if not self.live_trading_confirmed:
                raise ValueError(
                    "TRADING_MODE=live also needs LIVE_TRADING_CONFIRMED=true. Pass every gate first."
                )
            real = REAL_BROKER[self.asset_class]
            if self.broker != real:
                raise ValueError(f"TRADING_MODE=live requires BROKER={real} for the {self.asset_class} book.")
        return self

    @model_validator(mode="after")
    def _book_defaults(self) -> Settings:
        provided = set(self.model_fields_set)
        self._provided = frozenset(provided)
        defaults = {
            AssetClass.STOCKS: STOCK_DEFAULTS,
            AssetClass.CRYPTO: CRYPTO_DEFAULTS,
            AssetClass.FOREX: FOREX_DEFAULTS,
        }.get(self.asset_class, {})
        if self.asset_class == AssetClass.FOREX:
            defaults = defaults | PAIR_SETS[self.pair_set]
        for name, value in defaults.items():
            if name not in provided:
                setattr(self, name, value)
        if self.broker == BrokerKind.FAKE and "database_url" not in provided:
            # The demo's made-up trades never share a file with a real ledger.
            self.database_url = {
                AssetClass.CRYPTO: CRYPTO_DEMO_DATABASE_URL,
                AssetClass.FOREX: FOREX_DEMO_DATABASE_URL,
            }.get(self.asset_class, DEMO_DATABASE_URL)
        self._check_book()
        return self

    def _check_book(self) -> None:
        """Each book talks to the broker and the price feed that trade its assets."""
        real = REAL_BROKER[self.asset_class]
        if self.broker not in (BrokerKind.FAKE, real):
            raise ValueError(f"The {self.asset_class} book uses BROKER={real} (or fake for the demo).")
        feeds = (DataSourceKind.SYNTHETIC, DataSourceKind.CSV, DataSourceKind(real.value))
        if self.data_source not in feeds:
            raise ValueError(
                f"The {self.asset_class} book reads prices from DATA_SOURCE={real}, csv or synthetic."
            )
        if self.asset_class == AssetClass.FOREX:
            wrong = [s for s in [*self.universe_list, self.benchmark_symbol] if not _dollar_pair(s)]
            if wrong:
                raise ValueError(
                    "The forex book trades currency pairs with the US dollar on one side, like EUR/USD "
                    f"or USD/MXN, so every size and loss is counted in dollars. Not allowed: {', '.join(wrong)}."
                )
        if self.allow_shorts:
            if self.asset_class != AssetClass.FOREX:
                raise ValueError(
                    "ALLOW_SHORTS is for the forex book only: Alpaca doesn't sell crypto short, and this "
                    "app doesn't short stocks (that needs a margin account, and a short can lose more "
                    "than it was worth)."
                )
            if self.strategy != "trend":
                raise ValueError("Short selling works with STRATEGY=trend; the other strategies only buy.")

    @property
    def provided_fields(self) -> frozenset[str]:
        """The settings given in the environment or the settings file (the rest are defaults)."""
        return self._provided

    @property
    def universe_list(self) -> list[str]:
        return [symbol.upper() for symbol in split_csv(self.universe)]

    @property
    def watchlist_list(self) -> list[str]:
        return list(dict.fromkeys(symbol.upper() for symbol in split_csv(self.watchlist)))

    @property
    def benchmark_symbol(self) -> str:
        return self.benchmark.strip().upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return split_csv(self.cors_origins)

    @property
    def ai_veto_rating_set(self) -> set[str]:
        return {rating.lower() for rating in split_csv(self.ai_veto_ratings)}

    @property
    def is_crypto(self) -> bool:
        return self.asset_class == AssetClass.CRYPTO

    @property
    def is_forex(self) -> bool:
        return self.asset_class == AssetClass.FOREX

    @property
    def is_live(self) -> bool:
        return self.trading_mode == TradingMode.LIVE

    @property
    def client_order_prefix(self) -> str:
        return f"tp{self.account_label}"

    @property
    def mode_label(self) -> str:
        if self.broker == BrokerKind.FAKE:
            return "DEMO"
        return "LIVE" if self.is_live else "PAPER"


@lru_cache
def get_settings() -> Settings:
    env_file = os.environ.get(ENV_FILE_VAR)
    if env_file:
        if not Path(env_file).is_file():
            raise FileNotFoundError(f"{ENV_FILE_VAR} points to {env_file}, which does not exist.")
        return Settings(_env_file=env_file)
    return Settings()
