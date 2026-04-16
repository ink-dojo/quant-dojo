import Link from "next/link";
import { NAV_ITEMS, SITE } from "@/lib/constants";

export default function Home() {
  return (
    <div className="max-w-content mx-auto px-6">
      <section className="pt-24 pb-16">
        <p className="text-[11px] font-mono uppercase tracking-[0.25em] text-[var(--blue)] mb-4">
          Research · Strategy · Execution
        </p>
        <h1 className="text-4xl md:text-6xl font-semibold text-[var(--text-primary)] leading-tight max-w-4xl">
          {SITE.title}
          <span className="text-[var(--text-tertiary)] font-mono text-2xl md:text-3xl ml-3">
            量化道场
          </span>
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-[var(--text-secondary)] leading-relaxed">
          An A-share quantitative research workbench — 66 alpha factors, a 9-factor
          production strategy running live, walk-forward validation, and a full
          audit trail from hypothesis to execution.
        </p>
        <div className="mt-10 flex flex-wrap gap-3">
          <Link
            href="/research"
            className="px-5 py-2.5 rounded-md bg-[var(--blue)] text-[var(--bg-base)] font-medium hover:opacity-90 transition-opacity"
          >
            Explore Research
          </Link>
          <Link
            href="/strategy"
            className="px-5 py-2.5 rounded-md border border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--bg-surface)] transition-colors"
          >
            See Strategy
          </Link>
        </div>
      </section>

      <section className="py-16 border-t border-[var(--border-soft)]">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-8">
          Sections
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="group p-5 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] hover:border-[var(--border)] transition-all"
            >
              <div className="flex items-baseline gap-2 mb-2">
                <span className="text-[var(--text-primary)] font-medium group-hover:text-[var(--blue)] transition-colors">
                  {item.label}
                </span>
                <span className="text-xs font-mono text-[var(--text-tertiary)]">
                  {item.zh}
                </span>
              </div>
              <p className="text-xs text-[var(--text-tertiary)] font-mono">
                {item.href}
              </p>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
