"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DecayPayload } from "@/lib/types";

interface Props {
  decay: DecayPayload;
  height?: number;
}

export function DecayChart({ decay, height = 220 }: Props) {
  const data = decay.ic_by_lag
    .filter((d): d is { lag: number; ic: number } => typeof d.ic === "number")
    .map((d) => ({ lag: d.lag, ic: d.ic }));
  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs font-mono text-[var(--text-tertiary)]"
        style={{ height }}
      >
        no decay data
      </div>
    );
  }
  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: -12 }}>
          <CartesianGrid
            vertical={false}
            stroke="var(--border-soft)"
            strokeDasharray="2 4"
          />
          <XAxis
            dataKey="lag"
            tick={{
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              fill: "var(--text-tertiary)",
            }}
            stroke="var(--border-soft)"
            label={{
              value: "forward days",
              position: "insideBottom",
              offset: -2,
              fontSize: 10,
              fill: "var(--text-tertiary)",
            }}
          />
          <YAxis
            tick={{
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              fill: "var(--text-tertiary)",
            }}
            stroke="var(--border-soft)"
            tickFormatter={(v: number) => v.toFixed(3)}
            width={52}
          />
          <Tooltip
            contentStyle={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              fontSize: 12,
              fontFamily: "var(--font-mono)",
            }}
            formatter={(v) =>
              typeof v === "number" ? v.toFixed(4) : String(v)
            }
          />
          <ReferenceLine y={0} stroke="var(--text-tertiary)" />
          <Bar dataKey="ic" fill="var(--purple)" isAnimationActive={false} />
          {decay.half_life_days !== null &&
            decay.half_life_days >= 1 &&
            decay.half_life_days <= Math.max(...data.map((d) => d.lag)) && (
              <ReferenceLine
                x={decay.half_life_days}
                stroke="var(--gold)"
                strokeDasharray="4 4"
                label={{
                  value: `t½ ≈ ${decay.half_life_days.toFixed(1)}d`,
                  fill: "var(--gold)",
                  fontSize: 10,
                  position: "top",
                }}
              />
            )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
