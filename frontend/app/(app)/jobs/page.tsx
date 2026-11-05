"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Clock,
  ListChecks,
  RefreshCw,
  RotateCcw,
  TriangleAlert,
} from "lucide-react";
import { listDocuments, listJobs, retryJob } from "@/lib/api";
import type { DocumentListItem, Job } from "@/lib/types";
import { cn, formatDate, relativeTime } from "@/lib/format";
import { Alert, EmptyState, PageHeader, ProgressBar, Spinner, StatusBadge } from "@/components/ui";

const FILTERS = [
  { value: "", label: "All" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

function duration(job: Job): string {
  if (!job.started_at) return "—";
  const start = new Date(job.started_at).getTime();
  const end = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end)) return "—";
  const seconds = Math.max(0, (end - start) / 1000);
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [documents, setDocuments] = useState<Record<string, DocumentListItem>>({});
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const [jobList, documentList] = await Promise.all([
          listJobs(status || undefined),
          listDocuments({ limit: 100 }),
        ]);
        setJobs(jobList);
        setDocuments(
          Object.fromEntries(documentList.items.map((document) => [document.id, document])),
        );
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load jobs");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [status],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const active = useMemo(
    () => jobs.some((job) => ["queued", "running"].includes(job.status)),
    [jobs],
  );

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(true), 4000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  async function handleRetry(job: Job) {
    setRetrying(job.id);
    setError(null);
    setNotice(null);
    try {
      await retryJob(job.id);
      setNotice("Job re-queued. A worker will pick it up shortly.");
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not retry job");
    } finally {
      setRetrying(null);
    }
  }

  const counts = useMemo(() => {
    const result: Record<string, number> = {};
    jobs.forEach((job) => {
      result[job.status] = (result[job.status] || 0) + 1;
    });
    return result;
  }, [jobs]);

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="Operations"
        title="Processing jobs"
        description="Background work is claimed from a database queue with retries, backoff, and stale-worker recovery."
        actions={
          <button
            type="button"
            onClick={() => {
              setRefreshing(true);
              void load(true);
            }}
            className="btn-secondary"
            disabled={refreshing}
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} /> Refresh
          </button>
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        {FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            onClick={() => setStatus(filter.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold transition",
              status === filter.value
                ? "bg-ink-900 text-white shadow-sm"
                : "border border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:text-slate-800",
            )}
          >
            {filter.label}
            {status === filter.value ? (
              <span className="rounded-full bg-white/15 px-1.5 py-0.5 text-[10px]">
                {jobs.length}
              </span>
            ) : null}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-slate-400">
          {active ? (
            <span className="inline-flex items-center gap-1.5 text-sky-600">
              <RefreshCw className="h-3 w-3 animate-spin" /> live updates
            </span>
          ) : (
            `Showing ${jobs.length} job${jobs.length === 1 ? "" : "s"}`
          )}
        </span>
      </div>

      {error ? (
        <div className="mb-5">
          <Alert tone="error" title="Job action failed">
            {error}
          </Alert>
        </div>
      ) : null}
      {notice ? (
        <div className="mb-5">
          <Alert tone="success">{notice}</Alert>
        </div>
      ) : null}

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">Queue activity</h2>
            <p className="mt-0.5 text-xs text-slate-400">
              {counts.queued ?? 0} queued · {counts.running ?? 0} running ·{" "}
              {counts.completed ?? 0} completed · {counts.failed ?? 0} failed
            </p>
          </div>
          <ListChecks className="h-5 w-5 text-slate-300" />
        </div>

        {loading ? (
          <div className="divide-y divide-slate-100">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="flex items-center gap-4 px-5 py-4">
                <div className="skeleton h-9 w-9" />
                <div className="flex-1">
                  <div className="skeleton h-3.5 w-1/3" />
                  <div className="skeleton mt-2 h-3 w-1/4" />
                </div>
                <div className="skeleton h-6 w-20" />
              </div>
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <EmptyState
            icon={ListChecks}
            title={status ? `No ${status} jobs` : "No processing jobs yet"}
            description={
              status
                ? "Try another filter or refresh to see the latest queue state."
                : "Upload a document to enqueue its first processing job."
            }
            action={
              status ? (
                <button type="button" onClick={() => setStatus("")} className="btn-secondary">
                  Show all jobs
                </button>
              ) : (
                <Link href="/upload" className="btn-accent">
                  Upload a document
                </Link>
              )
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table-base min-w-[920px]">
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Progress</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => {
                  const document = documents[job.document_id];
                  const failed = ["failed", "cancelled"].includes(job.status);
                  return (
                    <tr key={job.id}>
                      <td>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-500">
                              {job.job_type}
                            </span>
                            <span className="font-mono text-[10px] text-slate-400">
                              {job.id.slice(0, 8)}
                            </span>
                          </div>
                          <Link
                            href={`/documents/${job.document_id}`}
                            className="mt-1 block max-w-[280px] truncate text-xs font-semibold text-slate-700 hover:text-accent-700"
                          >
                            {document?.original_filename || job.document_id}
                          </Link>
                          {job.error_message ? (
                            <div className="mt-1 flex items-start gap-1.5 text-[11px] text-rose-600">
                              <TriangleAlert className="mt-0.5 h-3 w-3 shrink-0" />
                              <span className="line-clamp-2 max-w-[360px]">
                                {job.error_code ? `${job.error_code}: ` : ""}
                                {job.error_message}
                              </span>
                            </div>
                          ) : null}
                        </div>
                      </td>
                      <td>
                        <StatusBadge status={job.status} />
                      </td>
                      <td>
                        <span className="text-xs font-medium tabular-nums text-slate-600">
                          {job.attempts}/{job.max_attempts}
                        </span>
                      </td>
                      <td>
                        <div className="w-28">
                          <ProgressBar
                            value={job.status === "completed" ? 100 : job.progress}
                            tone={job.status === "failed" ? "rose" : "accent"}
                          />
                          <div className="mt-1 text-[10px] tabular-nums text-slate-400">
                            {job.status === "completed" ? 100 : job.progress}%
                          </div>
                        </div>
                      </td>
                      <td>
                        <div className="text-xs text-slate-600">{formatDate(job.started_at)}</div>
                        <div className="text-[10px] text-slate-400">{relativeTime(job.created_at)}</div>
                      </td>
                      <td>
                        <span className="inline-flex items-center gap-1 text-xs tabular-nums text-slate-500">
                          <Clock className="h-3 w-3 text-slate-300" />
                          {duration(job)}
                        </span>
                      </td>
                      <td className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {failed ? (
                            <button
                              type="button"
                              onClick={() => void handleRetry(job)}
                              disabled={retrying === job.id}
                              className="btn-secondary btn-sm"
                            >
                              {retrying === job.id ? (
                                <Spinner className="h-3 w-3" />
                              ) : (
                                <RotateCcw className="h-3 w-3" />
                              )}
                              Retry
                            </button>
                          ) : null}
                          <Link
                            href={`/documents/${job.document_id}`}
                            className="btn-ghost btn-sm"
                            aria-label="Open document"
                          >
                            <ArrowRight className="h-3.5 w-3.5" />
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        {[
          ["Retries", "Exponential backoff up to 3 attempts", "15s · 30s · 60s"],
          ["Stale recovery", "Running jobs requeued after 30 minutes", "WORKER_LOST"],
          ["Concurrency", "SKIP LOCKED enables parallel workers", "PostgreSQL"],
        ].map(([title, description, badge]) => (
          <div key={title} className="rounded-xl border border-slate-200 bg-white p-3.5">
            <div className="text-[11px] font-semibold text-slate-700">{title}</div>
            <div className="mt-0.5 text-[11px] leading-4 text-slate-400">{description}</div>
            <div className="mt-1.5 font-mono text-[10px] text-slate-500">{badge}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
