import Link from "next/link";

export interface Crumb {
  label: string;
  href?: string;
}

export function Breadcrumb({ items }: { items: Crumb[] }) {
  return (
    <nav className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)] font-mono">
      {items.map((it, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span className="text-[var(--text-tertiary)]">/</span>}
          {it.href ? (
            <Link
              href={it.href}
              className="hover:text-[var(--blue)] transition-colors"
            >
              {it.label}
            </Link>
          ) : (
            <span className="text-[var(--text-secondary)]">{it.label}</span>
          )}
        </span>
      ))}
    </nav>
  );
}
