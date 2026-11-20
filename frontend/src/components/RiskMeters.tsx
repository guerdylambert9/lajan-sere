import type { BookKind } from "../book";
import { pct } from "../format";
import type { Risk } from "../types";
import { Term } from "./Term";

interface Meter {
  label: string;
  term?: string;
  value: number;
  limit: number;
  text: string;
}

/** Set only for spy-trend. Other strategies keep the account's stop, cap, and position slots. */
export interface SpyTrendDesk {
  window: number;
  stopPct: number;
  capPct: number;
}

export function RiskMeters({
  risk,
  kind = "stocks",
  spyTrend = null,
}: {
  risk: Risk;
  kind?: BookKind;
  spyTrend?: SpyTrendDesk | null;
}) {
  const { limits, usage } = risk;
  const loss = Math.max(0, -(usage.day_pnl_pct ?? 0));
  const slots = spyTrend ? 1 : limits.max_open_positions;
  const meters: Meter[] = [
    {
      label: "Orders sent today",
      value: usage.orders_today,
      limit: limits.max_orders_per_day,
      text: `${usage.orders_today} of ${limits.max_orders_per_day}`,
    },
    {
      label: "Open positions",
      value: usage.open_positions ?? 0,
      limit: slots,
      text: `${usage.open_positions ?? "–"} of ${slots}`,
    },
    {
      label: "Below peak",
      term: "drawdown",
      value: usage.drawdown_pct ?? 0,
      limit: limits.max_drawdown_pct,
      text: `${pct(usage.drawdown_pct)} of ${limits.max_drawdown_pct}%`,
    },
    {
      label: "Loss today",
      term: "daily-loss-limit",
      value: loss,
      limit: limits.daily_loss_limit_pct,
      text: `${pct(loss, 2)} of ${limits.daily_loss_limit_pct}%`,
    },
  ];

  return (
    <section className="panel risk">
      <h2>Risk limits</h2>
      <ul className="meters">
        {meters.map((meter) => {
          const ratio = meter.limit > 0 ? Math.min(meter.value / meter.limit, 1) : 0;
          const level = ratio >= 1 ? "hit" : ratio >= 0.75 ? "near" : "ok";
          return (
            <li key={meter.label} className={`meter meter-${level}`}>
              <div className="meter-text">
                <span>{meter.term ? <Term id={meter.term}>{meter.label}</Term> : meter.label}</span>
                <span className="figure-sm">{meter.text}</span>
              </div>
              <div
                className="meter-track"
                role="meter"
                aria-label={meter.label}
                aria-valuemin={0}
                aria-valuemax={meter.limit}
                aria-valuenow={meter.value}
              >
                <div className="meter-fill" style={{ width: `${ratio * 100}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
      <ul className="limits-list">
        {spyTrend ? (
          <>
            <li>One position for the whole account, with no {spyTrend.capPct}% cap.</li>
            <li>
              The {spyTrend.window}-day average is the exit, with no {spyTrend.stopPct}% stop.
            </li>
          </>
        ) : (
          <>
            <li>
              A trade risks at most {limits.risk_per_trade_pct}% of equity, with its stop {limits.stop_loss_pct}% below
              the entry{limits.allow_shorts ? " (above it for a short)" : ""}
              {limits.stop_limit_band_pct ? ` and its limit ${limits.stop_limit_band_pct}% below the stop` : ""}.
            </li>
            <li>A new position starts at no more than {limits.max_position_pct}% of equity.</li>
          </>
        )}
        <li>
          Hitting {limits.max_drawdown_pct}% below peak engages the kill switch; losing {limits.daily_loss_limit_pct}%
          in a day pauses new entries until tomorrow.
        </li>
        {kind === "forex" && (
          <li>
            No leverage: a new position{limits.allow_shorts ? ", long or short," : ""} only uses money the account
            has, although the broker would lend up to 50 times it.
          </li>
        )}
        {kind === "crypto" ? (
          <li>Orders go out at any hour, and skip any entry that rose more than {risk.max_gap_pct}% since its signal.</li>
        ) : kind === "forex" ? (
          <li>
            Orders go out while the forex market is open, never in the half hour around its 5 pm ET close, and skip
            any entry that rose more than {risk.max_gap_pct}% since its signal
            {limits.allow_shorts ? " (or a short whose pair fell that far)" : ""}.
          </li>
        ) : (
          <li>
            Orders go out from {limits.no_trade_after_open_min} minutes after the open until{" "}
            {limits.no_trade_before_close_min} minutes before the close, and skip any entry that gapped up more than{" "}
            {risk.max_gap_pct}%.
          </li>
        )}
      </ul>
    </section>
  );
}
