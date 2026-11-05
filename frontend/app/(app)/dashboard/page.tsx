"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock,
  FileStack,
  Layers,
  ListChecks,
  ScanText,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UploadCloud,
  XCircle,
} from "lucide-react";
import { getDashboard, getMeta } from "@/lib/api";
import type { DashboardStats, Meta } from "@/lib/types";
import { cn, isBusy } from "@/lib/format";
import { Alert, PageHeader, ProgressBar } from "@/components/ui";
import { DocumentTable } from "@/components/DocumentTable";

function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone,
  href,
}: {
  label: string;
  value: string | number;
  hint: string;
  icon: React.ElementType;
  tone: string;
  href?: string;
}) {
  const content = (
    <div className="card group h-full p-5 transition hover:-translate-y-0.5 hover:shadow-lift">
      <div className="flex items-start justify-between">
        <div className={cn("flex h-10 w-10 items-center justify-center rounded-xl ring-1 ring-inset", tone)}>
          <Icon className="h-[18px] w-[18px]" />
        </div>
        {href ? (
          <ArrowRight className="h-4 w-4 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-slate-500" />
        ) : null}
      </div>
      <div className="mt-4 text-[28px] font-bold leading-none tracking-tight text-slate-900 tabular-nums">
        {value}
      </div>
      <div className="mt-1.5 text-sm font-semibold text-slate-700">{label}</div>
      <div className="mt-0.5 text-[11px] text-slate-400">{hint}</div>
    </div>
  );
  return href ? <Link href={href}>{content}</Link> : content;
}

