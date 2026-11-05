"use client";

import { useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileWarning,
  Maximize2,
  ScanText,
} from "lucide-react";
import { fetchPagePreview } from "@/lib/api";
import { Spinner } from "@/components/ui";

export function DocumentPreview({
  documentId,
  page,
  pageCount,
  onPageChange,
  filename,
}: {
  documentId: string;
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  filename: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setLoading(true);
    setError(null);
    fetchPagePreview(documentId, page)
      .then((nextUrl) => {
        objectUrl = nextUrl;
        if (active) {
          setUrl(nextUrl);
          setLoading(false);
        } else {
          URL.revokeObjectURL(nextUrl);
        }
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Could not render page");
          setLoading(false);
        }
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId, page]);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-slate-900 shadow-card">
      <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2.5">
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-300">{filename}</span>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page <= 1}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white disabled:opacity-30"
            aria-label="Previous page"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[70px] text-center text-[11px] tabular-nums text-slate-400">
            {page} / {pageCount || "—"}
          </span>
          <button
            type="button"
            onClick={() => onPageChange(Math.min(pageCount || page, page + 1))}
            disabled={page >= pageCount}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white disabled:opacity-30"
            aria-label="Next page"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <a
          href={`/api/v1/documents/${documentId}/file`}
          target="_blank"
          rel="noreferrer"
          className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
          aria-label="Open original file"
          title="Open original"
        >
          <ExternalLink className="h-4 w-4" />
        </a>
      </div>

      <div className="relative flex min-h-[420px] flex-1 items-center justify-center overflow-auto bg-[radial-gradient(circle_at_center,_#1e293b,_#0f172a)] p-4">
        {loading ? (
          <div className="flex flex-col items-center gap-3 text-slate-400">
            <Spinner className="h-6 w-6" />
            <span className="text-xs">Rendering page {page}…</span>
          </div>
        ) : error ? (
          <div className="flex max-w-xs flex-col items-center gap-2 text-center text-slate-400">
            <FileWarning className="h-7 w-7 text-amber-400" />
            <div className="text-xs font-semibold text-slate-200">Preview unavailable</div>
            <p className="text-[11px] leading-5">{error}</p>
            <a
              href={`/api/v1/documents/${documentId}/file`}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-[11px] font-semibold text-accent-300 hover:text-accent-200"
            >
              Open original <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        ) : url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={url}
            alt={`${filename} page ${page}`}
            className="max-h-[720px] w-auto max-w-full rounded-md bg-white shadow-2xl"
          />
        ) : null}
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-white/10 px-3 py-2 text-[10px] text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <ScanText className="h-3 w-3" /> Page image rendered at 150 DPI
        </span>
        <a
          href={`/api/v1/documents/${documentId}/pages/${page}/preview`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 hover:text-slate-300"
        >
          <Maximize2 className="h-3 w-3" /> Full size
        </a>
      </div>
    </div>
  );
}
