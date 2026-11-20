import type { BookCopy } from "../book";
import { money, moment, pct, px, qty, signedMoney, trend } from "../format";
import type { Order, Position } from "../types";

export function PositionsTable({
  positions,
  copy,
  averageExit = false,
}: {
  positions: Position[];
  copy: BookCopy;
  /** spy-trend exits on the average, so a position without a stop is the rule. */
  averageExit?: boolean;
}) {
  return (
    <section className="section" aria-labelledby="positions-title">
      <h2 id="positions-title">Positions</h2>
      {positions.length === 0 ? (
        <p className="empty">No open positions.</p>
      ) : (
        <div className="table-wrap">
          <table className="ledger">
            <thead>
              <tr>
                <th scope="col">Symbol</th>
                <th scope="col" className="num">{copy.qtyHeading}</th>
                <th scope="col" className="num">Avg cost</th>
                <th scope="col" className="num">Price</th>
                <th scope="col" className="num">Value</th>
                <th scope="col" className="num">Gain</th>
                <th scope="col" className="num">Of equity</th>
                <th scope="col" className="num">Stop</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.symbol}>
                  <th scope="row" className="symbol">{p.symbol}</th>
                  <td className="num">
                    {p.qty < 0 && <span className="short-tag">Short</span>}
                    {qty(Math.abs(p.qty))}
                  </td>
                  <td className="num">{px(p.avg_entry_price, p.symbol)}</td>
                  <td className="num">{px(p.current_price, p.symbol)}</td>
                  <td className="num">{money(p.market_value)}</td>
                  <td className={`num ${trend(p.unrealized_pl)}`}>
                    {signedMoney(p.unrealized_pl)} <span className="muted">({pct(p.unrealized_pl_pct, 1, true)})</span>
                  </td>
                  <td className="num">{pct(p.weight_pct)}</td>
                  <td className="num">
                    {averageExit && !p.protected ? (
                      <span className="muted">The average is the exit</span>
                    ) : p.protected ? (
                      px(p.stop_price, p.symbol)
                    ) : (
                      <span className="warn">No stop</span>
                    )}
                    {p.protected && p.stop_limit_price != null && (
                      <span className="stop-floor muted">sells no lower than {px(p.stop_limit_price, p.symbol)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const ORDER_STATUS: Record<string, string> = {
  filled: "Filled",
  new: "Working",
  accepted: "Working",
  partially_filled: "Part filled",
  canceled: "Canceled",
  expired: "Expired",
  rejected: "Rejected",
};

const ORDER_WORD: Record<string, string> = {
  buy: "Buy",
  sell: "Sell",
  short: "Sell short",
  cover: "Buy to cover",
  stop_sell: "Stop sell",
  stop_buy: "Stop buy",
};

function orderWord(o: Order): string {
  if (o.action && ORDER_WORD[o.action]) return ORDER_WORD[o.action];
  return o.side === "buy" ? "Buy" : o.stop_price != null ? "Stop sell" : "Sell"; // an older server
}

export function OrdersTable({ orders, copy }: { orders: Order[]; copy: BookCopy }) {
  return (
    <section className="section" aria-labelledby="orders-title">
      <h2 id="orders-title">Orders sent</h2>
      {orders.length === 0 ? (
        <p className="empty">No orders sent yet. {copy.sendWhen}</p>
      ) : (
        <div className="table-wrap">
          <table className="ledger">
            <thead>
              <tr>
                <th scope="col">Sent (ET)</th>
                <th scope="col">Order</th>
                <th scope="col" className="num">Limit</th>
                <th scope="col" className="num">Stop</th>
                <th scope="col" className="num">Filled at</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.id}>
                  <td>{moment(o.submitted_at, false)}</td>
                  <td>
                    <span className={o.side === "buy" ? "side-word buy" : "side-word sell"}>{orderWord(o)}</span>{" "}
                    {qty(o.qty)} <span className="symbol">{o.symbol}</span>
                  </td>
                  <td className="num">{px(o.limit_price, o.symbol)}</td>
                  <td className="num">{px(o.stop_price, o.symbol)}</td>
                  <td className="num">{px(o.filled_avg_price, o.symbol)}</td>
                  <td>{ORDER_STATUS[o.status] ?? o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
