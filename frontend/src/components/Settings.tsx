import { useEffect, useState, type FormEvent } from "react";

import { ApiError, type Api } from "../api";
import type { BookKind } from "../book";
import { pct } from "../format";
import type { Notice, Preferences, PreferencesChange, PreferencesResult } from "../types";
import { Term } from "./Term";

interface Props {
  client: Api;
  kind: BookKind;
  /** Called after a change takes effect, with the server's one-line summary. */
  onSaved: (message: string) => void;
}

type PairSet = "standard" | "exotic";

interface Draft {
  stop: string;
  pairSet: PairSet | "custom";
  shorts: boolean;
}

function draftOf(prefs: Preferences): Draft {
  return {
    stop: String(prefs.stop_loss_pct),
    pairSet: prefs.forex?.pair_set ?? "custom",
    shorts: prefs.forex?.allow_shorts ?? false,
  };
}

const SET_WORDS: Record<PairSet, { name: string; blurb: string }> = {
  standard: { name: "Standard", blurb: "The seven majors: the most traded pairs, with the tightest spreads." },
  exotic: { name: "Exotic", blurb: "The dollar against six emerging-market currencies: most swing more, and all cost more to trade." },
};

function changesOf(prefs: Preferences, draft: Draft): PreferencesChange {
  const change: PreferencesChange = {};
  const stop = Number(draft.stop);
  const newSet = prefs.forex && draft.pairSet !== "custom" && draft.pairSet !== prefs.forex.pair_set ? draft.pairSet : null;
  if (newSet) {
    change.pair_set = newSet;
    // A new pair set starts from its own recommended stop; send a stop only if you typed another.
    if (Number.isFinite(stop) && stop !== prefs.forex?.pair_sets[newSet].stop_loss_pct) change.stop_loss_pct = stop;
  } else if (Number.isFinite(stop) && stop !== prefs.stop_loss_pct) {
    change.stop_loss_pct = stop;
  }
  if (prefs.forex && draft.shorts !== prefs.forex.allow_shorts) change.allow_shorts = draft.shorts;
  return change;
}

/** The book's own settings: the stop-loss, and for forex the pair set and short selling. Riskier
 * choices come back with plain warnings, and only take effect once you confirm them. */
