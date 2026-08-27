"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { api, ApiError } from "@/lib/api";
import { CATEGORIES, STATES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { Category, SubscribePayload } from "@/types";

const SELECTABLE = CATEGORIES.filter((c) => c.id !== "all");

export function SubscribeForm({ compact = false }: { compact?: boolean }) {
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [channel, setChannel] = useState<SubscribePayload["channel"]>("email");
  const [frequency, setFrequency] = useState<SubscribePayload["frequency"]>("weekly");
  const [categories, setCategories] = useState<Category[]>([]);
  const [state, setState] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const needsPhone = channel === "whatsapp" || channel === "both";
  const needsEmail = channel === "email" || channel === "both";

  function toggleCategory(id: Category) {
    setCategories((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id],
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await api.subscribe({
        email: needsEmail ? email.trim() : undefined,
        phone: needsPhone ? phone.trim() : undefined,
        channel,
        frequency,
        categories,
        states: state ? [state] : [],
      });
      toast.success(res.message);
      setDone(true);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Could not subscribe. Please try again.";
      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="rounded-2xl border border-secondary/40 bg-secondary/10 p-6 text-center">
        <div className="text-2xl" aria-hidden>
          ✅
        </div>
        <p className="mt-2 font-semibold text-ink">Almost there</p>
        <p className="mt-1 text-sm text-muted">
          {needsEmail
            ? "Check your inbox and click the confirmation link to activate your digest."
            : "We'll confirm your number on WhatsApp shortly."}
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {needsEmail && (
        <Input
          name="email"
          type="email"
          label="Email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
        />
      )}

      {needsPhone && (
        <Input
          name="phone"
          type="tel"
          label="WhatsApp number"
          required
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="+919876543210"
          hint="Include the country code."
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          name="channel"
          label="Deliver via"
          value={channel}
          onChange={(e) => setChannel(e.target.value as SubscribePayload["channel"])}
          options={[
            { value: "email", label: "Email" },
            { value: "whatsapp", label: "WhatsApp" },
            { value: "both", label: "Both" },
          ]}
        />
        <Select
          name="frequency"
          label="How often"
          value={frequency}
          onChange={(e) =>
            setFrequency(e.target.value as SubscribePayload["frequency"])
          }
          options={[
            { value: "weekly", label: "Weekly (free)" },
            { value: "daily", label: "Daily (Pro)" },
          ]}
        />
      </div>

      {!compact && (
        <>
          <fieldset>
            <legend className="mb-2 text-xs font-semibold text-muted">
              What are you interested in?{" "}
              <span className="font-normal text-faint">
                Leave empty for everything.
              </span>
            </legend>
            <div className="flex flex-wrap gap-2">
              {SELECTABLE.map((c) => {
                const on = categories.includes(c.id as Category);
                return (
                  <button
                    key={c.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggleCategory(c.id as Category)}
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

          <Select
            name="state"
            label="State"
            value={state}
            onChange={(e) => setState(e.target.value)}
            options={[
              { value: "", label: "Every state" },
              ...STATES.map((s) => ({ value: s.code, label: s.label })),
            ]}
          />
        </>
      )}

      <Button type="submit" size="lg" loading={submitting} className="w-full">
        Subscribe free
      </Button>
      <p className="text-center text-xs text-faint">
        One-click unsubscribe in every message. We never sell your data.
      </p>
    </form>
  );
}
