import Link from "next/link";
import { Suspense } from "react";
import { FeedCard } from "@/components/feed/FeedCard";
import { FeedSkeleton } from "@/components/feed/FeedSkeleton";
import { SearchBar } from "@/components/feed/Filters";
import { SubscribeForm } from "@/components/subscribe/SubscribeForm";
import { api } from "@/lib/api";
import { CATEGORIES } from "@/lib/constants";
import type { Entry, StatsResponse } from "@/types";

export const revalidate = 300;

const HOW_IT_WORKS = [
  {
    icon: "🔍",
    title: "We watch the portals",
    body: "Scrapers check government websites around the clock — central ministries, state procurement portals, recruitment boards.",
  },
  {
    icon: "✨",
    title: "AI writes the summary",
    body: "Every notification is rewritten in plain English and Hindi: who it's for, what it's worth, and by when.",
  },
  {
    icon: "📬",
    title: "It reaches you",
    body: "Read it on the web, or get a digest by email and WhatsApp filtered to your state and interests.",
  },
];

export default async function LandingPage() {
  const [stats, latest] = await Promise.all([
    api.stats(300).catch(() => null),
    api.entries({ limit: 5 }, 300).catch(() => null),
  ]);

  return (
    <>
      <section className="mx-auto max-w-5xl px-4 pb-12 pt-16 text-center sm:pt-24">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">
          Sarkari updates, without the jargon
        </p>
        <h1 className="mx-auto mt-4 max-w-3xl text-4xl font-extrabold leading-[1.1] tracking-tight sm:text-6xl">
          Every government notice that matters to you.{" "}
          <span className="text-primary">In language you actually use.</span>
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-base leading-relaxed text-muted sm:text-lg">
          Yojanas, naukri, tenders and rule changes from across India — scraped
          daily, summarised in simple English and Hindi, with deadlines front and
          centre.
        </p>

        <div className="mx-auto mt-8 max-w-2xl">
          <Suspense>
            <SearchBar />
          </Suspense>
        </div>

        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {CATEGORIES.filter((c) => c.id !== "all")
            .slice(0, 4)
            .map((c) => (
              <Link
                key={c.id}
                href={`/feed?category=${c.id}`}
                className="rounded-full border border-border bg-surface px-4 py-2 text-sm text-muted transition-colors hover:border-border-hover hover:text-ink"
              >
                <span aria-hidden className="mr-1.5">
                  {c.icon}
                </span>
                {c.label}
              </Link>
            ))}
        </div>
      </section>

      {stats && <StatsBar stats={stats} />}

      <section className="mx-auto max-w-5xl px-4 py-16">
        <div className="mb-6 flex items-end justify-between">
          <h2 className="text-2xl font-bold">Latest updates</h2>
          <Link
            href="/feed"
            className="text-sm font-semibold text-primary hover:underline"
          >
            See all →
          </Link>
        </div>

        <Suspense fallback={<FeedSkeleton count={3} />}>
          <LatestEntries entries={latest?.entries ?? null} />
        </Suspense>
      </section>

      <section className="border-y border-border bg-surface/40">
        <div className="mx-auto max-w-5xl px-4 py-16">
          <h2 className="text-center text-2xl font-bold">How it works</h2>
          <div className="mt-10 grid gap-8 sm:grid-cols-3">
            {HOW_IT_WORKS.map((step) => (
              <div key={step.title}>
                <div className="text-3xl" aria-hidden>
                  {step.icon}
                </div>
                <h3 className="mt-3 font-bold text-ink">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  {step.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-4 py-16">
        <div className="rounded-3xl border border-tender/30 bg-gradient-to-br from-tender/10 to-transparent p-8 sm:p-10">
          <div className="grid items-center gap-8 sm:grid-cols-[1.2fr_1fr]">
            <div>
              <span className="text-xs font-semibold uppercase tracking-widest text-tender">
                For thekedars
              </span>
              <h2 className="mt-3 text-2xl font-bold sm:text-3xl">
                Stop refreshing eProcurement portals at midnight.
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                Set your state, your departments and your budget range. When a
                matching tender goes live, it lands on your WhatsApp within
                minutes — with the estimated cost, EMD and closing date already
                pulled out.
              </p>
              <Link
                href="/pricing"
                className="mt-6 inline-block rounded-xl bg-tender px-6 py-3 text-sm font-bold text-black transition-opacity hover:opacity-90"
              >
                See the Thekedar plan
              </Link>
            </div>
            <ul className="space-y-3 text-sm text-muted">
              {[
                "Instant WhatsApp tender alerts",
                "Filter by budget and department",
                "EMD and closing date extracted",
                "Direct link to the official portal",
              ].map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="text-tender" aria-hidden>
                    ✓
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-xl px-4 pb-20">
        <h2 className="text-center text-2xl font-bold">
          Get the updates that matter to you
        </h2>
        <p className="mt-2 text-center text-sm text-muted">
          Free weekly digest. Pick your state and interests.
        </p>
        <div className="mt-8 rounded-2xl border border-border bg-card p-6">
          <SubscribeForm />
        </div>
      </section>
    </>
  );
}

function StatsBar({ stats }: { stats: StatsResponse }) {
  const items = [
    { value: stats.total_entries, label: "Updates tracked" },
    { value: stats.entries_today, label: "Added today" },
    { value: stats.states_covered, label: "States covered" },
    { value: stats.sources_active, label: "Sources watched" },
  ];

  return (
    <div className="border-y border-border bg-surface/40">
      <dl className="mx-auto grid max-w-5xl grid-cols-2 gap-y-8 px-4 py-8 sm:grid-cols-4">
        {items.map((item) => (
          <div key={item.label} className="text-center">
            <dt className="sr-only">{item.label}</dt>
            <dd>
              <span className="block text-2xl font-extrabold text-primary sm:text-3xl">
                {item.value.toLocaleString("en-IN")}
              </span>
              <span className="mt-1 block text-xs text-muted">{item.label}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function LatestEntries({ entries }: { entries: Entry[] | null }) {
  if (entries === null) {
    return (
      <div className="rounded-2xl border border-border bg-card p-8 text-center text-sm text-muted">
        The feed is warming up. Start the API and run a scrape to see live
        entries here.
      </div>
    );
  }
  if (entries.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-card p-8 text-center text-sm text-muted">
        No approved entries yet.
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {entries.map((entry) => (
        <FeedCard key={entry.id} entry={entry} />
      ))}
    </div>
  );
}
