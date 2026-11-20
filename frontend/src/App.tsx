import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError, api, makeApi, saveToken } from "./api";
import { bookCopy } from "./book";
import { Checks } from "./components/Checks";
import { EquityChart } from "./components/EquityChart";
import { ErrorBoundary, Toast, TokenPrompt, Unreachable, type ToastMessage } from "./components/Feedback";
import { Jobs } from "./components/Jobs";
import { KillSwitch } from "./components/KillSwitch";
import { ModeBand } from "./components/ModeBand";
import { Recommendations } from "./components/Recommendations";
import { RiskMeters } from "./components/RiskMeters";
import { Scanner } from "./components/Scanner";
import { Settings } from "./components/Settings";
import { Stats } from "./components/Stats";
import { OrdersTable, PositionsTable } from "./components/Tables";
import { ACTION_WORD, actionOf, clockTime, moment, qty } from "./format";
import { LESSONS } from "./learn/course";
import { GlossaryView, LearnHome, LearnPanel, LessonView, QuizView, lessonsDone } from "./learn/LearnViews";
import { useRoute } from "./learn/route";
import type { Book, DeskData, JobName, JobResult, LearnProgress, Proposal, Risk, Status, Tone } from "./types";

type Load =
  | { kind: "loading" }
  | { kind: "ready"; data: DeskData; at: Date; path: string }
  | { kind: "error"; message: string }
  | { kind: "token" };

const REFRESH_MS = 30_000;
const NO_PROGRESS: LearnProgress = { lessons: {}, quizzes: {} };
// Until /books answers (or on an older server), the one book at /api.
const MAIN_BOOK: Book = { id: "stocks", label: "Stocks", path: "/api", account_label: "", mode: "DEMO", pending_proposals: 0 };

function spyTrendDesk(strategy: Status["strategy"], risk: Risk) {
  if (strategy.name !== "spy-trend") return null;
  const window = strategy.window;
  return {
    window: typeof window === "number" ? window : 200,
    stopPct: risk.limits.stop_loss_pct,
    capPct: risk.limits.max_position_pct,
  };
}

