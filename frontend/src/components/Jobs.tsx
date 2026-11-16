import { useState } from "react";

import type { BookCopy } from "../book";
import { moment } from "../format";
import type { JobName, Status } from "../types";

interface Job {
  name: JobName;
  label: string;
  time: string;
  detail: string;
}

const STOCK_JOBS: Job[] = [
  {
    name: "nightly",
    label: "Run tonight's signals",
    time: "5:15 pm ET",
    detail: "Makes today's recommendations, proposes orders and scans the watchlist.",
  },
  { name: "submit", label: "Send approved orders", time: "9:50 am ET", detail: "Only works inside the trading window." },
  { name: "reconcile", label: "Check against the broker", time: "4:30 pm ET", detail: "Compares the ledger with the broker." },
  { name: "scan", label: "Scan the watchlist", time: "5:15 pm ET", detail: "Ranks the watchlist again, for example after you change it." },
];

const CRYPTO_JOBS: Job[] = [
  {
    name: "nightly",
    label: "Run the daily signals",
    time: "daily at 1:15 am ET",
    detail: "Makes the day's recommendations and proposes orders, once the crypto day has ended.",
  },
  { name: "submit", label: "Send approved orders", time: "every 5 minutes", detail: "Crypto trades at any hour, so this works any time." },
  {
    name: "protect",
    label: "Place missing stops",
    time: "every 5 minutes",
    detail: "Puts a stop-limit under each new position and cancels orders that sat unfilled.",
  },
  {
    name: "reconcile",
    label: "Check against the broker",
    time: "daily at 1:05 am ET",
    detail: "Compares the ledger with the broker and records the day's equity.",
  },
];

const FOREX_JOBS: Job[] = [
  {
    name: "nightly",
    label: "Run tonight's signals",
    time: "5:15 pm ET",
    detail: "Makes today's recommendations and proposes orders, once the forex day has closed at 5 pm ET.",
  },
  {
    name: "submit",
    label: "Send approved orders",
    time: "9:50 am ET",
    detail: "Works while the forex market is open, except the half hour around the 5 pm ET close.",
  },
  {
    name: "reconcile",
    label: "Check against the broker",
    time: "5:05 pm ET",
    detail: "Compares the ledger with the broker, records the day's equity and cancels orders that didn't fill.",
  },
];

const JOBS = { stocks: STOCK_JOBS, crypto: CRYPTO_JOBS, forex: FOREX_JOBS };

export function Jobs({ status, copy, onRun }: { status: Status; copy: BookCopy; onRun: (name: JobName) => Promise<void> }) {
  const [busy, setBusy] = useState<JobName | null>(null);

  async function run(name: JobName) {
    setBusy(name);
    try {
      await onRun(name);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel" aria-labelledby="jobs-title">
      <h2 id="jobs-title">Run a job now</h2>
      <p className="muted small">
        {status.scheduler_running
          ? copy.scheduleNote
          : (
            <>
              The scheduler is off, so these only run when you press them. Start it with{" "}
              <code>trader serve --scheduler</code>.
            </>
          )}
      </p>
      <ul className="jobs">
        {JOBS[copy.kind].map((job) => {
          const last = status.last_runs[job.name];
          return (
            <li key={job.name} className="job">
              <button type="button" className="btn btn-quiet" disabled={busy !== null} onClick={() => void run(job.name)}>
                {busy === job.name ? "Running" : job.label}
              </button>
              <span className="muted small">
                {job.name === "submit" && status.mode === "DEMO" ? "Sends them to the demo broker." : job.detail} Scheduled{" "}
                {job.time}. Last run {last ? moment(last.at) : "never"}.
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
