"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  FileJson,
  FileSearch,
  FileText,
  GitCompareArrows,
  Image as ImageIcon,
  ListChecks,
  RefreshCw,
  RotateCcw,
  Search,
  Sheet as SheetIcon,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import {
  approveDocument,
  downloadDocument,
  getDocument,
  getDocumentText,
  reprocessDocument,
  retryJob,
  updateFinding,
} from "@/lib/api";
import type { DocumentDetail, Job, PageInfo, Reconciliation } from "@/lib/types";
import {
  cn,
  formatBytes,
  formatDate,
  formatMoney,
  isBusy,
  kindLabel,
  percent,
  relativeTime,
  stageLabel,
} from "@/lib/format";
import {
  Alert,
  ConfidenceBadge,
  EmptyState,
  Modal,
  ProgressBar,
  Spinner,
  StatusBadge,
} from "@/components/ui";
import { DocumentPreview } from "@/components/DocumentPreview";
import { ExtractionReview } from "@/components/ExtractionReview";
import { FindingsList } from "@/components/FindingsList";
import { SheetView } from "@/components/SheetView";

type Tab = "review" | "pages" | "findings" | "history" | "reconciliation" | "sheet";

const KIND_ICON = {
  pdf: FileText,
  image: ImageIcon,
  spreadsheet: SheetIcon,
};