export function Settings({ client, kind, onSaved }: Props) {
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [warnings, setWarnings] = useState<Notice[] | null>(null);
  const [agreed, setAgreed] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    client
      .preferences()
      .then((loaded) => {
        if (!live) return;
        setPrefs(loaded);
        setDraft(draftOf(loaded));
      })
      .catch(() => live && setPrefs(null));
    return () => {
      live = false;
    };
  }, [client]);

  if (!prefs || !draft) return null;

  const change = changesOf(prefs, draft);
  const pending = Object.keys(change).length > 0;
  const [low, high] = prefs.stop_range;
  const stop = Number(draft.stop);
  const stopValid = Number.isFinite(stop) && stop >= low && stop <= high;
  const pairSet = draft.pairSet === "custom" ? null : prefs.forex?.pair_sets[draft.pairSet];
  // Picking a new pair set brings that set's recommended stop, unless you type your own.
  const recommended = change.pair_set && pairSet ? pairSet.stop_loss_pct : prefs.recommended_stop_loss_pct;
  const wider = stopValid && stop > recommended;

  function reset() {
    setWarnings(null);
    setAgreed(false);
    setProblem(null);
  }

  function edit(next: Partial<Draft>) {
    setDraft((current) => (current ? { ...current, ...next } : current));
    reset();
  }

  async function save(confirm: boolean) {
    setBusy(true);
    setProblem(null);
    try {
      const result: PreferencesResult = await client.savePreferences({ ...change, confirm });
      if (result.preferences) {
        setPrefs(result.preferences);
        setDraft(draftOf(result.preferences));
      }
      reset();
      onSaved(result.message);
    } catch (error) {
      const detail = error instanceof ApiError ? (error.detail as PreferencesResult | null) : null;
      if (detail?.status === "needs_confirm") {
        setWarnings(detail.notices.filter((notice) => notice.level === "warning"));
        setAgreed(false);
      } else {
        setProblem(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setBusy(false);
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (pending && stopValid) void save(false);
  };

  return (
    <section className="panel settings" aria-labelledby="settings-title">
      <h2 id="settings-title">Your settings</h2>
      <form onSubmit={submit} className="settings-form">
        <div className="setting">
          <label htmlFor="stop-loss">
            <Term id="stop-order">Stop-loss</Term>
          </label>
          <div className="stop-field">
            <input
              id="stop-loss"
              type="number"
              inputMode="decimal"
              min={low}
              max={high}
              step={0.5}
              value={draft.stop}
              onChange={(event) => edit({ stop: event.target.value })}
              aria-describedby="stop-help"
            />
            <span className="unit">%</span>
            {stop !== recommended && (
              <button type="button" className="btn btn-quiet btn-small" onClick={() => edit({ stop: String(recommended) })}>
                Use {recommended}%
              </button>
            )}
          </div>
          <p id="stop-help" className="muted small">
            {stopValid ? (
              <>
                Recommended: {recommended}%{kind === "forex" && draft.shorts ? " below a buy, above a short" : " below the entry"}.{" "}
                {!pending && `A full stop-out costs about ${pct(prefs.max_loss_per_position_pct, 2)} of the account.`}
              </>
            ) : (
              `Pick a stop between ${low}% and ${high}%.`
            )}
          </p>
          {wider && !warnings && (
            <p className="setting-caution small">
              Wider than recommended: losses run further before the app gets you out. You'll see the full warning before
              it takes effect.
            </p>
          )}
        </div>

        {prefs.forex && (
          <fieldset className="setting">
            <legend>Pairs</legend>
            {(["standard", "exotic"] as const).map((name) => {
              const set = prefs.forex!.pair_sets[name];
              return (
                <label key={name} className={`choice ${draft.pairSet === name ? "choice-on" : ""}`}>
                  <input
                    type="radio"
                    name="pair-set"
                    value={name}
                    checked={draft.pairSet === name}
                    onChange={() => edit({ pairSet: name, stop: String(set.stop_loss_pct) })}
                  />
                  <span className="choice-text">
                    <span className="choice-name">{SET_WORDS[name].name}</span>
                    <span className="muted small">
                      {SET_WORDS[name].blurb} {set.stop_loss_pct}% stop, up to {set.max_position_pct}% of the account per pair.
                    </span>
                    <span className="choice-pairs small">{set.pairs.join("  ")}</span>
                  </span>
                </label>
              );
            })}
            {draft.pairSet === "custom" && (
              <p className="muted small">Your settings file lists its own pairs: {prefs.forex.pairs.join(", ")}.</p>
            )}
          </fieldset>
        )}

        {prefs.forex && prefs.forex.shorts_available && (
          <div className="setting">
            <label className={`choice ${draft.shorts ? "choice-on" : ""}`}>
              <input type="checkbox" checked={draft.shorts} onChange={(event) => edit({ shorts: event.target.checked })} />
              <span className="choice-text">
                <span className="choice-name">
                  Allow <Term id="short-selling">short selling</Term>
                </span>
                <span className="muted small">
                  Off unless you switch it on. When a pair falls below its average, the book may sell it short: it gains if
                  the pair keeps falling and loses if it rises.
                </span>
              </span>
            </label>
          </div>
        )}

        {warnings && warnings.length > 0 ? (
          <div className="caution" role="alert">
            <p className="caution-head">Before this takes effect</p>
            {warnings.map((notice) => (
              <div key={notice.title} className="caution-notice">
                <p className="caution-title">{notice.title}</p>
                <ul>
                  {notice.lines.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            ))}
            <label className="caution-agree">
              <input type="checkbox" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} />
              I've read these warnings and want this change.
            </label>
            <div className="caution-actions">
              <button type="button" className="btn btn-stop" disabled={!agreed || busy} onClick={() => void save(true)}>
                Make the change
              </button>
              <button
                type="button"
                className="btn btn-quiet"
                disabled={busy}
                onClick={() => {
                  setDraft(draftOf(prefs));
                  reset();
                }}
              >
                Keep my settings
              </button>
            </div>
          </div>
        ) : (
          <div className="settings-actions">
            <button type="submit" className="btn btn-go" disabled={!pending || !stopValid || busy}>
              Save changes
            </button>
            {pending && (
              <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => edit(draftOf(prefs))}>
                Undo
              </button>
            )}
          </div>
        )}
        {problem && (
          <p className="notice notice-bad small" role="alert">
            {problem}
          </p>
        )}
      </form>

      {prefs.notes.length > 0 && !pending && (
        <div className="standing">
          {prefs.notes.map((notice) => (
            <details key={notice.title} className="standing-note">
              <summary>{notice.title}</summary>
              <ul>
                {notice.lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      )}
      <p className="muted small settings-foot">
        A change applies to new orders; open positions keep the stops they have, and proposals still waiting expire so
        the next nightly plan sizes them again.
      </p>
    </section>
  );
}
