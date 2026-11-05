"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Sheet as SheetIcon, Table2 } from "lucide-react";
import { getSheetRows } from "@/lib/api";
import type { SheetRow } from "@/lib/types";
import { cn, formatMoney } from "@/lib/format";
import { Alert, EmptyState, Spinner } from "@/components/ui";

const NORMALIZED_COLUMNS: Array<{ key: string; label: string; money?: boolean }> = [
  { key: "invoice_number", label: "Invoice #" },
  { key: "invoice_date", label: "Date" },
  { key: "supplier_name", label: "Supplier" },
  { key: "customer_name", label: "Customer" },
  { key: "subtotal", label: "Subtotal", money: true },
  { key: "tax", label: "Tax", money: true },
  { key: "total", label: "Total", money: true },
  { key: "currency", label: "Currency" },
];

const PAGE_SIZE = 50;

export function SheetView({ documentId }: { documentId: string }) {
  const [rows, setRows] = useState<SheetRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [mode, setMode] = useState<"normalized" | "raw">("normalized");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await getSheetRows(documentId, offset, PAGE_SIZE);
      setRows(response.items);
      setTotal(response.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load spreadsheet rows");
    } finally {
      setLoading(false);
    }
  }, [documentId, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const rawColumns = useMemo(() => {
    const keys = new Set<string>();
    rows.forEach((row) => Object.keys(row.data || {}).forEach((key) => keys.add(key)));
    return Array.from(keys).slice(0, 14);
  }, [rows]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  if (loading && rows.length === 0) {
    return (
      <div className="card flex items-center justify-center gap-3 py-20 text-sm text-slate-500">
        <Spinner /> Loading spreadsheet rows…
      </div>
    );
  }

  if (error) {
    return (
      <Alert tone="error" title="Could not load sheet">
        {error}
      </Alert>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <SheetIcon className="h-4 w-4 text-sky-500" /> Sheet rows
          </h2>
          <p className="mt-0.5 text-xs text-slate-400">
            {total} extracted row{total === 1 ? "" : "s"} · showing {rows.length} per page
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-0.5">
          {(["normalized", "raw"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              className={cn(
                "rounded-md px-2.5 py-1.5 text-[11px] font-semibold capitalize transition",
                mode === value ? "bg-white text-slate-800 shadow-sm" : "text-slate-500 hover:text-slate-700",
              )}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={Table2}
          title="No sheet rows found"
          description="The spreadsheet was parsed but no tabular rows were detected."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="table-base min-w-[900px]">
            <thead>
              <tr>
                <th className="w-16">Row</th>
                <th>Sheet</th>
                {mode === "normalized"
                  ? NORMALIZED_COLUMNS.map((column) => (
                      <th key={column.key} className={column.money ? "text-right" : ""}>
                        {column.label}
                      </th>
                    ))
                  : rawColumns.map((column) => <th key={column}>{column}</th>)}
                <th>Warnings</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="font-mono text-[11px] text-slate-400">{row.row_number}</td>
                  <td>
                    <span className="rounded-md bg-sky-50 px-1.5 py-0.5 text-[10px] font-semibold text-sky-700">
                      {row.sheet_name}
                    </span>
                  </td>
                  {mode === "normalized"
                    ? NORMALIZED_COLUMNS.map((column) => {
                        const value = row.normalized?.[column.key];
                        const display =
                          value === null || value === undefined || value === ""
                            ? "—"
                            : column.money
                              ? formatMoney(String(value), String(row.normalized?.currency || ""))
                              : String(value);
                        return (
                          <td
                            key={column.key}
                            className={cn(
                              "max-w-[180px] truncate text-xs",
                              column.money && "text-right font-medium tabular-nums",
                            )}
                            title={value === null || value === undefined ? "" : String(value)}
                          >
                            {display}
                          </td>
                        );
                      })
                    : rawColumns.map((column) => {
                        const value = row.data?.[column];
                        return (
                          <td
                            key={column}
                            className="max-w-[180px] truncate text-xs"
                            title={value === null || value === undefined ? "" : String(value)}
                          >
                            {value === null || value === undefined || value === ""
                              ? "—"
                              : String(value)}
                          </td>
                        );
                      })}
                  <td>
                    {row.warnings?.length ? (
                      <div className="flex flex-wrap gap-1">
                        {row.warnings.map((warning, index) => (
                          <span
                            key={index}
                            className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700"
                          >
                            {String(warning)}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-[11px] text-emerald-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > 0 ? (
        <div className="flex flex-col items-center justify-between gap-3 border-t border-slate-100 px-5 py-3.5 sm:flex-row">
          <div className="text-xs text-slate-400">
            Rows {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total} · page {Math.floor(offset / PAGE_SIZE) + 1} of{" "}
            {totalPages}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-secondary btn-sm"
              disabled={offset === 0 || loading}
              onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
            >
              <ChevronLeft className="h-3.5 w-3.5" /> Previous
            </button>
            <button
              type="button"
              className="btn-secondary btn-sm"
              disabled={offset + PAGE_SIZE >= total || loading}
              onClick={() => setOffset((value) => value + PAGE_SIZE)}
            >
              Next <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
