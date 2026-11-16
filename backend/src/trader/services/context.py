"""Everything a job needs, wired from settings (tests swap in fakes)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from trader import forex, ledger, preferences
from trader.ai import AIResearcher, get_researcher
from trader.assets import AssetRules
from trader.broker import Broker, FakeBroker, get_broker
from trader.config import (
    CRYPTO_DEFAULTS,
    CRYPTO_DEMO_DATABASE_URL,
    DEMO_DATABASE_URL,
    FOREX_DEFAULTS,
    FOREX_DEMO_DATABASE_URL,
    AssetClass,
    BrokerKind,
    DataSourceKind,
    Settings,
    get_settings,
)
from trader.data import BarSource, get_bar_source
from trader.db import init_db, make_engine, make_session_factory
from trader.notify import Notifier, get_notifier
from trader.notify.telegram import Buttons
from trader.risk.limits import RiskLimits
from trader.strategies import Strategy, get_strategy
from trader.utils import CT, NY, local_date, utcnow

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: Settings
    session_factory: sessionmaker[Session]
    broker: Broker
    bars: BarSource
    strategy: Strategy
    researcher: AIResearcher
    notifier: Notifier
    now_fn: Callable[[], datetime] = utcnow
    scheduler_running: bool = False
    _rules: AssetRules | None = field(default=None, repr=False)
    # The settings file's values, before the dashboard's choices (trader.preferences) go on top.
    base_settings: Settings = field(default=None, repr=False)  # type: ignore[assignment]
    strategy_from_settings: bool = False  # rebuild the strategy when short selling is switched

    def __post_init__(self) -> None:
        if self.base_settings is None:
            self.base_settings = self.settings

    @property
    def limits(self) -> RiskLimits:
        return RiskLimits.from_settings(self.settings)

    def apply_preferences(self, prefs: preferences.Preferences) -> None:
        """Trade from now on with these dashboard choices on top of the settings file."""
        settings = preferences.apply(self.base_settings, prefs)
        self._rules = None  # the pairs may have changed
        self.settings = settings
        if self.strategy_from_settings:
            self.strategy = get_strategy(settings.strategy, shorts=settings.allow_shorts)

    @property
    def is_crypto(self) -> bool:
        return self.settings.is_crypto

    @property
    def is_forex(self) -> bool:
        return self.settings.is_forex

    @property
    def rules(self) -> AssetRules:
        """Order sizes and price steps: whole shares, or each pair's steps from the broker."""
        if self._rules is not None:
            return self._rules
        lots = {}
        lookup = getattr(self.broker, "lots", None)
        if (self.is_crypto or self.is_forex) and callable(lookup):
            try:
                lots = lookup(dict.fromkeys([*self.settings.universe_list, self.settings.benchmark_symbol]))
            except Exception:
                log.warning("Could not read order sizes from the broker; using defaults for now.")
                return AssetRules(crypto=self.is_crypto, forex=self.is_forex)
        self._rules = AssetRules(crypto=self.is_crypto, forex=self.is_forex, lots=lots)
        return self._rules

    def bar_date(self) -> date:
        """The day of the newest finished daily bar: today for stocks after the close, yesterday
        (US Central) for crypto, whose day ends at midnight Chicago time, and for forex the
        last weekday whose 5 pm New York close has passed."""
        if self.is_crypto:
            return (self.now().astimezone(CT) - timedelta(days=1)).date()
        if self.is_forex:
            return forex.bar_date(self.now())
        return self.today()

    def market_open(self) -> bool:
        return True if self.is_crypto else self.broker.clock().is_open

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings.timezone)

    @property
    def label(self) -> str:
        return self.settings.account_label

    def now(self) -> datetime:
        return self.now_fn()

    def today(self) -> date:
        return local_date(self.now(), self.tz)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def notify(self, text: str, buttons: Buttons | None = None) -> None:
        try:
            self.notifier.send(text, buttons)
        except Exception:
            log.exception("Notification failed: %s", text[:120])

    def sync_fake_prices(self, prices: Mapping[str, float]) -> None:
        if isinstance(self.broker, FakeBroker):
            self.broker.set_prices(prices)


def _latest_close_lookup(bars: BarSource) -> Callable[[str], float | None]:
    def lookup(symbol: str) -> float | None:
        end = datetime.now(NY).date()
        try:
            closes = bars.get_closes([symbol], end - timedelta(days=14), end)
        except Exception:
            return None
        if symbol not in closes.columns:
            return None
        series = closes[symbol].dropna()
        return float(series.iloc[-1]) if len(series) else None

    return lookup


