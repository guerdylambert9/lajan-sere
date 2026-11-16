const MINUS = "−";

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const dollarsCents = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const price = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pairPrices = new Map(
  [3, 4, 5].map((digits) => [
    digits,
    new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }),
  ]),
);
// A pair priced in a currency with many units to the dollar shows fewer decimals (OANDA's own).
const QUOTE_DECIMALS: Record<string, number> = { JPY: 3, HUF: 3, THB: 3, CZK: 4 };

// ISO codes of the currencies retail forex desks quote: a pair of two of them is forex.
const FIAT = new Set("USD EUR GBP JPY CHF CAD AUD NZD SEK NOK DKK SGD HKD MXN ZAR PLN HUF CZK TRY CNH THB".split(" "));

/** True for a currency pair such as EUR/USD (BTC/USD is crypto). */
export function isForexPair(symbol: string | null | undefined): boolean {
  const parts = (symbol ?? "").toUpperCase().split("/");
  return parts.length === 2 && FIAT.has(parts[0]) && FIAT.has(parts[1]);
}

/** True for a pair with the dollar first, like USD/MXN: a unit is one dollar, priced in pesos. */
export function isDollarFirst(symbol: string | null | undefined): boolean {
  const parts = (symbol ?? "").toUpperCase().split("/");
  return isForexPair(symbol) && parts[0] === "USD" && parts[1] !== "USD";
}

/** Dollar size of an order or a position (as the app counts it: a USD/MXN unit is $1). */
export function notional(symbol: string, units: number, at: number): number {
  return Math.abs(units) * (isDollarFirst(symbol) ? 1 : at);
}

/** Dollars lost if a position of `units` (below zero: a short) opened at `entry` closes at `at`. */
export function lossAt(symbol: string, units: number, entry: number, at: number): number {
  const perQuote = isDollarFirst(symbol) && at > 0 ? 1 / at : 1;
  return -units * (at - entry) * perQuote;
}

export type Action = "buy" | "sell" | "short" | "cover";

/** What an order does: buy, sell, or for a forex short, short (sell to open) and cover (buy back). */
export function actionOf(side: string, kind: string): Action {
  if (kind === "entry") return side === "sell" ? "short" : "buy";
  return side === "buy" ? "cover" : "sell";
}

export const ACTION_WORD: Record<Action, string> = {
  buy: "Buy",
  sell: "Sell",
  short: "Sell short",
  cover: "Buy to cover",
};

function withMinus(text: string): string {
  return text.replace("-", MINUS);
}

export function money(value: number | null | undefined, cents = false): string {
  if (value == null || !Number.isFinite(value)) return "–";
  return withMinus((cents ? dollarsCents : dollars).format(value));
}

export function signedMoney(value: number): string {
  const text = money(Math.abs(value), true);
  if (value > 0) return `+${text}`;
  if (value < 0) return `${MINUS}${text}`;
  return text;
}

/** A price: 512.40 for a share or a coin, 1.08423 for a currency pair (1.08 would hide the move). */
export function px(value: number | null | undefined, symbol?: string): string {
  if (value == null || !Number.isFinite(value)) return "–";
  if (isForexPair(symbol)) {
    const digits = QUOTE_DECIMALS[(symbol ?? "").toUpperCase().split("/")[1]] ?? 5;
    return withMinus((pairPrices.get(digits) ?? price).format(value));
  }
  return withMinus(price.format(value));
}

/** An order price as people say it: $512.40 for a share or a coin, plain 1.08423 for a pair. */
export function quote(value: number | null | undefined, symbol?: string): string {
  return isForexPair(symbol) ? px(value, symbol) : money(value, true);
}

export function pct(value: number | null | undefined, digits = 1, signed = false): string {
  if (value == null || !Number.isFinite(value)) return "–";
  const text = Math.abs(value).toFixed(digits);
  if (value < 0 && Number(text) !== 0) return `${MINUS}${text}%`;
  return `${signed && value > 0 ? "+" : ""}${text}%`;
}

/** 120 shares, 22,704 units of a currency, or a slice of a coin such as 0.0841. */
export function qty(value: number): string {
  return Number.isInteger(value)
    ? value.toLocaleString("en-US")
    : value.toLocaleString("en-US", { maximumFractionDigits: value < 1 ? 8 : 4 });
}

export function day(isoDate: string): string {
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// Times are shown in New York time, the market's clock, to match the job schedule.
const MARKET_ZONE = "America/New_York";

function lowerDayPeriod(text: string): string {
  return text.replace(/(AM|PM)$/, (period) => period.toLowerCase());
}

/** "Nov 13, 9:50 am ET"; pass zone=false where a column header already says ET. */
export function moment(iso: string | null | undefined, zone = true): string {
  if (!iso) return "–";
  const text = new Date(iso).toLocaleString("en-US", {
    timeZone: MARKET_ZONE,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  return lowerDayPeriod(text) + (zone ? " ET" : "");
}

/** "8:16 pm ET" */
export function clockTime(date: Date): string {
  const text = date.toLocaleTimeString("en-US", { timeZone: MARKET_ZONE, hour: "numeric", minute: "2-digit" });
  return `${lowerDayPeriod(text)} ET`;
}

export function trend(value: number | null | undefined): "up" | "down" | "" {
  if (value == null || value === 0) return "";
  return value > 0 ? "up" : "down";
}

export function sentence(code: string): string {
  const text = code.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** A fraction (0.042) as a percent ("4.2%"), with a real minus sign. */
export function share(value: number | null | undefined, digits = 1, signed = false): string {
  return pct(value == null ? value : value * 100, digits, signed);
}

/** "Jan 2016" from an ISO date. */
export function monthYear(isoDate: string): string {
  return new Date(`${isoDate}T12:00:00`).toLocaleDateString("en-US", { month: "short", year: "numeric" });
}
