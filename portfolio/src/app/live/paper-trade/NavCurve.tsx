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
      <div className="h-[160px] flex items-center justify-center text-[var(--text-tertiary)] text-xs font-mono">
        还没有 NAV 数据 · 等待第一次 EOD
      </div>
    );
  }

  // 少于 15 个交易日时, 画折线只是噪声可视化, 改显示日志表
  if (points.length < 15) {
    return <NavLog points={points} initial={initial} />;
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

function NavLog({ points, initial }: Props) {
  const rows = points.map((p, i) => ({
    date: p.date,
    nav: p.nav,
    cum_ret: p.nav / initial - 1,
    day_change:
      i === 0 ? 0 : p.nav / points[i - 1].nav - 1,
  }));
  return (
    <div className="text-xs font-mono">
      <p className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
        Daily log · {points.length} 天 &lt; 15d 画图噪声
      </p>
      <table className="w-full">
        <thead>
          <tr className="text-[10px] uppercase text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
            <th className="text-left py-2 font-normal">Date</th>
            <th className="text-right py-2 font-normal">NAV</th>
            <th className="text-right py-2 font-normal">Day Δ</th>
            <th className="text-right py-2 font-normal">Cum</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const dayTone =
              r.day_change > 0
                ? "var(--green)"
                : r.day_change < 0
                  ? "var(--red)"
                  : "var(--text-secondary)";
            const cumTone =
              r.cum_ret > 0
                ? "var(--green)"
                : r.cum_ret < 0
                  ? "var(--red)"
                  : "var(--text-secondary)";
            return (
              <tr
                key={r.date}
                className="border-b border-[var(--border-soft)]/60 last:border-b-0"
              >
                <td className="py-1.5 text-[var(--text-primary)]">
                  {r.date}
                </td>
                <td className="py-1.5 text-right text-[var(--text-secondary)]">
                  {r.nav.toLocaleString(undefined, {
                    maximumFractionDigits: 0,
                  })}
                </td>
                <td
                  className="py-1.5 text-right"
                  style={{ color: dayTone }}
                >
                  {r.day_change === 0
                    ? "—"
                    : `${(r.day_change * 100).toFixed(3)}%`}
                </td>
                <td
                  className="py-1.5 text-right"
                  style={{ color: cumTone }}
                >
                  {r.cum_ret === 0
                    ? "0.00%"
                    : `${r.cum_ret >= 0 ? "+" : ""}${(r.cum_ret * 100).toFixed(3)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
