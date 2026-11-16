import type { Status } from "./types";

export type BookKind = "stocks" | "crypto" | "forex";

/** Words that differ between the stock, crypto and forex books. */
export interface BookCopy {
  kind: BookKind;
  crypto: boolean;
  title: string;
  qtyHeading: string;
  holdings: (count: number) => string;
  market: string | null;
  sendWhen: string;
  approvedNote: string;
  approvedToast: string;
  signalsWhen: string;
  scheduleNote: string;
}

const STOCKS: BookCopy = {
  kind: "stocks",
  crypto: false,
  title: "Trading desk",
  qtyHeading: "Shares",
  holdings: (count) => `${count} tickers`,
  market: null,
  sendWhen: "Approved orders go out at 9:50 am ET on the next trading day.",
  approvedNote: "Approved; goes out at 9:50 am ET.",
  approvedToast: "It goes out at 9:50 am ET on the next trading day.",
  signalsWhen: "They appear after the 5:15 pm ET signals run.",
  scheduleNote: "The scheduler runs these on weekdays (New York time).",
};

const CRYPTO: BookCopy = {
  kind: "crypto",
  crypto: true,
  title: "Crypto desk",
  qtyHeading: "Quantity",
  holdings: (count) => `${count} coin${count === 1 ? "" : "s"}`,
  market: "Crypto trades around the clock, every day of the week.",
  sendWhen: "Approved orders go out within 5 minutes, at any hour, and get their stop as soon as they fill.",
  approvedNote: "Approved; goes out within 5 minutes.",
  approvedToast: "It goes out within 5 minutes and gets its stop as soon as it fills.",
  signalsWhen: "They appear after the daily run at 1:15 am ET, when the crypto day ends.",
  scheduleNote: "The scheduler runs these every day, weekends included (times in New York time).",
};

const FOREX: BookCopy = {
  kind: "forex",
  crypto: false,
  title: "Forex desk",
  qtyHeading: "Units",
  holdings: (count) => `${count} pair${count === 1 ? "" : "s"}`,
  market: null,
  sendWhen: "Approved orders go out at 9:50 am ET on the next weekday, while London and New York are both trading.",
  approvedNote: "Approved; goes out at 9:50 am ET.",
  approvedToast: "It goes out at 9:50 am ET on the next weekday.",
  signalsWhen: "They appear after the 5:15 pm ET signals run, just after the forex day closes at 5 pm.",
  scheduleNote: "The scheduler runs these on weekdays (New York time); the forex week ends Friday at 5 pm ET.",
};

export function bookCopy(status: Pick<Status, "asset_class"> | null | undefined): BookCopy {
  if (status?.asset_class === "crypto") return CRYPTO;
  return status?.asset_class === "forex" ? FOREX : STOCKS;
}
