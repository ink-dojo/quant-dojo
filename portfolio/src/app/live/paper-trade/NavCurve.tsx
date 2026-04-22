"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PaperTradeNavPoint } from "@/lib/types";

interface Props {
  points: PaperTradeNavPoint[];
  initial: number;
}

export function NavCurve({ points, initial }: Props) {
  if (points.length === 0) {
    return (
      <div className="h-[260px] flex items-center justify-center text-[var(--text-tertiary)] text-xs font-mono">
        还没有 NAV 数据 · 等待第一次 EOD
      </div>
    );
  }

  const data = points.map((p) => ({
    date: p.date,
    nav: p.nav,
    cum_ret: p.nav / initial - 1,
  }));

  // 单点时用 ReferenceLine 显示初始本金做参照
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart
        data={data}
        margin={{ top: 8, right: 16, left: 8, bottom: 8 }}
      >
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="var(--border)"
          strokeOpacity={0.4}
        />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
          tickFormatter={(d: string) => d.slice(5)}
          minTickGap={20}
        />
        <YAxis
          yAxisId="pct"
          tick={{ fill: "var(--text-tertiary)", fontSize: 10 }}
          tickFormatter={(v: number) => `${(v * 100).toFixed(1)}%`}
          width={60}
          domain={["auto", "auto"]}
        />
        <Tooltip
          contentStyle={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
          }}
          labelStyle={{ color: "var(--text-tertiary)" }}
          formatter={(value, name) => {
            const v = typeof value === "number" ? value : Number(value);
            if (name === "cum_ret")
              return [`${(v * 100).toFixed(2)}%`, "Cum ret"];
            return [String(value), String(name)];
          }}
        />
        <ReferenceLine
          yAxisId="pct"
          y={0}
          stroke="var(--text-tertiary)"
          strokeDasharray="2 2"
        />
        <Line
          yAxisId="pct"
          type="monotone"
          dataKey="cum_ret"
          stroke="var(--green)"
          strokeWidth={1.8}
          dot={data.length <= 30}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
