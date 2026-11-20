import { useState } from "react";

import type { BookCopy } from "../book";
import { ACTION_WORD, actionOf, day, lossAt, money, monthYear, notional, pct, qty, quote, share, signedMoney, trend } from "../format";
import type { Proposal, RecItem, Recommendations as Recs } from "../types";
import { Term } from "./Term";

interface Props {
  recs: Recs | null;
  pending: Proposal[];
  recent: Proposal[];
  equity: number | null;
  schedulerRunning: boolean;
  copy: BookCopy;
  onDecide: (proposal: Proposal, approve: boolean) => Promise<void>;
  /** spy-trend exits on its average, so a hold with no stop is the rule. */
  spyTrend?: { window: number } | null;
}

const CALL_WORD: Record<RecItem["call"], string> = {
  buy: "Buy",
  short: "Sell short",
  sell: "Sell",
  cover: "Buy to cover",
  hold: "Hold",
  hold_short: "Hold short",
  stay_out: "Stay out",
};

const STATUS_WORD: Record<string, string> = {
  approved: "Approved",
  rejected: "Rejected",
  blocked: "Blocked",
  submitted: "Sent",
  filled: "Filled",
  canceled: "Canceled",
  expired: "Expired",
  dry_run: "Dry run",
  error: "Error",
};

