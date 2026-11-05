"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Filter, RefreshCw, Search, UploadCloud, X } from "lucide-react";
import { listDocuments } from "@/lib/api";
import type { DocumentListItem } from "@/lib/types";
import { isBusy } from "@/lib/format";
import { Alert, PageHeader } from "@/components/ui";
import { DocumentTable } from "@/components/DocumentTable";

const PAGE_SIZE = 25;

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "completed", label: "Completed" },
  { value: "needs_review", label: "Needs review" },
  { value: "processing", label: "Processing" },
  { value: "queued", label: "Queued" },
  { value: "failed", label: "Failed" },
];

const KIND_OPTIONS = [
  { value: "", label: "All types" },
  { value: "pdf", label: "PDF" },
  { value: "image", label: "Image / scan" },
  { value: "spreadsheet", label: "Spreadsheet" },
];

export default function DocumentsPage() {
  const [items, setItems] = useState<DocumentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [qInput, setQInput] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const response = await listDocuments({
          q: q || undefined,
          status: status || undefined,
          kind: kind || undefined,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        });
        setItems(response.items);
        setTotal(response.total);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load documents");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [q, status, kind, page],
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initialStatus = params.get("status") || "";
    const initialKind = params.get("kind") || "";
    const initialQuery = params.get("q") || "";
    setStatus(initialStatus);
    setKind(initialKind);
    setQ(initialQuery);
    setQInput(initialQuery);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const hasBusy = items.some((item) => isBusy(item.status));

  useEffect(() => {
    if (!hasBusy) return;
    const timer = window.setInterval(() => void load(true), 4000);
    return () => window.clearInterval(timer);
  }, [hasBusy, load]);

  function applyFilters(nextQ = qInput) {
    setPage(0);
    setQ(nextQ.trim());
    setRefreshing(true);
    const params = new URLSearchParams();
    if (nextQ.trim()) params.set("q", nextQ.trim());
    if (status) params.set("status", status);
    if (kind) params.set("kind", kind);
    const suffix = params.toString();
    window.history.replaceState(null, "", suffix ? `/documents?${suffix}` : "/documents");
  }

  function resetFilters() {
    setQ("");
    setQInput("");
    setStatus("");
    setKind("");
    setPage(0);
    setRefreshing(true);
    window.history.replaceState(null, "", "/documents");
  }

  const pageStart = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const pageEnd = Math.min(total, (page + 1) * PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtersActive = Boolean(q || status || kind);

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="Archive"
        title="Documents"
        description="Every uploaded file, its processing state, and the latest invoice summary."
        actions={
          <>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setRefreshing(true);
                void load(true);
              }}
              disabled={refreshing}
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} /> Refresh
            </button>
            <Link href="/upload" className="btn-accent">
              <UploadCloud className="h-4 w-4" /> Upload
            </Link>
          </>
        }
      />

      <section className="card mb-5 p-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            applyFilters();
          }}
          className="flex flex-col gap-3 lg:flex-row lg:items-end"
        >
          <div className="min-w-0 flex-1">
            <label htmlFor="document-search" className="label">
              Search
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                id="document-search"
                className="input pl-10"
                placeholder="Filename, invoice number, or supplier…"
                value={qInput}
                onChange={(event) => setQInput(event.target.value)}
              />
            </div>
          </div>
          <div className="w-full lg:w-44">
            <label htmlFor="document-status" className="label">
              Status
            </label>
            <select
              id="document-status"
              className="input"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(0);
                setRefreshing(true);
              }}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="w-full lg:w-44">
            <label htmlFor="document-kind" className="label">
              Type
            </label>
            <select
              id="document-kind"
              className="input"
              value={kind}
              onChange={(event) => {
                setKind(event.target.value);
                setPage(0);
                setRefreshing(true);
              }}
            >
              {KIND_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button type="submit" className="btn-primary">
              <Filter className="h-4 w-4" /> Apply
            </button>
            {filtersActive ? (
              <button type="button" onClick={resetFilters} className="btn-ghost" aria-label="Reset filters">
                <X className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        </form>
        {filtersActive ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Active filters
            </span>
            {q ? <span className="chip bg-slate-100 text-slate-600 ring-slate-200">“{q}”</span> : null}
            {status ? (
              <span className="chip bg-slate-100 text-slate-600 ring-slate-200">
                {STATUS_OPTIONS.find((option) => option.value === status)?.label || status}
              </span>
            ) : null}
            {kind ? (
              <span className="chip bg-slate-100 text-slate-600 ring-slate-200">
                {KIND_OPTIONS.find((option) => option.value === kind)?.label || kind}
              </span>
            ) : null}
          </div>
        ) : null}
      </section>

      {error ? (
        <div className="mb-5">
          <Alert tone="error" title="Could not load documents">
            {error}
          </Alert>
        </div>
      ) : null}

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              {filtersActive ? "Filtered documents" : "All documents"}
            </h2>
            <p className="mt-0.5 text-xs text-slate-400">
              {total === 0
                ? "No matching results"
                : `Showing ${pageStart}–${pageEnd} of ${total}`}
              {hasBusy ? " · live updates" : ""}
            </p>
          </div>
          {hasBusy ? (
            <span className="chip bg-sky-50 text-sky-700 ring-sky-200">
              <RefreshCw className="h-3 w-3 animate-spin" /> Processing
            </span>
          ) : null}
        </div>

        <DocumentTable
          items={items}
          loading={loading}
          emptyTitle={filtersActive ? "No documents match these filters" : "No documents yet"}
          emptyDescription={
            filtersActive
              ? "Try a different search term, status, or document type."
              : "Upload an invoice, scan, or spreadsheet to begin."
          }
          emptyAction={
            filtersActive ? (
              <button type="button" onClick={resetFilters} className="btn-secondary">
                Clear filters
              </button>
            ) : (
              <Link href="/upload" className="btn-accent">
                <UploadCloud className="h-4 w-4" /> Upload a document
              </Link>
            )
          }
        />

        {total > 0 ? (
          <div className="flex flex-col items-center justify-between gap-3 border-t border-slate-100 px-5 py-3.5 sm:flex-row">
            <div className="text-xs text-slate-400">
              Page {page + 1} of {totalPages}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-secondary btn-sm"
                disabled={page === 0 || loading}
                onClick={() => setPage((value) => Math.max(0, value - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn-secondary btn-sm"
                disabled={page + 1 >= totalPages || loading}
                onClick={() => setPage((value) => value + 1)}
              >
                Next
              </button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
