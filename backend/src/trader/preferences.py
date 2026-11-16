"""Choices you make on the dashboard: the stop-loss for each book, and for the forex book the pair
set (standard or exotic) and short selling.

They are kept in the book's own ledger and win over its settings file. Each shows the value the
app recommends beside it. A riskier choice (a stop wider than recommended, the exotic pairs, or
short selling) comes back with plain warnings first and only takes effect once you confirm.

A change expires the proposals still waiting for approval or submission, since they were sized
on the old settings; the next nightly plan sizes them again. Positions already open keep the
stops they have. Backtests and gates (`trader backtest`, `trader gate1`) use these choices too,
so you can test a change before trading real money with it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from trader import ledger
from trader.config import CRYPTO_DEFAULTS, PAIR_SETS, PairSet, Settings, split_csv
from trader.risk.limits import RiskLimits

if TYPE_CHECKING:
    from trader.services.context import AppContext

PREFS_KEY = "preferences"
MIN_STOP_PCT = 1.0
MAX_STOP_PCT = 30.0
STOP_RANGE_MULTIPLE = 3  # the widest stop allowed is three times the recommended one
FIELDS = ("stop_loss_pct", "pair_set", "allow_shorts")

CURRENCY_NAMES = {
    "EUR": "euro",
    "GBP": "British pound",
    "JPY": "Japanese yen",
    "CHF": "Swiss franc",
    "CAD": "Canadian dollar",
    "AUD": "Australian dollar",
    "NZD": "New Zealand dollar",
    "MXN": "Mexican peso",
    "ZAR": "South African rand",
    "PLN": "Polish zloty",
    "HUF": "Hungarian forint",
    "CZK": "Czech koruna",
    "SGD": "Singapore dollar",
}


@dataclass(frozen=True)
class Preferences:
    stop_loss_pct: float | None = None  # None: the settings file's stop, or the recommended one
    pair_set: str | None = None  # forex: standard or exotic; None: the settings file's pairs
    allow_shorts: bool | None = None  # forex; None: the settings file's ALLOW_SHORTS

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Preferences:
        data = data or {}
        stop = data.get("stop_loss_pct")
        shorts = data.get("allow_shorts")
        return cls(
            stop_loss_pct=float(stop) if stop is not None else None,
            pair_set=str(data["pair_set"]) if data.get("pair_set") else None,
            allow_shorts=bool(shorts) if shorts is not None else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Notice:
    topic: str  # stop, pairs or shorts
    level: str  # warning: you confirm it before it takes effect; info: just so you know
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class UpdateResult:
    status: str  # applied, unchanged, needs_confirm, blocked or invalid
    message: str = ""
    notices: list[Notice] = field(default_factory=list)
    expired: list[int] = field(default_factory=list)


# ------------------------------------------------------------------------- reading and applying


def load(session: Any) -> Preferences:
    return Preferences.from_dict(ledger.get_state(session, PREFS_KEY))


def stored(settings: Settings) -> Preferences:
    """The choices saved in this book's ledger, read without creating it (none if it's new)."""
    try:
        return Preferences.from_dict(ledger.read_state(settings.database_url, PREFS_KEY))
    except Exception:  # an unreachable database has no choices to add
        return Preferences()


def apply(base: Settings, prefs: Preferences) -> Settings:
    """The settings with the dashboard's choices on top. Picking a pair set brings that set's
    pairs and risk settings; a stop chosen on the dashboard wins over both."""
    update: dict[str, Any] = {}
    if base.is_forex and prefs.pair_set in PAIR_SETS:
        update |= {"pair_set": PairSet(prefs.pair_set), **PAIR_SETS[prefs.pair_set]}
    if prefs.stop_loss_pct is not None:
        update["stop_loss_pct"] = float(prefs.stop_loss_pct)
    if base.is_forex and prefs.allow_shorts is not None and base.strategy == "trend":
        update["allow_shorts"] = bool(prefs.allow_shorts)
    return base.model_copy(update=update) if update else base


def effective(settings: Settings) -> Settings:
    """A book's settings as it trades them: its settings file plus the dashboard's choices."""
    return apply(settings, stored(settings))


def recommended_stop(settings: Settings) -> float:
    """The stop the app recommends for this book (for forex, for its pair set)."""
    if settings.is_forex:
        return float(PAIR_SETS[settings.pair_set]["stop_loss_pct"])
    if settings.is_crypto:
        return float(CRYPTO_DEFAULTS["stop_loss_pct"])
    return float(Settings.model_fields["stop_loss_pct"].default)


def stop_range(settings: Settings) -> tuple[float, float]:
    widest = min(MAX_STOP_PCT, STOP_RANGE_MULTIPLE * recommended_stop(settings))
    return MIN_STOP_PCT, widest


def pair_set_of(settings: Settings) -> str:
    """standard or exotic when the book trades exactly that set's pairs, custom otherwise."""
    for name, preset in PAIR_SETS.items():
        if settings.universe_list == split_csv(str(preset["universe"]).upper()):
            return str(name)
    return "custom"


