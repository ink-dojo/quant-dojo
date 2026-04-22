import Link from "next/link";
import { CategoryBadge } from "./CategoryBadge";
import { MiniSparkline } from "@/components/viz/MiniSparkline";
import type { FactorIndexItem } from "@/lib/types";

interface Props {
  factor: FactorIndexItem;
  href?: string;
  sparkline?: (number | null)[];
  intro?: string;
}

export function FactorCard({ factor, href, sparkline, intro }: Props) {
  const blurb = intro && intro.trim().length > 0 ? intro : factor.docstring;
  const inner = (
    <article className="h-full p-4 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] hover:border-[var(--border)] transition-all flex flex-col gap-3">
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono font-semibold text-sm text-[var(--text-primary)] truncate">
            {factor.name}
          </p>
          <div className="mt-1">
            <CategoryBadge category={factor.category} />
          </div>
        </div>
        <CoverageDots score={factor.coverage_score} />
      </header>
      <p className="text-xs text-[var(--text-secondary)] line-clamp-3 leading-relaxed">
        {blurb}
      </p>
      <div className="mt-auto flex items-end justify-between gap-3">
        <div className="font-mono text-[11px] text-[var(--text-tertiary)] flex gap-3">
          {factor.icir !== null ? (
            <span>
              ICIR{" "}
              <span
                className="font-semibold"
                style={{
                  color:
                    factor.icir >= 0.3
                      ? "var(--green)"
                      : factor.icir >= 0.15
                      ? "var(--gold)"
                      : factor.icir < 0
                      ? "var(--red)"
                      : "var(--text-tertiary)",
                }}
              >
                {factor.icir.toFixed(2)}
              </span>
            </span>
          ) : (
            <span className="opacity-50">ICIR —</span>
          )}
          {factor.in_v16 && <span className="text-[var(--blue)]">v16</span>}
          {factor.in_v7 && !factor.in_v16 && <span className="text-[var(--purple)]">v7</span>}
        </div>
        {sparkline && <MiniSparkline values={sparkline} />}
      </div>
    </article>
  );
  if (href) {
    return (
      <Link href={href} className="block group h-full">
        {inner}
      </Link>
    );
  }
  return <div className="h-full">{inner}</div>;
}

function CoverageDots({ score }: { score: number }) {
  const total = 6;
  return (
    <div className="flex gap-0.5" aria-label={`coverage ${score}/${total}`}>
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full"
          style={{
            background:
              i < score ? "var(--blue)" : "var(--border-soft)",
          }}
        />
      ))}
    </div>
  );
}
