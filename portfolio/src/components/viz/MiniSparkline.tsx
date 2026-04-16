interface Props {
  values: (number | null)[];
  width?: number;
  height?: number;
  stroke?: string;
  zeroLine?: boolean;
}

/**
 * No-dep SVG sparkline. Used in factor cards to show IC trend without
 * pulling Recharts into the library/long-tail pages.
 */
export function MiniSparkline({
  values,
  width = 80,
  height = 24,
  stroke = "var(--blue)",
  zeroLine = true,
}: Props) {
  const clean = values.filter((v): v is number => typeof v === "number" && !Number.isNaN(v));
  if (clean.length < 2) {
    return (
      <div
        className="inline-block"
        style={{ width, height }}
        aria-label="no data"
      />
    );
  }
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;

  const points = values.map((v, i) => {
    const x = (i / Math.max(values.length - 1, 1)) * width;
    if (typeof v !== "number" || Number.isNaN(v)) {
      return null;
    }
    const y = height - ((v - min) / range) * height;
    return `${x},${y}`;
  });

  const path = points
    .filter((p): p is string => p !== null)
    .join(" ");

  const zeroY =
    zeroLine && min < 0 && max > 0
      ? height - ((0 - min) / range) * height
      : null;

  return (
    <svg width={width} height={height} className="inline-block">
      {zeroY !== null && (
        <line
          x1={0}
          x2={width}
          y1={zeroY}
          y2={zeroY}
          stroke="var(--border-soft)"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      )}
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        points={path}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