def max_loss_pct(settings: Settings) -> float:
    """About the most one stop-out costs at full size, in percent of the account."""
    limits = RiskLimits.from_settings(settings)
    return limits.max_entry_fraction() * limits.worst_exit_loss() * 100


def _all_stopped_pct(settings: Settings) -> float:
    """About what every slot stopping out together would cost (never more than the account holds)."""
    limits = RiskLimits.from_settings(settings)
    invested = min(limits.max_open_positions * limits.max_entry_fraction(), 1.0)
    return invested * limits.worst_exit_loss() * 100


def _names(pairs: list[str]) -> str:
    others = [
        CURRENCY_NAMES.get(p.split("/")[1] if p.startswith("USD/") else p.split("/")[0], p) for p in pairs
    ]
    if len(others) < 2:
        return "".join(others)
    return ", ".join(others[:-1]) + " and " + others[-1]


# ------------------------------------------------------------------------- what a change means


def review(before: Settings, after: Settings) -> list[Notice]:
    """Plain warnings and notes for going from `before` to `after`."""
    notices: list[Notice] = []
    gate = "Run Gate 1 again (trader gate1) before you trade real money with it."

    if after.is_forex and pair_set_of(after) != pair_set_of(before):
        pairs = after.universe_list
        if pair_set_of(after) == PairSet.EXOTIC:
            notices.append(
                Notice(
                    "pairs",
                    "warning",
                    f"Exotic pairs: the dollar against the {_names(pairs)}",
                    [
                        "Most of these currencies swing more than the majors, and all of them cost more "
                        "to trade (wider spreads).",
                        "Overnight financing follows the gap between the two interest rates, which is "
                        "wider here: holding the dollar against a high-interest currency costs more each "
                        "night.",
                        "Their prices can jump on local news, like an election or a central bank "
                        "surprise, and spreads widen further while those markets are closed.",
                        f"To allow for that this set uses a {after.stop_loss_pct:g}% stop, at most "
                        f"{after.max_position_pct:g}% of the account per pair, and higher costs in "
                        "backtests.",
                        "The Turkish lira is left out: its interest rate is so far above the dollar's "
                        "that holding the dollar against it costs a large share of the position in "
                        "financing every year.",
                        "Your OANDA account has to offer these pairs; OANDA refuses orders for any it "
                        "doesn't, and the dashboard shows the refusal.",
                        f"Backtests and gates you ran were on other pairs. {gate}",
                    ],
                )
            )
        else:
            notices.append(
                Notice(
                    "pairs",
                    "info",
                    f"Standard pairs: the dollar against the {_names(pairs)}",
                    [
                        "The most traded pairs, with the tightest spreads.",
                        f"This set uses a {after.stop_loss_pct:g}% stop and at most "
                        f"{after.max_position_pct:g}% of the account per pair.",
                    ],
                )
            )

    if after.stop_loss_pct != before.stop_loss_pct:
        notices.extend(_stop_notices(before, after, gate))

    if after.allow_shorts and not before.allow_shorts:
        notices.append(
            Notice(
                "shorts",
                "warning",
                "Short selling: the forex book may also bet on a pair falling",
                [
                    "When a pair closes below its long-term average, the book proposes selling it "
                    "short: the trade makes money if the pair keeps falling and loses if it rises.",
                    f"A rising price has no ceiling. The stop {after.stop_loss_pct:g}% above the entry "
                    "is what limits the loss, and a jump over a weekend or on news can carry the price "
                    "past it.",
                    "Holding a short overnight costs or earns financing, depending on the two "
                    "currencies' interest rates.",
                    "Every short is sized as if fully paid for (nothing borrowed), carries its stop "
                    "from the start, and still needs your approval.",
                    f"Backtests and gates you ran only bought. {gate}",
                ],
            )
        )
    elif before.allow_shorts and not after.allow_shorts:
        notices.append(
            Notice(
                "shorts",
                "info",
                "Short selling off",
                [
                    "Any open short gets a buy-to-cover proposal at the next nightly plan; each one "
                    "needs your approval as usual.",
                ],
            )
        )
    return notices


