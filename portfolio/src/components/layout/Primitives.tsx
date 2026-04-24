import Link from "next/link";
import { Lang } from "./LanguageText";

type Tone = "green" | "red" | "gold" | "blue" | "neutral";

const TONE_COLOR: Record<Tone, string> = {
  green: "var(--green)",
  red: "var(--red)",
  gold: "var(--gold)",
  blue: "var(--blue)",
  neutral: "var(--text-tertiary)",
};

export function SectionLabel({
  eyebrow,
  title,
  body,
  action,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  body?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <div className="max-w-2xl">
        {eyebrow && (
          <p className="mb-2 text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--text-tertiary)]">
            {eyebrow}
          </p>
        )}
        <h2 className="text-xl font-semibold tracking-[-0.01em] text-[var(--text-primary)]">
          {title}
        </h2>
        {body && (
          <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
            {body}
          </p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function StatusPill({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  const color = TONE_COLOR[tone];
  return (
    <span
      className="inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.16em]"
      style={{
        color,
        borderColor: `color-mix(in srgb, ${color} 34%, transparent)`,
        background: `color-mix(in srgb, ${color} 7%, transparent)`,
      }}
    >
      {children}
    </span>
  );
}

export function EvidenceCard({
  tone = "neutral",
  label,
  value,
  detail,
  href,
}: {
  tone?: Tone;
  label: React.ReactNode;
  value: React.ReactNode;
  detail?: React.ReactNode;
  href?: string;
}) {
  const color = TONE_COLOR[tone];
  const inner = (
    <article className="group h-full rounded-xl border border-[var(--border-soft)] bg-[var(--bg-surface)]/35 p-4 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-surface)]/55">
      <p
        className="mb-3 text-[10px] font-mono uppercase tracking-[0.18em]"
        style={{ color }}
      >
        {label}
      </p>
      <p className="text-2xl font-semibold tracking-[-0.02em] text-[var(--text-primary)]">
        {value}
      </p>
      {detail && (
        <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
          {detail}
        </p>
      )}
      {href && (
        <p className="mt-4 text-[11px] font-mono text-[var(--text-tertiary)] group-hover:text-[var(--blue)]">
          <Lang zh="查看详情" en="Open detail" />
        </p>
      )}
    </article>
  );
  return href ? <Link href={href}>{inner}</Link> : inner;
}

export function DisclosurePanel({
  tone = "neutral",
  title,
  summary,
  children,
}: {
  tone?: Tone;
  title: React.ReactNode;
  summary: React.ReactNode;
  children: React.ReactNode;
}) {
  const color = TONE_COLOR[tone];
  return (
    <details className="group rounded-xl border border-[var(--border-soft)] bg-[var(--bg-surface)]/30 p-4 open:bg-[var(--bg-surface)]/45">
      <summary className="cursor-pointer list-none">
        <div className="flex items-start gap-4">
          <span
            className="mt-1 h-2 w-2 shrink-0 rounded-full"
            style={{ background: color }}
          />
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              {title}
            </h3>
            <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
              {summary}
            </p>
          </div>
          <span className="shrink-0 text-[11px] font-mono text-[var(--text-tertiary)] group-open:hidden">
            <Lang zh="展开" en="Expand" />
          </span>
          <span className="hidden shrink-0 text-[11px] font-mono text-[var(--text-tertiary)] group-open:inline">
            <Lang zh="收起" en="Close" />
          </span>
        </div>
      </summary>
      <div className="mt-4 border-t border-[var(--border-soft)] pt-4 text-sm leading-relaxed text-[var(--text-secondary)]">
        {children}
      </div>
    </details>
  );
}

export function TextLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className="font-mono text-xs text-[var(--blue)] hover:underline">
      {children}
    </Link>
  );
}
