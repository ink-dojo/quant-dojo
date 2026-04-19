"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EquityCurveFile } from "@/lib/types";

interface Series {
  id: string;
  label: string;
  color: string;
  dashed?: boolean;
  curve: EquityCurveFile;
}

interface Props {
  series: Series[];
  height?: number;
  /** Downsample factor — pick every Nth point. Default 5 (weekly-ish from daily). */
  stride?: number;
  /** Plot log(1 + cum_return) on Y axis — use when one curve dominates in linear scale. */
  logScale?: boolean;
}

/**
 * Overlay multiple cumulative-return curves on one axis. Aligns by date,
 * downsamples to keep the SVG node count sane, and formats the Y axis as %.
 */
export function EquityChart({ series, height = 320, stride = 5, logScale = false }: Props) {
  if (series.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs font-mono text-[var(--text-tertiary)]"
        style={{ height }}
      >
        no equity data
      </div>
    );
  }

  const byDate = new Map<string, Record<string, number | string>>();
  for (const s of series) {
    s.curve.points.forEach((p, i) => {
      if (i % stride !== 0 && i !== s.curve.points.length - 1) return;
      const row = byDate.get(p.date) ?? { date: p.date };
      const v = logScale ? Math.log(1 + Math.max(p.cum_return, -0.999)) : p.cum_return;
      row[s.id] = v;
      byDate.set(p.date, row);
    });
  }
  const data = Array.from(byDate.values()).sort((a, b) =>
    String(a.date).localeCompare(String(b.date))
  );

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: -8 }}>
        <CartesianGrid
          vertical={false}
          stroke="var(--border-soft)"
          strokeDasharray="2 4"
        />
        <XAxis
          dataKey="date"
          tick={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fill: "var(--text-tertiary)",
          }}
          stroke="var(--border-soft)"
          tickFormatter={(v: string) => v.slice(0, 7)}
          minTickGap={50}
        />
        <YAxis
          tick={{
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            fill: "var(--text-tertiary)",
          }}
          stroke="var(--border-soft)"
          tickFormatter={(v: number) =>
            logScale
              ? `${(Math.exp(v) - 1 >= 0 ? "+" : "")}${((Math.exp(v) - 1) * 100).toFixed(0)}%`
              : `${(v * 100).toFixed(0)}%`
          }
          width={60}
        />
        <Tooltip
          contentStyle={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
          }}
          formatter={(v) => {
            if (typeof v !== "number") return String(v);
            const cum = logScale ? Math.exp(v) - 1 : v;
            return `${(cum * 100).toFixed(2)}%`;
          }}
        />
        <Legend
          wrapperStyle={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            paddingTop: 8,
          }}
          iconType="plainline"
        />
        <ReferenceLine y={0} stroke="var(--text-tertiary)" strokeDasharray="3 3" />
        {series.map((s) => (
          <Line
            key={s.id}
            dataKey={s.id}
            name={s.label}
            type="monotone"
            stroke={s.color}
            strokeWidth={1.8}
            strokeDasharray={s.dashed ? "4 4" : undefined}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
