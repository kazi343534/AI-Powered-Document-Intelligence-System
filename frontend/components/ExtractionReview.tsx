"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Edit3,
  Plus,
  Quote,
  RotateCcw,
  Save,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { saveExtraction, reviewInvoice, updateFinding } from "@/lib/api";
import type {
  Extraction,
  ExtractionData,
  ExtractionLineItem,
  FieldValue,
  Finding,
  Invoice,
} from "@/lib/types";
import { useAuth } from "@/components/AuthProvider";
import {
  cn,
  confidenceTone,
  formatMoney,
  percent,
  relativeTime,
  statusLabel,
  STATUS_STYLES,
} from "@/lib/format";
import { Alert, ConfidenceBadge, ProgressBar, Spinner } from "@/components/ui";
import { FindingsList } from "@/components/FindingsList";

type FieldKey =
  | "invoice_number"
  | "invoice_date"
  | "supplier_name"
  | "customer_name"
  | "currency"
  | "subtotal"
  | "tax"
  | "total";

const FIELD_DEFS: Array<{
  key: FieldKey;
  label: string;
  required?: boolean;
  kind: "text" | "date" | "money" | "currency";
  placeholder: string;
}> = [
  { key: "invoice_number", label: "Invoice number", required: true, kind: "text", placeholder: "INV-2024-0042" },
  { key: "invoice_date", label: "Invoice date", required: true, kind: "date", placeholder: "YYYY-MM-DD" },
  { key: "supplier_name", label: "Supplier", required: true, kind: "text", placeholder: "Supplier name" },
  { key: "customer_name", label: "Customer", kind: "text", placeholder: "Customer name" },
  { key: "currency", label: "Currency", required: true, kind: "currency", placeholder: "GBP" },
  { key: "subtotal", label: "Subtotal", kind: "money", placeholder: "0.00" },
  { key: "tax", label: "Tax", kind: "money", placeholder: "0.00" },
  { key: "total", label: "Total", required: true, kind: "money", placeholder: "0.00" },
];

function inputValue(data: ExtractionData, key: FieldKey): string {
  return data[key]?.value ?? "";
}

function displayValue(data: ExtractionData, key: FieldKey): string {
  const value = data[key]?.value;
  if (!value) return "Not found";
  if (["subtotal", "tax", "total"].includes(key)) {
    return formatMoney(value, data.currency?.value);
  }
  return value;
}

function lineItemsFrom(data: ExtractionData): ExtractionLineItem[] {
  return (data.line_items || []).map((item) => ({
    description: item.description || "",
    quantity: item.quantity ?? null,
    unit_price: item.unit_price ?? null,
    amount: item.amount ?? null,
    tax_rate: item.tax_rate ?? null,
    confidence: item.confidence ?? 1,
    page: item.page ?? null,
  }));
}

function normalizeItems(items: ExtractionLineItem[]): ExtractionLineItem[] {
  return items
    .map((item) => ({
      description: (item.description || "").trim(),
      quantity: item.quantity?.trim() || null,
      unit_price: item.unit_price?.trim() || null,
      amount: item.amount?.trim() || null,
      tax_rate: item.tax_rate?.trim() || null,
      confidence: 1,
      page: item.page ?? null,
    }))
    .filter((item) => item.description || item.amount || item.quantity || item.unit_price);
}

function EvidenceLine({
  field,
  onPage,
}: {
  field: FieldValue;
  onPage: (page: number) => void;
}) {
  if (!field.evidence?.quote && !field.evidence?.page) {
    return (
      <div className="mt-1 text-[10px] font-medium text-amber-600">
        {field.value ? "No source quote — verify manually" : ""}
      </div>
    );
  }
  return (
    <div className="mt-1.5 flex flex-wrap items-start gap-1.5 text-[10px] leading-4 text-slate-400">
      <Quote className="mt-0.5 h-3 w-3 shrink-0 text-slate-300" />
      <span className="line-clamp-2 max-w-full italic">
        {field.evidence.quote || "Source page"}
      </span>
      {field.evidence.page ? (
        <button
          type="button"
          onClick={() => onPage(field.evidence!.page!)}
          className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-slate-500 hover:bg-accent-50 hover:text-accent-700"
        >
          p.{field.evidence.page}
        </button>
      ) : null}
    </div>
  );
}

