import Link from "next/link";
import { redirect } from "next/navigation";
import { FeedCard } from "@/components/feed/FeedCard";
import { SignOutButton } from "@/components/auth/SignOutButton";
import { PreferencesForm } from "@/components/dashboard/PreferencesForm";
import { api } from "@/lib/api";
import { createClient, getAccessToken } from "@/lib/supabase/server";
import type { Entry } from "@/types";

export const metadata = { title: "Dashboard" };
export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/auth/login?next=/dashboard");

  const token = await getAccessToken();

  const [bookmarks, plan, preferences] = await Promise.all([
    token ? api.bookmarks(token).catch(() => null) : null,
    token ? api.plan(token).catch(() => null) : null,
    token ? api.preferences(token).catch(() => null) : null,
  ]);

  const planId = (plan?.plan ?? "free") as string;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">Your dashboard</h1>
          <p className="mt-1 text-sm text-muted">
            {user.email ?? user.phone}
          </p>
        </div>
        <SignOutButton />
      </header>

      <section className="mt-8 rounded-2xl border border-border bg-card p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-faint">
              Current plan
            </div>
            <div className="mt-1 text-xl font-bold capitalize text-ink">{planId}</div>
            {plan?.expires_at && (
              <div className="mt-1 text-xs text-muted">
                Renews {new Date(plan.expires_at).toLocaleDateString("en-IN")}
              </div>
            )}
          </div>
          {planId === "free" && (
            <Link
              href="/pricing"
              className="rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-white hover:bg-primary-dim"
            >
              Upgrade
            </Link>
          )}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="mb-4 text-lg font-bold">Saved updates</h2>
        <SavedEntries entries={bookmarks?.entries ?? null} />
      </section>

      <section className="mt-10">
        <h2 className="mb-4 text-lg font-bold">Digest preferences</h2>
        <div className="rounded-2xl border border-border bg-card p-6">
          <PreferencesForm initial={preferences ?? null} />
        </div>
      </section>
    </div>
  );
}

function SavedEntries({ entries }: { entries: Entry[] | null }) {
  if (!entries || entries.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-card p-10 text-center">
        <p className="text-sm text-muted">
          Nothing saved yet. Tap the flag on any update to keep it here.
        </p>
        <Link
          href="/feed"
          className="mt-4 inline-block rounded-xl bg-surface px-5 py-2.5 text-sm font-semibold text-ink hover:bg-border"
        >
          Browse the feed
        </Link>
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
