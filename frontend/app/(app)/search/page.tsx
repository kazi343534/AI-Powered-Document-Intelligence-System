"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  FileText,
  Image as ImageIcon,
  Layers,
  Search as SearchIcon,
  Sheet,
  Sparkles,
  Type,
  X,
} from "lucide-react";
import { getMeta, searchDocuments } from "@/lib/api";
import type { Meta, SearchHit, SearchResponse } from "@/lib/types";
import { cn, formatMoney, kindLabel } from "@/lib/format";
import { Alert, EmptyState, PageHeader, Spinner, StatusBadge } from "@/components/ui";

const MODES = [
  { value: "hybrid", label: "Hybrid", icon: Layers, hint: "Keyword + semantic, reciprocal rank fusion" },
  { value: "keyword", label: "Keyword", icon: Type, hint: "Full-text search; falls back to ILIKE on SQLite" },
  { value: "semantic", label: "Semantic", icon: Sparkles, hint: "Vector similarity using FastEmbed bge-small" },
] as const;

type SearchMode = (typeof MODES)[number]["value"];

function Highlight({ text, query }: { text: string; query: string }) {
  const terms = query
    .split(/\s+/)
    .map((term) => term.trim())
    .filter((term) => term.length > 1)
    .slice(0, 6);
  if (!terms.length) return <>{text}</>;
  const pattern = new RegExp(`(${terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) =>
        terms.some((term) => term.toLowerCase() === part.toLowerCase()) ? (
          <mark key={index} className="rounded bg-amber-100 px-0.5 text-slate-900">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

function ResultCard({ hit, query }: { hit: SearchHit; query: string }) {
  const doc = hit.document;
  const Icon = doc.kind === "pdf" ? FileText : doc.kind === "image" ? ImageIcon : Sheet;
  return (
    <Link
      href={`/documents/${doc.id}`}
      className="group block rounded-2xl border border-slate-200/80 bg-white p-4 shadow-card transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-lift"
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset",
            doc.kind === "pdf"
              ? "bg-rose-50 text-rose-600 ring-rose-100"
              : doc.kind === "image"
                ? "bg-violet-50 text-violet-600 ring-violet-100"
                : "bg-sky-50 text-sky-600 ring-sky-100",
          )}
        >
          <Icon className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="max-w-full truncate text-sm font-semibold text-slate-900 group-hover:text-accent-700">
              {doc.original_filename}
            </h3>
            <StatusBadge status={doc.status} />
            <span className="chip bg-slate-50 text-slate-500 ring-slate-200">{kindLabel(doc.kind)}</span>
            <span className="chip bg-slate-50 text-slate-500 ring-slate-200">
              {hit.match === "keyword"
                ? "keyword"
                : hit.match === "semantic"
                  ? "semantic"
                  : hit.match === "filter"
                    ? "latest"
                    : "hybrid"}
            </span>
          </div>

          <p className="mt-2 line-clamp-3 text-[13px] leading-6 text-slate-600">
            <Highlight text={hit.snippet} query={query} />
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
            {hit.page_number ? <span>Page {hit.page_number}</span> : null}
            {doc.summary?.invoice_number ? <span>{doc.summary.invoice_number}</span> : null}
            {doc.summary?.supplier_name ? <span>{doc.summary.supplier_name}</span> : null}
            {doc.summary?.total ? (
              <span className="font-semibold text-slate-600">
                {formatMoney(doc.summary.total, doc.summary.currency)}
              </span>
            ) : null}
            {hit.score ? <span className="ml-auto tabular-nums">score {hit.score.toFixed(3)}</span> : null}
          </div>
        </div>
        <ArrowRight className="mt-2 h-4 w-4 shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-slate-500" />
      </div>
    </Link>
  );
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [supplier, setSupplier] = useState("");
  const [currency, setCurrency] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const runSearch = useCallback(
    async (searchQuery: string, searchMode: SearchMode) => {
      setLoading(true);
      try {
        const result = await searchDocuments({
          q: searchQuery,
          mode: searchMode,
          status: status || undefined,
          kind: kind || undefined,
          supplier: supplier || undefined,
          currency: currency || undefined,
          limit: 30,
        });
        setResponse(result);
        setSubmittedQuery(searchQuery);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed");
      } finally {
        setLoading(false);
      }
    },
    [status, kind, supplier, currency],
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const initialMode = params.get("mode");
    const initialQuery = params.get("q") || "";
    const modeValue = MODES.some((item) => item.value === initialMode)
      ? (initialMode as SearchMode)
      : "hybrid";
    setMode(modeValue);
    setQuery(initialQuery);
    void runSearch(initialQuery, modeValue);
    getMeta().then(setMeta).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    window.history.replaceState(
      null,
      "",
      `/search?mode=${mode}${query.trim() ? `&q=${encodeURIComponent(query.trim())}` : ""}`,
    );
    void runSearch(query.trim(), mode);
  }

  function chooseMode(next: SearchMode) {
    setMode(next);
    window.history.replaceState(
      null,
      "",
      `/search?mode=${next}${query.trim() ? `&q=${encodeURIComponent(query.trim())}` : ""}`,
    );
    if (response) void runSearch(query.trim(), next);
  }

  const resultCount = response?.items.length ?? 0;
  const modeMeta = useMemo(() => MODES.find((item) => item.value === mode)!, [mode]);

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="Discovery"
        title="Search"
        description="Find invoices by text, supplier, invoice number, or meaning. Hybrid search fuses PostgreSQL full-text ranking with pgvector cosine similarity."
        actions={
          meta ? (
            <span className="chip bg-white text-slate-600 ring-slate-200">
              <Sparkles className="h-3 w-3 text-accent-600" />
              {meta.embedding_provider.split(":").pop()}
            </span>
          ) : null
        }
      />

      <section className="card p-5">
        <form onSubmit={onSubmit}>
          <div className="flex flex-col gap-3 lg:flex-row">
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input
                className="input py-3 pl-12 pr-10 text-[15px]"
                placeholder="Try “steel bracket ACME”, “INV-2024-0042”, or “office supplies”…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search query"
              />
              {query ? (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                  aria-label="Clear search"
                >
                  <X className="h-4 w-4" />
                </button>
              ) : null}
            </div>
            <button type="submit" className="btn-primary px-5" disabled={loading}>
              {loading ? <Spinner /> : <SearchIcon className="h-4 w-4" />} Search
            </button>
          </div>

          <div className="mt-4 flex flex-col justify-between gap-3 border-t border-slate-100 pt-4 lg:flex-row lg:items-center">
            <div className="flex flex-wrap gap-1.5">
              {MODES.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => chooseMode(item.value)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition",
                    mode === item.value
                      ? "bg-ink-900 text-white shadow-sm"
                      : "text-slate-500 hover:bg-slate-100 hover:text-slate-800",
                  )}
                >
                  <item.icon className="h-3.5 w-3.5" />
                  {item.label}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-400">{modeMeta.hint}</p>
          </div>

          <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            <select className="input py-2 text-xs" value={kind} onChange={(event) => setKind(event.target.value)} aria-label="Document type">
              <option value="">All document types</option>
              <option value="pdf">PDF</option>
              <option value="image">Image / scan</option>
              <option value="spreadsheet">Spreadsheet</option>
            </select>
            <select className="input py-2 text-xs" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Document status">
              <option value="">All statuses</option>
              <option value="completed">Completed</option>
              <option value="needs_review">Needs review</option>
              <option value="processing">Processing</option>
              <option value="failed">Failed</option>
            </select>
            <input
              className="input py-2 text-xs"
              placeholder="Supplier contains…"
              value={supplier}
              onChange={(event) => setSupplier(event.target.value)}
              aria-label="Supplier filter"
            />
            <input
              className="input py-2 text-xs uppercase"
              placeholder="Currency (e.g. GBP)"
              maxLength={3}
              value={currency}
              onChange={(event) => setCurrency(event.target.value.toUpperCase())}
              aria-label="Currency filter"
            />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Try
            </span>
            {["ACME", "steel bracket", "INV-2024-0042", "Northwind"].map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => {
                  setQuery(suggestion);
                  void runSearch(suggestion, mode);
                  window.history.replaceState(
                    null,
                    "",
                    `/search?mode=${mode}&q=${encodeURIComponent(suggestion)}`,
                  );
                }}
                className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-500 transition hover:border-accent-200 hover:bg-accent-50 hover:text-accent-800"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </form>
      </section>

      {error ? (
        <div className="mt-5">
          <Alert tone="error" title="Search failed">
            {error}
          </Alert>
        </div>
      ) : null}

      <section className="mt-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-xs font-medium text-slate-500">
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <Spinner className="h-3.5 w-3.5" /> Searching…
              </span>
            ) : submittedQuery ? (
              <>
                <span className="font-semibold text-slate-800">{resultCount}</span> result
                {resultCount === 1 ? "" : "s"} for “{submittedQuery}”
                <span className="ml-2 text-slate-400">· {response?.mode || mode}</span>
              </>
            ) : (
              <>
                <span className="font-semibold text-slate-800">{resultCount}</span> recent documents
              </>
            )}
          </div>
          {response?.mode === "semantic" && meta && !meta.ai_enabled ? (
            <span className="hidden text-[10px] text-slate-400 sm:block">
              Embeddings: {meta.embedding_provider}
            </span>
          ) : null}
        </div>

        {loading && !response ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, index) => (
              <div key={index} className="card p-4">
                <div className="skeleton h-4 w-1/3" />
                <div className="skeleton mt-3 h-3 w-full" />
                <div className="skeleton mt-2 h-3 w-2/3" />
              </div>
            ))}
          </div>
        ) : response && response.items.length ? (
          <div className="space-y-3">
            {response.items.map((hit) => (
              <ResultCard key={`${hit.document_id}-${hit.invoice_id || "doc"}`} hit={hit} query={submittedQuery} />
            ))}
          </div>
        ) : (
          <div className="card">
            <EmptyState
              icon={SearchIcon}
              title={submittedQuery ? "No matches found" : "Your archive is empty"}
              description={
                submittedQuery
                  ? "Try fewer words, a different mode, or clear the filters. Keyword mode requires exact terms."
                  : "Upload documents to build a searchable index of page text and invoice summaries."
              }
              action={
                submittedQuery ? (
                  <button
                    type="button"
                    onClick={() => {
                      setQuery("");
                      setSupplier("");
                      setCurrency("");
                      setKind("");
                      setStatus("");
                      void runSearch("", mode);
                    }}
                    className="btn-secondary"
                  >
                    Clear search
                  </button>
                ) : (
                  <Link href="/upload" className="btn-accent">
                    Upload documents
                  </Link>
                )
              }
            />
          </div>
        )}
      </section>
    </div>
  );
}
