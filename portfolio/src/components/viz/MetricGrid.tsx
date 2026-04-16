interface Metric {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "good" | "bad" | "warn";
}

const toneClass: Record<NonNullable<Metric["tone"]>, string> = {
  neutral: "text-[var(--text-primary)]",
  good: "text-[var(--green)]",
  bad: "text-[var(--red)]",
  warn: "text-[var(--gold)]",
};

export function MetricGrid({ metrics }: { metrics: Metric[] }) {
  return (
    <dl className="grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-4">
      {metrics.map((m, i) => (
        <div key={i}>
          <dt className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-1">
            {m.label}
          </dt>
          <dd
            className={`text-xl font-semibold font-mono ${
              toneClass[m.tone ?? "neutral"]
            }`}
          >
            {m.value}
          </dd>
          {m.hint && (
            <p className="text-[10px] text-[var(--text-tertiary)] mt-0.5">
              {m.hint}
            </p>
          )}
        </div>
      ))}
    </dl>
  );
}
