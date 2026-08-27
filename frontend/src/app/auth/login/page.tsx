import { Suspense } from "react";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-md px-4 py-16">
      <h1 className="text-center text-3xl font-extrabold tracking-tight">
        Sign in to SarkariSaar
      </h1>
      <p className="mt-2 text-center text-sm text-muted">
        Save updates, set filters, and manage your digest.
      </p>
      <div className="mt-8 rounded-2xl border border-border bg-card p-6">
        <Suspense fallback={<div className="skeleton h-64 rounded-xl" />}>
          <LoginForm />
        </Suspense>
      </div>
    </div>
  );
}
