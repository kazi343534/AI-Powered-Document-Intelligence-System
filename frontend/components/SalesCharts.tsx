"use client";

import { useId } from "react";
import { ChartColumn } from "lucide-react";
import type {
  SalesCurrencyBreakdown,
  SalesPeriodPoint,
  SalesStatusPoint,
  SalesSupplierPoint,
} from "@/lib/types";
import { cn, formatMoney } from "@/lib/format";

export function displayCurrency(currency: string): string | null {
  return currency && currency !== "UNSPECIFIED" ? currency : null;
}

export function currencyLabel(currency: string): string {
  return currency === "UNSPECIFIED" ? "Unspecified" : currency;
}

export function formatCompactMoney(value: number, currency?: string): string {
  const options: Intl.NumberFormatOptions = {
    notation: "compact",
    maximumFractionDigits: 1,
  };
  if (currency) {
    options.style = "currency";
    options.currency = currency;
  }
  try {
    return new Intl.NumberFormat("en-GB", options).format(value);
  } catch {
    return new Intl.NumberFormat("en-GB", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
}

function niceCeiling(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 100;
  const exponent = Math.floor(Math.log10(value));
  const base = 10 ** exponent;
  const normalized = value / base;
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return nice * base;
}

export function ChartEmpty({ label }: { label: string }) {
  return (
    <div className="flex h-[210px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-6 text-center">
      <ChartColumn className="h-5 w-5 text-slate-300" />
      <p className="text-xs text-slate-400">{label}</p>
    </div>
  );
}

export function SalesBarChart({
  points,
  currency,
  tone = "emerald",
  emptyLabel = "No invoice totals in this window yet.",
}: {
  points: SalesPeriodPoint[];
  currency: string;
  tone?: "emerald" | "sky";
  emptyLabel?: string;
}) {
  const gradientId = `sales-bar-${useId().replace(/:/g, "")}`;
  const width = 720;
  const height = 250;
  const margin = { top: 20, right: 8, bottom: 34, left: 58 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const maxValue = Math.max(...points.map((point) => Math.max(point.total, 0)), 0);
  const ceiling = niceCeiling(maxValue);
  const step = plotWidth / Math.max(points.length, 1);
  const barWidth = Math.min(34, Math.max(8, step * 0.58));
  const labelEvery = points.length <= 12 ? 1 : points.length <= 24 ? 2 : 3;
  const hasData = points.some((point) => point.total > 0 || point.invoice_count > 0);
  const money = displayCurrency(currency) ?? undefined;
  const colors =
    tone === "sky"
      ? { top: "#38bdf8", bottom: "#0284c7" }
      : { top: "#34d399", bottom: "#059669" };

  if (!points.length || !hasData) {
    return <ChartEmpty label={emptyLabel} />;
  }

  return (
    <div className="mt-4 overflow-x-auto pb-1">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full min-w-[540px]"
        role="img"
        aria-label="Sales bar chart"
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={colors.top} />
            <stop offset="100%" stopColor={colors.bottom} />
          </linearGradient>
        </defs>

        {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
          const y = margin.top + plotHeight - fraction * plotHeight;
          return (
            <g key={fraction}>
              <line
                x1={margin.left}
                x2={width - margin.right}
                y1={y}
                y2={y}
                stroke="#e2e8f0"
                strokeDasharray={fraction === 0 ? undefined : "3 4"}
              />
              <text
                x={margin.left - 10}
                y={y + 3}
                textAnchor="end"
                fontSize={10}
                fill="#94a3b8"
              >
                {formatCompactMoney(ceiling * fraction, money)}
              </text>
            </g>
          );
        })}

        {points.map((point, index) => {
          const value = Math.max(point.total, 0);
          const barHeight = ceiling > 0 ? (value / ceiling) * plotHeight : 0;
          const x = margin.left + index * step + (step - barWidth) / 2;
          const y = margin.top + plotHeight - barHeight;
          return (
            <g key={point.period} className="group">
              <rect
                x={x}
                y={y}
                width={barWidth}
                height={Math.max(barHeight, value > 0 ? 2 : 0)}
                rx={3}
                fill={`url(#${gradientId})`}
                className="transition-opacity group-hover:opacity-80"
              >
                <title>
                  {`${point.label}: ${formatMoney(String(point.total), money)} (${point.invoice_count} invoice${point.invoice_count === 1 ? "" : "s"})`}
                </title>
              </rect>
              {value > 0 ? (
                <text
                  x={x + barWidth / 2}
                  y={Math.max(y - 6, margin.top + 9)}
                  textAnchor="middle"
                  fontSize={9}
                  fill="#475569"
                  className="pointer-events-none opacity-0 transition-opacity group-hover:opacity-100"
                >
                  {formatCompactMoney(point.total, money)}
                </text>
              ) : null}
              {index % labelEvery === 0 ? (
                <text
                  x={x + barWidth / 2}
                  y={height - 12}
                  textAnchor="middle"
                  fontSize={9}
                  fill="#94a3b8"
                >
                  {point.label}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

type DonutSegment = {
  label: string;
  value: number;
  color: string;
  detail: string;
};

function DonutChart({
  segments,
  centerLabel,
  centerValue,
}: {
  segments: DonutSegment[];
  centerLabel: string;
  centerValue: string;
}) {
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const total = segments.reduce((sum, segment) => sum + Math.max(segment.value, 0), 0);
  let offset = 0;

  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center">
      <div className="relative h-40 w-40 shrink-0">
        <svg viewBox="0 0 160 160" className="h-full w-full -rotate-90" aria-hidden>
          <circle
            cx="80"
            cy="80"
            r={radius}
            fill="none"
            stroke="#f1f5f9"
            strokeWidth="18"
          />
          {segments.map((segment) => {
            const fraction = total > 0 ? Math.max(segment.value, 0) / total : 0;
            const length = fraction * circumference;
            const circle = (
              <circle
                key={segment.label}
                cx="80"
                cy="80"
                r={radius}
                fill="none"
                stroke={segment.color}
                strokeWidth="18"
                strokeDasharray={`${length} ${circumference - length}`}
                strokeDashoffset={-offset}
              />
            );
            offset += length;
            return circle;
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-400">
            {centerLabel}
          </span>
          <span className="mt-0.5 text-xl font-bold tabular-nums text-slate-900">
            {centerValue}
          </span>
        </div>
      </div>

      <div className="w-full min-w-0 space-y-3">
        {segments.map((segment) => (
          <div key={segment.label} className="flex items-center gap-2.5">
            <span
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: segment.color }}
            />
            <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-slate-600">
              {segment.label}
            </span>
            <span className="shrink-0 text-[11px] font-semibold tabular-nums text-slate-700">
              {segment.detail}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

const DONUT_COLORS = ["#10b981", "#0ea5e9", "#8b5cf6", "#f59e0b", "#f43f5e", "#64748b"];

export function CurrencyMixChart({
  items,
}: {
  items: SalesCurrencyBreakdown[];
}) {
  if (!items.length) {
    return <ChartEmpty label="No currencies extracted yet." />;
  }
  const totalInvoices = items.reduce((sum, item) => sum + item.invoice_count, 0);
  return (
    <DonutChart
      segments={items.map((item, index) => ({
        label: currencyLabel(item.currency),
        value: item.invoice_count,
        color: DONUT_COLORS[index % DONUT_COLORS.length],
        detail: formatMoney(String(item.total), displayCurrency(item.currency)),
      }))}
      centerLabel="invoices"
      centerValue={String(totalInvoices)}
    />
  );
}

export function StatusMixChart({
  items,
  currency,
}: {
  items: SalesStatusPoint[];
  currency: string;
}) {
  const totalInvoices = items.reduce((sum, item) => sum + item.count, 0);
  if (!totalInvoices) {
    return <ChartEmpty label="No invoices to review yet." />;
  }
  const colors: Record<string, string> = {
    approved: "#10b981",
    pending: "#f59e0b",
  };
  return (
    <DonutChart
      segments={items.map((item) => ({
        label: item.status === "approved" ? "Approved" : "Pending review",
        value: item.count,
        color: colors[item.status] ?? "#64748b",
        detail: formatMoney(String(item.total), displayCurrency(currency)),
      }))}
      centerLabel="invoices"
      centerValue={String(totalInvoices)}
    />
  );
}

export function SupplierBars({
  items,
  currency,
}: {
  items: SalesSupplierPoint[];
  currency: string;
}) {
  if (!items.length) {
    return <ChartEmpty label="No suppliers extracted yet." />;
  }
  const max = Math.max(...items.map((item) => Math.max(item.total, 0)), 0);
  return (
    <div className="mt-5 space-y-4">
      {items.map((item, index) => (
        <div key={item.supplier_name}>
          <div className="mb-1.5 flex items-end justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-slate-100 text-[10px] font-bold text-slate-500">
                {index + 1}
              </span>
              <span className="truncate text-[11px] font-semibold text-slate-700">
                {item.supplier_name}
              </span>
            </div>
            <span className="shrink-0 text-[11px] font-semibold tabular-nums text-slate-700">
              {formatMoney(String(item.total), displayCurrency(currency))}
            </span>
          </div>
          <div className="ml-7 h-2 overflow-hidden rounded-full bg-slate-100">
            <div
              className={cn(
                "h-full rounded-full bg-gradient-to-r",
                index === 0 ? "from-accent-500 to-sky-400" : "from-accent-400/80 to-sky-300/80",
              )}
              style={{ width: `${max > 0 ? (Math.max(item.total, 0) / max) * 100 : 0}%` }}
            />
          </div>
          <div className="ml-7 mt-1 text-[10px] text-slate-400">
            {item.invoice_count} invoice{item.invoice_count === 1 ? "" : "s"}
          </div>
        </div>
      ))}
    </div>
  );
}
