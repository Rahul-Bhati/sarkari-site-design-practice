"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState, useTransition } from "react";
import { CATEGORIES, STATES } from "@/lib/constants";
import { cn } from "@/lib/utils";

/**
 * Filter state lives in the URL so a filtered feed is shareable and the back
 * button works. Each control rewrites the query string and lets the server
 * component re-fetch.
 */
function useFilterNav() {
  const router = useRouter();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();

  const setParam = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (!value || value === "all" || value === "ALL_STATES") {
        next.delete(key);
      } else {
        next.set(key, value);
      }
      next.delete("page"); // any filter change resets pagination
      startTransition(() => {
        router.push(next.toString() ? `/feed?${next}` : "/feed", { scroll: false });
      });
    },
    [params, router],
  );

  return { params, setParam, pending };
}

export function CategoryFilter() {
  const { params, setParam } = useFilterNav();
  const active = params.get("category") ?? "all";

  return (
    <div
      className="no-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1 pb-1"
      role="group"
      aria-label="Filter by category"
    >
      {CATEGORIES.map((c) => {
        const selected = active === c.id;
        return (
          <button
            key={c.id}
            type="button"
            aria-pressed={selected}
            onClick={() => setParam("category", c.id)}
            className={cn(
              "shrink-0 rounded-full border px-4 py-2 text-sm font-semibold transition-colors",
              selected
                ? "border-transparent text-white"
                : "border-border bg-surface text-muted hover:border-border-hover hover:text-ink",
            )}
            style={selected ? { backgroundColor: c.color } : undefined}
          >
            <span aria-hidden className="mr-1.5">
              {c.icon}
            </span>
            {c.label}
          </button>
        );
      })}
    </div>
  );
}

export function StateFilter() {
  const { params, setParam } = useFilterNav();

  return (
    <select
      aria-label="Filter by state"
      value={params.get("state") ?? "ALL_STATES"}
      onChange={(e) => setParam("state", e.target.value)}
      className="w-full cursor-pointer rounded-xl border border-border bg-surface px-4 py-2.5 text-sm text-ink hover:border-border-hover focus:border-primary focus:outline-none sm:w-56"
    >
      <option value="ALL_STATES">Every state</option>
      {STATES.map((s) => (
        <option key={s.code} value={s.code}>
          {s.label}
        </option>
      ))}
    </select>
  );
}

export function SortFilter() {
  const { params, setParam } = useFilterNav();

  return (
    <select
      aria-label="Sort results"
      value={params.get("sort") ?? "published_at"}
      onChange={(e) => setParam("sort", e.target.value)}
      className="w-full cursor-pointer rounded-xl border border-border bg-surface px-4 py-2.5 text-sm text-ink hover:border-border-hover focus:border-primary focus:outline-none sm:w-44"
    >
      <option value="published_at">Newest first</option>
      <option value="deadline">Deadline soonest</option>
    </select>
  );
}

export function SearchBar({ autoFocus = false }: { autoFocus?: boolean }) {
  const { params, setParam, pending } = useFilterNav();
  const [value, setValue] = useState(params.get("search") ?? "");

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        setParam("search", value.trim() || null);
      }}
      className="flex gap-2"
    >
      <div className="relative grow">
        <span
          aria-hidden
          className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-muted"
        >
          🔍
        </span>
        <input
          type="search"
          autoFocus={autoFocus}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Search tenders, jobs, schemes…"
          aria-label="Search government updates"
          className="w-full rounded-xl border border-border bg-surface py-3 pl-11 pr-4 text-sm text-ink placeholder:text-faint hover:border-border-hover focus:border-primary focus:outline-none"
        />
      </div>
      <button
        type="submit"
        disabled={pending}
        className="shrink-0 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white transition-colors hover:bg-primary-dim disabled:opacity-60"
      >
        {pending ? "…" : "Search"}
      </button>
    </form>
  );
}

export function ActiveFilters() {
  const { params, setParam } = useFilterNav();
  const chips: { key: string; label: string }[] = [];

  const category = params.get("category");
  if (category && category !== "all") {
    chips.push({
      key: "category",
      label: CATEGORIES.find((c) => c.id === category)?.label ?? category,
    });
  }
  const state = params.get("state");
  if (state) {
    chips.push({
      key: "state",
      label: STATES.find((s) => s.code === state)?.label ?? state,
    });
  }
  const search = params.get("search");
  if (search) chips.push({ key: "search", label: `"${search}"` });

  if (chips.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="text-faint">Filtered by</span>
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={() => setParam(chip.key, null)}
          className="rounded-full border border-border bg-surface px-3 py-1 text-muted transition-colors hover:border-rule hover:text-rule"
        >
          {chip.label} ✕
        </button>
      ))}
    </div>
  );
}
