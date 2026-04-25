import Link from "next/link";
import { sourceHref, sourceLabel } from "@/lib/source";
import { Lang } from "@/components/layout/LanguageText";

export function SourceLink({
  path,
  line,
  label,
  className = "",
}: {
  path: string;
  line?: number | null;
  label?: React.ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={sourceHref(path, line)}
      className={`inline-flex items-center gap-1 rounded-md border border-[var(--border-soft)] bg-[var(--bg-surface)]/35 px-2 py-1 font-mono text-[10px] text-[var(--text-secondary)] transition-colors hover:border-[var(--blue)]/45 hover:text-[var(--blue)] ${className}`}
    >
      <span>{label ?? sourceLabel(path)}</span>
      {line ? <span className="text-[var(--text-tertiary)]">:{line}</span> : null}
    </Link>
  );
}

export function SourceLinkList({
  paths,
  label,
}: {
  paths: string[];
  label?: React.ReactNode;
}) {
  if (paths.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">
        {label ?? <Lang zh="源码" en="Source" />}
      </span>
      {paths.map((path) => (
        <SourceLink key={path} path={path} />
      ))}
    </div>
  );
}
