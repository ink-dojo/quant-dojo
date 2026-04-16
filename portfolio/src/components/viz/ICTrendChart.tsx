"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ICMonthlyPoint } from "@/lib/types";

interface Props {
  points: ICMonthlyPoint[];
  height?: number;
  factorName?: string;
}

/**
 * IC time series with a zero reference line and color-filled positive/
 * negative bands. Monthly aggregated — 5 years of daily IC compresses to
 * ~60 points which reads well without downsampling noise.
 */
export function ICTrendChart({ points, height = 260, factorName }: Props) {
  if (!points || points.length === 0) {
    return <EmptyState msg="no IC series" height={height} />;
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart
        data={points}
        margin={{ top: 12, right: 16, bottom: 4, left: -12 }}
      >
        <defs>
          <linearGradient id="icPos" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--green)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--green)" stopOpacity={0} />
          </linearGradient>
        </defs>
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
          tickFormatter={(v: number) => v.toFixed(2)}
          width={46}
        />
        <Tooltip
          contentStyle={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            fontSize: 12,
            fontFamily: "var(--font-mono)",
          }}
          labelFormatter={(v) => String(v)}
          formatter={(v) => [
            typeof v === "number" ? v.toFixed(4) : String(v),
            factorName ?? "IC",
          ]}
        />
        <ReferenceLine y={0} stroke="var(--text-tertiary)" strokeDasharray="3 3" />
        <Area
          dataKey="ic"
          type="monotone"
          stroke="var(--green)"
          strokeWidth={1.5}
          fill="url(#icPos)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function EmptyState({ msg, height }: { msg: string; height: number }) {
  return (
    <div
      className="flex items-center justify-center text-xs font-mono text-[var(--text-tertiary)]"
      style={{ height }}
    >
      {msg}
    </div>
  );
}
