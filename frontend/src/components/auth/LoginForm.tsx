"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

type Mode = "phone" | "email";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") ?? "/dashboard";

  const [mode, setMode] = useState<Mode>("phone");
  const [busy, setBusy] = useState(false);

  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [otpSent, setOtpSent] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);

  const supabase = createClient();

  async function sendOtp(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const { error } = await supabase.auth.signInWithOtp({ phone });
    setBusy(false);
    if (error) return toast.error(error.message);
    setOtpSent(true);
    toast.success("OTP sent to your phone");
  }

  async function verifyOtp(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const { error } = await supabase.auth.verifyOtp({
      phone,
      token: otp,
      type: "sms",
    });
    setBusy(false);
    if (error) return toast.error(error.message);
    router.push(next);
    router.refresh();
  }

  async function emailAuth(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const { error } = isSignUp
      ? await supabase.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: `${location.origin}/auth/callback?next=${next}` },
        })
      : await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);

    if (error) return toast.error(error.message);
    if (isSignUp) return toast.success("Check your email to confirm your account");
    router.push(next);
    router.refresh();
  }

  async function google() {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${location.origin}/auth/callback?next=${next}` },
    });
    if (error) toast.error(error.message);
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-1 rounded-xl bg-surface p-1">
        {(["phone", "email"] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              "rounded-lg py-2 text-sm font-semibold transition-colors",
              mode === m ? "bg-primary text-white" : "text-muted hover:text-ink",
            )}
          >
            {m === "phone" ? "Phone OTP" : "Email"}
          </button>
        ))}
      </div>

      {mode === "phone" ? (
        <form onSubmit={otpSent ? verifyOtp : sendOtp} className="space-y-4">
          <Input
            name="phone"
            type="tel"
            label="Mobile number"
            required
            disabled={otpSent}
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+919876543210"
            hint="Include +91."
          />
          {otpSent && (
            <Input
              name="otp"
              inputMode="numeric"
              label="6-digit OTP"
              required
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              placeholder="123456"
            />
          )}
          <Button type="submit" size="lg" loading={busy} className="w-full">
            {otpSent ? "Verify and sign in" : "Send OTP"}
          </Button>
          {otpSent && (
            <button
              type="button"
              onClick={() => setOtpSent(false)}
              className="w-full text-xs text-muted hover:text-ink"
            >
              Change number
            </button>
          )}
        </form>
      ) : (
        <form onSubmit={emailAuth} className="space-y-4">
          <Input
            name="email"
            type="email"
            label="Email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            name="password"
            type="password"
            label="Password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" size="lg" loading={busy} className="w-full">
            {isSignUp ? "Create account" : "Sign in"}
          </Button>
          <button
            type="button"
            onClick={() => setIsSignUp((v) => !v)}
            className="w-full text-xs text-muted hover:text-ink"
          >
            {isSignUp ? "Already have an account? Sign in" : "New here? Create an account"}
          </button>
        </form>
      )}

      <div className="flex items-center gap-3 text-xs text-faint">
        <span className="h-px grow bg-border" />
        or
        <span className="h-px grow bg-border" />
      </div>

      <Button variant="secondary" size="lg" onClick={google} className="w-full">
        Continue with Google
      </Button>
    </div>
  );
}
