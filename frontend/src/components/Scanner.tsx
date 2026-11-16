import { day, money, qty, share } from "../format";
import type { ScanResult, ScanRow } from "../types";
import { Term } from "./Term";

const IDEA_WORD: Record<ScanRow["label"], string> = {
  buy_idea: "Buy idea",
  watch: "Watch",
  skip: "Skip",
  no_data: "No data",
};

export function Scanner({ scan }: { scan: ScanResult | null }) {
  if (!scan) return null;
  const rows = scan.rows;
  const ranked = rows.filter((row) => row.rank != null);
  const ideas = rows.filter((row) => row.label === "buy_idea");
  const untested = scan.how_to_test.replace(/^Untested:\s*/, "");

  return (
    <section className="section scan" aria-labelledby="scan-title">
      <div className="section-head">
        <h2 id="scan-title">Ideas from your watchlist</h2>
        {scan.as_of && <p className="muted small">From the close on {day(scan.as_of)}</p>}
      </div>
      <p className="untested">
        <strong>Untested.</strong> {untested.charAt(0).toUpperCase() + untested.slice(1)}{" "}
        <a href="#/learn/reading-a-recommendation">How ideas differ from recommendations</a>
      </p>
      <p className="muted rule-quiet">{scan.rule}</p>

      {rows.length === 0 ? (
        <p className="empty">No scan yet. It runs with tonight's signals, or press Scan the watchlist below.</p>
      ) : ideas.length === 0 && ranked.length > 0 ? (
        <p className="empty">
          No buy ideas today: every name on the watchlist has a negative past-year return, and momentum only buys
          rising names.
        </p>
      ) : null}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="ledger scan-table">
            <thead>
              <tr>
                <th scope="col" className="num">
                  Rank
                </th>
                <th scope="col">Symbol</th>
                <th scope="col">Idea</th>
                <th scope="col" className="num">
                  <Term id="momentum-return">Past-year return</Term>
                </th>
                <th scope="col" className="num">
                  <Term id="moving-average">vs 200-day</Term>
                </th>
                <th scope="col" className="num">
                  From 52-week high
                </th>
                <th scope="col" className="num">
                  <Term id="limit-order">Entry</Term>
                </th>
                <th scope="col" className="num">
                  <Term id="stop-order">Stop</Term>
                </th>
                <th scope="col" className="num">
                  Shares
                </th>
                <th scope="col" className="num">
                  <Term id="risk-per-trade">At risk</Term>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.symbol} className={`idea-${row.label}`}>
                  <td className="num">{row.rank ?? "–"}</td>
                  <th scope="row" className="symbol">
                    {row.symbol}
                    {row.held && <span className="muted small"> held</span>}
                  </th>
                  <td>
                    <span className={`idea-word idea-word-${row.label}`}>{IDEA_WORD[row.label]}</span>
                  </td>
                  <td className="num">{share(row.momentum, 1, true)}</td>
                  <td className="num">{share(row.trend_gap, 1, true)}</td>
                  <td className="num">{share(row.from_high, 1)}</td>
                  <td className="num">{money(row.entry, true)}</td>
                  <td className="num">{money(row.stop, true)}</td>
                  <td className="num">{row.qty != null ? qty(row.qty) : "–"}</td>
                  <td className="num">{money(row.risk_dollars)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {ideas.length > 0 && (
        <ul className="idea-reasons">
          {ideas.map((row) => (
            <li key={row.symbol}>
              <strong>{row.symbol}</strong> {row.reason}
            </li>
          ))}
        </ul>
      )}
      {rows.length > 0 && (
        <p className="small muted">
          Entry, stop and shares follow the same risk rules as real orders, so each idea reads like the order it would
          become.
        </p>
      )}
    </section>
  );
}