const PIPELINE = [
  { label: "Upload", detail: "Validate & dedupe", icon: UploadCloud },
  { label: "Parse / OCR", detail: "Digital text or OCR", icon: ScanText },
  { label: "AI extraction", detail: "Groq + deterministic", icon: Sparkles },
  { label: "Validation", detail: "Arithmetic & duplicates", icon: ShieldCheck },
  { label: "Index", detail: "Keyword + vectors", icon: Layers },
];

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [dashboard, metaResult] = await Promise.all([getDashboard(), getMeta()]);
      setStats(dashboard);
      setMeta(metaResult);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const shouldPoll = useMemo(() => {
    if (!stats) return false;
    if (stats.queue_depth > 0) return true;
    return stats.recent_documents.some((document) => isBusy(document.status));
  }, [stats]);

  useEffect(() => {
    if (!shouldPoll) return;
    const timer = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(timer);
  }, [shouldPoll, load]);

  const total = stats?.total_documents ?? 0;
  const completed = stats?.documents.completed ?? 0;
  const processing = (stats?.documents.processing ?? 0) + (stats?.documents.queued ?? 0);
  const kinds = stats?.kinds ?? { pdf: 0, image: 0, spreadsheet: 0 };
  const openFindings = (stats?.findings.error ?? 0) + (stats?.findings.warning ?? 0);

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="Workspace overview"
        title="Document intelligence"
        description="Monitor processing, resolve exceptions, and keep extraction quality high."
        actions={
          <>
            <Link href="/documents" className="btn-secondary">
              <FileStack className="h-4 w-4" /> Browse documents
            </Link>
            <Link href="/upload" className="btn-accent">
              <UploadCloud className="h-4 w-4" /> Upload documents
            </Link>
          </>
        }
      />

      {error ? (
        <div className="mb-5">
          <Alert tone="error" title="Dashboard unavailable">
            {error}
          </Alert>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {loading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="card p-5">
              <div className="skeleton h-10 w-10" />
              <div className="skeleton mt-4 h-7 w-20" />
              <div className="skeleton mt-2 h-3 w-32" />
            </div>
          ))
        ) : (
          <>
            <MetricCard
              label="Total documents"
              value={total}
              hint={`${completed} completed · ${processing} in flight`}
              icon={FileStack}
              tone="bg-sky-50 text-sky-600 ring-sky-100"
              href="/documents"
            />
            <MetricCard
              label="Needs review"
              value={stats?.needs_review ?? 0}
              hint={`${openFindings} validation findings`}
              icon={TriangleAlert}
              tone="bg-amber-50 text-amber-600 ring-amber-100"
              href="/documents?status=needs_review"
            />
            <MetricCard
              label="Failed"
              value={stats?.failed ?? 0}
              hint="Open jobs to retry"
              icon={XCircle}
              tone="bg-rose-50 text-rose-600 ring-rose-100"
              href="/jobs?status=failed"
            />
            <MetricCard
              label="Queue depth"
              value={stats?.queue_depth ?? 0}
              hint={
                stats?.avg_processing_seconds
                  ? `Avg job ${stats.avg_processing_seconds.toFixed(1)}s`
                  : "No completed jobs yet"
              }
              icon={Activity}
              tone="bg-emerald-50 text-emerald-600 ring-emerald-100"
              href="/jobs"
            />
          </>
        )}
      </div>

      {stats && stats.needs_review > 0 && !loading ? (
        <div className="mt-5 flex flex-col gap-3 rounded-2xl border border-amber-200 bg-gradient-to-r from-amber-50 to-white p-4 sm:flex-row sm:items-center">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-slate-900">
              {stats.needs_review} document{stats.needs_review === 1 ? "" : "s"} await a human decision
            </div>
            <div className="mt-0.5 text-xs text-slate-500">
              Low confidence, arithmetic mismatches, duplicates, and cross-document conflicts are never auto-approved.
            </div>
          </div>
          <Link href="/documents?status=needs_review" className="btn-secondary btn-sm shrink-0">
            Review queue <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      ) : null}

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Recent documents</h2>
              <p className="mt-0.5 text-xs text-slate-400">Latest uploads across all sources</p>
            </div>
            <Link href="/documents" className="text-xs font-semibold text-accent-700 hover:text-accent-800">
              View all →
            </Link>
          </div>
          <DocumentTable
            items={stats?.recent_documents ?? []}
            loading={loading}
            compact
            emptyTitle="No documents yet"
            emptyDescription="Upload your first invoice or spreadsheet to see it here."
            emptyAction={
              <Link href="/upload" className="btn-accent btn-sm">
                <UploadCloud className="h-3.5 w-3.5" /> Upload a document
              </Link>
            }
          />
        </section>

        <div className="space-y-5">
          <section className="card overflow-hidden">
            <div className="border-b border-slate-100 px-5 py-4">
              <h2 className="text-sm font-semibold text-slate-900">Processing pipeline</h2>
              <p className="mt-0.5 text-xs text-slate-400">Every document follows the same path</p>
            </div>
            <ol className="space-y-0 px-5 py-4">
              {PIPELINE.map((step, index) => (
                <li key={step.label} className="relative flex gap-3 pb-4 last:pb-0">
                  {index < PIPELINE.length - 1 ? (
                    <span className="absolute left-[15px] top-8 h-[calc(100%-22px)] w-px bg-slate-200" />
                  ) : null}
                  <span className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 shadow-sm">
                    <step.icon className="h-3.5 w-3.5" />
                  </span>
                  <div className="min-w-0 pt-0.5">
                    <div className="text-xs font-semibold text-slate-700">{step.label}</div>
                    <div className="text-[11px] text-slate-400">{step.detail}</div>
                  </div>
                  <CheckCircle2 className="ml-auto mt-1.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                </li>
              ))}
            </ol>
            <div className="border-t border-slate-100 px-5 py-3">
              <div className="mb-1.5 flex items-center justify-between text-[11px] text-slate-400">
                <span>Work queue</span>
                <span className="font-semibold text-slate-600">{stats?.queue_depth ?? 0} active</span>
              </div>
              <ProgressBar
                value={
                  total > 0
                    ? Math.min(100, Math.round(((completed + (stats?.needs_review ?? 0)) / total) * 100))
                    : 0
                }
              />
            </div>
          </section>

          <section className="card p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900">Document mix</h2>
              <span className="text-[11px] text-slate-400">{total} total</span>
            </div>
            <div className="mt-4 space-y-3">
              {[
                ["PDF", kinds.pdf ?? 0, "bg-rose-400"],
                ["Images / scans", kinds.image ?? 0, "bg-violet-400"],
                ["Spreadsheets", kinds.spreadsheet ?? 0, "bg-sky-400"],
              ].map(([label, count, color]) => (
                <div key={String(label)}>
                  <div className="mb-1 flex items-center justify-between text-[11px]">
                    <span className="font-medium text-slate-600">{label}</span>
                    <span className="tabular-nums text-slate-400">{count}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className={cn("h-full rounded-full", String(color))}
                      style={{ width: total ? `${(Number(count) / total) * 100}%` : "0%" }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 border-t border-slate-100 pt-4">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  AI engine
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-[11px] font-semibold text-slate-700">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      meta?.ai_enabled ? "bg-emerald-500" : "bg-amber-500",
                    )}
                  />
                  {meta?.ai_enabled ? "Groq connected" : "Deterministic fallback"}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Search
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-[11px] font-semibold text-slate-700">
                  <ListChecks className="h-3 w-3 text-slate-400" />
                  Hybrid ready
                </div>
              </div>
            </div>
          </section>

          <div className="rounded-2xl border border-slate-200 bg-ink-950 p-5 text-white shadow-card">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-300">
              <Sparkles className="h-3.5 w-3.5" /> Evidence-first extraction
            </div>
            <p className="mt-2 text-[12px] leading-5 text-slate-400">
              Every non-null field carries a source quote and page. Unsupported values are nulled and
              flagged — the system never fills gaps by guessing.
            </p>
            <Link
              href="/search?mode=semantic"
              className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-white hover:text-accent-200"
            >
              Try semantic search <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-slate-400">
        <span className="inline-flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" /> Background processing
        </span>
        <span className="inline-flex items-center gap-1.5">
          <ShieldCheck className="h-3.5 w-3.5" /> 17 validation rules
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5" /> Prompt {meta?.ai_enabled ? "extract_invoice.v1" : "deterministic v1"}
        </span>
      </div>
    </div>
  );
}
