"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

export function FollowButton({
  entryId,
  hasDeadline,
}: {
  entryId: string;
  hasDeadline: boolean;
}) {
  const [token, setToken] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [following, setFollowing] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(async ({ data }) => {
      const access = data.session?.access_token ?? null;
      setToken(access);
      if (access && hasDeadline) {
        try {
          const state = await api.followState(entryId, access);
          setFollowing(state.following);
        } catch {
          setFollowing(false);
        }
      }
      setReady(true);
    });
  }, [entryId, hasDeadline]);

  if (!hasDeadline) return null;
  if (!ready) return <div className="skeleton h-11 w-40 rounded-xl" />;

  if (!token) {
    return (
      <Link
        href={`/auth/login?next=/entry/${entryId}`}
        className="rounded-xl border border-border bg-surface px-5 py-2.5 text-center text-sm font-semibold text-ink"
      >
        Sign in to follow
      </Link>
    );
  }

  async function toggle() {
    if (!token) return;
    setBusy(true);
    try {
      const result = await api.toggleFollow(entryId, token);
      setFollowing(result.following);
      toast.success(result.following ? "We'll email you before this closes" : "Unfollowed");
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Could not update follow";
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={busy}
      className="rounded-xl border border-primary/40 bg-primary/10 px-5 py-2.5 text-sm font-semibold text-primary disabled:opacity-60"
    >
      {following ? "Following" : "Follow this notice"}
    </button>
  );
}
