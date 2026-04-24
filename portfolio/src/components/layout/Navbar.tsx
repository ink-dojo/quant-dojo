"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, SITE } from "@/lib/constants";

export function Navbar() {
  const pathname = usePathname();

  return (
    <nav className="fixed top-0 inset-x-0 z-40 h-16 border-b border-[var(--border-soft)] bg-[var(--bg-base)]/82 backdrop-blur-md">
      <div className="max-w-content mx-auto h-full px-6 flex items-center gap-6">
        <Link href="/" className="flex items-center gap-2 group">
          <div className="w-7 h-7 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] flex items-center justify-center font-mono font-bold text-[var(--text-primary)] text-xs">
            Q
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {SITE.title}
            </p>
            <p className="hidden sm:block text-[10px] text-[var(--text-tertiary)] font-mono">
              research ledger
            </p>
          </div>
        </Link>

        <div className="ml-auto flex min-w-0 items-center gap-1 overflow-x-auto">
          {NAV_ITEMS.map((item) => {
            const active = pathname?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`shrink-0 px-3 py-1.5 rounded-md text-xs font-mono transition-colors ${
                  active
                    ? "bg-[var(--bg-surface)] text-[var(--text-primary)]"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface)]/60"
                }`}
              >
                <span>{item.label}</span>
                <span className="hidden lg:inline ml-1.5 text-[10px] text-[var(--text-tertiary)]">
                  {item.zh}
                </span>
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
