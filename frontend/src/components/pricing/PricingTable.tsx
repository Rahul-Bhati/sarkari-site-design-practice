"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { PLANS } from "@/lib/constants";
import { createClient } from "@/lib/supabase/client";
import { cn, formatINR } from "@/lib/utils";

type Period = "monthly" | "yearly";

export function PricingTable() {
  const router = useRouter();
  const [period, setPeriod] = useState<Period>("monthly");
  const [busy, setBusy] = useState<string | null>(null);

  async function upgrade(planId: string) {
    if (planId === "free") return router.push("/");

    setBusy(planId);
    try {
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session) {
        router.push(`/auth/login?next=/pricing`);
        return;
      }

      const res = await api.createSubscription(
        { plan: planId, period },
        session.access_token,
      );
      // Razorpay's hosted checkout — no PCI surface on our side.
      window.location.href = res.short_url;
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Could not start checkout",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="mt-8 flex justify-center">
        <div
          className="inline-flex rounded-xl bg-surface p-1"
          role="group"
          aria-label="Billing period"
        >
          {(["monthly", "yearly"] as Period[]).map((p) => (
            <button
              key={p}
              type="button"
              aria-pressed={period === p}
              onClick={() => setPeriod(p)}
              className={cn(
                "rounded-lg px-5 py-2 text-sm font-semibold transition-colors",
                period === p ? "bg-primary text-white" : "text-muted hover:text-ink",
              )}
            >
              {p === "monthly" ? "Monthly" : "Yearly"}
              {p === "yearly" && (
                <span className="ml-1.5 text-xs opacity-90">save 16%</span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-10 grid gap-6 md:grid-cols-3">
        {PLANS.map((plan) => {
          const price = period === "monthly" ? plan.priceMonthly : plan.priceYearly;
          const highlight = "highlight" in plan && plan.highlight;

          return (
            <div
              key={plan.id}
              className={cn(
                "relative flex flex-col rounded-2xl border bg-card p-6",
                highlight ? "border-primary" : "border-border",
              )}
            >
              {highlight && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-primary px-3 py-1 text-[11px] font-bold uppercase tracking-wide text-white">
                  Most popular
                </span>
              )}

              <h3 className="text-lg font-bold text-ink">{plan.name}</h3>
              <p className="mt-1 text-xs text-muted">{plan.tagline}</p>

              <div className="mt-5">
                <span className="text-3xl font-extrabold text-ink">
                  {price === 0 ? "Free" : formatINR(price)}
                </span>
                {price > 0 && (
                  <span className="text-sm text-faint">
                    /{period === "monthly" ? "month" : "year"}
                  </span>
                )}
              </div>

              <ul className="mt-6 grow space-y-2.5 text-sm">
                {plan.features.map((f) => (
                  <li key={f} className="flex gap-2 text-muted">
                    <span className="text-secondary" aria-hidden>
                      ✓
                    </span>
                    {f}
                  </li>
                ))}
                {plan.missing.map((f) => (
                  <li key={f} className="flex gap-2 text-faint line-through">
                    <span aria-hidden>✕</span>
                    {f}
                  </li>
                ))}
              </ul>

              <Button
                className="mt-6 w-full"
                variant={highlight ? "primary" : "secondary"}
                loading={busy === plan.id}
                onClick={() => upgrade(plan.id)}
              >
                {plan.id === "free" ? "Start free" : "Start 7-day trial"}
              </Button>
            </div>
          );
        })}
      </div>
    </>
  );
}
