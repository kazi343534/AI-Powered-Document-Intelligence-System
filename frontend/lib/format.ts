import type { DocumentStatus, Finding } from "./types";

export function cn(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** exponent).toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatShortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value).getTime();
  if (Number.isNaN(date)) return "—";
  const seconds = Math.round((Date.now() - date) / 1000);
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function formatMoney(amount: string | null | undefined, currency?: string | null): string {
  if (!amount) return "—";
  const value = Number(amount);
  if (Number.isNaN(value)) return `${currency || ""} ${amount}`.trim();
  if (currency) {
    try {
      return new Intl.NumberFormat("en-GB", {
        style: "currency",
        currency,
        maximumFractionDigits: 2,
      }).format(value);
    } catch {
      return `${currency} ${value.toLocaleString("en-GB", { minimumFractionDigits: 2 })}`;
    }
  }
  return value.toLocaleString("en-GB", { minimumFractionDigits: 2 });
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

export function initials(name: string | null | undefined): string {
  if (!name) return "U";
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export const STATUS_LABELS: Record<string, string> = {
  uploaded: "Uploaded",
  queued: "Queued",
  processing: "Processing",
  completed: "Completed",
  needs_review: "Needs review",
  failed: "Failed",
  cancelled: "Cancelled",
  running: "Running",
  retry_wait: "Retrying",
};

export const STATUS_STYLES: Record<string, string> = {
  uploaded: "bg-slate-100 text-slate-600 ring-slate-200",
  queued: "bg-sky-50 text-sky-700 ring-sky-200",
  processing: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  completed: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  needs_review: "bg-amber-50 text-amber-700 ring-amber-200",
  failed: "bg-rose-50 text-rose-700 ring-rose-200",
  cancelled: "bg-slate-100 text-slate-500 ring-slate-200",
  running: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  retry_wait: "bg-amber-50 text-amber-700 ring-amber-200",
};

export const STAGE_LABELS: Record<string, string> = {
  queued: "Waiting for a worker",
  downloading: "Fetching source file",
  parsing: "Parsing document",
  text_extraction: "Reading digital text",
  ocr: "OCR in progress",
  extraction: "AI extraction",
  spreadsheet_parsing: "Parsing sheets",
  validation: "Validating data",
  indexing: "Indexing for search",
  review_required: "Awaiting review",
  completed: "Complete",
  failed: "Failed",
  retry_wait: "Waiting to retry",
};

export function isBusy(status: string): boolean {
  return ["uploaded", "queued", "processing", "running", "retry_wait"].includes(status);
}

export function confidenceTone(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined) return "bg-slate-100 text-slate-500 ring-slate-200";
  if (confidence >= 0.85) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (confidence >= 0.6) return "bg-amber-50 text-amber-700 ring-amber-200";
  return "bg-rose-50 text-rose-700 ring-rose-200";
}

export function severityTone(severity: Finding["severity"] | string): string {
  if (severity === "error") return "bg-rose-50 text-rose-700 ring-rose-200";
  if (severity === "warning") return "bg-amber-50 text-amber-700 ring-amber-200";
  return "bg-sky-50 text-sky-700 ring-sky-200";
}

export function docTitle(name: string): string {
  return name.replace(/\.[^.]+$/, "");
}

export function truncate(value: string, length = 80): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] || stage.replace(/_/g, " ");
}

export function kindLabel(kind: string): string {
  if (kind === "pdf") return "PDF";
  if (kind === "image") return "Image";
  if (kind === "spreadsheet") return "Spreadsheet";
  return kind;
}

export function numericConfidence(value: number | null | undefined): number | null {
  return typeof value === "number" ? value : null;
}

export function statusFromDoc(status: DocumentStatus): string {
  return status;
}
