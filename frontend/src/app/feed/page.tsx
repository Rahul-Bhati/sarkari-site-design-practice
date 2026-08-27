import Link from "next/link";
import { Suspense } from "react";
import { FeedCard } from "@/components/feed/FeedCard";
import { FeedSkeleton } from "@/components/feed/FeedSkeleton";
import {
  ActiveFilters,
  CategoryFilter,
  SearchBar,
  SortFilter,
  StateFilter,
} from "@/components/feed/Filters";
import { api } from "@/lib/api";
import type { EntriesResponse, EntryFilters } from "@/types";

export const revalidate = 300;

export const metadata = {
  title: "Feed",
  description:
    "Every government update we track — filter by category, state and deadline.",
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function toFilters(params: Record<string, string | string[] | undefined>): EntryFilters {
  const one = (key: string) => {
    const value = params[key];
    return Array.isArray(value) ? value[0] : value;
  };
  const page = Number(one("page") ?? 1);

  return {
    category: one("category"),
    state: one("state"),
    search: one("search"),
    urgency: one("urgency"),
    sort: (one("sort") as EntryFilters["sort"]) ?? "published_at",
    page: Number.isFinite(page) && page > 0 ? page : 1,
    limit: 20,
  };
}

export default async function FeedPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const filters = toFilters(params);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-3xl font-extrabold tracking-tight">Government feed</h1>
      <p className="mt-1.5 text-sm text-muted">
        Scraped from official portals, summarised in plain language.
      </p>

      <div className="mt-6 space-y-4">
        <Suspense fallback={<div className="skeleton h-12 rounded-xl" />}>
          <SearchBar />
        </Suspense>
        <Suspense fallback={<div className="skeleton h-10 rounded-xl" />}>
          <CategoryFilter />
        </Suspense>
        <div className="flex flex-col gap-3 sm:flex-row">
          <Suspense fallback={<div className="skeleton h-11 w-56 rounded-xl" />}>
            <StateFilter />
          </Suspense>
          <Suspense fallback={<div className="skeleton h-11 w-44 rounded-xl" />}>
            <SortFilter />
          </Suspense>
        </div>
        <Suspense>
          <ActiveFilters />
        </Suspense>
      </div>

      <div className="mt-8">
        <Suspense key={JSON.stringify(filters)} fallback={<FeedSkeleton />}>
          <Results filters={filters} />
        </Suspense>
      </div>
    </div>
  );
}

async function Results({ filters }: { filters: EntryFilters }) {
  let data: EntriesResponse | null = null;
  let failed = false;

  try {
    data = await api.entries(filters, 300);
  } catch {
    failed = true;
  }

  if (failed) {
    return (
      <div className="rounded-2xl border border-rule/30 bg-rule/5 p-10 text-center">
        <p className="font-semibold text-ink">Could not reach the API</p>
        <p className="mt-1.5 text-sm text-muted">
          Check that the backend is running at{" "}
          <code className="text-faint">
            {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
          </code>
          .
        </p>
      </div>
    );
  }

  if (!data || data.entries.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-card p-12 text-center">
        <div className="text-3xl" aria-hidden>
          🔍
        </div>
        <p className="mt-3 font-semibold text-ink">Nothing matches these filters</p>
        <p className="mt-1.5 text-sm text-muted">
          Try a different category or state, or clear the search.
        </p>
        <Link
          href="/feed"
          className="mt-5 inline-block rounded-xl bg-surface px-5 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-border"
        >
          Clear all filters
        </Link>
      </div>
    );
  }

  const page = filters.page ?? 1;

  return (
    <>
      <p className="mb-4 text-xs text-faint">
        {data.total.toLocaleString("en-IN")} update
        {data.total === 1 ? "" : "s"}
        {data.total > data.limit &&
          ` · page ${page} of ${Math.ceil(data.total / data.limit)}`}
      </p>

      <div className="space-y-4">
        {data.entries.map((entry) => (
          <FeedCard key={entry.id} entry={entry} />
        ))}
      </div>

      <Pagination page={page} hasMore={data.has_more} filters={filters} />
    </>
  );
}

function Pagination({
  page,
  hasMore,
  filters,
}: {
  page: number;
  hasMore: boolean;
  filters: EntryFilters;
}) {
  if (page === 1 && !hasMore) return null;

  const href = (target: number) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value && key !== "page" && key !== "limit") {
        params.set(key, String(value));
      }
    }
    if (target > 1) params.set("page", String(target));
    return params.toString() ? `/feed?${params}` : "/feed";
  };

  return (
    <nav className="mt-8 flex items-center justify-between" aria-label="Pagination">
      {page > 1 ? (
        <Link
          href={href(page - 1)}
          className="rounded-xl border border-border bg-surface px-5 py-2.5 text-sm font-semibold text-ink hover:border-border-hover"
        >
          ← Previous
        </Link>
      ) : (
        <span />
      )}
      {hasMore && (
        <Link
          href={href(page + 1)}
          className="rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white hover:bg-primary-dim"
        >
          Load more →
        </Link>
      )}
    </nav>
  );
}