def build_context(
    settings: Settings | None = None,
    *,
    broker: Broker | None = None,
    bars: BarSource | None = None,
    strategy: Strategy | None = None,
    researcher: AIResearcher | None = None,
    notifier: Notifier | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> AppContext:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        ledger.claim_ledger(session, settings.mode_label, settings.account_label)
        session.commit()
        chosen = preferences.load(session)
    base, settings = settings, preferences.apply(settings, chosen)  # the dashboard's choices win
    bars = bars or get_bar_source(settings)
    broker = broker or get_broker(settings, price_source=_latest_close_lookup(bars))
    return AppContext(
        settings=settings,
        session_factory=session_factory,
        broker=broker,
        bars=bars,
        strategy=strategy or get_strategy(settings.strategy, shorts=settings.allow_shorts),
        researcher=researcher or get_researcher(settings),
        notifier=notifier or get_notifier(settings),
        now_fn=now_fn or utcnow,
        base_settings=base,
        strategy_from_settings=strategy is None,
    )


class _FileOnlySettings(Settings):
    @classmethod
    def settings_customise_sources(  # type: ignore[no-untyped-def,override]
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return (init_settings,)


def settings_from_file(path: Path) -> Settings:
    """Settings from one file and nothing else.

    The process running several books holds the stock book's settings in its environment
    (Docker passes .env in as variables), and those must not leak into a crypto or forex book:
    its own file, then that book's defaults, decide everything.
    """
    values = {key.lower(): value for key, value in dotenv_values(path).items() if value is not None}
    return _FileOnlySettings(**{key: value for key, value in values.items() if key in Settings.model_fields})


@dataclass(frozen=True)
class _ExtraBook:
    defaults: dict[str, object]
    env_field: str  # the main book's setting that names this book's file
    demo_database: str
    demo_broker_state: str


EXTRA_BOOKS = {
    AssetClass.CRYPTO: _ExtraBook(
        CRYPTO_DEFAULTS, "crypto_env_file", "crypto-demo.db", "fake_broker_crypto.json"
    ),
    AssetClass.FOREX: _ExtraBook(FOREX_DEFAULTS, "forex_env_file", "forex-demo.db", "fake_broker_forex.json"),
}
_DEMO_URLS = {AssetClass.CRYPTO: CRYPTO_DEMO_DATABASE_URL, AssetClass.FOREX: FOREX_DEMO_DATABASE_URL}


def book_settings(main: Settings, kind: AssetClass) -> Settings | None:
    """Settings for a crypto or forex book that runs next to the main book, if there is one.

    CRYPTO_ENV_FILE and FOREX_ENV_FILE each name that book's own settings file (its own broker
    account and ledger). The demo always gets both, on made-up prices, so the dashboard's Crypto
    and Forex tabs have something to show.
    """
    if main.asset_class == kind or kind not in EXTRA_BOOKS:
        return None
    book = EXTRA_BOOKS[kind]
    env_file = str(getattr(main, book.env_field))
    if env_file:
        path = Path(env_file)
        if not path.is_file():
            raise FileNotFoundError(f"{book.env_field.upper()} points to {path}, which does not exist.")
        settings = settings_from_file(path)
        if settings.asset_class != kind:
            raise ValueError(f"{path} must set ASSET_CLASS={kind}.")
        return settings
    if main.broker == BrokerKind.FAKE:
        # The demo's files sit next to the stock demo's.
        database_url = _DEMO_URLS[kind]
        if main.database_url.startswith("sqlite:///") and main.database_url != DEMO_DATABASE_URL:
            folder = Path(make_url(main.database_url).database or "demo.db").parent
            database_url = f"sqlite:///{folder / book.demo_database}"
        broker_state = str(book.defaults["fake_broker_state"])
        if main.fake_broker_state:
            broker_state = str(Path(main.fake_broker_state).with_name(book.demo_broker_state))
        # Only these values and the book's defaults: none of the stock book's own settings in
        # the environment (its UNIVERSE, say) may leak in.
        return _FileOnlySettings(
            **book.defaults
            | {
                "asset_class": kind,
                "broker": BrokerKind.FAKE,
                "data_source": DataSourceKind.SYNTHETIC,
                "database_url": database_url,
                "fake_broker_state": broker_state,
                "reports_dir": main.reports_dir,
                "api_token": main.api_token,
                "telegram_bot_token": main.telegram_bot_token,
                "telegram_chat_id": main.telegram_chat_id,
                "timezone": main.timezone,
                "enable_scheduler": main.enable_scheduler,
                "frontend_dist": main.frontend_dist,
            },
        )
    return None


def crypto_book_settings(main: Settings) -> Settings | None:
    return book_settings(main, AssetClass.CRYPTO)


def forex_book_settings(main: Settings) -> Settings | None:
    return book_settings(main, AssetClass.FOREX)


def extra_book_settings(main: Settings) -> dict[AssetClass, Settings]:
    """Every book that runs beside the main one, crypto first."""
    books = {kind: book_settings(main, kind) for kind in EXTRA_BOOKS}
    return {kind: settings for kind, settings in books.items() if settings is not None}
