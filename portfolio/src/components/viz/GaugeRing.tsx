import clsx from "clsx";

interface Props {
  value: number | null;
  max?: number;
  label: string;
  sublabel?: string;
  size?: number;
  thresholds?: { good: number; ok: number };
}

/**
 * Circular gauge — used for ICIR / IC / Sharpe where a single number needs
 * a pass-fail read at a glance. `value` goes from 0..max; negatives render
 * as a red sliver so honest-failure cases (roe IC≈0, v10 OOS 0.27) still
 * show up visibly.
 */
export function GaugeRing({
  value,
  max = 1,
  label,
  sublabel,
  size = 120,
  thresholds = { good: 0.3, ok: 0.15 },
}: Props) {
  const v = value ?? 0;
  const clamped = Math.max(Math.min(v, max), -max);
  const pct = Math.abs(clamped) / max;
  const stroke = 8;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const absV = Math.abs(v);

  const color =
    v === null || Number.isNaN(v)
      ? "var(--text-tertiary)"
      : v < 0
      ? "var(--red)"
      : absV >= thresholds.good
      ? "var(--green)"
      : absV >= thresholds.ok
      ? "var(--gold)"
      : "var(--text-tertiary)";

  return (
    <div
      className="inline-flex flex-col items-center"
      style={{ width: size }}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--border-soft)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={circ}
          strokeDashoffset={circ * (1 - pct)}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <div className="-mt-[75%] text-center pointer-events-none">
        <p
          className={clsx(
            "text-2xl font-semibold font-mono leading-none",
            v === null && "text-[var(--text-tertiary)]"
          )}
          style={{ color }}
        >
          {value === null ? "—" : value.toFixed(2)}
        </p>
        <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mt-1">
          {label}
        </p>
        {sublabel && (
          <p className="text-[10px] text-[var(--text-tertiary)]">{sublabel}</p>
        )}
      </div>
    </div>
  );
}
