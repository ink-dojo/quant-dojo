import { Breadcrumb, type Crumb } from "./Breadcrumb";

interface Props {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  description?: string;
  crumbs?: Crumb[];
  actions?: React.ReactNode;
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  description,
  crumbs,
  actions,
}: Props) {
  return (
    <header className="max-w-content mx-auto px-6 pt-12 pb-8">
      {crumbs && crumbs.length > 0 && (
        <div className="mb-5">
          <Breadcrumb items={crumbs} />
        </div>
      )}
      <div className="flex items-start justify-between gap-8">
        <div className="min-w-0">
          {eyebrow && (
            <p className="text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--blue)] mb-2">
              {eyebrow}
            </p>
          )}
          <h1 className="text-3xl md:text-4xl font-semibold text-[var(--text-primary)] leading-tight">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-2 text-sm font-mono text-[var(--text-tertiary)]">
              {subtitle}
            </p>
          )}
          {description && (
            <p className="mt-4 max-w-2xl text-[var(--text-secondary)] leading-relaxed">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </div>
    </header>
  );
}