function FieldRow({
  def,
  field,
  data,
  onPage,
}: {
  def: (typeof FIELD_DEFS)[number];
  field: FieldValue;
  data: ExtractionData;
  onPage: (page: number) => void;
}) {
  const missingRequired = def.required && !field.value;
  return (
    <div className={cn("py-3", missingRequired && "rounded-lg bg-rose-50/50 px-2")}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          {def.label}
          {def.required ? <span className="text-rose-400">*</span> : null}
        </div>
        <ConfidenceBadge value={field.value ? field.confidence : null} />
      </div>
      <div
        className={cn(
          "mt-1 break-words text-[13px] font-semibold leading-5",
          field.value ? "text-slate-900" : "text-slate-400",
        )}
      >
        {displayValue(data, def.key)}
      </div>
      {field.value ? <EvidenceLine field={field} onPage={onPage} /> : null}
      {field.reason ? (
        <div className="mt-1 text-[10px] text-amber-600">{field.reason}</div>
      ) : null}
    </div>
  );
}

function LineItemsTable({ data }: { data: ExtractionData }) {
  const items = data.line_items || [];
  if (!items.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-5 text-center">
        <div className="text-xs font-semibold text-slate-500">No line items extracted</div>
        <p className="mt-1 text-[11px] text-slate-400">
          Invoice total must still be checked. Add items during correction if the source lists them.
        </p>
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="table-base min-w-[520px]">
        <thead>
          <tr>
            <th>Description</th>
            <th className="text-right">Qty</th>
            <th className="text-right">Unit price</th>
            <th className="text-right">Amount</th>
            <th className="text-right">Tax</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={`${item.description}-${index}`}>
              <td className="max-w-[240px]">
                <div className="text-xs font-medium text-slate-700">{item.description || "—"}</div>
                {item.page ? (
                  <div className="text-[10px] text-slate-400">page {item.page}</div>
                ) : null}
              </td>
              <td className="text-right text-xs tabular-nums">{item.quantity ?? "—"}</td>
              <td className="text-right text-xs tabular-nums">{item.unit_price ?? "—"}</td>
              <td className="text-right text-xs font-semibold tabular-nums text-slate-800">
                {item.amount ? formatMoney(item.amount, data.currency?.value) : "—"}
              </td>
              <td className="text-right text-xs tabular-nums">{item.tax_rate ? `${item.tax_rate}%` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ExtractionReview({
  invoice,
  extraction,
  findings,
  onReload,
  onPageChange,
}: {
  invoice: Invoice;
  extraction: Extraction;
  findings: Finding[];
  onReload: () => Promise<void>;
  onPageChange: (page: number) => void;
}) {
  const { user } = useAuth();
  const data = extraction.data;
  const canEdit = user?.role === "admin" || user?.role === "reviewer";
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  const [items, setItems] = useState<ExtractionLineItem[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setEditing(false);
    setError(null);
    setMessage(null);
    setForm(
      Object.fromEntries(FIELD_DEFS.map((definition) => [definition.key, inputValue(data, definition.key)])),
    );
    setItems(lineItemsFrom(data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [extraction.id]);

  const blocking = useMemo(
    () => findings.filter((finding) => finding.status === "open" && finding.severity !== "info"),
    [findings],
  );
  const approved = extraction.review_status === "approved";

  const itemSum = useMemo(
    () =>
      (data.line_items || []).reduce((total, item) => {
        const amount = Number.parseFloat(item.amount || "0");
        return total + (Number.isFinite(amount) ? amount : 0);
      }, 0),
    [data.line_items],
  );
  const subtotalNumber = Number.parseFloat(data.subtotal?.value || "");
  const sumMismatch =
    Number.isFinite(subtotalNumber) &&
    (data.line_items?.length || 0) > 0 &&
    Math.abs(itemSum - subtotalNumber) > 0.011;

  function startEditing() {
    setForm(
      Object.fromEntries(FIELD_DEFS.map((definition) => [definition.key, inputValue(data, definition.key)])),
    );
    setItems(lineItemsFrom(data));
    setReason("");
    setError(null);
    setMessage(null);
    setEditing(true);
  }

  async function handleSave() {
    const changes: Record<string, unknown> = {};
    FIELD_DEFS.forEach((definition) => {
      const original = inputValue(data, definition.key).trim();
      const next = (form[definition.key] ?? "").trim();
      if (next !== original) changes[definition.key] = next || null;
    });
    const originalItems = JSON.stringify(lineItemsFrom(data).map((item) => ({ ...item, confidence: 1 })));
    const nextItems = normalizeItems(items);
    if (JSON.stringify(nextItems) !== originalItems) changes.line_items = nextItems;

    if (!Object.keys(changes).length) {
      setError("No changes to save.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await saveExtraction(
        invoice.id,
        extraction.id,
        extraction.version,
        changes,
        reason.trim() || "Manual correction from review UI",
      );
      setEditing(false);
      setMessage("Correction saved as a new extraction version. Validation was re-run.");
      await onReload();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not save correction. Reload the page and try again.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleReview(action: "approve" | "reopen") {
    setReviewing(true);
    setError(null);
    setMessage(null);
    try {
      await reviewInvoice(invoice.id, action);
      setMessage(action === "approve" ? "Invoice approved." : "Invoice reopened for review.");
      await onReload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review action failed.");
    } finally {
      setReviewing(false);
    }
  }

  async function handleFindingUpdate(id: string, status: "resolved" | "dismissed") {
    setError(null);
    try {
      await updateFinding(id, status);
      await onReload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update finding.");
    }
  }

  const sourceLabel =
    extraction.source === "ai"
      ? `AI · ${extraction.model}`
      : extraction.source === "manual"
        ? "Manual correction"
        : "Deterministic fallback";

  return (
    <div className="space-y-4">
      <div className="card overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-start">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold text-slate-900">Extracted fields</h2>
              <span className="chip bg-slate-100 text-slate-600 ring-slate-200">
                v{extraction.version}
              </span>
              <span className="chip bg-slate-50 text-slate-500 ring-slate-200">
                <Sparkles className="h-3 w-3" /> {sourceLabel}
              </span>
              <span className={cn("chip", STATUS_STYLES[approved ? "completed" : "needs_review"])}>
                {approved ? "Approved" : "Pending review"}
              </span>
            </div>
            <div className="mt-1 text-[11px] text-slate-400">
              Prompt {extraction.prompt_version || "—"} · {relativeTime(extraction.created_at)}
              {extraction.reviewed_at ? ` · reviewed ${relativeTime(extraction.reviewed_at)}` : ""}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {approved ? (
              canEdit ? (
                <button
                  type="button"
                  onClick={() => void handleReview("reopen")}
                  disabled={reviewing}
                  className="btn-secondary btn-sm"
                >
                  {reviewing ? <Spinner className="h-3 w-3" /> : <RotateCcw className="h-3 w-3" />}
                  Reopen
                </button>
              ) : null
            ) : (
              <>
                {canEdit && !editing ? (
                  <button type="button" onClick={startEditing} className="btn-secondary btn-sm">
                    <Edit3 className="h-3 w-3" /> Correct
                  </button>
                ) : null}
                {canEdit ? (
                  <button
                    type="button"
                    onClick={() => void handleReview("approve")}
                    disabled={reviewing || blocking.length > 0}
                    className="btn-accent btn-sm"
                    title={
                      blocking.length
                        ? "Resolve or dismiss blocking findings before approving"
                        : "Approve extraction"
                    }
                  >
                    {reviewing ? <Spinner className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />}
                    Approve
                  </button>
                ) : null}
              </>
            )}
          </div>
        </div>

        {blocking.length > 0 && !approved ? (
          <div className="flex items-start gap-2 border-b border-amber-100 bg-amber-50/70 px-5 py-2.5 text-[11px] text-amber-800">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {blocking.length} open check{blocking.length === 1 ? "" : "s"} must be resolved or dismissed before
            approval.
          </div>
        ) : null}

        {error ? (
          <div className="border-b border-slate-100 p-4">
            <Alert tone="error">{error}</Alert>
          </div>
        ) : null}
        {message ? (
          <div className="border-b border-slate-100 p-4">
            <Alert tone="success">{message}</Alert>
          </div>
        ) : null}

        {data.warnings?.length ? (
          <div className="border-b border-slate-100 px-5 py-3">
            <div className="flex items-start gap-2 text-[11px] leading-5 text-slate-500">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              <div>
                <span className="font-semibold text-slate-700">Extraction warnings:</span>{" "}
                {data.warnings.join(" · ")}
              </div>
            </div>
          </div>
        ) : null}

        {editing ? (
          <div className="px-5 py-5">
            <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              {FIELD_DEFS.map((definition) => (
                <div key={definition.key}>
                  <label htmlFor={`field-${definition.key}`} className="label">
                    {definition.label}
                    {definition.required ? <span className="ml-0.5 text-rose-400">*</span> : null}
                  </label>
                  <input
                    id={`field-${definition.key}`}
                    className={cn(
                      "input",
                      definition.kind === "currency" && "uppercase",
                      definition.kind === "money" && "font-mono",
                    )}
                    value={form[definition.key] ?? ""}
                    placeholder={definition.placeholder}
                    inputMode={definition.kind === "money" ? "decimal" : undefined}
                    maxLength={definition.kind === "currency" ? 3 : undefined}
                    onChange={(event) =>
                      setForm((previous) => ({
                        ...previous,
                        [definition.key]:
                          definition.kind === "currency"
                            ? event.target.value.toUpperCase()
                            : event.target.value,
                      }))
                    }
                  />
                </div>
              ))}
            </div>

            <div className="mt-6">
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-slate-700">Line items</div>
                  <div className="text-[11px] text-slate-400">
                    Enter amounts without currency symbols. Leave blank when absent.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setItems((previous) => [
                      ...previous,
                      {
                        description: "",
                        quantity: null,
                        unit_price: null,
                        amount: null,
                        tax_rate: null,
                        confidence: 1,
                        page: null,
                      },
                    ])
                  }
                  className="btn-secondary btn-sm"
                >
                  <Plus className="h-3 w-3" /> Add item
                </button>
              </div>
              <div className="space-y-2">
                {items.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-slate-200 px-4 py-4 text-center text-xs text-slate-400">
                    No line items. Add one if the document lists items.
                  </div>
                ) : null}
                {items.map((item, index) => (
                  <div
                    key={index}
                    className="grid gap-2 rounded-xl border border-slate-200 bg-slate-50/50 p-2.5 sm:grid-cols-[minmax(0,2.4fr)_repeat(4,minmax(0,0.8fr))_auto]"
                  >
                    <input
                      className="input py-2 text-xs"
                      placeholder="Description"
                      value={item.description}
                      onChange={(event) =>
                        setItems((previous) =>
                          previous.map((entry, entryIndex) =>
                            entryIndex === index
                              ? { ...entry, description: event.target.value }
                              : entry,
                          ),
                        )
                      }
                    />
                    {(["quantity", "unit_price", "amount", "tax_rate"] as const).map((field) => (
                      <input
                        key={field}
                        className="input py-2 text-right font-mono text-xs"
                        placeholder={
                          field === "quantity"
                            ? "Qty"
                            : field === "unit_price"
                              ? "Unit"
                              : field === "amount"
                                ? "Amount"
                                : "Tax %"
                        }
                        inputMode="decimal"
                        value={item[field] ?? ""}
                        onChange={(event) =>
                          setItems((previous) =>
                            previous.map((entry, entryIndex) =>
                              entryIndex === index
                                ? { ...entry, [field]: event.target.value || null }
                                : entry,
                            ),
                          )
                        }
                      />
                    ))}
                    <button
                      type="button"
                      onClick={() =>
                        setItems((previous) => previous.filter((_, entryIndex) => entryIndex !== index))
                      }
                      className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                      aria-label="Remove line item"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4">
              <label htmlFor="correction-reason" className="label">
                Reason for correction
              </label>
              <textarea
                id="correction-reason"
                className="input min-h-[72px] resize-y"
                placeholder="e.g. OCR misread the total; verified against the page image."
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={saving}
                className="btn-accent"
              >
                {saving ? <Spinner /> : <Save className="h-4 w-4" />} Save as new version
              </button>
              <button
                type="button"
                onClick={() => {
                  setEditing(false);
                  setError(null);
                }}
                disabled={saving}
                className="btn-secondary"
              >
                <X className="h-4 w-4" /> Cancel
              </button>
              <span className="text-[11px] text-slate-400">
                Corrections are versioned, audited, and re-validated.
              </span>
            </div>
          </div>
        ) : (
          <>
            <div className="grid gap-x-6 px-5 py-2 sm:grid-cols-2">
              {FIELD_DEFS.map((definition) => (
                <FieldRow
                  key={definition.key}
                  def={definition}
                  field={data[definition.key]}
                  data={data}
                  onPage={onPageChange}
                />
              ))}
            </div>

            <div className="border-t border-slate-100 px-5 py-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-xs font-semibold text-slate-700">Line items</h3>
                  <p className="text-[11px] text-slate-400">
                    {data.line_items?.length || 0} extracted
                    {data.line_items?.length ? ` · ${data.currency?.value || ""} ${itemSum.toFixed(2)} total` : ""}
                  </p>
                </div>
                {sumMismatch ? (
                  <span className="chip bg-amber-50 text-amber-700 ring-amber-200">
                    <AlertTriangle className="h-3 w-3" /> Items ≠ subtotal
                  </span>
                ) : data.line_items?.length && Number.isFinite(subtotalNumber) ? (
                  <span className="chip bg-emerald-50 text-emerald-700 ring-emerald-200">
                    <CheckCircle2 className="h-3 w-3" /> Items reconcile
                  </span>
                ) : null}
              </div>
              <LineItemsTable data={data} />
            </div>
          </>
        )}

        <div className="border-t border-slate-100 bg-slate-50/60 px-5 py-3">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[10px] text-slate-400">
            <span>
              Grouping confidence{" "}
              <span className="font-semibold text-slate-600">{percent(invoice.grouping_confidence)}</span>
            </span>
            <span>
              Overall confidence{" "}
              <span className={cn("font-semibold", confidenceTone(extraction.confidence?.overall))}>
                {percent(extraction.confidence?.overall)}
              </span>
            </span>
            <span>
              Invoice status <span className="font-semibold text-slate-600">{statusLabel(invoice.status)}</span>
            </span>
            <span className="ml-auto font-mono">pages {invoice.page_start}–{invoice.page_end}</span>
          </div>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="border-b border-slate-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-900">Validation & reconciliation</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Checks V001–V017: required fields, arithmetic, dates, duplicates, cross-document consistency, and confidence.
          </p>
        </div>
        <FindingsList findings={findings} onUpdate={handleFindingUpdate} />
      </div>
    </div>
  );
}
