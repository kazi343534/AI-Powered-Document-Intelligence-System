"use client";

import { useMemo, useState } from "react";
import { Check, CheckCircle2, EyeOff, ShieldCheck } from "lucide-react";
import type { Finding } from "@/lib/types";
import { cn } from "@/lib/format";
import { EmptyState, SeverityBadge, Spinner } from "@/components/ui";

export function FindingsList({
  findings,
  onUpdate,
  emptyTitle = "No validation findings",
  emptyDescription = "This invoice passed all automated checks.",
  compact = false,
}: {
  findings: Finding[];
  onUpdate: (id: string, status: "resolved" | "dismissed") => Promise<void>;
  emptyTitle?: string;
  emptyDescription?: string;
  compact?: boolean;
}) {
  const [showResolved, setShowResolved] = useState(false);
  const [working, setWorking] = useState<string | null>(null);

  const open = findings.filter((finding) => finding.status === "open");
  const resolved = findings.filter((finding) => finding.status !== "open");
  const visible = showResolved ? findings : open;

  const counts = useMemo(
    () => ({
      error: open.filter((finding) => finding.severity === "error").length,
      warning: open.filter((finding) => finding.severity === "warning").length,
      info: open.filter((finding) => finding.severity === "info").length,
    }),
    [open],
  );

  if (!findings.length) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title={emptyTitle}
        description={emptyDescription}
        compact={compact}
      />
    );
  }

  async function update(id: string, status: "resolved" | "dismissed") {
    setWorking(id);
    try {
      await onUpdate(id, status);
    } finally {
      setWorking(null);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {counts.error > 0 ? (
            <span className="chip bg-rose-50 text-rose-700 ring-rose-200">{counts.error} errors</span>
          ) : null}
          {counts.warning > 0 ? (
            <span className="chip bg-amber-50 text-amber-700 ring-amber-200">
              {counts.warning} warnings
            </span>
          ) : null}
          {counts.info > 0 ? (
            <span className="chip bg-sky-50 text-sky-700 ring-sky-200">{counts.info} info</span>
          ) : null}
          {!open.length ? (
            <span className="chip bg-emerald-50 text-emerald-700 ring-emerald-200">
              <CheckCircle2 className="h-3 w-3" /> All clear
            </span>
          ) : null}
        </div>
        {resolved.length ? (
          <button
            type="button"
            onClick={() => setShowResolved((value) => !value)}
            className="ml-auto text-[11px] font-semibold text-slate-500 hover:text-slate-800"
          >
            {showResolved ? "Hide" : "Show"} resolved ({resolved.length})
          </button>
        ) : null}
      </div>

      {!visible.length ? (
        <div className="flex items-center gap-2 px-5 py-6 text-xs text-slate-400">
          <ShieldCheck className="h-4 w-4 text-emerald-500" />
          No open findings. Resolve or dismiss checks before approving.
        </div>
      ) : (
        <ul className="divide-y divide-slate-100">
          {visible.map((finding) => (
            <li
              key={finding.id}
              className={cn(
                "px-4 py-3.5 sm:px-5",
                finding.status !== "open" && "bg-slate-50/60 opacity-75",
              )}
            >
              <div className="flex items-start gap-3">
                <div className="mt-0.5">
                  <SeverityBadge severity={finding.severity} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-500">
                      {finding.rule_code}
                    </span>
                    {finding.field_path ? (
                      <span className="font-mono text-[10px] text-slate-400">
                        {finding.field_path}
                      </span>
                    ) : null}
                    {finding.status !== "open" ? (
                      <span className="text-[10px] font-semibold capitalize text-slate-400">
                        {finding.status}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1.5 text-[13px] leading-5 text-slate-700">{finding.message}</p>
                  {finding.expected || finding.actual ? (
                    <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
                      {finding.expected ? (
                        <span className="text-slate-500">
                          Expected:{" "}
                          <span className="font-mono font-semibold text-slate-700">
                            {finding.expected}
                          </span>
                        </span>
                      ) : null}
                      {finding.actual ? (
                        <span className="text-slate-500">
                          Actual:{" "}
                          <span className="font-mono font-semibold text-slate-700">
                            {finding.actual}
                          </span>
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                  {finding.resolution_note ? (
                    <p className="mt-1.5 text-[11px] italic text-slate-400">
                      Note: {finding.resolution_note}
                    </p>
                  ) : null}
                </div>
                {finding.status === "open" ? (
                  <div className="flex shrink-0 flex-col gap-1 sm:flex-row">
                    <button
                      type="button"
                      onClick={() => void update(finding.id, "resolved")}
                      disabled={working === finding.id}
                      className="btn-secondary btn-sm"
                      title="Mark as resolved"
                    >
                      {working === finding.id ? <Spinner className="h-3 w-3" /> : <Check className="h-3 w-3" />}
                      Resolve
                    </button>
                    <button
                      type="button"
                      onClick={() => void update(finding.id, "dismissed")}
                      disabled={working === finding.id}
                      className="btn-ghost btn-sm"
                      title="Dismiss this finding"
                    >
                      <EyeOff className="h-3 w-3" /> Dismiss
                    </button>
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
