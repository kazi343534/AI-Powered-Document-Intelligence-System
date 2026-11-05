"use client";

import type { LucideIcon } from "lucide-react";
import {
  AlertCircle,
  CheckCircle2,
  Info,
  Loader2,
  XCircle,
  X,
} from "lucide-react";
import { cn, confidenceTone, percent, severityTone, statusLabel, STATUS_STYLES } from "@/lib/format";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin", className)} aria-hidden />;
}

export function LoadingScreen({ label = "Loading workspace" }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-[#f5f7fb]">
      <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl bg-ink-900 text-accent-300 shadow-lift">
        <span className="text-lg font-black">D</span>
        <span className="absolute -right-1 -top-1 h-3 w-3 animate-ping rounded-full bg-accent-400" />
      </div>
      <div className="flex items-center gap-2 text-sm font-medium text-slate-500">
        <Spinner /> {label}
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  eyebrow?: string;
}) {
  return (
    <div className="mb-7 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        {eyebrow ? (
          <div className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.16em] text-accent-700">
            {eyebrow}
          </div>
        ) : null}
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-[28px]">
          {title}
        </h1>
        {description ? (
          <p className="mt-1.5 max-w-3xl text-sm leading-6 text-slate-500">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <span className={cn("chip", STATUS_STYLES[status] || STATUS_STYLES.uploaded, className)}>
      {status === "processing" || status === "running" ? (
        <Spinner className="h-3 w-3" />
      ) : (
        <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      )}
      {statusLabel(status)}
    </span>
  );
}

export function ConfidenceBadge({
  value,
  showLabel = false,
}: {
  value: number | null | undefined;
  showLabel?: boolean;
}) {
  return (
    <span className={cn("chip tabular-nums", confidenceTone(value))}>
      {value === null || value === undefined ? "—" : percent(value)}
      {showLabel ? <span className="font-medium opacity-70">confidence</span> : null}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const Icon = severity === "error" ? XCircle : severity === "warning" ? AlertCircle : Info;
  return (
    <span className={cn("chip", severityTone(severity))}>
      <Icon className="h-3 w-3" />
      {severity === "error" ? "Error" : severity === "warning" ? "Warning" : "Info"}
    </span>
  );
}

export function ProgressBar({
  value,
  className,
  tone = "accent",
}: {
  value: number;
  className?: string;
  tone?: "accent" | "ink" | "rose";
}) {
  const safe = Math.max(0, Math.min(100, value || 0));
  return (
    <div
      className={cn("h-2 w-full overflow-hidden rounded-full bg-slate-100", className)}
      role="progressbar"
      aria-valuenow={safe}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn(
          "h-full rounded-full transition-all duration-500",
          tone === "rose" ? "bg-rose-500" : tone === "ink" ? "bg-ink-900" : "bg-accent-500",
        )}
        style={{ width: `${safe}%` }}
      />
    </div>
  );
}

export function Alert({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: "info" | "error" | "success" | "warning";
  title?: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  const styles = {
    info: "border-sky-200 bg-sky-50 text-sky-800",
    error: "border-rose-200 bg-rose-50 text-rose-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
  }[tone];
  const Icon = tone === "error" ? XCircle : tone === "success" ? CheckCircle2 : tone === "warning" ? AlertCircle : Info;
  return (
    <div className={cn("flex items-start gap-3 rounded-xl border p-3.5 text-sm", styles)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        {title ? <div className="font-semibold">{title}</div> : null}
        {children ? <div className={cn(title && "mt-0.5", "text-[13px] leading-5 opacity-90")}>{children}</div> : null}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  compact = false,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "px-6 py-10" : "px-6 py-16",
      )}
    >
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-500">
        <Icon className="h-5 w-5" />
      </div>
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {description ? (
        <p className="mt-1.5 max-w-md text-[13px] leading-5 text-slate-500">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function TableSkeleton({ rows = 5, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="divide-y divide-slate-100">
      {Array.from({ length: rows }).map((_, row) => (
        <div key={row} className="flex items-center gap-4 px-4 py-4">
          {Array.from({ length: cols }).map((__, col) => (
            <div
              key={col}
              className={cn(
                "skeleton h-4",
                col === 0 ? "w-2/5" : col === cols - 1 ? "w-16" : "w-24",
              )}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function Modal({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  width = "max-w-lg",
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close dialog"
        className="absolute inset-0 bg-ink-950/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "relative w-full animate-fade-up rounded-2xl border border-slate-200 bg-white p-6 shadow-lift",
          width,
        )}
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          aria-label="Close"
        >
          <X className="h-4 w-4" />
        </button>
        <h2 className="pr-8 text-lg font-semibold text-slate-900">{title}</h2>
        {description ? <p className="mt-1 text-sm leading-6 text-slate-500">{description}</p> : null}
        {children ? <div className="mt-5">{children}</div> : null}
        {footer ? <div className="mt-6 flex justify-end gap-2">{footer}</div> : null}
      </div>
    </div>
  );
}

export function InlineStat({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-slate-900">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}
