"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  FileSearch,
  LockKeyhole,
  Mail,
  ScanLine,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { ApiError } from "@/lib/api";
import { Alert, Spinner } from "@/components/ui";

const DEMO_EMAIL = "admin@docintel.local";
const DEMO_PASSWORD = "admin12345";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, login } = useAuth();
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not sign in. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-dvh bg-[#f5f7fb] lg:grid-cols-[minmax(0,1fr)_minmax(0,1.08fr)]">
      <section className="flex flex-col px-6 py-8 sm:px-12 lg:px-16 xl:px-24">
        <Link href="/" className="flex items-center gap-3">
          <span className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-ink-950 text-lg font-black text-accent-300 shadow-lg">
            D
            <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-[#f5f7fb] bg-accent-400" />
          </span>
          <span>
            <span className="block text-[17px] font-bold leading-5 tracking-tight text-slate-900">
              DocIntel
            </span>
            <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Document intelligence
            </span>
          </span>
        </Link>

        <div className="my-auto w-full max-w-[420px] py-14">
          <div className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Secure workspace
          </div>
          <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-900">Welcome back</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            Sign in to process invoices, review extractions, and search your document archive.
          </p>

          <form onSubmit={onSubmit} className="mt-8 space-y-4">
            <div>
              <label htmlFor="email" className="label">
                Email address
              </label>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="input pl-10"
                  placeholder="you@company.com"
                />
              </div>
            </div>

            <div>
              <label htmlFor="password" className="label">
                Password
              </label>
              <div className="relative">
                <LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="input pl-10 pr-11"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error ? <Alert tone="error">{error}</Alert> : null}

            <button type="submit" disabled={submitting} className="btn-primary w-full py-3">
              {submitting ? (
                <>
                  <Spinner /> Signing in…
                </>
              ) : (
                <>
                  Sign in <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
          </form>

          <div className="mt-6 rounded-xl border border-slate-200 bg-white/80 p-3.5">
            <div className="flex items-start gap-2.5">
              <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent-600" />
              <div className="text-xs leading-5 text-slate-500">
                <span className="font-semibold text-slate-700">Demo access is pre-filled.</span>{" "}
                Use{" "}
                <button
                  type="button"
                  onClick={() => {
                    setEmail(DEMO_EMAIL);
                    setPassword(DEMO_PASSWORD);
                  }}
                  className="font-mono text-[11px] font-semibold text-accent-700 underline decoration-accent-300 underline-offset-2"
                >
                  {DEMO_EMAIL}
                </button>{" "}
                with password <span className="font-mono text-[11px] font-semibold text-slate-700">{DEMO_PASSWORD}</span>.
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-slate-400">
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5" /> Role-based access
          </span>
          <span className="inline-flex items-center gap-1.5">
            <LockKeyhole className="h-3.5 w-3.5" /> HttpOnly sessions
          </span>
          <span className="inline-flex items-center gap-1.5">
            <CheckCircle2 className="h-3.5 w-3.5" /> Audit trail
          </span>
        </div>
      </section>

      <section className="relative hidden overflow-hidden bg-ink-950 p-12 lg:flex lg:flex-col lg:justify-between xl:p-16">
        <div className="surface-grid absolute inset-0 opacity-40" />
        <div className="absolute -right-32 -top-32 h-96 w-96 rounded-full bg-accent-500/15 blur-3xl" />
        <div className="absolute -bottom-24 -left-16 h-80 w-80 rounded-full bg-sky-500/10 blur-3xl" />

        <div className="relative z-10 flex items-center justify-between">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] font-medium text-slate-300">
            <ScanLine className="h-3.5 w-3.5 text-accent-300" />
            OCR · LLM extraction · Validation · Search
          </div>
          <div className="text-[11px] font-medium text-slate-500">v1.0</div>
        </div>

        <div className="relative z-10 my-auto max-w-xl py-12">
          <h2 className="text-[40px] font-bold leading-[1.1] tracking-tight text-white xl:text-5xl">
            From messy documents
            <span className="block text-accent-300">to trusted data.</span>
          </h2>
          <p className="mt-5 max-w-md text-[15px] leading-7 text-slate-400">
            DocIntel reads invoices, scans, and spreadsheets, extracts structured fields with evidence,
            then validates the arithmetic, duplicates, and cross-document consistency before anything
            is approved.
          </p>

          <div className="mt-10 rounded-2xl border border-white/10 bg-white/[0.04] p-4 backdrop-blur-sm">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <FileSearch className="h-4 w-4 text-accent-300" />
                <span className="text-xs font-semibold text-white">INV-2024-0042.pdf</span>
              </div>
              <span className="rounded-full bg-amber-400/10 px-2 py-0.5 text-[10px] font-semibold text-amber-300 ring-1 ring-inset ring-amber-400/20">
                Review required
              </span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2.5">
              {[
                ["Supplier", "Acme Components Ltd", "98%"],
                ["Total", "£1,650.00", "97%"],
                ["Invoice date", "15 Mar 2024", "96%"],
                ["Line items", "1 of 2 matched", "Check"],
              ].map(([label, value, badge]) => (
                <div key={label} className="rounded-xl border border-white/[0.07] bg-ink-900/60 p-3">
                  <div className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
                    {label}
                  </div>
                  <div className="mt-1 truncate text-xs font-semibold text-slate-100">{value}</div>
                  <div className="mt-1 text-[10px] font-semibold text-accent-300">{badge}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-amber-400/15 bg-amber-400/[0.06] px-3 py-2 text-[11px] text-amber-200">
              <ShieldCheck className="h-3.5 w-3.5" />
              Line item sum does not match subtotal — routed to human review
            </div>
          </div>
        </div>

        <div className="relative z-10 grid grid-cols-3 gap-4 border-t border-white/10 pt-6">
          {[
            ["PDF · JPG · PNG · TIFF", "Document formats"],
            ["XLSX · XLS · CSV", "Spreadsheets"],
            ["Keyword + semantic", "Hybrid search"],
          ].map(([title, subtitle]) => (
            <div key={title}>
              <div className="text-xs font-semibold text-slate-200">{title}</div>
              <div className="mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">
                {subtitle}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