export function Recommendations({
  recs,
  pending,
  recent,
  equity,
  schedulerRunning,
  copy,
  onDecide,
  spyTrend = null,
}: Props) {
  const [busy, setBusy] = useState<number | null>(null);
  const items = recs?.items ?? [];
  const pendingById = new Map(pending.map((p) => [p.id, p]));
  const actionable = items.filter((item) => item.proposal && pendingById.has(item.proposal.id));
  const covered = new Set(actionable.map((item) => item.proposal?.id));
  const strays = pending.filter((p) => !covered.has(p.id)); // waiting, but not among today's calls
  const rest = items.filter((item) => !actionable.includes(item));
  const decided = recent.filter((p) => p.status !== "pending").slice(0, 6);
  const lesson = recs?.lesson ?? "reading-a-recommendation";

  async function decide(proposal: Proposal, approve: boolean) {
    setBusy(proposal.id);
    try {
      await onDecide(proposal, approve);
    } finally {
      setBusy(null);
    }
  }

  const waiting = actionable.length + strays.length;
  return (
    <section className="recs" aria-labelledby="recs-title">
      <div className="section-head">
        <h2 id="recs-title">Today's recommendations</h2>
        {recs?.as_of && <p className="muted small">From the close on {day(recs.as_of)}</p>}
      </div>
      {recs && (
        <p className="rule">
          {recs.rule} <a href={`#/learn/${lesson}`}>Why this rule?</a>
        </p>
      )}
      {recs && <TrackRecordLine recs={recs} />}

      {waiting > 0 ? (
        <>
          <p className="muted small waiting-note">
            {waiting === 1 ? "One order waits" : `${waiting} orders wait`} for you.{" "}
            {schedulerRunning ? copy.sendWhen : "Approved orders go out when you press Send approved orders."}
          </p>
          <ul className="tickets">
            {actionable.map((item) => {
              const proposal = pendingById.get(item.proposal?.id ?? -1);
              return proposal ? (
                <Ticket
                  key={proposal.id}
                  proposal={proposal}
                  item={item}
                  equity={equity}
                  lesson={lesson}
                  busy={busy === proposal.id}
                  onDecide={(approve) => void decide(proposal, approve)}
                />
              ) : null;
            })}
            {strays.map((proposal) => (
              <Ticket
                key={proposal.id}
                proposal={proposal}
                item={null}
                equity={equity}
                lesson={lesson}
                busy={busy === proposal.id}
                onDecide={(approve) => void decide(proposal, approve)}
              />
            ))}
          </ul>
        </>
      ) : (
        <p className="empty">
          {items.length > 0
            ? "Nothing to approve today. The calls below need no order, or their orders are already on the way."
            : schedulerRunning
              ? `No recommendations yet. ${copy.signalsWhen}`
              : `No recommendations yet. Press ${copy.crypto ? "Run the daily signals" : "Run tonight's signals"} to make them.`}
        </p>
      )}

      {rest.length > 0 && (
        <CallsTable items={rest} schedulerRunning={schedulerRunning} copy={copy} spyTrend={spyTrend} />
      )}

      {decided.length > 0 && (
        <div className="decided">
          <h3>Recent decisions</h3>
          <ul className="decided-list">
            {decided.map((proposal) => (
              <DecidedRow key={proposal.id} proposal={proposal} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function TrackRecordLine({ recs }: { recs: Recs }) {
  const { backtest, gate1, account } = recs.track_record;
  const madeUp = (source: string) => (source === "synthetic" ? " (made-up prices)" : "");
  return (
    <dl className="record">
      <div>
        <dt>Backtest</dt>
        <dd>
          {backtest
            ? `${monthYear(backtest.start)} to ${monthYear(backtest.end)}${madeUp(backtest.data_source)}: ` +
              `${share(backtest.win_rate, 0)} of ${backtest.round_trips} trades won, ` +
              `average win ${pct(backtest.avg_win_pct, 1, true)}, average loss ${pct(backtest.avg_loss_pct, 1, true)}.`
            : "Not run yet. Run trader backtest to see this rule's record."}
        </dd>
      </div>
      <div>
        <dt>Gate 1</dt>
        <dd className={gate1 ? (gate1.passed ? "up" : "down") : ""}>
          {gate1
            ? `${gate1.passed ? "Passed" : "Failed"} on ${day(gate1.on)}${madeUp(gate1.data_source)}.`
            : "Not run yet, so treat these calls as an experiment."}
        </dd>
      </div>
      <div>
        <dt>This account</dt>
        <dd>
          {account
            ? `${share(account.return, 1, true)} since ${day(account.since)}` +
              (account.benchmark_return != null ? ` (${recs.benchmark} ${share(account.benchmark_return, 1, true)}).` : ".")
            : "No history yet."}
        </dd>
      </div>
    </dl>
  );
}

function Ticket({
  proposal,
  item,
  equity,
  lesson,
  busy,
  onDecide,
}: {
  proposal: Proposal;
  item: RecItem | null;
  equity: number | null;
  lesson: string;
  busy: boolean;
  onDecide: (approve: boolean) => void;
}) {
  const action = actionOf(proposal.side, proposal.kind);
  const entry = proposal.kind === "entry";
  const amount = item?.proposal?.notional ?? notional(proposal.symbol, proposal.qty, proposal.limit_price);
  const units = action === "short" ? -proposal.qty : proposal.qty;
  const risk =
    item?.proposal?.risk_dollars ??
    (proposal.stop_price != null ? lossAt(proposal.symbol, units, proposal.limit_price, proposal.stop_price) : null);
  const of = (value: number | null) => (equity && value != null ? ` (${share(value / equity)} of equity)` : "");
  const gain = item?.position?.unrealized_pl ?? null;
  const label = `${ACTION_WORD[action]} ${qty(proposal.qty)} ${proposal.symbol}`;
  const amountWord =
    action === "buy" ? "Cost" : action === "sell" ? <Term id="proceeds">Proceeds</Term> : action === "short" ? "Set aside" : "Buys back";

  return (
    <li className={`ticket side-${proposal.side}`}>
      <div className="ticket-body">
        <p className="ticket-line">
          <span className="ticket-side">{ACTION_WORD[action]}</span>
          <span className="ticket-qty">{qty(proposal.qty)}</span>
          <span className="ticket-symbol">{proposal.symbol}</span>
        </p>
        <dl className="ticket-terms">
          <div>
            <dt>
              <Term id="limit-order">Limit</Term>
            </dt>
            <dd>{quote(proposal.limit_price, proposal.symbol)}</dd>
          </div>
          {proposal.stop_price != null && (
            <div>
              <dt>
                <Term id="stop-order">Stop</Term>
              </dt>
              <dd>{quote(proposal.stop_price, proposal.symbol)}</dd>
            </div>
          )}
          {item?.proposal?.stop_limit_price != null && (
            <div>
              <dt>
                <Term id="stop-limit-order">Sells no lower than</Term>
              </dt>
              <dd>{quote(item.proposal.stop_limit_price, proposal.symbol)}</dd>
            </div>
          )}
          <div>
            <dt>{amountWord}</dt>
            <dd>
              {money(amount)}
              <span className="muted">{of(amount)}</span>
            </dd>
          </div>
          {entry && risk != null && (
            <div>
              <dt>
                <Term id="risk-per-trade">At risk</Term>
              </dt>
              <dd>
                {money(risk)}
                <span className="muted">{of(risk)}</span>
              </dd>
            </div>
          )}
          {!entry && gain != null && (
            <div>
              <dt>Gain so far</dt>
              <dd className={trend(gain)}>
                {signedMoney(gain)}
                {item?.position?.unrealized_pct != null && (
                  <span className="muted"> ({share(item.position.unrealized_pct, 1, true)})</span>
                )}
              </dd>
            </div>
          )}
        </dl>
        <p className="ticket-reason">{item?.reason || proposal.reason}</p>
        {action === "short" && (
          <p className="ticket-ai">
            A short gains if {proposal.symbol} falls and loses if it rises; the stop above the entry caps the loss.
          </p>
        )}
        {proposal.ai_rating && proposal.ai_rating !== "no_opinion" && (
          <p className="ticket-ai">AI note: rated {proposal.ai_rating}. It can block a trade, never add one.</p>
        )}
        <p className="ticket-meta muted small">
          Signal from {day(proposal.as_of)}, proposal #{proposal.id}. <a href={`#/learn/${lesson}`}>Why?</a>
        </p>
      </div>
      <div className="ticket-stub">
        <button type="button" className="btn btn-go" disabled={busy} onClick={() => onDecide(true)} aria-label={`Approve: ${label}`}>
          Approve
        </button>
        <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => onDecide(false)} aria-label={`Reject: ${label}`}>
          Reject
        </button>
      </div>
    </li>
  );
}

function note(
  item: RecItem,
  schedulerRunning: boolean,
  copy: BookCopy,
  spyTrend: { window: number } | null,
): string {
  const proposal = item.proposal;
  if (item.call === "hold" || item.call === "hold_short") {
    const stop = item.position?.stop_price;
    if (stop == null)
      return spyTrend ? `The ${spyTrend.window}-day average is the exit.` : "No protective stop at the broker.";
    const atRisk = item.position?.at_risk;
    const floor = item.position?.stop_limit_price;
    const limitText = floor != null ? `, sells no lower than ${quote(floor, item.symbol)}` : "";
    return `Stop ${quote(stop, item.symbol)}${limitText}${atRisk != null ? ` (${money(atRisk)} at risk)` : ""}`;
  }
  if (proposal) {
    if (proposal.status === "approved")
      return schedulerRunning ? copy.approvedNote : "Approved; press Send approved orders.";
    if (proposal.status === "blocked") return item.detail ?? "Blocked by the risk checks.";
    if (proposal.status === "rejected") return "You rejected it.";
    if (proposal.status === "submitted") return "Sent to the broker.";
    if (proposal.status === "dry_run") return "Logged as a dry run; nothing was sent.";
    return STATUS_WORD[proposal.status] ?? proposal.status;
  }
  return item.detail ?? "";
}

function CallsTable({
  items,
  schedulerRunning,
  copy,
  spyTrend,
}: {
  items: RecItem[];
  schedulerRunning: boolean;
  copy: BookCopy;
  spyTrend: { window: number } | null;
}) {
  return (
    <div className="calls">
      <h3>The other calls</h3>
      <div className="table-wrap">
        <table className="ledger compact calls-table">
          <thead>
            <tr>
              <th scope="col">Call</th>
              <th scope="col">Symbol</th>
              <th scope="col">Why</th>
              <th scope="col">Note</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.symbol}>
                <td>
                  <span className={`call-word call-${item.call}`}>{CALL_WORD[item.call]}</span>
                </td>
                <th scope="row" className="symbol">
                  {item.symbol}
                </th>
                <td className="why">{item.reason}</td>
                <td className={`note ${item.proposal?.status === "blocked" || item.detail ? "warn-soft" : ""}`}>
                  {note(item, schedulerRunning, copy, spyTrend)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DecidedRow({ proposal }: { proposal: Proposal }) {
  const why = proposal.violations.length
    ? proposal.violations.map((v) => v.message).join(" ")
    : proposal.status === "error" || proposal.status === "canceled"
      ? proposal.error
      : null;
  return (
    <li className={`decided-row status-${proposal.status}`}>
      <span className="decided-status">{STATUS_WORD[proposal.status] ?? proposal.status}</span>
      <span className="decided-what">
        {ACTION_WORD[actionOf(proposal.side, proposal.kind)]} {qty(proposal.qty)} {proposal.symbol}
      </span>
      <span className="decided-when muted">{day(proposal.as_of)}</span>
      {why && <span className="decided-why">{why}</span>}
    </li>
  );
}
