"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Banknote,
  Building2,
  ChartColumn,
  Files,
  ReceiptText,
  RefreshCw,
  UploadCloud,
} from "lucide-react";
import { getSalesAnalytics } from "@/lib/api";
import type { SalesAnalytics } from "@/lib/types";
import { cn, formatMoney } from "@/lib/format";
import { Alert, EmptyState, PageHeader } from "@/components/ui";
import {
  CurrencyMixChart,
  SalesBarChart,
  StatusMixChart,
  SupplierBars,
  currencyLabel,
  displayCurrency,
} from "@/components/SalesCharts";

function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string | number;
  hint: string;
  icon: React.ElementType;
  tone: string;
}) {
  return (
    <div className="card p-5">
      <div className={cn("flex h-10 w-10 items-center justify-center rounded-xl ring-1 ring-inset", tone)}>
        <Icon className="h-[18px] w-[18px]" />
      </div>
      <div className="mt-4 text-2xl font-bold leading-none tracking-tight text-slate-900 tabular-nums">
        {value}
      </div>
      <div className="mt-1.5 text-sm font-semibold text-slate-700">{label}</div>
      <div className="mt-0.5 truncate text-[11px] text-slate-400" title={hint}>
        {hint}
      </div>
    </div>
  );
}

function ChartCard({
  title,
  description,
  value,
  className,
  children,
}: {
  title: string;
  description: string;
  value?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("card overflow-hidden", className)}>
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          <p className="mt-0.5 text-xs text-slate-400">{description}</p>
        </div>
        {value ? (
          <span className="chip bg-slate-50 text-slate-600 ring-slate-200 tabular-nums">
            {value}
          </span>
        ) : null}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function periodLabel(period: string): string {
  const [year, month] = period.split("-").map(Number);
  if (!year || !month) return period;
  return new Intl.DateTimeFormat("en-GB", {
    month: "long",
    year: "numeric",
  }).format(new Date(year, month - 1, 1));
}

export default function AnalyticsPage() {
  const [months, setMonths] = useState(12);
  const [currency, setCurrency] = useState("");
  const [data, setData] = useState<SalesAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (silent = false) => {
      if (silent) setRefreshing(true);
      else setLoading(true);
      try {
        const result = await getSalesAnalytics({
          months,
          currency: currency || undefined,
          years: 5,
        });
        setData(result);
        if (!currency) setCurrency(result.currency);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load sales analytics");
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [currency, months],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const selectedCurrency = currency || data?.currency || "USD";
  const selectedLabel = currencyLabel(selectedCurrency);
  const monthlyWindowTotal = useMemo(
    () => (data ? data.monthly.reduce((sum, point) => sum + point.total, 0) : 0),
    [data],
  );
  const yearlyWindowTotal = useMemo(
    () => (data ? data.yearly.reduce((sum, point) => sum + point.total, 0) : 0),
    [data],
  );
  const currencyOptions = data?.currencies ?? [];
  const currencyOptionExists = currencyOptions.some(
    (item) => item.currency === selectedCurrency,
  );

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="Revenue intelligence"
        title="Sales analytics"
        description="Monthly and yearly invoice totals from the current extraction of every reviewed document."
        actions={
          <>
            <Link href="/documents" className="btn-secondary">
              <Files className="h-4 w-4" /> Documents
            </Link>
            <Link href="/upload" className="btn-accent">
              <UploadCloud className="h-4 w-4" /> Upload invoices
            </Link>
          </>
        }
      />

      {error ? (
        <div className="mb-5">
          <Alert
            tone="error"
            title="Analytics unavailable"
            action={
              <button type="button" onClick={() => void load()} className="btn-secondary btn-sm">
                Retry
              </button>
            }
          >
            {error}
          </Alert>
        </div>
      ) : null}

      {loading && !data ? (
        <>
          <div className="card p-4">
            <div className="skeleton h-10 w-80" />
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="card p-5">
                <div className="skeleton h-10 w-10" />
                <div className="skeleton mt-4 h-7 w-24" />
                <div className="skeleton mt-2 h-3 w-32" />
              </div>
            ))}
          </div>
          <div className="mt-5 grid gap-5 xl:grid-cols-3">
            <div className="card h-80 p-5 xl:col-span-2">
              <div className="skeleton h-full w-full" />
            </div>
            <div className="card h-80 p-5">
              <div className="skeleton h-full w-full" />
            </div>
          </div>
        </>
      ) : data ? (
        <>
          <div className="card flex flex-col gap-3 p-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="flex flex-wrap items-end gap-3">
              <div className="w-full sm:w-48">
                <label htmlFor="analytics-currency" className="label">
                  Currency
                </label>
                <select
                  id="analytics-currency"
                  className="input py-2 text-xs"
                  value={selectedCurrency}
                  onChange={(event) => setCurrency(event.target.value)}
                >
                  {!currencyOptionExists ? (
                    <option value={selectedCurrency}>{selectedLabel}</option>
                  ) : null}
                  {currencyOptions.map((item) => (
                    <option key={item.currency} value={item.currency}>
                      {currencyLabel(item.currency)} ·{" "}
                      {formatMoney(String(item.total), displayCurrency(item.currency))} (
                      {item.invoice_count})
                    </option>
                  ))}
                </select>
              </div>
              <div className="w-full sm:w-44">
                <label htmlFor="analytics-months" className="label">
                  Monthly window
                </label>
                <select
                  id="analytics-months"
                  className="input py-2 text-xs"
                  value={months}
                  onChange={(event) => setMonths(Number(event.target.value))}
                >
                  <option value={6}>Last 6 months</option>
                  <option value={12}>Last 12 months</option>
                  <option value={24}>Last 24 months</option>
                  <option value={36}>Last 36 months</option>
                </select>
              </div>
              <div className="pb-2 text-[11px] leading-4 text-slate-400">
                Data through{" "}
                <span className="font-semibold text-slate-600">
                  {periodLabel(data.period_end)}
                </span>
                <span className="mx-1.5 text-slate-300">·</span>
                {data.summary.dated_count} dated invoice
                {data.summary.dated_count === 1 ? "" : "s"}
              </div>
            </div>
            <button
              type="button"
              onClick={() => void load(true)}
              disabled={refreshing}
              className="btn-secondary btn-sm shrink-0"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {data.summary.excluded_duplicates > 0 ? (
            <div className="mt-4">
              <Alert tone="info">
                {data.summary.excluded_duplicates} duplicate invoice
                {data.summary.excluded_duplicates === 1 ? "" : "s"}{" "}
                {data.summary.excluded_duplicates === 1 ? "was" : "were"} excluded from
                these totals so the same sale is not counted twice.
              </Alert>
            </div>
          ) : null}

          <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Total invoiced"
              value={formatMoney(
                String(data.summary.total),
                displayCurrency(data.currency),
              )}
              hint={`${selectedLabel} · ${data.summary.approved_count} approved · ${data.summary.pending_count} pending`}
              icon={Banknote}
              tone="bg-emerald-50 text-emerald-600 ring-emerald-100"
            />
            <MetricCard
              label="Invoices"
              value={data.summary.invoice_count}
              hint={`${data.summary.dated_count} dated · ${data.summary.undated_count} undated`}
              icon={ReceiptText}
              tone="bg-sky-50 text-sky-600 ring-sky-100"
            />
            <MetricCard
              label="Average invoice"
              value={formatMoney(
                String(data.summary.average_invoice),
                displayCurrency(data.currency),
              )}
              hint={`${data.summary.missing_total_count} missing total`}
              icon={ChartColumn}
              tone="bg-violet-50 text-violet-600 ring-violet-100"
            />
            <MetricCard
              label="Suppliers"
              value={data.summary.supplier_count}
              hint={
                data.top_suppliers[0]
                  ? `Top: ${data.top_suppliers[0].supplier_name}`
                  : "No suppliers yet"
              }
              icon={Building2}
              tone="bg-amber-50 text-amber-600 ring-amber-100"
            />
          </div>

          {data.summary.invoice_count === 0 ? (
            <div className="card mt-5">
              <EmptyState
                icon={ChartColumn}
                title={
                  currencyOptions.length
                    ? `No invoices in ${selectedLabel}`
                    : "No invoice data yet"
                }
                description={
                  currencyOptions.length
                    ? "Switch currency to see totals from another extracted currency."
                    : "Upload PDF or image invoices to see monthly and yearly sales trends."
                }
                action={
                  currencyOptions.length ? (
                    <button
                      type="button"
                      onClick={() => setCurrency(currencyOptions[0].currency)}
                      className="btn-secondary btn-sm"
                    >
                      View {currencyLabel(currencyOptions[0].currency)}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </button>
                  ) : (
                    <Link href="/upload" className="btn-accent btn-sm">
                      <UploadCloud className="h-3.5 w-3.5" /> Upload invoices
                    </Link>
                  )
                }
              />
            </div>
          ) : (
            <>
              <div className="mt-5 grid gap-5 xl:grid-cols-3">
                <ChartCard
                  className="xl:col-span-2"
                  title="Monthly sales"
                  description={`${data.months} months through ${periodLabel(data.period_end)}`}
                  value={formatMoney(
                    String(monthlyWindowTotal),
                    displayCurrency(data.currency),
                  )}
                >
                  <SalesBarChart points={data.monthly} currency={data.currency} />
                </ChartCard>
                <ChartCard
                  title="Currency mix"
                  description="Invoice count by extracted currency"
                  value={`${data.currencies.length} currenc${data.currencies.length === 1 ? "y" : "ies"}`}
                >
                  <CurrencyMixChart items={data.currencies} />
                </ChartCard>
              </div>

              <div className="mt-5 grid gap-5 lg:grid-cols-3">
                <ChartCard
                  title="Yearly sales"
                  description={`Last ${data.years} calendar years`}
                  value={formatMoney(
                    String(yearlyWindowTotal),
                    displayCurrency(data.currency),
                  )}
                >
                  <SalesBarChart
                    points={data.yearly}
                    currency={data.currency}
                    tone="sky"
                    emptyLabel="No dated invoices in this range."
                  />
                </ChartCard>
                <ChartCard
                  title="Top suppliers"
                  description={`By invoiced amount in ${selectedLabel}`}
                  value={`${data.top_suppliers.length} shown`}
                >
                  <SupplierBars items={data.top_suppliers} currency={data.currency} />
                </ChartCard>
                <ChartCard
                  title="Review status"
                  description="Invoice count by approval state"
                  value={`${data.summary.pending_count} pending`}
                >
                  <StatusMixChart items={data.statuses} currency={data.currency} />
                  <p className="mt-4 border-t border-slate-100 pt-3 text-[10px] leading-4 text-slate-400">
                    Pending invoices are included in the charts. Approve or dismiss their
                    findings to finalize them.
                  </p>
                </ChartCard>
              </div>
            </>
          )}
        </>
      ) : null}
    </div>
  );
}
