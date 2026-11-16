import { money, pct, trend } from "../format";
import type { Account } from "../types";
import { Term } from "./Term";

export function Stats({ account, maxPositions }: { account: Account; maxPositions: number }) {
  return (
    <dl className="stats">
      <div className="stat stat-equity">
        <dt>
          <Term id="equity">Equity</Term>
        </dt>
        <dd className="figure">{money(account.equity)}</dd>
      </div>
      <div className="stat">
        <dt>Today</dt>
        <dd className={`figure ${trend(account.day_pnl_pct)}`}>{pct(account.day_pnl_pct, 2, true)}</dd>
      </div>
      <div className="stat">
        <dt>
          <Term id="drawdown">Below peak</Term>
        </dt>
        <dd className="figure">{pct(account.drawdown_pct, 1)}</dd>
      </div>
      <div className="stat">
        <dt>
          <Term id="cash">Cash</Term>
        </dt>
        <dd className="figure">{money(account.cash)}</dd>
      </div>
      <div className="stat">
        <dt>
          <Term id="position">Positions</Term>
        </dt>
        <dd className="figure">
          {account.open_positions}
          <span className="of"> of {maxPositions}</span>
        </dd>
      </div>
    </dl>
  );
}
