"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, SITE } from "@/lib/constants";

export function Navbar() {
  const pathname = usePathname();

  return (
    <nav className="fixed top-0 inset-x-0 z-40 h-16 bg-[var(--bg-base)]/80 backdrop-blur-md border-b border-[var(--border-soft)]">
      <div className="max-w-content mx-auto h-full px-6 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 group">
          <div className="w-7 h-7 rounded-md bg-gradient-to-br from-[var(--blue)] to-[var(--purple)] flex items-center justify-center font-mono font-bold text-[var(--bg-base)] text-xs">
            Q
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {SITE.title}
            </p>
            <p className="text-[10px] text-[var(--text-tertiary)] font-mono">
              {SITE.subtitle}
            </p>
          </div>
        </Link>

        <div className="flex items-center gap-1">
          {NAV_ITEMS.map((item) => {
            const active = pathname?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  active
                    ? "bg-[var(--bg-surface)] text-[var(--text-primary)]"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface)]/60"
                }`}
              >
                <span>{item.label}</span>
                <span className="ml-1.5 text-[10px] font-mono text-[var(--text-tertiary)]">
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
