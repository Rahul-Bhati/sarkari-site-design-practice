import type {
  EntriesResponse,
  Entry,
  EntryFilters,
  StatsResponse,
  SubscribePayload,
} from "@/types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type FetchOptions = RequestInit & {
  /** Seconds. Server components use this for ISR; omit for no caching. */
  revalidate?: number;
  token?: string;
};

async function request<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { revalidate, token, headers, ...init } = options;

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    ...(revalidate !== undefined
      ? { next: { revalidate } }
      : { cache: "no-store" as const }),
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // Non-JSON error body — keep the status text.
    }
    throw new ApiError(
      typeof detail === "string" ? detail : "Request failed",
      res.status,
    );
  }

  return res.json() as Promise<T>;
}

function toQuery(filters: EntryFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "" || value === "all") {
      continue;
    }
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  entries: (filters: EntryFilters = {}, revalidate?: number) =>
    request<EntriesResponse>(`/api/entries${toQuery(filters)}`, { revalidate }),

  entry: (id: string, revalidate?: number) =>
    request<Entry>(`/api/entries/${id}`, { revalidate }),

  relatedEntries: (id: string, revalidate?: number) =>
    request<Entry[]>(`/api/entries/${id}/related`, { revalidate }),

  stats: (revalidate?: number) =>
    request<StatsResponse>("/api/stats", { revalidate }),

  subscribe: (payload: SubscribePayload) =>
    request<{ success: boolean; message: string }>("/api/subscribe", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  bookmarks: (token: string) =>
    request<{ entries: Entry[]; total: number }>("/api/bookmarks", { token }),

  toggleBookmark: (id: string, token: string) =>
    request<{ bookmarked: boolean }>(`/api/bookmarks/${id}`, {
      method: "POST",
      token,
    }),

  preferences: (token: string) =>
    request<Record<string, unknown>>("/api/preferences", { token }),

  updatePreferences: (body: Record<string, unknown>, token: string) =>
    request<{ success: boolean }>("/api/preferences", {
      method: "PATCH",
      body: JSON.stringify(body),
      token,
    }),

  plan: (token: string) =>
    request<{ plan: string; expires_at: string | null; features: string[] }>(
      "/api/payments/plan",
      { token },
    ),

  createSubscription: (
    body: { plan: string; period: string },
    token: string,
  ) =>
    request<{ subscription_id: string; short_url: string; amount_inr: number }>(
      "/api/payments/create-subscription",
      { method: "POST", body: JSON.stringify(body), token },
    ),

  admin: {
    pending: (token: string, page = 1) =>
      request<{ entries: Entry[]; total: number; has_more: boolean }>(
        `/api/admin/entries/pending?page=${page}`,
        { token },
      ),

    approve: (id: string, token: string) =>
      request<{ success: boolean }>(`/api/admin/entries/${id}/approve`, {
        method: "PATCH",
        token,
      }),

    reject: (id: string, token: string) =>
      request<{ success: boolean }>(`/api/admin/entries/${id}/reject`, {
        method: "PATCH",
        token,
      }),

    edit: (id: string, body: Record<string, unknown>, token: string) =>
      request<{ success: boolean }>(`/api/admin/entries/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
        token,
      }),

    bulkApprove: (entryIds: string[], token: string) =>
      request<{ approved: number }>("/api/admin/entries/bulk-approve", {
        method: "POST",
        body: JSON.stringify({ entry_ids: entryIds }),
        token,
      }),

    scraperStatus: (token: string) =>
      request<{ sources: unknown[] }>("/api/admin/scraper-status", { token }),

    runScraper: (token: string, source?: string) =>
      request<{ success: boolean; results: unknown[] }>(
        `/api/admin/scrape${source ? `?source=${source}` : ""}`,
        { method: "POST", token },
      ),

    process: (token: string) =>
      request<Record<string, unknown>>("/api/admin/process", {
        method: "POST",
        token,
      }),
  },
};
