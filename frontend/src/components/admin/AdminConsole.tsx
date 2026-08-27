"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { categoryMeta, formatDate, relativeTime, stateLabel } from "@/lib/utils";
import type { Entry, ScraperSource } from "@/types";

type Tab = "queue" | "sources";

export function AdminConsole() {
  const [tab, setTab] = useState<Tab>("queue");
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    createClient()
      .auth.getSession()
      .then(({ data }) => setToken(data.session?.access_token ?? null));
  }, []);

  if (!token) return <div className="skeleton mt-8 h-64 rounded-2xl" />;

  return (
    <>
      <div className="mt-6 flex gap-2">
        {(
          [
            ["queue", "Review queue"],
            ["sources", "Scraper health"],
          ] as [Tab, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={
              tab === id
                ? "rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-white"
                : "rounded-xl border border-border bg-surface px-4 py-2 text-sm font-semibold text-muted hover:text-ink"
            }
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "queue" ? <ReviewQueue token={token} /> : <ScraperHealth token={token} />}
    </>
  );
}

function ReviewQueue({ token }: { token: string }) {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.admin.pending(token);
      setEntries(data.entries);
      setSelected(new Set());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load the queue");
      setEntries([]);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(id: string, action: "approve" | "reject") {
    setBusy(true);
    try {
      await (action === "approve"
        ? api.admin.approve(id, token)
        : api.admin.reject(id, token));
      setEntries((prev) => prev?.filter((e) => e.id !== id) ?? null);
      toast.success(action === "approve" ? "Approved" : "Rejected");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  async function bulkApprove() {
    if (selected.size === 0) return;
    setBusy(true);
    try {
      const res = await api.admin.bulkApprove([...selected], token);
      toast.success(`Approved ${res.approved} entries`);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Bulk approve failed");
    } finally {
      setBusy(false);
    }
  }

  async function runAi() {
    setBusy(true);
    try {
      const report = await api.admin.process(token);
      toast.success(
        `Processed ${report.processed ?? 0}, approved ${report.approved ?? 0}`,
      );
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Processing failed");
    } finally {
      setBusy(false);
    }
  }

  if (entries === null) return <div className="skeleton mt-6 h-64 rounded-2xl" />;

  return (
    <div className="mt-6">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted">{entries.length} awaiting review</span>
        <span className="grow" />
        <Button size="sm" variant="secondary" onClick={runAi} loading={busy}>
          Run AI batch
        </Button>
        <Button
          size="sm"
          onClick={bulkApprove}
          disabled={selected.size === 0 || busy}
        >
          Approve selected ({selected.size})
        </Button>
      </div>

      {entries.length === 0 ? (
        <div className="rounded-2xl border border-border bg-card p-10 text-center text-sm text-muted">
          Queue is clear.
        </div>
      ) : (
        <div className="space-y-4">
          {entries.map((entry) => {
            const category = categoryMeta(entry.category);
            const confidence = Math.round((entry.ai_confidence ?? 0) * 100);
            const checked = selected.has(entry.id);
            return (
              <div
                key={entry.id}
                className="rounded-2xl border border-border bg-card p-5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="checkbox"
                    checked={checked}
                    aria-label={`Select ${entry.title}`}
                    onChange={() =>
                      setSelected((prev) => {
                        const next = new Set(prev);
                        if (checked) next.delete(entry.id);
                        else next.add(entry.id);
                        return next;
                      })
                    }
                    className="size-4 accent-[#FF6B35]"
                  />
                  <Badge color={category.color}>{category.label}</Badge>
                  <Badge>{stateLabel(entry.state)}</Badge>
                  <Badge color={confidence >= 90 ? "#10B981" : "#F59E0B"}>
                    {confidence}% confident
                  </Badge>
                  <span className="grow" />
                  <span className="text-xs text-faint">
                    {relativeTime(entry.created_at)}
                  </span>
                </div>

                <h3 className="mt-3 font-bold text-ink">{entry.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  {entry.summary_en}
                </p>
                {entry.summary_hi && (
                  <p
                    className="mt-2 text-sm leading-relaxed text-muted/75"
                    lang="hi"
                  >
                    {entry.summary_hi}
                  </p>
                )}

                <div className="mt-3 flex flex-wrap gap-x-4 text-xs text-faint">
                  {entry.deadline && <span>Deadline {formatDate(entry.deadline)}</span>}
                  {entry.department && <span>{entry.department}</span>}
                </div>

                <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
                  <Button size="sm" onClick={() => act(entry.id, "approve")} disabled={busy}>
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => act(entry.id, "reject")}
                    disabled={busy}
                  >
                    Reject
                  </Button>
                  <a
                    href={entry.original_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-muted hover:text-ink"
                  >
                    Open source ↗
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const HEALTH_COLORS = {
  green: "#10B981",
  yellow: "#F59E0B",
  red: "#EF4444",
} as const;

function ScraperHealth({ token }: { token: string }) {
  const [sources, setSources] = useState<ScraperSource[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.admin.scraperStatus(token);
      setSources(data.sources as ScraperSource[]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not load sources");
      setSources([]);
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(key?: string) {
    setBusy(key ?? "all");
    try {
      await api.admin.runScraper(token, key);
      toast.success(key ? `Ran ${key}` : "Ran all scrapers");
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Scrape failed");
    } finally {
      setBusy(null);
    }
  }

  if (sources === null) return <div className="skeleton mt-6 h-64 rounded-2xl" />;

  return (
    <div className="mt-6">
      <div className="mb-4 flex justify-end">
        <Button size="sm" onClick={() => run()} loading={busy === "all"}>
          Run all scrapers
        </Button>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-surface text-left text-xs uppercase tracking-wide text-faint">
            <tr>
              <th className="p-3 font-semibold">Source</th>
              <th className="p-3 font-semibold">Last run</th>
              <th className="p-3 font-semibold">Last success</th>
              <th className="p-3 font-semibold">Failures</th>
              <th className="p-3 font-semibold">Total</th>
              <th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id} className="border-t border-border">
                <td className="p-3">
                  <div className="flex items-center gap-2">
                    <span
                      aria-label={`Health: ${s.health}`}
                      className="size-2 shrink-0 rounded-full"
                      style={{ background: HEALTH_COLORS[s.health] }}
                    />
                    <div>
                      <div className="font-semibold text-ink">{s.name}</div>
                      <div className="text-xs text-faint">{s.scraper_key}</div>
                    </div>
                  </div>
                </td>
                <td className="p-3 text-muted">{relativeTime(s.last_run_at) || "never"}</td>
                <td className="p-3 text-muted">
                  {relativeTime(s.last_success_at) || "never"}
                </td>
                <td className="p-3 text-muted">{s.consecutive_failures}</td>
                <td className="p-3 text-muted">{s.total_entries_scraped}</td>
                <td className="p-3 text-right">
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={!s.registered || busy !== null}
                    loading={busy === s.scraper_key}
                    onClick={() => run(s.scraper_key)}
                  >
                    Run
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sources.some((s) => s.last_error) && (
        <div className="mt-4 rounded-2xl border border-rule/30 bg-rule/5 p-4">
          <h3 className="text-xs font-semibold uppercase text-rule">Recent errors</h3>
          <ul className="mt-2 space-y-1.5 text-xs text-muted">
            {sources
              .filter((s) => s.last_error)
              .map((s) => (
                <li key={s.id}>
                  <span className="font-semibold text-ink">{s.scraper_key}:</span>{" "}
                  {s.last_error}
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  );
}
