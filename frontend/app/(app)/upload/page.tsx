"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  FileText,
  Image as ImageIcon,
  Info,
  Loader2,
  RefreshCw,
  Sheet,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { getDocument, getMeta, uploadDocuments } from "@/lib/api";
import type { DocumentListItem, Meta } from "@/lib/types";
import { cn, formatBytes, isBusy, stageLabel } from "@/lib/format";
import { Alert, PageHeader, ProgressBar, Spinner, StatusBadge } from "@/components/ui";

type QueueStatus = "ready" | "uploading" | "processing" | "done" | "error";

interface QueueItem {
  id: string;
  file: File;
  progress: number;
  status: QueueStatus;
  document?: DocumentListItem;
  error?: string;
}

const FALLBACK_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".xlsx", ".xls", ".csv"];

function fileIcon(file: File) {
  const name = file.name.toLowerCase();
  if (name.endsWith(".pdf")) return FileText;
  if (name.endsWith(".xlsx") || name.endsWith(".xls") || name.endsWith(".csv")) return Sheet;
  return ImageIcon;
}

function extensionOf(name: string): string {
  const index = name.lastIndexOf(".");
  return index === -1 ? "" : name.slice(index).toLowerCase();
}

export default function UploadPage() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const queueRef = useRef(queue);

  useEffect(() => {
    queueRef.current = queue;
  }, [queue]);

  useEffect(() => {
    getMeta().then(setMeta).catch(() => undefined);
  }, []);

  const extensions = meta?.supported_extensions?.length ? meta.supported_extensions : FALLBACK_EXTENSIONS;
  const maxMb = meta?.max_file_mb ?? 200;
  const maxFiles = 20;

  const hasProcessing = useMemo(
    () => queue.some((item) => item.status === "processing"),
    [queue],
  );

  useEffect(() => {
    if (!hasProcessing) return;
    let active = true;
    const tick = async () => {
      const pending = queueRef.current.filter(
        (item) => item.status === "processing" && item.document,
      );
      await Promise.all(
        pending.map(async (item) => {
          if (!item.document) return;
          try {
            const document = await getDocument(item.document.id);
            if (!active) return;
            setQueue((previous) =>
              previous.map((entry) =>
                entry.id === item.id
                  ? {
                      ...entry,
                      document,
                      status: isBusy(document.status)
                        ? "processing"
                        : document.status === "failed"
                          ? "error"
                          : "done",
                      error: document.error_message || undefined,
                    }
                  : entry,
              ),
            );
          } catch {
            // Transient polling errors are ignored; the next tick retries.
          }
        }),
      );
    };
    const timer = window.setInterval(tick, 3000);
    void tick();
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [hasProcessing]);

  function addFiles(files: FileList | File[]) {
    setNotice(null);
    setError(null);
    const incoming = Array.from(files);
    if (!incoming.length) return;

    const existingKeys = new Set(queue.map((item) => `${item.file.name}:${item.file.size}`));
    const accepted: QueueItem[] = [];
    const rejected: string[] = [];

    for (const file of incoming) {
      if (queue.length + accepted.length >= maxFiles) {
        rejected.push(`${file.name}: upload limit is ${maxFiles} files at once`);
        continue;
      }
      const extension = extensionOf(file.name);
      if (!extensions.includes(extension)) {
        rejected.push(`${file.name}: unsupported file type`);
        continue;
      }
      if (file.size > maxMb * 1024 * 1024) {
        rejected.push(`${file.name}: larger than ${maxMb} MB`);
        continue;
      }
      if (file.size === 0) {
        rejected.push(`${file.name}: file is empty`);
        continue;
      }
      const key = `${file.name}:${file.size}`;
      if (existingKeys.has(key)) {
        rejected.push(`${file.name}: already in the queue`);
        continue;
      }
      existingKeys.add(key);
      accepted.push({
        id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
        file,
        progress: 0,
        status: "ready",
      });
    }

    if (accepted.length) setQueue((previous) => [...previous, ...accepted]);
    if (rejected.length) setError(rejected.join(" · "));
  }

  async function startUpload() {
    const ready = queueRef.current.filter((item) => item.status === "ready");
    if (!ready.length) return;
    setBusy(true);
    setError(null);
    setNotice(null);

    for (const item of ready) {
      setQueue((previous) =>
        previous.map((entry) =>
          entry.id === item.id ? { ...entry, status: "uploading", progress: 0, error: undefined } : entry,
        ),
      );
      try {
        const response = await uploadDocuments([item.file], (progress) => {
          setQueue((previous) =>
            previous.map((entry) => (entry.id === item.id ? { ...entry, progress } : entry)),
          );
        });
        const document = response.documents[0];
        const rejected = response.rejected[0];
        setQueue((previous) =>
          previous.map((entry) => {
            if (entry.id !== item.id) return entry;
            if (document) {
              return {
                ...entry,
                progress: 100,
                document,
                status: isBusy(document.status) ? "processing" : "done",
                error: document.status === "failed" ? document.error_message || "Processing failed" : undefined,
              };
            }
            return {
              ...entry,
              status: "error",
              error: rejected ? `${rejected.code}: ${rejected.message}` : "The server rejected this file",
            };
          }),
        );
      } catch (err) {
        setQueue((previous) =>
          previous.map((entry) =>
            entry.id === item.id
              ? {
                  ...entry,
                  status: "error",
                  error: err instanceof Error ? err.message : "Upload failed",
                }
              : entry,
          ),
        );
      }
    }

    setBusy(false);
    setNotice("Upload complete. Processing continues in the background.");
  }

  function removeItem(id: string) {
    setQueue((previous) => previous.filter((item) => item.id !== id));
  }

  const readyCount = queue.filter((item) => item.status === "ready").length;
  const activeCount = queue.filter((item) => ["uploading", "processing"].includes(item.status)).length;
  const doneCount = queue.filter((item) => item.status === "done").length;

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="Ingestion"
        title="Upload documents"
        description="Add invoices, scanned images, or spreadsheets. Files are validated, deduplicated by SHA-256, stored, and queued for background processing."
        actions={
          queue.length ? (
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setQueue([])}
              disabled={busy || activeCount > 0}
            >
              <Trash2 className="h-4 w-4" /> Clear queue
            </button>
          ) : null
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <div
            onDragOver={(event) => {
              event.preventDefault();
              if (!busy) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              if (!busy) addFiles(event.dataTransfer.files);
            }}
            className={cn(
              "relative overflow-hidden rounded-2xl border-2 border-dashed bg-white p-8 text-center transition sm:p-12",
              dragging
                ? "border-accent-400 bg-accent-50/50 shadow-[0_0_0_6px_rgba(16,185,129,0.06)]"
                : "border-slate-200 hover:border-slate-300",
            )}
          >
            <div className="pointer-events-none absolute inset-0 surface-grid opacity-40" />
            <div className="relative mx-auto flex max-w-lg flex-col items-center">
              <div
                className={cn(
                  "flex h-16 w-16 items-center justify-center rounded-2xl transition",
                  dragging
                    ? "bg-accent-500 text-white shadow-lg shadow-accent-500/25"
                    : "bg-ink-950 text-accent-300 shadow-lg shadow-ink-900/10",
                )}
              >
                <UploadCloud className="h-7 w-7" />
              </div>
              <h2 className="mt-5 text-lg font-semibold text-slate-900">
                {dragging ? "Drop files to add them" : "Drag & drop documents here"}
              </h2>
              <p className="mt-1.5 text-sm text-slate-500">
                or{" "}
                <button
                  type="button"
                  onClick={() => inputRef.current?.click()}
                  disabled={busy}
                  className="font-semibold text-accent-700 underline decoration-accent-300 underline-offset-2 hover:text-accent-800 disabled:opacity-50"
                >
                  browse your files
                </button>
                . Up to {maxFiles} files, {maxMb} MB each.
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-1.5">
                {extensions.map((extension) => (
                  <span
                    key={extension}
                    className="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 font-mono text-[10px] font-semibold uppercase text-slate-500"
                  >
                    {extension.replace(".", "")}
                  </span>
                ))}
              </div>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept={extensions.join(",")}
                className="hidden"
                onChange={(event) => {
                  if (event.target.files) addFiles(event.target.files);
                  event.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => inputRef.current?.click()}
                disabled={busy}
                className="btn-secondary mt-6"
              >
                <UploadCloud className="h-4 w-4" /> Choose files
              </button>
            </div>
          </div>

          {error ? <Alert tone="error" title="Some files were not added">{error}</Alert> : null}
          {notice ? (
            <Alert tone="success" title={notice}>
              {doneCount > 0
                ? `${doneCount} document${doneCount === 1 ? "" : "s"} processed. Open a document to review its extraction.`
                : null}
            </Alert>
          ) : null}

          {queue.length ? (
            <section className="card overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold text-slate-900">
                    Upload queue{" "}
                    <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500">
                      {queue.length}
                    </span>
                  </h2>
                  <p className="mt-0.5 text-xs text-slate-400">
                    {readyCount} ready · {activeCount} uploading or processing · {doneCount} complete
                  </p>
                </div>
                <button
                  type="button"
                  onClick={startUpload}
                  disabled={busy || readyCount === 0}
                  className="btn-accent"
                >
                  {busy ? <Spinner /> : <UploadCloud className="h-4 w-4" />}
                  {busy ? "Uploading…" : `Upload ${readyCount || ""} file${readyCount === 1 ? "" : "s"}`}
                </button>
              </div>

              <ul className="divide-y divide-slate-100">
                {queue.map((item) => {
                  const Icon = fileIcon(item.file);
                  return (
                    <li key={item.id} className="px-5 py-4">
                      <div className="flex items-start gap-3">
                        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-500">
                          <Icon className="h-[17px] w-[17px]" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="max-w-full truncate text-sm font-semibold text-slate-800">
                              {item.file.name}
                            </span>
                            <span className="text-[11px] text-slate-400">
                              {formatBytes(item.file.size)}
                            </span>
                            {item.status === "uploading" ? (
                              <span className="chip bg-sky-50 text-sky-700 ring-sky-200">
                                <Loader2 className="h-3 w-3 animate-spin" /> Uploading
                              </span>
                            ) : null}
                            {item.status === "processing" && item.document ? (
                              <StatusBadge status={item.document.status} />
                            ) : null}
                            {item.status === "done" && item.document ? (
                              <StatusBadge status={item.document.status} />
                            ) : null}
                            {item.status === "error" ? (
                              <span className="chip bg-rose-50 text-rose-700 ring-rose-200">
                                <AlertCircle className="h-3 w-3" /> Failed
                              </span>
                            ) : null}
                          </div>

                          {item.status === "uploading" ? (
                            <div className="mt-2 flex items-center gap-3">
                              <ProgressBar value={item.progress} className="max-w-sm" />
                              <span className="text-[11px] tabular-nums text-slate-400">
                                {item.progress}%
                              </span>
                            </div>
                          ) : null}

                          {item.status === "processing" && item.document ? (
                            <div className="mt-2">
                              <div className="flex items-center gap-3">
                                <ProgressBar value={item.document.progress} className="max-w-sm" />
                                <span className="text-[11px] tabular-nums text-slate-400">
                                  {item.document.progress}%
                                </span>
                              </div>
                              <div className="mt-1 flex items-center gap-1.5 text-[11px] text-slate-400">
                                <RefreshCw className="h-3 w-3 animate-spin" />
                                {stageLabel(item.document.stage)} · updates every 3s
                              </div>
                            </div>
                          ) : null}

                          {item.error ? (
                            <p className="mt-1.5 text-xs leading-5 text-rose-600">{item.error}</p>
                          ) : null}

                          {item.status === "done" && item.document ? (
                            <p className="mt-1.5 text-xs text-slate-400">
                              {item.document.summary?.invoice_number
                                ? `Extracted ${item.document.summary.invoice_number}`
                                : "Processing complete"}
                              {item.document.summary?.supplier_name
                                ? ` · ${item.document.summary.supplier_name}`
                                : ""}
                            </p>
                          ) : null}
                        </div>

                        <div className="flex shrink-0 items-center gap-1">
                          {item.document && ["processing", "done"].includes(item.status) ? (
                            <Link
                              href={`/documents/${item.document.id}`}
                              className="btn-ghost btn-sm text-accent-700"
                            >
                              Open <ArrowRight className="h-3.5 w-3.5" />
                            </Link>
                          ) : null}
                          {item.status === "ready" ? (
                            <button
                              type="button"
                              onClick={() => removeItem(item.id)}
                              className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                              aria-label={`Remove ${item.file.name}`}
                            >
                              <X className="h-4 w-4" />
                            </button>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}
        </div>

        <aside className="space-y-5">
          <section className="card p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Sparkles className="h-4 w-4 text-accent-600" /> What happens next
            </h2>
            <ol className="mt-4 space-y-4">
              {[
                ["Validate & store", "Type, size, header, and zip-bomb checks. Azure SHA-256 dedupe prevents double processing.", "1"],
                ["Parse or OCR", "Digital PDF text is used first. Scanned pages fall back to RapidOCR/Tesseract.", "2"],
                ["Extract with evidence", "Groq returns strict JSON with source quotes. Missing values stay null.", "3"],
                ["Validate & reconcile", "Arithmetic, duplicates, PDF↔Excel, and PDF↔PDF checks route exceptions to review.", "4"],
                ["Index & search", "Text and invoice summaries are chunked for keyword + semantic hybrid search.", "5"],
              ].map(([title, description, step]) => (
                <li key={step} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-500">
                    {step}
                  </span>
                  <div>
                    <div className="text-xs font-semibold text-slate-700">{title}</div>
                    <div className="mt-0.5 text-[11px] leading-4 text-slate-400">{description}</div>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section className="card p-5">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Info className="h-4 w-4 text-sky-500" /> Limits & behaviour
            </h2>
            <dl className="mt-3 space-y-2.5 text-xs">
              {[
                ["File size", `${maxMb} MB max`],
                ["Files per upload", `${maxFiles} max`],
                ["PDF pages", "Up to 1,500"],
                ["Duplicates", "SHA-256 reused, not reprocessed"],
                ["Corrupted files", "Marked failed with a retryable job"],
              ].map(([term, value]) => (
                <div key={term} className="flex items-start justify-between gap-3">
                  <dt className="text-slate-400">{term}</dt>
                  <dd className="text-right font-medium text-slate-700">{value}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-ink-950 p-5 text-white">
            <div className="flex items-center gap-2 text-xs font-semibold text-accent-300">
              <CheckCircle2 className="h-4 w-4" /> Processing worker
            </div>
            <p className="mt-2 text-[11px] leading-5 text-slate-400">
              Uploads are queued in the database. If files stay queued, start the worker:
            </p>
            <code className="mt-3 block overflow-x-auto rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-[10px] text-accent-200">
              uv run python -m app.worker
            </code>
            <p className="mt-2 text-[10px] leading-4 text-slate-500">
              In production run workers separately from the API; they scale horizontally using
              <span className="font-mono"> FOR UPDATE SKIP LOCKED</span>.
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}
