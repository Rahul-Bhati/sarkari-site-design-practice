"use client";

import { useState } from "react";
import { toast } from "sonner";

export function ShareButtons({
  title,
  entryId,
  deadline,
  vacancies,
}: {
  title: string;
  entryId: string;
  deadline?: string | null;
  vacancies?: number | null;
}) {
  const [copied, setCopied] = useState(false);

  const url =
    typeof window === "undefined"
      ? `${process.env.NEXT_PUBLIC_SITE_URL ?? ""}/entry/${entryId}`
      : window.location.href;

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success("Link copied");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Could not copy the link");
    }
  }

  const message = [
    title,
    `Last date: ${deadline || "not listed"}`,
    typeof vacancies === "number" ? `Posts: ${vacancies}` : null,
    url,
  ]
    .filter(Boolean)
    .join("\n");
  const whatsapp = `https://wa.me/?text=${encodeURIComponent(message)}`;

  return (
    <div className="mt-6 flex flex-wrap gap-3">
      <a
        href={whatsapp}
        target="_blank"
        rel="noopener noreferrer"
        className="rounded-xl border border-secondary/40 bg-secondary/10 px-5 py-2.5 text-sm font-semibold text-secondary transition-colors hover:bg-secondary/20"
      >
        Share on WhatsApp
      </a>
      <button
        type="button"
        onClick={copy}
        className="rounded-xl border border-border bg-surface px-5 py-2.5 text-sm font-semibold text-muted transition-colors hover:border-border-hover hover:text-ink"
      >
        {copied ? "Copied ✓" : "Copy link"}
      </button>
    </div>
  );
}
