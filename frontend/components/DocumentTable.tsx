"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, FileText, Files, Image as ImageIcon, Sheet, TriangleAlert } from "lucide-react";
import type { DocumentListItem } from "@/lib/types";
import {
  cn,
  formatBytes,
  formatMoney,
  kindLabel,
  relativeTime,
} from "@/lib/format";
import { ConfidenceBadge, EmptyState, StatusBadge, TableSkeleton } from "@/components/ui";

function KindIcon({ kind }: { kind: string }) {
  const Icon = kind === "image" ? ImageIcon : kind === "spreadsheet" ? Sheet : FileText;
  const tone =
    kind === "image"
      ? "bg-violet-50 text-violet-600 ring-violet-100"
      : kind === "spreadsheet"
        ? "bg-sky-50 text-sky-600 ring-sky-100"
        : "bg-rose-50 text-rose-600 ring-rose-100";
  return (
    <span className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ring-inset", tone)}>
      <Icon className="h-[17px] w-[17px]" />
    </span>
  );
}

export function DocumentTable({
  items,
  loading = false,
  emptyAction,
  emptyTitle = "No documents yet",
  emptyDescription = "Upload an invoice, scan, or spreadsheet to start processing.",
  compact = false,
}: {
  items: DocumentListItem[];
  loading?: boolean;
  emptyAction?: React.ReactNode;
  emptyTitle?: string;
  emptyDescription?: string;
  compact?: boolean;
}) {
  const router = useRouter();

  if (loading) return <TableSkeleton rows={compact ? 4 : 6} cols={compact ? 5 : 7} />;

  if (!items.length) {
    return (
      <EmptyState
        icon={Files}
        title={emptyTitle}
        description={emptyDescription}
        action={emptyAction}
        compact={compact}
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="table-base min-w-[860px]">
        <thead>
          <tr>
            <th>Document</th>
            <th>Status</th>
            <th>Invoice</th>
            <th className="text-right">Total</th>
            <th>Confidence</th>
            {!compact ? <th>Checks</th> : null}
            <th className="text-right">Uploaded</th>
            <th aria-label="Open" />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              key={item.id}
              className="group cursor-pointer"
              onClick={() => router.push(`/documents/${item.id}`)}
            >
              <td>
                <div className="flex items-center gap-3">
                  <KindIcon kind={item.kind} />
                  <div className="min-w-0">
                    <Link
                      href={`/documents/${item.id}`}
                      onClick={(event) => event.stopPropagation()}
                      className="block max-w-[280px] truncate font-semibold text-slate-800 hover:text-accent-700"
                      title={item.original_filename}
                    >
                      {item.original_filename}
                    </Link>
                    <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-400">
                      <span>{kindLabel(item.kind)}</span>
                      <span className="text-slate-300">·</span>
                      <span>{formatBytes(item.size_bytes)}</span>
                      {item.page_count ? (
                        <>
                          <span className="text-slate-300">·</span>
                          <span>
                            {item.page_count} {item.kind === "spreadsheet" ? "sheet" : "page"}
                            {item.page_count === 1 ? "" : "s"}
                          </span>
                        </>
                      ) : null}
                      {item.duplicate ? (
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-500">
                          Duplicate file
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>
              </td>
              <td>
                <StatusBadge status={item.status} />
                {item.status === "processing" ? (
                  <div className="mt-1.5 w-28">
                    <div className="h-1 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className="h-full rounded-full bg-accent-500 transition-all"
                        style={{ width: `${item.progress}%` }}
                      />
                    </div>
                    <div className="mt-1 text-[10px] text-slate-400">
                      {item.progress}% · {item.stage.replace(/_/g, " ")}
                    </div>
                  </div>
                ) : null}
              </td>
              <td>
                <div className="max-w-[220px]">
                  <div className="truncate font-medium text-slate-700">
                    {item.summary?.invoice_number || "—"}
                  </div>
                  <div className="truncate text-[11px] text-slate-400">
                    {item.summary?.supplier_name || (item.invoice_count > 1 ? `${item.invoice_count} invoices` : "Awaiting extraction")}
                  </div>
                </div>
              </td>
              <td className="text-right">
                <div className="font-semibold tabular-nums text-slate-800">
                  {item.summary?.total
                    ? formatMoney(item.summary.total, item.summary.currency)
                    : "—"}
                </div>
                {item.summary?.currency ? (
                  <div className="text-[10px] font-medium uppercase tracking-wider text-slate-400">
                    {item.summary.currency}
                  </div>
                ) : null}
              </td>
              <td>
                <ConfidenceBadge value={item.summary?.confidence} />
              </td>
              {!compact ? (
                <td>
                  {item.finding_count > 0 ? (
                    <span className="chip bg-amber-50 text-amber-700 ring-amber-200">
                      <TriangleAlert className="h-3 w-3" />
                      {item.finding_count} open
                    </span>
                  ) : item.status === "completed" ? (
                    <span className="text-[11px] font-medium text-emerald-600">Clear</span>
                  ) : (
                    <span className="text-[11px] text-slate-400">—</span>
                  )}
                </td>
              ) : null}
              <td className="text-right">
                <div className="text-xs font-medium text-slate-500">
                  {relativeTime(item.updated_at)}
                </div>
                {item.error_code ? (
                  <div className="text-[10px] font-semibold text-rose-600">{item.error_code}</div>
                ) : null}
              </td>
              <td>
                <ChevronRight className="h-4 w-4 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-slate-500" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
