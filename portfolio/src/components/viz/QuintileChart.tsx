"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { QuintilePoint } from "@/lib/types";

interface Props {
  points: QuintilePoint[];
  height?: number;
}

const QUINTILE_COLORS: Record<string, string> = {
  Q1: "var(--blue)",
  Q2: "var(--cyan)",
  Q3: "var(--text-tertiary)",
  Q4: "var(--gold)",
  Q5: "var(--red)",
};

export function QuintileChart({ points, height = 280 }: Props) {
  if (!points || points.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs font-mono text-[var(--text-tertiary)]"
        style={{ height }}
      >
        no quintile data
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={points} margin={{ top: 12, right: 16, bottom: 4, left: -12 }}>
        <CartesianGrid
          vertical={false}
          stroke="var(--border-soft)"
          strokeDasharray="2 4"
        />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: "var(--text-tertiary)" }}
          stroke="var(--border-soft)"
          tickFormatter={(v: string) => v.slice(0, 7)}
          minTickGap={40}
        />
        <YAxis
          tick={{ fontSize: 10, fontFamily: "var(--font-mono)", fill: "var(--text-tertiary)" }}
          stroke="var(--border-soft)"
          tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
          width={50}
        />
        <Tooltip
          contentStyle={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
          }}
          formatter={(v) =>
            typeof v === "number" ? `${(v * 100).toFixed(2)}%` : String(v)
          }
        />
        <Legend
          wrapperStyle={{
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            paddingTop: 8,
          }}
          iconType="plainline"
        />
        {(["Q1", "Q2", "Q3", "Q4", "Q5"] as const).map((q) => (
          <Line
            key={q}
            dataKey={q}
            type="monotone"
            stroke={QUINTILE_COLORS[q]}
            strokeWidth={q === "Q1" || q === "Q5" ? 1.8 : 1.1}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
