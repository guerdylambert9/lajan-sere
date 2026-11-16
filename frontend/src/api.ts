import type {
  AIDecision,
  Book,
  EquityPoint,
  JobName,
  JobResult,
  KillSwitchState,
  LearnProgress,
  Order,
  Position,
  Preferences,
  PreferencesChange,
  PreferencesResult,
  Proposal,
  Recommendations,
  Reconciliation,
  Risk,
  ScanResult,
  Status,
} from "./types";

const TOKEN_KEY = "trading-desk-api-token";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    /** The server's answer when it is more than a sentence (a settings change's warnings). */
    public readonly detail: unknown = null,
  ) {
    super(message);
  }
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveToken(value: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, value.trim());
  } catch {
    // Storage can be unavailable (private mode); the token then lasts for this page only.
  }
}

async function request<T>(base: string, path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the trading API.");
  }
  if (!response.ok) {
    let detail = response.statusText || `Request failed (${response.status})`;
    let extra: unknown = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail && typeof body.detail === "object") {
        extra = body.detail;
        const message = (body.detail as { message?: unknown }).message;
        if (typeof message === "string" && message) detail = message;
      }
    } catch {
      // Not JSON; keep the status text.
    }
    throw new ApiError(response.status, detail, extra);
  }
  return (await response.json()) as T;
}

const post = { method: "POST" } as const;

/** The API of one book: "/api" for the main one, "/api/crypto" for the crypto book beside it. */
export function makeApi(base = "/api") {
  const get = <T,>(path: string, init?: RequestInit) => request<T>(base, path, init);
  return {
    status: () => get<Status>("/status"),
    books: () => get<Book[]>("/books"),
    proposals: (status: string | null, limit = 100) => {
      const query = new URLSearchParams({ limit: String(limit) });
      if (status) query.set("status", status);
      return get<Proposal[]>(`/proposals?${query}`);
    },
    approve: (id: number) => get<Proposal>(`/proposals/${id}/approve`, post),
    reject: (id: number) => get<Proposal>(`/proposals/${id}/reject`, post),
    positions: () => get<Position[]>("/positions"),
    orders: (limit = 40) => get<Order[]>(`/orders?limit=${limit}`),
    equity: () => get<EquityPoint[]>("/equity"),
    risk: () => get<Risk>("/risk"),
    aiDecisions: (limit = 12) => get<AIDecision[]>(`/ai-decisions?limit=${limit}`),
    reconciliations: (limit = 5) => get<Reconciliation[]>(`/reconciliations?limit=${limit}`),
    killSwitch: (body: { engage: boolean; reason?: string; confirm?: string }) =>
      get<KillSwitchState>("/kill-switch", { method: "POST", body: JSON.stringify(body) }),
    runJob: (name: JobName) => get<JobResult>(`/jobs/${name}`, post),
    recommendations: () => get<Recommendations>("/recommendations"),
    preferences: () => get<Preferences>("/preferences"),
    savePreferences: (change: PreferencesChange) =>
      get<PreferencesResult>("/preferences", { method: "PUT", body: JSON.stringify(change) }),
    scan: () => get<ScanResult>("/scan"),
    learnProgress: () => get<LearnProgress>("/learn/progress"),
    markLesson: (id: string, done: boolean) =>
      get<LearnProgress>(`/learn/lessons/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ done }) }),
    recordQuiz: (moduleId: string, score: number, total: number) =>
      get<LearnProgress>(`/learn/quizzes/${encodeURIComponent(moduleId)}`, {
        method: "POST",
        body: JSON.stringify({ score, total }),
      }),
  };
}

export type Api = ReturnType<typeof makeApi>;

export const api = makeApi("/api");