function PageTextViewer({
  doc,
  onOpenPreview,
}: {
  doc: DocumentDetail;
  onOpenPreview: (page: number) => void;
}) {
  const [selected, setSelected] = useState(doc.pages[0]?.page_number ?? 1);
  const [page, setPage] = useState<PageInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    getDocumentText(doc.id, selected, selected)
      .then((response) => {
        if (!active) return;
        setPage(response.pages[0] ?? null);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Could not load page text");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [doc.id, selected]);

  return (
    <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <div className="card max-h-[640px] overflow-y-auto p-2">
        <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          Pages
        </div>
        <div className="space-y-0.5">
          {doc.pages.map((item) => (
            <button
              key={item.page_number}
              type="button"
              onClick={() => setSelected(item.page_number)}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition",
                selected === item.page_number
                  ? "bg-ink-900 text-white"
                  : "text-slate-600 hover:bg-slate-100",
              )}
            >
              <span className="w-8 shrink-0 font-mono text-[10px] opacity-70">
                p.{item.page_number}
              </span>
              <span className="min-w-0 flex-1 truncate capitalize">{item.text_source}</span>
              {item.ocr_confidence !== null ? (
                <span
                  className={cn(
                    "text-[9px] font-semibold",
                    selected === item.page_number ? "text-accent-300" : "text-slate-400",
                  )}
                >
                  {percent(item.ocr_confidence)}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-3.5">
          <div>
            <div className="text-sm font-semibold text-slate-900">Page {selected} text</div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-400">
              {page ? (
                <>
                  <span className="capitalize">{page.text_source === "digital" ? "Digital text layer" : page.text_source === "ocr" ? "OCR result" : "No text"}</span>
                  {page.ocr_confidence !== null ? (
                    <span>· OCR confidence {percent(page.ocr_confidence)}</span>
                  ) : null}
                  {page.width ? <span>· {page.width} × {page.height}px</span> : null}
                </>
              ) : (
                <span>Loading page metadata…</span>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onOpenPreview(selected)}
            className="btn-secondary btn-sm"
          >
            <ExternalLink className="h-3.5 w-3.5" /> Show on page
          </button>
        </div>
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-sm text-slate-500">
            <Spinner /> Loading text…
          </div>
        ) : error ? (
          <div className="p-5">
            <Alert tone="error">{error}</Alert>
          </div>
        ) : page?.text ? (
          <pre className="max-h-[640px] overflow-auto whitespace-pre-wrap break-words bg-slate-50/50 px-5 py-4 font-sans text-[12px] leading-6 text-slate-700">
            {page.text}
          </pre>
        ) : (
          <EmptyState
            icon={FileText}
            title="No text on this page"
            description={
              page?.error
                ? page.error
                : "The page may be blank, corrupted, or too low quality for OCR. Open the preview to inspect it visually."
            }
            compact
          />
        )}
      </div>
    </div>
  );
}

function JobHistory({ jobs, onRetry }: { jobs: Job[]; onRetry: (job: Job) => Promise<void> }) {
  const [retrying, setRetrying] = useState<string | null>(null);

  if (!jobs.length) {
    return (
      <div className="card">
        <EmptyState icon={Clock} title="No job history" description="Processing jobs for this document will appear here." compact />
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-4">
        <h2 className="text-sm font-semibold text-slate-900">Processing history</h2>
        <p className="mt-0.5 text-xs text-slate-400">
          Every attempt, retry, and state transition for this document.
        </p>
      </div>
      <ol className="divide-y divide-slate-100">
        {jobs.map((job) => (
          <li key={job.id} className="px-5 py-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500">
                <Clock className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={job.status} />
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
                    {job.job_type}
                  </span>
                  <span className="font-mono text-[10px] text-slate-400">{job.id.slice(0, 8)}</span>
                  <span className="text-[11px] text-slate-400">
                    attempt {job.attempts}/{job.max_attempts}
                  </span>
                </div>
                <div className="mt-2 grid gap-2 text-[11px] text-slate-500 sm:grid-cols-3">
                  <div>
                    <span className="text-slate-400">Created</span>
                    <div className="font-medium text-slate-600">{formatDate(job.created_at)}</div>
                  </div>
                  <div>
                    <span className="text-slate-400">Started</span>
                    <div className="font-medium text-slate-600">{formatDate(job.started_at)}</div>
                  </div>
                  <div>
                    <span className="text-slate-400">Finished</span>
                    <div className="font-medium text-slate-600">{formatDate(job.finished_at)}</div>
                  </div>
                </div>
                {job.status !== "completed" ? (
                  <div className="mt-2 max-w-md">
                    <ProgressBar value={job.progress} tone={job.status === "failed" ? "rose" : "accent"} />
                  </div>
                ) : null}
                {job.error_message ? (
                  <div className="mt-2 flex items-start gap-1.5 rounded-lg border border-rose-100 bg-rose-50 px-3 py-2 text-[11px] text-rose-700">
                    <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>
                      {job.error_code ? `${job.error_code}: ` : ""}
                      {job.error_message}
                    </span>
                  </div>
                ) : null}
              </div>
              {["failed", "cancelled"].includes(job.status) ? (
                <button
                  type="button"
                  className="btn-secondary btn-sm shrink-0"
                  disabled={retrying === job.id}
                  onClick={async () => {
                    setRetrying(job.id);
                    try {
                      await onRetry(job);
                    } finally {
                      setRetrying(null);
                    }
                  }}
                >
                  {retrying === job.id ? <Spinner className="h-3 w-3" /> : <RotateCcw className="h-3 w-3" />}
                  Retry
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ReconciliationView({ items }: { items: Reconciliation[] }) {
  if (!items.length) {
    return (
      <div className="card">
        <EmptyState
          icon={GitCompareArrows}
          title="No cross-document matches"
          description="Upload a matching spreadsheet or a second copy of an invoice to trigger PDF↔Excel or PDF↔PDF reconciliation."
          compact
        />
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {items.map((item) => (
        <div key={item.id} className="card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "chip",
                  item.status === "matched"
                    ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                    : "bg-amber-50 text-amber-700 ring-amber-200",
                )}
              >
                {item.status === "matched" ? <CheckCircle2 className="h-3 w-3" /> : <TriangleAlert className="h-3 w-3" />}
                {item.status === "matched" ? "Matched" : "Mismatch"}
              </span>
              <span className="text-xs font-semibold text-slate-700">
                {item.match_type === "pdf_pdf" ? "PDF ↔ PDF duplicate" : "PDF ↔ spreadsheet"}
              </span>
              <span className="text-[11px] text-slate-400">
                confidence {percent(item.confidence)}
              </span>
            </div>
            {item.matched_document_id ? (
              <Link
                href={`/documents/${item.matched_document_id}`}
                className="text-[11px] font-semibold text-accent-700 hover:text-accent-800"
              >
                Open matched document →
              </Link>
            ) : null}
          </div>
          {item.diffs.length ? (
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>This invoice</th>
                    <th>Matched source</th>
                    <th>Severity</th>
                  </tr>
                </thead>
                <tbody>
                  {item.diffs.map((diff, index) => (
                    <tr key={index}>
                      <td className="font-mono text-[11px] text-slate-500">{diff.field}</td>
                      <td className="font-mono text-xs text-slate-700">{diff.invoice_value ?? "—"}</td>
                      <td className="font-mono text-xs text-slate-700">{diff.sheet_value ?? "—"}</td>
                      <td>
                        <span
                          className={cn(
                            "chip",
                            diff.severity === "error"
                              ? "bg-rose-50 text-rose-700 ring-rose-200"
                              : "bg-amber-50 text-amber-700 ring-amber-200",
                          )}
                        >
                          {diff.severity}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-5 py-4 text-xs text-emerald-700">
              All comparable values agree. No differences were found.
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function DocumentDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("review");
  const [activeInvoiceId, setActiveInvoiceId] = useState<string | null>(null);
  const [previewPage, setPreviewPage] = useState(1);
  const [reprocessOpen, setReprocessOpen] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [approving, setApproving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const initialized = useRef(false);

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const detail = await getDocument(id);
        setDoc(detail);
        setError(null);
        if (!initialized.current) {
          initialized.current = true;
          if (detail.kind === "spreadsheet") setTab("sheet");
          if (detail.invoices[0]) {
            setActiveInvoiceId(detail.invoices[0].id);
            setPreviewPage(detail.invoices[0].page_start);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load document");
      } finally {
        setLoading(false);
      }
    },
    [id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const busy = doc ? isBusy(doc.status) : false;

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => void load(true), 3000);
    return () => window.clearInterval(timer);
  }, [busy, load]);

  useEffect(() => {
    if (!doc) return;
    if (!activeInvoiceId || !doc.invoices.some((invoice) => invoice.id === activeInvoiceId)) {
      const first = doc.invoices[0];
      if (first) {
        setActiveInvoiceId(first.id);
        setPreviewPage(first.page_start);
      }
    }
  }, [doc, activeInvoiceId]);

  const activeInvoice = useMemo(
    () => doc?.invoices.find((invoice) => invoice.id === activeInvoiceId) ?? doc?.invoices[0] ?? null,
    [doc, activeInvoiceId],
  );

  const invoiceFindings = useMemo(
    () => (doc && activeInvoice ? doc.findings.filter((finding) => finding.invoice_id === activeInvoice.id) : []),
    [doc, activeInvoice],
  );

  const openFindings = doc?.findings.filter((finding) => finding.status === "open").length ?? 0;

  const canApprove =
    !!doc &&
    doc.status === "needs_review" &&
    !busy &&
    openFindings === 0 &&
    !!activeInvoice?.current_extraction;

  async function handleDownload() {
    if (!doc) return;
    setActionError(null);
    try {
      await downloadDocument(doc.id, doc.original_filename);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Download failed");
    }
  }

  async function handleReprocess() {
    if (!doc) return;
    setReprocessing(true);
    setActionError(null);
    try {
      await reprocessDocument(doc.id);
      setReprocessOpen(false);
      initialized.current = true;
      setDoc((previous) =>
        previous ? { ...previous, status: "queued", stage: "queued", progress: 0, error_message: null } : previous,
      );
      await load(true);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not reprocess document");
    } finally {
      setReprocessing(false);
    }
  }

  async function handleApprove() {
    if (!doc) return;
    setApproving(true);
    setActionError(null);
    try {
      const result = await approveDocument(doc.id, "Approved via document review UI");
      setDoc((previous) =>
        previous ? { ...previous, status: result.status === "completed" ? "completed" : previous.status } : previous,
      );
      await load(true);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Could not approve document");
    } finally {
      setApproving(false);
    }
  }

  async function handleFindingUpdate(findingId: string, status: "resolved" | "dismissed") {
    await updateFinding(findingId, status);
    await load(true);
  }

  async function handleRetry(job: Job) {
    await retryJob(job.id);
    await load(true);
  }

  function exportJson() {
    if (!activeInvoice?.current_extraction) return;
    const blob = new Blob([JSON.stringify(activeInvoice.current_extraction, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${doc?.summary?.invoice_number || doc?.original_filename || "extraction"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  if (loading && !doc) {
    return (
      <div className="animate-fade-up">
        <div className="skeleton h-4 w-32" />
        <div className="skeleton mt-4 h-8 w-2/3" />
        <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="card p-4">
              <div className="skeleton h-3 w-20" />
              <div className="skeleton mt-2 h-5 w-32" />
            </div>
          ))}
        </div>
        <div className="skeleton mt-6 h-96 w-full" />
      </div>
    );
  }

  if (error || !doc) {
    return (
      <div className="card">
        <EmptyState
          icon={AlertCircle}
          title="Document not available"
          description={error || "The document may have been removed."}
          action={
            <Link href="/documents" className="btn-secondary">
              Back to documents
            </Link>
          }
        />
      </div>
    );
  }

  const KindIcon = KIND_ICON[doc.kind] || FileText;
  const tabs: Array<{ key: Tab; label: string; icon: React.ElementType; count?: number }> = [
    ...(doc.kind === "spreadsheet"
      ? [{ key: "sheet" as Tab, label: "Sheet rows", icon: SheetIcon, count: doc.page_count }]
      : [
          { key: "review" as Tab, label: "Review", icon: FileSearch },
          { key: "pages" as Tab, label: "Pages", icon: FileText, count: doc.page_count },
        ]),
    { key: "findings", label: "Findings", icon: ListChecks, count: openFindings },
    { key: "reconciliation", label: "Reconciliation", icon: GitCompareArrows, count: doc.reconciliations.length },
    { key: "history", label: "History", icon: Clock },
  ];

  return (
    <div className="animate-fade-up">
      <Link
        href="/documents"
        className="mb-4 inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All documents
      </Link>

      <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className={cn(
              "mt-0.5 flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ring-1 ring-inset",
              doc.kind === "pdf"
                ? "bg-rose-50 text-rose-600 ring-rose-100"
                : doc.kind === "image"
                  ? "bg-violet-50 text-violet-600 ring-violet-100"
                  : "bg-sky-50 text-sky-600 ring-sky-100",
            )}
          >
            <KindIcon className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="max-w-full truncate text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
                {doc.original_filename}
              </h1>
              <StatusBadge status={doc.status} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
              <span>{kindLabel(doc.kind)}</span>
              <span>·</span>
              <span>{formatBytes(doc.size_bytes)}</span>
              <span>·</span>
              <span>
                {doc.page_count} {doc.kind === "spreadsheet" ? "sheet" : "page"}
                {doc.page_count === 1 ? "" : "s"}
              </span>
              <span>·</span>
              <span>uploaded {formatDate(doc.created_at)}</span>
              {doc.invoice_count > 1 ? (
                <>
                  <span>·</span>
                  <span>{doc.invoice_count} invoices</span>
                </>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void handleDownload()} className="btn-secondary btn-sm">
            <Download className="h-3.5 w-3.5" /> Download
          </button>
          {activeInvoice?.current_extraction ? (
            <button type="button" onClick={exportJson} className="btn-secondary btn-sm">
              <FileJson className="h-3.5 w-3.5" /> JSON
            </button>
          ) : null}
          {doc.summary?.invoice_number ? (
            <Link
              href={`/search?mode=hybrid&q=${encodeURIComponent(doc.summary.invoice_number)}`}
              className="btn-secondary btn-sm"
            >
              <Search className="h-3.5 w-3.5" /> Find similar
            </Link>
          ) : null}
          {canApprove ? (
            <button
              type="button"
              onClick={() => void handleApprove()}
              disabled={approving}
              className="btn-success btn-sm"
            >
              <CheckCircle2 className="h-3.5 w-3.5" /> {approving ? "Approving…" : "Approve Document"}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setReprocessOpen(true)}
            disabled={busy}
            className="btn-primary btn-sm"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", busy && "animate-spin")} />
            {busy ? "Processing" : "Reprocess"}
          </button>
        </div>
      </div>

      {actionError ? (
        <div className="mb-4">
          <Alert tone="error">{actionError}</Alert>
        </div>
      ) : null}

      {doc.summary ? (
        <div className="mb-5 grid overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card sm:grid-cols-2 lg:grid-cols-4">
          {[
            [
              "Invoice number",
              doc.summary.invoice_number || "—",
              doc.invoice_count > 1 ? `${doc.invoice_count} logical invoices` : null,
            ],
            ["Supplier", doc.summary.supplier_name || "—", null],
            [
              "Total",
              doc.summary.total ? formatMoney(doc.summary.total, doc.summary.currency) : "—",
              doc.summary.currency,
            ],
            [
              "Extraction confidence",
              doc.summary.confidence !== null ? percent(doc.summary.confidence) : "—",
              doc.summary.review_status,
            ],
          ].map(([label, value, hint], index) => (
            <div
              key={String(label)}
              className={cn(
                "px-5 py-4",
                index > 0 && "border-t border-slate-100 sm:border-l sm:border-t-0",
                index === 2 && "sm:border-t lg:border-t-0",
              )}
            >
              <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                {label}
              </div>
              <div className="mt-1 truncate text-sm font-semibold text-slate-900">{value}</div>
              {hint ? (
                <div className="mt-0.5 truncate text-[10px] capitalize text-slate-400">{hint}</div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}

      {busy ? (
        <div className="mb-5 overflow-hidden rounded-2xl border border-sky-200 bg-white shadow-card">
          <div className="flex items-start gap-3 p-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600">
              <Sparkles className="h-5 w-5 animate-pulse-soft" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-semibold text-slate-900">
                  {stageLabel(doc.stage)}
                  <span className="ml-2 text-xs font-normal text-slate-400">{doc.progress}%</span>
                </div>
                <span className="text-[10px] font-medium text-slate-400">auto-refreshing every 3s</span>
              </div>
              <div className="mt-2">
                <ProgressBar value={doc.progress} />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
                <span>Queued → Parse/OCR → Extraction → Validation → Index</span>
                {doc.jobs[0] ? (
                  <span>
                    Job attempt {doc.jobs[0].attempts}/{doc.jobs[0].max_attempts}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {doc.status === "failed" ? (
        <div className="mb-5">
          <Alert
            tone="error"
            title={doc.error_code ? `Processing failed · ${doc.error_code}` : "Processing failed"}
            action={
              <button type="button" onClick={() => setReprocessOpen(true)} className="btn-danger btn-sm shrink-0">
                <RotateCcw className="h-3 w-3" /> Retry
              </button>
            }
          >
            {doc.error_message || "The document could not be processed. Retry after checking the file."}
          </Alert>
        </div>
      ) : null}

      {doc.status === "needs_review" && !busy ? (
        <div className="mb-5 flex flex-col gap-2 rounded-2xl border border-amber-200 bg-amber-50/70 p-4 sm:flex-row sm:items-center">
          <TriangleAlert className="h-4 w-4 shrink-0 text-amber-600" />
          <div className="min-w-0 flex-1 text-xs leading-5 text-amber-800">
            <span className="font-semibold">Human review required.</span>{" "}
            {openFindings > 0
              ? `${openFindings} open finding${openFindings === 1 ? "" : "s"} must be resolved or dismissed before approval.`
              : "Extraction confidence is below the auto-approval threshold."}
          </div>
          {doc.findings.length ? (
            <button type="button" onClick={() => setTab("findings")} className="btn-secondary btn-sm shrink-0">
              View findings
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="mb-5 flex gap-1 overflow-x-auto border-b border-slate-200 pb-px">
        {tabs.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-xs font-semibold transition",
              tab === item.key
                ? "border-accent-500 text-slate-900"
                : "border-transparent text-slate-400 hover:border-slate-300 hover:text-slate-700",
            )}
          >
            <item.icon className="h-3.5 w-3.5" />
            {item.label}
            {item.count ? (
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.5 text-[9px] font-bold",
                  tab === item.key ? "bg-accent-50 text-accent-700" : "bg-slate-100 text-slate-400",
                )}
              >
                {item.count}
              </span>
            ) : null}
          </button>
        ))}
      </div>

      {tab === "review" && doc.kind !== "spreadsheet" ? (
        !doc.invoices.length ? (
          <div className="card">
            <EmptyState
              icon={FileSearch}
              title={busy ? "Extraction in progress" : "No invoices found"}
              description={
                busy
                  ? "This page will update automatically when extraction completes."
                  : "The document may not be an invoice, or its text could not be read. Check the Pages tab and reprocess."
              }
              action={
                !busy ? (
                  <button type="button" onClick={() => setTab("pages")} className="btn-secondary">
                    Inspect page text
                  </button>
                ) : undefined
              }
            />
          </div>
        ) : (
          <div className="space-y-4">
            {doc.invoices.length > 1 ? (
              <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-slate-200 bg-white p-1.5 shadow-sm">
                <span className="px-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Logical invoice
                </span>
                {doc.invoices.map((invoice, index) => (
                  <button
                    key={invoice.id}
                    type="button"
                    onClick={() => {
                      setActiveInvoiceId(invoice.id);
                      setPreviewPage(invoice.page_start);
                    }}
                    className={cn(
                      "rounded-lg px-2.5 py-1.5 text-[11px] font-semibold transition",
                      activeInvoice?.id === invoice.id
                        ? "bg-ink-900 text-white shadow-sm"
                        : "text-slate-500 hover:bg-slate-100",
                    )}
                  >
                    #{index + 1} · pages {invoice.page_start}–{invoice.page_end}
                    {invoice.current_extraction?.data.invoice_number.value
                      ? ` · ${invoice.current_extraction.data.invoice_number.value}`
                      : ""}
                  </button>
                ))}
              </div>
            ) : null}

            <div className="grid gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
              <div className="xl:sticky xl:top-20 xl:h-fit">
                <DocumentPreview
                  documentId={doc.id}
                  page={previewPage}
                  pageCount={doc.page_count}
                  filename={doc.original_filename}
                  onPageChange={(page) => {
                    setPreviewPage(page);
                    setTab("review");
                  }}
                />
              </div>
              <div>
                {activeInvoice?.current_extraction ? (
                  <ExtractionReview
                    invoice={activeInvoice}
                    extraction={activeInvoice.current_extraction}
                    findings={invoiceFindings}
                    onReload={() => load(true)}
                    onPageChange={(page) => {
                      setPreviewPage(page);
                      document.querySelector('[data-preview-top]')?.scrollIntoView({ behavior: "smooth" });
                    }}
                  />
                ) : (
                  <div className="card">
                    <EmptyState
                      icon={FileSearch}
                      title="Extraction not available"
                      description="This invoice does not have an extraction yet. Reprocess the document or check the job history."
                      action={
                        <button type="button" onClick={() => setReprocessOpen(true)} className="btn-secondary">
                          Reprocess
                        </button>
                      }
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      ) : null}

      {tab === "pages" && doc.kind !== "spreadsheet" ? (
        <PageTextViewer
          doc={doc}
          onOpenPreview={(page) => {
            setPreviewPage(page);
            setTab("review");
          }}
        />
      ) : null}

      {tab === "sheet" && doc.kind === "spreadsheet" ? <SheetView documentId={doc.id} /> : null}

      {tab === "findings" ? (
        <div className="card overflow-hidden">
          <div className="border-b border-slate-100 px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Validation findings</h2>
                <p className="mt-0.5 text-xs text-slate-400">
                  All checks across the document, including resolved and dismissed items.
                </p>
              </div>
              <span className="chip bg-slate-100 text-slate-600 ring-slate-200">
                {openFindings} open / {doc.findings.length} total
              </span>
            </div>
          </div>
          <FindingsList
            findings={doc.findings}
            onUpdate={handleFindingUpdate}
            emptyDescription="No validation issues were raised for this document."
          />
        </div>
      ) : null}

      {tab === "history" ? <JobHistory jobs={doc.jobs} onRetry={handleRetry} /> : null}

      {tab === "reconciliation" ? <ReconciliationView items={doc.reconciliations} /> : null}

      <div className="mt-6 flex flex-wrap items-center justify-between gap-2 text-[10px] text-slate-400">
        <span className="font-mono">document {doc.id}</span>
        <span>
          Last updated {relativeTime(doc.updated_at)} · human approval is required for exceptions
        </span>
      </div>

      <Modal
        open={reprocessOpen}
        title="Reprocess this document?"
        description="Existing pages, extractions, findings, reconciliations, and search chunks will be removed and rebuilt from the stored original. This creates a new versioned extraction."
        onClose={() => {
          if (!reprocessing) setReprocessOpen(false);
        }}
        footer={
          <>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setReprocessOpen(false)}
              disabled={reprocessing}
            >
              Cancel
            </button>
            <button type="button" className="btn-primary" onClick={() => void handleReprocess()} disabled={reprocessing}>
              {reprocessing ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
              {reprocessing ? "Queueing…" : "Reprocess document"}
            </button>
          </>
        }
      >
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5 text-xs leading-5 text-slate-500">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
            <span>
              Manual corrections will remain in the audit log but will no longer be the current result.
              A worker must be running to process the new job.
            </span>
          </div>
        </div>
      </Modal>
    </div>
  );
}