function describeStrategy(strategy: Status["strategy"]): string {
  if (strategy.name === "spy-trend")
    return `Hold SPY above its ${String(strategy.window)}-day average and BIL otherwise, one position for the whole account`;
  if (strategy.name === "trend")
    return `Trend following on a ${String(strategy.window)}-day average${strategy.shorts ? ", long and short," : ""}`;
  if (strategy.name === "momentum") return `Momentum: top ${String(strategy.top_n)} by ${String(strategy.lookback)}-day return`;
  return strategy.name;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function describeJob(outcome: JobResult): string {
  const result = outcome.result;
  if (result.skipped_reason) return String(result.skipped_reason);
  const count = (key: string) => (Array.isArray(result[key]) ? (result[key] as unknown[]).length : Number(result[key] ?? 0));
  const parts: string[] = [];

  if (outcome.job === "nightly") {
    if (count("pending")) parts.push(`${plural(count("pending"), "order")} waiting for you`);
    if (count("approved")) parts.push(`${count("approved")} approved automatically`);
    if (count("blocked")) parts.push(`${count("blocked")} blocked by the risk checks`);
    return parts.length ? `Signals are done: ${parts.join(", ")}.` : "Signals are done. No orders are needed.";
  }
  if (outcome.job === "submit") {
    if (count("submitted")) parts.push(`Sent ${plural(count("submitted"), "order")}`);
    if (count("dry_run")) parts.push(`Logged ${plural(count("dry_run"), "dry-run order")}`);
    if (count("blocked")) parts.push(`${count("blocked")} blocked by the risk checks`);
    if (count("expired")) parts.push(`${count("expired")} expired`);
    if (count("errors")) parts.push(plural(count("errors"), "error"));
    return parts.length ? `${parts.join(", ")}.` : "No approved orders to send.";
  }
  if (outcome.job === "protect") {
    if (count("placed")) parts.push(`Placed ${plural(count("placed"), "stop")}`);
    if (count("replaced")) parts.push(`resized ${plural(count("replaced"), "stop")}`);
    if (count("sold")) parts.push(`sold ${count("sold")} that had already fallen through its stop`);
    if (count("canceled_orders")) parts.push(`canceled ${plural(count("canceled_orders"), "stale order")}`);
    if (count("alerts")) parts.push(plural(count("alerts"), "warning"));
    if (count("errors")) parts.push(plural(count("errors"), "error"));
    return parts.length ? `${parts.join(", ")}.` : "Every position has its stop; nothing was stale.";
  }
  if (outcome.job === "scan") {
    const rows = Array.isArray(result.rows) ? (result.rows as { label: string }[]) : [];
    const ideas = rows.filter((row) => row.label === "buy_idea").length;
    return rows.length ? `Scanned ${plural(rows.length, "symbol")}: ${plural(ideas, "buy idea")}.` : "No prices for the watchlist.";
  }
  if (result.kill_switch_engaged) return "The account hit its drawdown limit, so the kill switch is now engaged.";
  return result.ok ? "The ledger matches the broker." : `The broker check found ${plural(count("mismatches"), "problem")}.`;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export default function App() {
  const route = useRoute();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [books, setBooks] = useState<Book[]>([]);
  // The desk on screen: the route's book, or the last one viewed while you're in Learn.
  const [bookId, setBookId] = useState<string | null>(route.view === "desk" ? route.book : null);
  useEffect(() => {
    if (route.view === "desk") setBookId(route.book);
  }, [route]);
  const book = books.find((b) => b.id === bookId) ?? books[0] ?? MAIN_BOOK;
  const client = useMemo(() => makeApi(book.path), [book.path]);
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const say = useCallback((text: string, tone: Tone = "neutral") => setToast({ id: Date.now(), text, tone }), []);
  const clearToast = useCallback(() => setToast(null), []);
  const schedulerOn = useRef(false);
  useEffect(() => {
    if (load.kind === "ready") schedulerOn.current = load.data.status.scheduler_running;
  }, [load]);

  const refresh = useCallback(async () => {
    const path = book.path;
    try {
      const [status, listed] = await Promise.all([client.status(), api.books().catch(() => null)]);
      if (listed && listed.length) setBooks(listed);
      const results = await Promise.allSettled([
        client.proposals("pending"),
        client.proposals(null, 30),
        client.positions(),
        client.orders(),
        client.equity(),
        client.risk(),
        client.aiDecisions(),
        client.recommendations(),
        client.scan(),
        api.learnProgress(),
      ] as const);
      const pick = <T,>(result: PromiseSettledResult<T>, fallback: T): T =>
        result.status === "fulfilled" ? result.value : fallback;
      const [pending, recent, positions, orders, equity, risk, ai, recommendations, scan, progress] = results;
      if (risk.status === "rejected") throw risk.reason;
      setLoad({
        kind: "ready",
        at: new Date(),
        path,
        data: {
          status,
          pending: pick(pending, []),
          recent: pick(recent, []),
          positions: pick(positions, []),
          orders: pick(orders, []),
          equity: pick(equity, []),
          risk: risk.value,
          ai: pick(ai, []),
          recommendations: pick(recommendations, null),
          scan: pick(scan, null),
          progress: pick(progress, NO_PROGRESS),
        },
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setLoad({ kind: "token" });
        return;
      }
      setLoad((previous) => {
        if (previous.kind === "ready") {
          say(`Couldn't refresh: ${errorText(error)}`, "bad");
          return previous;
        }
        return { kind: "error", message: errorText(error) };
      });
    }
  }, [book.path, client, say]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refresh]);

  const decide = useCallback(
    async (proposal: Proposal, approve: boolean) => {
      const what = `${ACTION_WORD[actionOf(proposal.side, proposal.kind)].toLowerCase()} ${qty(proposal.qty)} ${proposal.symbol}`;
      try {
        if (approve) {
          await client.approve(proposal.id);
          const copy = bookCopy(load.kind === "ready" ? load.data.status : null);
          const when = schedulerOn.current ? copy.approvedToast : "Press Send approved orders to send it.";
          say(`Approved: ${what}. ${when}`, "good");
        } else {
          await client.reject(proposal.id);
          say(`Rejected: ${what}.`);
        }
      } catch (error) {
        say(errorText(error), "bad");
      }
      await refresh();
    },
    [client, load, refresh, say],
  );

  const engage = useCallback(
    async (reason: string) => {
      try {
        await client.killSwitch({ engage: true, reason });
        say("Kill switch engaged. Pending entries were canceled; stops stay in place.", "bad");
      } catch (error) {
        say(errorText(error), "bad");
      }
      await refresh();
    },
    [client, refresh, say],
  );

  const release = useCallback(async () => {
    try {
      await client.killSwitch({ engage: false, confirm: "RELEASE" });
      say("Kill switch released. New orders are allowed again.", "good");
    } catch (error) {
      say(errorText(error), "bad");
    }
    await refresh();
  }, [client, refresh, say]);

  const runJob = useCallback(
    async (name: JobName) => {
      try {
        say(describeJob(await client.runJob(name)));
      } catch (error) {
        say(errorText(error), "bad");
      }
      await refresh();
    },
    [client, refresh, say],
  );

  const setProgress = useCallback((progress: LearnProgress) => {
    setLoad((previous) => (previous.kind === "ready" ? { ...previous, data: { ...previous.data, progress } } : previous));
  }, []);

  const markLesson = useCallback(
    async (id: string, done: boolean) => {
      try {
        setProgress(await api.markLesson(id, done));
        if (done) say("Lesson marked as done.", "good");
      } catch (error) {
        say(`Couldn't save your progress: ${errorText(error)}`, "bad");
      }
    },
    [say, setProgress],
  );

  const recordQuiz = useCallback(
    async (moduleId: string, score: number, total: number) => {
      try {
        setProgress(await api.recordQuiz(moduleId, score, total));
      } catch (error) {
        say(`Couldn't save your quiz score: ${errorText(error)}`, "bad");
      }
    },
    [say, setProgress],
  );

  if (load.kind === "loading" || (load.kind === "ready" && load.path !== book.path))
    return <p className="boot">Loading the {book.id === "stocks" ? "trading" : book.id} desk</p>;
  if (load.kind === "token")
    return (
      <TokenPrompt
        onSave={(token) => {
          saveToken(token);
          setLoad({ kind: "loading" });
          void refresh();
        }}
      />
    );
  if (load.kind === "error") return <Unreachable message={load.message} onRetry={() => void refresh()} />;

  const { data, at } = load;
  const { status, risk, progress } = data;
  const copy = bookCopy(status);
  const spyTrend = spyTrendDesk(status.strategy, risk);
  const onDesk = route.view === "desk";
  const market = copy.market
    ? copy.market
    : status.mode === "DEMO"
      ? "The demo market never closes, so you can send orders at any hour."
      : status.clock
        ? status.clock.is_open
          ? "The market is open."
          : `The market is closed; it opens ${moment(status.clock.next_open)}.`
        : "";
  const deskTabs = books.length ? books : [book];

  return (
    <>
      <ModeBand status={status} />
      <main className="desk">
        <nav className="tabs" aria-label="Sections">
          {deskTabs.map((tab) => {
            const current = onDesk && tab.id === book.id;
            const waiting = tab.id === book.id ? data.pending.length : tab.pending_proposals;
            return (
              <a key={tab.id} href={tab.path === "/api" ? "#/" : `#/${tab.id}`} aria-current={current ? "page" : undefined}>
                {deskTabs.length > 1 ? tab.label : "Desk"}
                {waiting > 0 && <span className="tab-count">{waiting} waiting</span>}
              </a>
            );
          })}
          <a href="#/learn" aria-current={onDesk ? undefined : "page"}>
            Learn
            <span className="tab-count">
              {lessonsDone(progress)} of {LESSONS.length}
            </span>
          </a>
        </nav>

        <ErrorBoundary resetKey={window.location.hash}>
        {route.view === "learn" && <LearnHome progress={progress} />}
        {route.view === "lesson" && <LessonView id={route.id} progress={progress} onMark={markLesson} />}
        {route.view === "quiz" && <QuizView key={route.id} id={route.id} progress={progress} onQuiz={recordQuiz} />}
        {route.view === "glossary" && <GlossaryView />}

        {onDesk && (
          <>
            <header className="desk-head">
              <div>
                <h1>{copy.title}</h1>
                <p className="muted">
                  {status.strategy.name === "spy-trend"
                    ? `${describeStrategy(status.strategy)}, measured against ${status.benchmark}. `
                    : `${describeStrategy(status.strategy)} across ${copy.holdings(status.universe.length)}, measured against ${status.benchmark}. `}
                  {market}
                </p>
              </div>
              <KillSwitch state={status.kill_switch} onEngage={engage} onRelease={release} />
            </header>

            {status.broker_error && (
              <p className="notice notice-bad" role="alert">
                Can't read the account from the broker: {status.broker_error}
              </p>
            )}
            {status.account && (
              <Stats account={status.account} maxPositions={spyTrend ? 1 : risk.limits.max_open_positions} />
            )}

            <div className="main-grid">
              <Recommendations
                recs={data.recommendations}
                pending={data.pending}
                recent={data.recent}
                equity={status.account?.equity ?? null}
                schedulerRunning={status.scheduler_running}
                copy={copy}
                onDecide={decide}
                spyTrend={spyTrend}
              />
              <div className="side">
                <EquityChart points={data.equity} benchmark={status.benchmark} />
                <RiskMeters risk={risk} kind={copy.kind} spyTrend={spyTrend} />
                <Settings
                  key={book.path}
                  client={client}
                  kind={copy.kind}
                  spyTrend={spyTrend}
                  onSaved={(message) => {
                    say(message, "good");
                    void refresh();
                  }}
                />
              </div>
            </div>

            <PositionsTable positions={data.positions} copy={copy} averageExit={spyTrend != null} />
            {copy.kind === "stocks" && <Scanner scan={data.scan} />}
            <OrdersTable orders={data.orders} copy={copy} />

            <div className="lower">
              <LearnPanel progress={progress} />
              <Checks status={status} ai={data.ai} />
              <Jobs status={status} copy={copy} onRun={runJob} />
            </div>
          </>
        )}
        </ErrorBoundary>

        <footer className="foot muted small">
          Updated {clockTime(at)}; refreshes every 30 seconds. Account {status.account_label}. This tool places only the
          orders its rules and limits allow; it is not investment advice.
        </footer>
      </main>
      <Toast message={toast} onDone={clearToast} />
    </>
  );
}
