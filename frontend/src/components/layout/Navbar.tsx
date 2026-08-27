"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/feed", label: "Feed" },
  { href: "/pricing", label: "Premium" },
];

export function Navbar() {
  const pathname = usePathname();
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => setSignedIn(Boolean(data.user)));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) =>
      setSignedIn(Boolean(session?.user)),
    );
    return () => sub.subscription.unsubscribe();
  }, []);

  useEffect(() => setOpen(false), [pathname]);

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-bg/85 backdrop-blur">
      <nav className="mx-auto flex max-w-5xl items-center gap-4 px-4 py-3.5">
        <Link href="/" className="text-lg font-extrabold tracking-tight">
          Sarkari<span className="text-primary">Saar</span>
        </Link>

        <div className="hidden gap-1 sm:flex">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={cn(
                "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                pathname.startsWith(l.href)
                  ? "text-ink"
                  : "text-muted hover:text-ink",
              )}
            >
              {l.label}
            </Link>
          ))}
        </div>

        <span className="grow" />

        <Link
          href={signedIn ? "/dashboard" : "/auth/login"}
          className="hidden rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary-dim sm:inline-block"
        >
          {signedIn ? "Dashboard" : "Get Started"}
        </Link>

        <button
          type="button"
          aria-label="Menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="rounded-lg border border-border px-3 py-1.5 text-muted sm:hidden"
        >
          {open ? "✕" : "☰"}
        </button>
      </nav>

      {open && (
        <div className="border-t border-border px-4 py-3 sm:hidden">
          {[...LINKS, { href: signedIn ? "/dashboard" : "/auth/login", label: signedIn ? "Dashboard" : "Get Started" }].map(
            (l) => (
              <Link
                key={l.href}
                href={l.href}
                className="block rounded-lg px-3 py-2.5 text-sm font-medium text-muted hover:bg-surface hover:text-ink"
              >
                {l.label}
              </Link>
            ),
          )}
        </div>
      )}
    </header>
  );
}
