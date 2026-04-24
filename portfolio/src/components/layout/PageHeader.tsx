import { Breadcrumb, type Crumb } from "./Breadcrumb";

interface Props {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  description?: React.ReactNode;
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
    <header className="max-w-content mx-auto px-6 pt-14 pb-10">
      {crumbs && crumbs.length > 0 && (
        <div className="mb-5">
          <Breadcrumb items={crumbs} />
        </div>
      )}
      <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          {eyebrow && (
            <p className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--text-tertiary)] mb-3">
              {eyebrow}
            </p>
          )}
          <h1 className="max-w-4xl text-3xl md:text-5xl font-semibold tracking-[-0.03em] text-[var(--text-primary)] leading-tight">
            {title}
          </h1>
          {subtitle && (
            <p className="mt-3 text-sm font-mono text-[var(--text-tertiary)]">
              {subtitle}
            </p>
          )}
          {description && (
            <p className="mt-5 max-w-2xl text-sm md:text-base text-[var(--text-secondary)] leading-relaxed">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </div>
    </header>
  );
}