def _stop_notices(before: Settings, after: Settings, gate: str) -> list[Notice]:
    new = after.stop_loss_pct
    recommended = recommended_stop(after)
    kept = "Positions already open keep the stop they have; the new stop applies to new entries."
    if new > recommended:
        baseline = after.model_copy(update={"stop_loss_pct": recommended})
        lines = [
            f"A full stop-out could cost about {max_loss_pct(after):.2f}% of the account per position, "
            f"up from {max_loss_pct(baseline):.2f}% at the recommended stop.",
        ]
        limits, base_limits = RiskLimits.from_settings(after), RiskLimits.from_settings(baseline)
        if limits.max_entry_fraction() < base_limits.max_entry_fraction() - 1e-9:
            lines.append(
                f"To keep each stop-out inside the {after.risk_per_trade_pct:g}% loss limit per trade, "
                f"new positions get smaller: at most {limits.max_entry_fraction():.0%} of the account "
                f"each instead of {base_limits.max_entry_fraction():.0%}."
            )
        lines += [
            f"With all {after.max_open_positions} positions open, stop-outs together could cost about "
            f"{_all_stopped_pct(after):.1f}% of the account.",
            "Prices have further to run against you before the app gets you out, and a jump over a "
            "weekend or on news can still carry the price past the stop.",
            kept,
            f"Backtests and gates you ran used a {before.stop_loss_pct:g}% stop. {gate}",
        ]
        return [
            Notice(
                "stop",
                "warning",
                f"Wider stop-loss: {new:g}% instead of the recommended {recommended:g}%",
                lines,
            )
        ]
    if new < recommended:
        return [
            Notice(
                "stop",
                "info",
                f"Tighter stop-loss: {new:g}% instead of the recommended {recommended:g}%",
                [
                    "Ordinary daily swings reach a tighter stop more often, so expect more small losses "
                    "and more trades, and each trade pays the spread.",
                    kept,
                ],
            )
        ]
    return [Notice("stop", "info", f"The recommended {recommended:g}% stop-loss", [kept])]


def standing_notes(settings: Settings) -> list[Notice]:
    """The warnings that still apply to the book's current settings, measured against the
    recommended ones (the standard pairs, no short selling, the recommended stop)."""
    baseline: dict[str, Any] = {}
    if settings.is_forex:
        baseline |= {**PAIR_SETS[PairSet.STANDARD], "pair_set": PairSet.STANDARD, "allow_shorts": False}
    baseline["stop_loss_pct"] = recommended_stop(settings)
    notes = [n for n in review(settings.model_copy(update=baseline), settings) if n.level == "warning"]
    for note in notes:  # whether old backtests covered it is a question for the moment of change
        note.lines = [line for line in note.lines if not line.startswith("Backtests and gates")]
    return notes


# ------------------------------------------------------------------------- the dashboard's view


def view(ctx: AppContext) -> dict[str, Any]:
    settings, base = ctx.settings, ctx.base_settings
    with ctx.session() as session:
        prefs = load(session)
    low, high = stop_range(settings)
    if prefs.stop_loss_pct is not None:
        source = "dashboard"
    elif prefs.pair_set or "stop_loss_pct" not in base.provided_fields:
        source = "recommended"
    else:
        source = "settings file"
    data: dict[str, Any] = {
        "book": str(settings.asset_class),
        "stop_loss_pct": settings.stop_loss_pct,
        "recommended_stop_loss_pct": recommended_stop(settings),
        "stop_range": [low, high],
        "stop_source": source,
        "max_loss_per_position_pct": max_loss_pct(settings),
        "risk_per_trade_pct": settings.risk_per_trade_pct,
        "notes": [asdict(n) for n in standing_notes(settings)],
        "forex": None,
    }
    if settings.is_forex:
        data["forex"] = {
            "pair_set": pair_set_of(settings),
            "pairs": settings.universe_list,
            "pair_sets": {
                str(name): {
                    "pairs": split_csv(str(preset["universe"])),
                    "stop_loss_pct": preset["stop_loss_pct"],
                    "max_position_pct": preset["max_position_pct"],
                    "max_open_positions": preset["max_open_positions"],
                }
                for name, preset in PAIR_SETS.items()
            },
            "allow_shorts": settings.allow_shorts,
            "shorts_available": settings.strategy == "trend",
        }
    return data


