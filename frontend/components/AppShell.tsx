"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Files,
  Gauge,
  ListChecks,
  LogOut,
  Menu,
  Search,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
  Cpu,
  Database,
  ScanText,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { getMeta } from "@/lib/api";
import type { Meta } from "@/lib/types";
import { cn, initials } from "@/lib/format";
import { LoadingScreen } from "@/components/ui";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
  { href: "/upload", label: "Upload", icon: UploadCloud },
  { href: "/documents", label: "Documents", icon: Files },
  { href: "/search", label: "Search", icon: Search },
  { href: "/jobs", label: "Jobs", icon: ListChecks },
];

const TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/upload": "Upload documents",
  "/documents": "Documents",
  "/search": "Search",
  "/jobs": "Processing jobs",
};

function Brand() {
  return (
    <Link href="/dashboard" className="flex items-center gap-3 px-1">
      <span className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent-400 to-accent-600 text-lg font-black text-ink-950 shadow-lg shadow-accent-500/20">
        D
        <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-ink-950 bg-sky-400" />
      </span>
      <span>
        <span className="block text-[17px] font-bold leading-5 tracking-tight text-white">
          DocIntel
        </span>
        <span className="block text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
          Document intelligence
        </span>
      </span>
    </Link>
  );
}

function EngineCard({ meta }: { meta: Meta | null }) {
  if (!meta) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3.5">
        <div className="skeleton h-3 w-2/3 bg-white/10" />
        <div className="skeleton mt-2 h-3 w-1/2 bg-white/10" />
      </div>
    );
  }
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-3.5">
      <div className="mb-2.5 flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">
          Engine status
        </span>
        <span
          className={cn(
            "h-2 w-2 rounded-full",
            meta.ai_enabled ? "bg-accent-400 shadow-[0_0_8px_#34d399]" : "bg-amber-400",
          )}
        />
      </div>
      <div className="space-y-2 text-[11px] text-slate-300">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-accent-300" />
          <span className="text-slate-400">AI</span>
          <span className="ml-auto max-w-[110px] truncate font-semibold text-slate-200">
            {meta.ai_enabled ? meta.ai_model : "Deterministic"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <ScanText className="h-3.5 w-3.5 text-slate-400" />
          <span className="text-slate-400">OCR</span>
          <span className="ml-auto font-semibold capitalize text-slate-200">{meta.ocr_engine}</span>
        </div>
        <div className="flex items-center gap-2">
          <Database className="h-3.5 w-3.5 text-slate-400" />
          <span className="text-slate-400">Storage</span>
          <span className="ml-auto font-semibold capitalize text-slate-200">
            {meta.storage_backend}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Cpu className="h-3.5 w-3.5 text-slate-400" />
          <span className="text-slate-400">Vectors</span>
          <span className="ml-auto max-w-[110px] truncate font-semibold text-slate-200">
            {meta.embedding_provider.split(":").pop()}
          </span>
        </div>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    getMeta().then(setMeta).catch(() => undefined);
  }, [user]);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  if (loading || !user) return <LoadingScreen />;

  const title =
    TITLES[pathname] ||
    (pathname.startsWith("/documents/") ? "Document review" : "Workspace");

  const sidebar = (
    <div className="flex h-full flex-col bg-ink-950 px-4 py-5">
      <Brand />
      <nav className="mt-8 space-y-1" aria-label="Main navigation">
        <div className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
          Workspace
        </div>
        {NAV.map((item) => {
          const active =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(`${item.href}/`));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn("nav-link", active && "nav-link-active")}
              aria-current={active ? "page" : undefined}
            >
              <item.icon className={cn("h-[17px] w-[17px]", active ? "text-accent-300" : "text-slate-400")} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 pt-6">
        <EngineCard meta={meta} />
        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <div className="flex items-center gap-2 text-[11px] font-medium text-slate-300">
            <ShieldCheck className="h-3.5 w-3.5 text-accent-300" />
            <span>Human-in-the-loop review</span>
          </div>
          <p className="mt-1.5 text-[11px] leading-4 text-slate-500">
            Low-confidence fields and failed checks are routed to review. Nothing is invented.
          </p>
        </div>
        <div className="flex items-center gap-2.5 rounded-xl border border-white/10 px-2.5 py-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-[11px] font-bold text-white">
            {initials(user.name || user.email)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-semibold text-white">{user.name || user.email}</div>
            <div className="truncate text-[10px] capitalize text-slate-400">{user.role} · signed in</div>
          </div>
          <button
            type="button"
            onClick={async () => {
              await logout();
              router.replace("/login");
            }}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-white/10 hover:text-white"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[268px_minmax(0,1fr)]">
      <aside className="sticky top-0 hidden h-dvh lg:block">{sidebar}</aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-ink-950/60 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          />
          <div className="relative h-full w-[286px] animate-fade-up shadow-lift">
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              className="absolute right-3 top-4 z-10 rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white"
              aria-label="Close navigation"
            >
              <X className="h-4 w-4" />
            </button>
            {sidebar}
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-col">
        <header className="no-print sticky top-0 z-30 border-b border-slate-200/70 bg-[#f5f7fb]/85 backdrop-blur-xl">
          <div className="flex h-16 items-center gap-3 px-4 sm:px-6 lg:px-8">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-xl border border-slate-200 bg-white p-2 text-slate-600 shadow-sm lg:hidden"
              aria-label="Open navigation"
            >
              <Menu className="h-4 w-4" />
            </button>
            <div className="min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                DocIntel
              </div>
              <div className="truncate text-sm font-semibold text-slate-900">{title}</div>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <Link
                href="/search"
                className="group hidden items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-500 shadow-sm transition hover:border-slate-300 hover:text-slate-800 sm:flex"
              >
                <Search className="h-3.5 w-3.5" />
                Search documents
                <span className="kbd ml-3">/</span>
              </Link>
              <Link href="/upload" className="btn-accent btn-sm sm:px-3.5 sm:py-2.5 sm:text-sm">
                <UploadCloud className="h-4 w-4" />
                <span className="hidden sm:inline">Upload</span>
              </Link>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>

        <footer className="no-print border-t border-slate-200/70 px-6 py-4 text-center text-[11px] text-slate-400">
          DocIntel · AI output is assistive. Verify before approving ·{" "}
          <a href="/api/v1/meta" className="underline decoration-slate-300 hover:text-slate-600">
            system status
          </a>
        </footer>
      </div>
    </div>
  );
}
