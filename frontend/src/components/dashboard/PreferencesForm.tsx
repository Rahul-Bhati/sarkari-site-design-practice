"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { CATEGORIES, STATES } from "@/lib/constants";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";
import type { Category } from "@/types";

const SELECTABLE = CATEGORIES.filter((c) => c.id !== "all");

interface Props {
  initial: Record<string, unknown> | null;
}

export function PreferencesForm({ initial }: Props) {
  const subscribed = Boolean(initial?.subscribed);

  const [channel, setChannel] = useState(String(initial?.channel ?? "email"));
  const [frequency, setFrequency] = useState(String(initial?.frequency ?? "weekly"));
  const [categories, setCategories] = useState<Category[]>(
    (initial?.categories as Category[]) ?? [],
  );
  const [states, setStates] = useState<string[]>((initial?.states as string[]) ?? []);
  const [busy, setBusy] = useState(false);

  if (!subscribed) {
    return (
      <p className="text-sm text-muted">
        You don&apos;t have a digest yet. Subscribe from the{" "}
        <a href="/" className="font-semibold text-primary hover:underline">
          home page
        </a>{" "}
        to start receiving updates.
      </p>
    );
  }

  async function save() {
    setBusy(true);
    try {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) throw new Error("Session expired — sign in again");

      await api.updatePreferences(
        { channel, frequency, categories, states },
        session.access_token,
      );
      toast.success("Preferences saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label="Deliver via"
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
          options={[
            { value: "email", label: "Email" },
            { value: "whatsapp", label: "WhatsApp" },
            { value: "both", label: "Both" },
          ]}
        />
        <Select
          label="How often"
          value={frequency}
          onChange={(e) => setFrequency(e.target.value)}
          options={[
            { value: "weekly", label: "Weekly" },
            { value: "daily", label: "Daily (Pro)" },
          ]}
        />
      </div>

      <fieldset>
        <legend className="mb-2 text-xs font-semibold text-muted">Categories</legend>
        <div className="flex flex-wrap gap-2">
          {SELECTABLE.map((c) => {
            const on = categories.includes(c.id as Category);
            return (
              <button
                key={c.id}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  setCategories((prev) =>
                    on
                      ? prev.filter((x) => x !== c.id)
                      : [...prev, c.id as Category],
                  )
                }
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors",
                  on
                    ? "border-transparent text-white"
                    : "border-border bg-surface text-muted hover:text-ink",
                )}
                style={on ? { backgroundColor: c.color } : undefined}
              >
                {c.label}
              </button>
            );
          })}
        </div>
      </fieldset>

      <fieldset>
        <legend className="mb-2 text-xs font-semibold text-muted">States</legend>
        <div className="no-scrollbar flex max-h-40 flex-wrap gap-2 overflow-y-auto">
          {STATES.map((s) => {
            const on = states.includes(s.code);
            return (
              <button
                key={s.code}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  setStates((prev) =>
                    on ? prev.filter((x) => x !== s.code) : [...prev, s.code],
                  )
                }
                className={cn(
                  "rounded-full border px-3 py-1.5 text-xs transition-colors",
                  on
                    ? "border-primary bg-primary/15 text-primary"
                    : "border-border bg-surface text-muted hover:text-ink",
                )}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </fieldset>

      <Button loading={busy} onClick={save}>
        Save preferences
      </Button>
    </div>
  );
}