# ------------------------------------------------------------------------- changing them


def update(ctx: AppContext, changes: dict[str, Any], confirm: bool = False) -> UpdateResult:
    """Change some of the choices. `changes` holds only what changes; None goes back to the
    settings file (or the recommendation). Riskier choices need confirm=True."""
    unknown = set(changes) - set(FIELDS)
    if unknown:
        return UpdateResult("invalid", f"Unknown setting: {', '.join(sorted(unknown))}.")
    base = ctx.base_settings
    if not base.is_forex and any(changes.get(name) is not None for name in ("pair_set", "allow_shorts")):
        return UpdateResult(
            "invalid", "Pair sets and short selling are forex settings; this book only has the stop-loss."
        )
    if changes.get("pair_set") is not None and changes["pair_set"] not in PAIR_SETS:
        return UpdateResult("invalid", "Pick the standard or the exotic pair set.")
    if changes.get("allow_shorts") and base.strategy != "trend":
        return UpdateResult(
            "invalid", "Short selling works with STRATEGY=trend; the other strategies only buy."
        )

    with ctx.session() as session:
        current = load(session)
        values = current.as_dict() | changes
        if (
            "pair_set" in changes
            and changes["pair_set"] != current.pair_set
            and "stop_loss_pct" not in changes
        ):
            values["stop_loss_pct"] = None  # a new pair set starts from its own recommended stop
        proposed = Preferences.from_dict(values)
        after = apply(base, proposed)
        stop = after.stop_loss_pct
        low, high = stop_range(after)
        if not low <= stop <= high:
            return UpdateResult("invalid", f"Pick a stop-loss between {low:g}% and {high:g}%.")
        before = ctx.settings
        if proposed == current or _same(before, after):
            if proposed != current:
                ledger.set_state(session, PREFS_KEY, proposed.as_dict())
            return UpdateResult("unchanged", "Nothing changed.")

        if after.universe_list != before.universe_list:
            try:
                held = {p.symbol for p in ctx.broker.get_positions() if p.qty != 0}
            except Exception as exc:
                return UpdateResult("blocked", f"Couldn't check the open positions first: {exc}")
            stranded = sorted(held & set(before.universe_list) - set(after.universe_list))
            if stranded:
                return UpdateResult(
                    "blocked",
                    f"Close your {', '.join(stranded)} position{'s' if len(stranded) > 1 else ''} first: "
                    "the app only manages the pairs of the set you pick, so it would stop watching them.",
                )

        notices = review(before, after)
        if any(n.level == "warning" for n in notices) and not confirm:
            return UpdateResult(
                "needs_confirm", "Read the warnings, then confirm to make the change.", notices
            )

        ledger.set_state(session, PREFS_KEY, proposed.as_dict())
        expired = ledger.expire_open(
            session,
            ctx.label,
            "Your settings changed after it was planned; the next nightly plan sizes it again.",
        )
        ledger.audit(
            session,
            "preferences_changed",
            before=current.as_dict(),
            after=proposed.as_dict(),
            confirmed=confirm,
            expired_proposals=expired,
        )
    ctx.apply_preferences(proposed)
    summary = ", ".join(n.title for n in notices) or "Settings changed"
    ctx.notify(f"[{after.mode_label} {ctx.label}] {summary}.")
    message = "Saved. Today's calls refresh at the next nightly plan."
    if expired:
        message += f" {len(expired)} waiting proposal{'s' if len(expired) > 1 else ''} expired."
    return UpdateResult("applied", message, notices, expired)


def _same(before: Settings, after: Settings) -> bool:
    keys = ("stop_loss_pct", "allow_shorts", "universe", "max_position_pct", "max_open_positions")
    return all(getattr(before, key) == getattr(after, key) for key in keys)
