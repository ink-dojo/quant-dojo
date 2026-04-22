"use client";

// Preview: Variant A — Terminal Dossier (from Claude Design 2026-04-20 handoff).
// Standalone, full-viewport. Does NOT replace the existing routes.
// Data is inlined from the design bundle sample — wire to real /data/*.json later.

import { useRef, useState, type ReactNode } from "react";

const T = {
  bg: "#0e1013",
  panel: "#14171c",
  panel2: "#181c22",
  border: "#252a31",
  text: "#d8dde4",
  muted: "#7a828c",
  dim: "#4a525b",
  green: "#7ac07a",
  red: "#e07c6b",
  amber: "#d4b26a",
  blue: "#6ea3d4",
  font: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace',
};

type Tone = "dim" | "green" | "red" | "amber" | "blue";
type Version = {
  id: string;
  name: string;
  status: "production" | "candidate" | "rejected" | "legacy";
  ann: number | null;
  sharpe: number | null;
  mdd: number | null;
  note: string;
};
type Gate = { name: string; value: string; pass: boolean };
type Factor = {
  name: string;
  tier: "core" | "experimental";
  cat: string;
  ic: number | null;
  icir: number | null;
  t: number | null;
  inV7: boolean;
  inV16: boolean;
  pitch: string;
};
type Run = { id: string; name: string; ann: number; sharpe: number; mdd: number; status: "success" | "rejected"; ts: string };
type Signal = { date: string; strat: string; n: number };
type Phase = { id: number; title: string; status: "done" | "planned"; done: number; total: number };

const QD = {
  meta: {
    updated: "2026-04-20",
    gitSha: "9bd7b2f7",
    production: "v9",
    candidate: "v25",
    declaredActive: "v16",
  },
  candidate: {
    id: "v25",
    tagline: "Drawdown -43% -> -26%. Sharpe still 0.03 short. WF pending.",
    gates: [
      { name: "Ann. return >= 15%", value: "18.7%", pass: true },
      { name: "Sharpe >= 0.80", value: "0.768", pass: false },
      { name: "MDD > -30%", value: "-26.1%", pass: true },
      { name: "WF validated", value: "pending", pass: false },
    ] as Gate[],
  },
  versions: [
    { id: "v7", name: "5-Factor Baseline", status: "legacy", ann: null, sharpe: null, mdd: null, note: "Handcrafted equal weights — passed admission." },
    { id: "v9", name: "ICIR-Weighted", status: "production", ann: 0.1287, sharpe: 0.48, mdd: -0.266, note: "Data-driven weights. WF median 0.53, OOS +18% vs v7." },
    { id: "v10", name: "v9 + portfolio stop-loss", status: "rejected", ann: 0.1932, sharpe: 0.63, mdd: -0.436, note: "Naked stop killed OOS edge. Rolled back honestly." },
    { id: "v16", name: "9-factor mining candidate", status: "candidate", ann: 0.2237, sharpe: 0.73, mdd: -0.431, note: "IS looks strong; MDD -43% broke the -30% gate." },
    { id: "v25", name: "v16 + HS300 regime stop", status: "candidate", ann: 0.1872, sharpe: 0.768, mdd: -0.261, note: "Regime-gated stop fixed drawdown. Sharpe 0.03 short." },
  ] as Version[],
  factors: [
    { name: "low_vol_20d", tier: "core", cat: "technical", ic: 0.067, icir: 0.338, t: 2.83, inV7: true, inV16: true, pitch: "Most-covered factor in the library — research + notebook + IC stats + v7 + v16 + snapshot." },
    { name: "team_coin", tier: "experimental", cat: "behavioral", ic: 0.039, icir: 0.453, t: 5.08, inV7: true, inV16: true, pitch: "ICIR #1 (0.45) and FM-t #1 (5.08). Low-vol plays momentum, high-vol plays reversal." },
    { name: "bp_factor", tier: "core", cat: "fundamental", ic: 0.042, icir: 0.277, t: 1.94, inV7: true, inV16: false, pitch: "Classic Fama-French value. 1/PB winsorized cross-sectionally." },
    { name: "enhanced_momentum", tier: "core", cat: "technical", ic: 0.057, icir: 0.274, t: 2.94, inV7: true, inV16: false, pitch: "Risk-adjusted momentum — the evolution of reversal_1m." },
    { name: "roe_factor", tier: "core", cat: "fundamental", ic: null, icir: null, t: null, inV7: false, inV16: false, pitch: "Hypothesized quality premium; IC ~ 0, FM not significant. Kept visible as a research-process artifact." },
    { name: "cgo", tier: "experimental", cat: "behavioral", ic: 0.058, icir: 0.329, t: 3.38, inV7: true, inV16: false, pitch: "Behavioral-finance angle — unrealized P/L pressure. v7 weight 0.20." },
    { name: "amihud_illiquidity", tier: "experimental", cat: "liquidity", ic: null, icir: null, t: null, inV7: false, inV16: true, pitch: "Liquidity dimension added in v16 once core factors were stable." },
    { name: "momentum_6m_skip1m", tier: "experimental", cat: "technical", ic: null, icir: null, t: null, inV7: false, inV16: true, pitch: "Medium-term variant; complements 60-day enhanced_momentum." },
  ] as Factor[],
  factorCounts: { total: 66, withIcStats: 9 },
  runs: [
    { id: "v25_20260417", name: "v25 (v16 + HS300 regime stop)", ann: 0.1872, sharpe: 0.768, mdd: -0.261, status: "success", ts: "2026-04-17 01:00" },
    { id: "v24_20260417", name: "v24 (v16 wider book, n=60)", ann: 0.1859, sharpe: 0.691, mdd: -0.406, status: "success", ts: "2026-04-17 00:35" },
    { id: "v23_20260416", name: "v23 (v16 + adaptive stop)", ann: 0.1481, sharpe: 0.674, mdd: -0.282, status: "success", ts: "2026-04-16 15:17" },
    { id: "v22_20260416", name: "v22 (orthogonal pruning)", ann: 0.1654, sharpe: 0.545, mdd: -0.409, status: "success", ts: "2026-04-16 15:09" },
    { id: "v16_20260414", name: "v16 (9-factor mining)", ann: 0.2237, sharpe: 0.73, mdd: -0.431, status: "success", ts: "2026-04-14 00:08" },
    { id: "v13_20260413", name: "v13 (8-factor + mid reversal)", ann: 0.2141, sharpe: 0.699, mdd: -0.416, status: "success", ts: "2026-04-13 23:56" },
    { id: "v11_20260413", name: "v11 (orthogonal extension)", ann: 0.2173, sharpe: 0.774, mdd: -0.428, status: "success", ts: "2026-04-13 23:45" },
    { id: "v10_20260413", name: "v10 (v9 + naked stop) rejected", ann: 0.1932, sharpe: 0.632, mdd: -0.436, status: "rejected", ts: "2026-04-13 12:10" },
  ] as Run[],
  signals: [
    { date: "2026-04-10", strat: "v10", n: 20 },
    { date: "2026-04-09", strat: "v10", n: 20 },
    { date: "2026-04-07", strat: "v10", n: 20 },
    { date: "2026-03-20", strat: "v9", n: 20 },
  ] as Signal[],
  phases: [
    { id: 0, title: "Environment (wk 1)", status: "done", done: 4, total: 4 },
    { id: 1, title: "Foundation (wk 2-4)", status: "done", done: 10, total: 10 },
    { id: 2, title: "Backtest infrastructure (wk 5-8)", status: "done", done: 5, total: 5 },
    { id: 3, title: "Factor research (wk 9-16)", status: "done", done: 8, total: 8 },
    { id: 4, title: "Strategy refinement (wk 17-24)", status: "done", done: 9, total: 9 },
    { id: 5, title: "Paper-trading infra (wk 25-36)", status: "done", done: 17, total: 17 },
    { id: 6, title: "Control plane (CLI + dashboard)", status: "planned", done: 9, total: 10 },
    { id: 7, title: "Agentic research (AI co-pilot)", status: "planned", done: 7, total: 7 },
    { id: 8, title: "Agentic execution / real money", status: "planned", done: 0, total: 5 },
  ] as Phase[],
  equity: {
    v9: [1, 1.02, 1.05, 1.03, 1.08, 1.12, 1.09, 1.14, 1.18, 1.22, 1.19, 1.26, 1.31, 1.28, 1.34, 1.38, 1.35, 1.42, 1.47, 1.43, 1.49, 1.54, 1.5, 1.56, 1.59, 1.55, 1.59],
    v25: [1, 1.03, 1.07, 1.04, 1.1, 1.15, 1.13, 1.2, 1.24, 1.22, 1.3, 1.35, 1.32, 1.39, 1.44, 1.41, 1.48, 1.53, 1.49, 1.56, 1.62, 1.57, 1.64, 1.69, 1.66, 1.72, 1.78],
    v16: [1, 1.04, 1.09, 1.06, 1.14, 1.22, 1.19, 1.28, 1.33, 1.3, 1.4, 1.46, 1.41, 1.52, 1.59, 1.54, 1.64, 1.71, 1.65, 1.73, 1.81, 1.74, 1.85, 1.93, 1.88, 1.98, 2.09],
  },
};

function Spark({ data, color = T.green, w = 120, h = 28 }: { data: number[]; color?: string; w?: number; h?: number }) {
  if (!data?.length) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const r = max - min || 1;
  const pts = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * w;
      const y = h - ((v - min) / r) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.2} />
    </svg>
  );
}

function Chip({ children, tone = "dim" }: { children: ReactNode; tone?: Tone }) {
  const tones: Record<Tone, { bg: string; fg: string; bd: string }> = {
    dim: { bg: "transparent", fg: T.muted, bd: T.border },
    green: { bg: "rgba(122,192,122,.1)", fg: T.green, bd: "rgba(122,192,122,.3)" },
    red: { bg: "rgba(224,124,107,.1)", fg: T.red, bd: "rgba(224,124,107,.3)" },
    amber: { bg: "rgba(212,178,106,.1)", fg: T.amber, bd: "rgba(212,178,106,.3)" },
    blue: { bg: "rgba(110,163,212,.1)", fg: T.blue, bd: "rgba(110,163,212,.3)" },
  };
  const c = tones[tone];
  return (
    <span
      style={{
        fontSize: 10,
        letterSpacing: 0.5,
        textTransform: "uppercase",
        padding: "2px 6px",
        border: `1px solid ${c.bd}`,
        background: c.bg,
        color: c.fg,
        borderRadius: 2,
      }}
    >
      {children}
    </span>
  );
}

function Pct({ v, digits = 1 }: { v: number | null; digits?: number }) {
  if (v == null) return <span style={{ color: T.dim }}>—</span>;
  const s = (v * 100).toFixed(digits) + "%";
  return <span style={{ color: v < 0 ? T.red : T.text }}>{s}</span>;
}

const SECTIONS: [string, string][] = [
  ["00", "README"],
  ["01", "STRATEGY / versions"],
  ["02", "STRATEGY / v25 gate-check"],
  ["03", "RESEARCH / factor library"],
  ["04", "VALIDATION / walk-forward"],
  ["05", "LIVE / recent runs"],
  ["06", "LIVE / signal ledger"],
  ["07", "JOURNEY / phases"],
  ["08", "INFRA / stack"],
];

function statusTone(s: Version["status"]): Tone {
  if (s === "production") return "green";
  if (s === "rejected") return "red";
  if (s === "candidate") return "amber";
  return "dim";
}

function statusColor(s: Version["status"]): string {
  if (s === "production") return T.green;
  if (s === "rejected") return T.red;
  if (s === "candidate") return T.amber;
  return T.muted;
}

export default function PreviewTerminalPage() {
  const [active, setActive] = useState("00");
  const scrollRef = useRef<HTMLDivElement>(null);

  const go = (id: string) => {
    setActive(id);
    const el = document.getElementById(`sec-${id}`);
    if (el && scrollRef.current) {
      scrollRef.current.scrollTo({ top: el.offsetTop - 20, behavior: "smooth" });
    }
  };

  const wfWindows = [0.81, 0.44, -0.12, 0.67, 0.53, 0.71, 0.28, 0.55, 0.49, -0.02, 0.73, 0.61, 0.33, 0.58, 0.45, 0.68, 0.51];

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        background: T.bg,
        color: T.text,
        fontFamily: T.font,
        fontSize: 11,
        lineHeight: 1.55,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Top bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "8px 14px",
          borderBottom: `1px solid ${T.border}`,
          gap: 12,
          background: T.panel,
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: 5, background: "#2a2f36" }} />
          <div style={{ width: 10, height: 10, borderRadius: 5, background: "#2a2f36" }} />
          <div style={{ width: 10, height: 10, borderRadius: 5, background: "#2a2f36" }} />
        </div>
        <span style={{ color: T.muted }}>quant-dojo</span>
        <span style={{ color: T.dim }}>·</span>
        <span style={{ color: T.green }}>~/portfolio</span>
        <span style={{ color: T.dim, marginLeft: 12, fontSize: 10 }}>[preview · variant A · terminal dossier]</span>
        <span style={{ flex: 1 }} />
        <a href="/" style={{ color: T.muted, fontSize: 10, textDecoration: "none", border: `1px solid ${T.border}`, padding: "2px 8px", borderRadius: 2 }}>
          ← exit preview
        </a>
        <span style={{ color: T.dim, fontSize: 10 }}>
          git {QD.meta.gitSha} · {QD.meta.updated}
        </span>
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Left rail */}
        <nav
          style={{
            width: 180,
            borderRight: `1px solid ${T.border}`,
            padding: "14px 10px",
            background: T.panel,
            flexShrink: 0,
            overflow: "auto",
          }}
        >
          <div style={{ color: T.dim, fontSize: 9, letterSpacing: 1, marginBottom: 8 }}>— TOC —</div>
          {SECTIONS.map(([id, label]) => (
            <button
              key={id}
              onClick={() => go(id)}
              style={{
                display: "flex",
                width: "100%",
                gap: 6,
                alignItems: "baseline",
                padding: "3px 4px",
                border: "none",
                background: active === id ? "rgba(122,192,122,.08)" : "transparent",
                color: active === id ? T.green : T.muted,
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 10.5,
                textAlign: "left",
                borderLeft: `2px solid ${active === id ? T.green : "transparent"}`,
              }}
            >
              <span style={{ color: T.dim, fontSize: 9 }}>{id}</span>
              <span>{label}</span>
            </button>
          ))}
          <div style={{ marginTop: 20, padding: 8, border: `1px solid ${T.border}`, borderRadius: 2 }}>
            <div style={{ color: T.dim, fontSize: 9, letterSpacing: 1 }}>STATUS</div>
            <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 3, fontSize: 10 }}>
              <div>
                <span style={{ color: T.dim }}>prod  </span>
                <span style={{ color: T.green }}>{QD.meta.production}</span>
              </div>
              <div>
                <span style={{ color: T.dim }}>cand  </span>
                <span style={{ color: T.amber }}>{QD.meta.candidate}</span>
              </div>
              <div>
                <span style={{ color: T.dim }}>decl  </span>
                <span style={{ color: T.blue }}>{QD.meta.declaredActive}</span>
              </div>
            </div>
          </div>
        </nav>

        {/* Main */}
        <main ref={scrollRef} style={{ flex: 1, overflow: "auto", padding: "20px 24px 60px", minWidth: 0 }}>
          {/* 00 — README */}
          <section id="sec-00" style={{ marginBottom: 36 }}>
            <div style={{ color: T.dim, fontSize: 10 }}># 00 · README</div>
            <h1 style={{ fontSize: 24, fontWeight: 500, letterSpacing: -0.5, margin: "6px 0 4px", color: T.text }}>
              quant-dojo<span style={{ color: T.green }}>/</span>portfolio
            </h1>
            <div style={{ color: T.muted, fontSize: 13, maxWidth: 560 }}>
              A-share systematic equity research. 66 factors explored, 9 IC-validated, 4 strategy generations shipped, 1 production, 1 candidate waiting on walk-forward. Every rejection is documented.
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(4, 1fr)",
                gap: 1,
                background: T.border,
                marginTop: 18,
                border: `1px solid ${T.border}`,
              }}
            >
              {[
                ["factors explored", QD.factorCounts.total],
                ["IC-validated", QD.factorCounts.withIcStats],
                ["strat. generations", QD.versions.length],
                ["live signals ytd", "48"],
              ].map(([k, v]) => (
                <div key={String(k)} style={{ background: T.panel, padding: "14px 12px" }}>
                  <div style={{ color: T.dim, fontSize: 9, letterSpacing: 1 }}>{String(k).toUpperCase()}</div>
                  <div style={{ fontSize: 22, fontWeight: 500, color: T.text, marginTop: 4 }}>{v}</div>
                </div>
              ))}
            </div>
            <div
              style={{
                marginTop: 16,
                padding: 12,
                border: `1px solid ${T.border}`,
                background: T.panel,
                display: "flex",
                gap: 20,
                alignItems: "center",
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ color: T.amber, fontSize: 10, letterSpacing: 1 }}>⚠ INTEGRITY NOTE</div>
                <div style={{ marginTop: 3, fontSize: 11.5 }}>
                  <code style={{ color: T.blue }}>strategy_state.json</code> declares <code style={{ color: T.blue }}>v16</code> active, but v16 failed the –30% MDD gate.{" "}
                  <span style={{ color: T.green }}>v9</span> remains the only walk-forward-validated face. Shown as-is.
                </div>
              </div>
            </div>
          </section>

          {/* 01 — versions */}
          <section id="sec-01" style={{ marginBottom: 36 }}>
            <div style={{ color: T.dim, fontSize: 10 }}># 01 · STRATEGY / versions</div>
            <h2 style={{ fontSize: 14, fontWeight: 500, margin: "4px 0 14px" }}>
              Four generations → one production, one candidate, two honest rejects.
            </h2>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ color: T.dim, textAlign: "left", borderBottom: `1px solid ${T.border}` }}>
                  <th style={{ padding: "6px 4px", fontWeight: 400 }}>ID</th>
                  <th style={{ padding: "6px 4px", fontWeight: 400 }}>NAME</th>
                  <th style={{ padding: "6px 4px", fontWeight: 400 }}>STATUS</th>
                  <th style={{ padding: "6px 4px", fontWeight: 400, textAlign: "right" }}>ANN</th>
                  <th style={{ padding: "6px 4px", fontWeight: 400, textAlign: "right" }}>SHARPE</th>
                  <th style={{ padding: "6px 4px", fontWeight: 400, textAlign: "right" }}>MDD</th>
                  <th style={{ padding: "6px 4px", fontWeight: 400 }}>NOTE</th>
                </tr>
              </thead>
              <tbody>
                {QD.versions.map((v) => (
                  <tr key={v.id} style={{ borderBottom: `1px solid ${T.border}` }}>
                    <td style={{ padding: "8px 4px", color: statusColor(v.status) }}>{v.id}</td>
                    <td style={{ padding: "8px 4px" }}>{v.name}</td>
                    <td style={{ padding: "8px 4px" }}>
                      <Chip tone={statusTone(v.status)}>{v.status}</Chip>
                    </td>
                    <td style={{ padding: "8px 4px", textAlign: "right" }}>
                      <Pct v={v.ann} />
                    </td>
                    <td style={{ padding: "8px 4px", textAlign: "right" }}>
                      {v.sharpe != null ? v.sharpe.toFixed(2) : <span style={{ color: T.dim }}>—</span>}
                    </td>
                    <td style={{ padding: "8px 4px", textAlign: "right" }}>
                      <Pct v={v.mdd} />
                    </td>
                    <td style={{ padding: "8px 4px", color: T.muted, maxWidth: 260 }}>{v.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* 02 — gate check */}
          <section id="sec-02" style={{ marginBottom: 36 }}>
            <div style={{ color: T.dim, fontSize: 10 }}># 02 · STRATEGY / v25 gate-check</div>
            <h2 style={{ fontSize: 14, fontWeight: 500, margin: "4px 0 10px" }}>
              Admission gate for <code style={{ color: T.amber }}>{QD.candidate.id}</code> — {QD.candidate.tagline}
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
              {QD.candidate.gates.map((g) => (
                <div
                  key={g.name}
                  style={{
                    padding: 10,
                    border: `1px solid ${g.pass ? "rgba(122,192,122,.3)" : "rgba(224,124,107,.3)"}`,
                    background: g.pass ? "rgba(122,192,122,.04)" : "rgba(224,124,107,.04)",
                  }}
                >
                  <div style={{ color: T.dim, fontSize: 9, letterSpacing: 1 }}>{g.name.toUpperCase()}</div>
                  <div style={{ fontSize: 16, marginTop: 4, color: g.pass ? T.green : T.red }}>{g.value}</div>
                  <div style={{ fontSize: 9, marginTop: 2, color: g.pass ? T.green : T.red }}>{g.pass ? "✓ pass" : "✗ fail"}</div>
                </div>
              ))}
            </div>
          </section>

          {/* 03 — factors */}
          <section id="sec-03" style={{ marginBottom: 36 }}>
            <div style={{ color: T.dim, fontSize: 10 }}># 03 · RESEARCH / factor library</div>
            <h2 style={{ fontSize: 14, fontWeight: 500, margin: "4px 0 14px" }}>
              {QD.factorCounts.total} factors · {QD.factorCounts.withIcStats} with IC stats · filter: tier = core | experimental
            </h2>
            <div style={{ border: `1px solid ${T.border}` }}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "18px 2fr 1fr 0.7fr 0.7fr 0.7fr 0.6fr 0.6fr",
                  padding: "7px 10px",
                  background: T.panel,
                  color: T.dim,
                  fontSize: 9,
                  letterSpacing: 1,
                  borderBottom: `1px solid ${T.border}`,
                }}
              >
                <div>★</div>
                <div>FACTOR</div>
                <div>CATEGORY</div>
                <div style={{ textAlign: "right" }}>IC</div>
                <div style={{ textAlign: "right" }}>ICIR</div>
                <div style={{ textAlign: "right" }}>FM-t</div>
                <div style={{ textAlign: "center" }}>v7</div>
                <div style={{ textAlign: "center" }}>v16</div>
              </div>
              {QD.factors.map((f) => (
                <div
                  key={f.name}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "18px 2fr 1fr 0.7fr 0.7fr 0.7fr 0.6fr 0.6fr",
                    padding: "8px 10px",
                    borderBottom: `1px solid ${T.border}`,
                    alignItems: "center",
                    fontSize: 11,
                  }}
                >
                  <div style={{ color: f.tier === "core" ? T.amber : T.muted }}>{f.tier === "core" ? "★" : "○"}</div>
                  <div>
                    <div style={{ color: T.text }}>{f.name}</div>
                    <div style={{ color: T.dim, fontSize: 10, marginTop: 1 }}>{f.pitch}</div>
                  </div>
                  <div style={{ color: T.muted }}>{f.cat}</div>
                  <div style={{ textAlign: "right", color: f.ic == null ? T.dim : f.ic > 0.05 ? T.green : T.text }}>
                    {f.ic != null ? f.ic.toFixed(3) : "—"}
                  </div>
                  <div style={{ textAlign: "right", color: f.icir == null ? T.dim : T.text }}>
                    {f.icir != null ? f.icir.toFixed(2) : "—"}
                  </div>
                  <div style={{ textAlign: "right", color: f.t == null ? T.dim : Math.abs(f.t) >= 2 ? T.green : T.muted }}>
                    {f.t != null ? f.t.toFixed(2) : "—"}
                  </div>
                  <div style={{ textAlign: "center", color: f.inV7 ? T.green : T.dim }}>{f.inV7 ? "●" : "·"}</div>
                  <div style={{ textAlign: "center", color: f.inV16 ? T.green : T.dim }}>{f.inV16 ? "●" : "·"}</div>
                </div>
              ))}
            </div>
          </section>

          {/* 04 — walk forward */}
          <section id="sec-04" style={{ marginBottom: 36 }}>
            <div style={{ color: T.dim, fontSize: 10 }}># 04 · VALIDATION / walk-forward</div>
            <h2 style={{ fontSize: 14, fontWeight: 500, margin: "4px 0 10px" }}>v9 walk-forward — 17 windows, median sharpe 0.53, OOS +18% vs v7</h2>
            <div style={{ padding: 14, background: T.panel, border: `1px solid ${T.border}` }}>
              <div style={{ display: "flex", gap: 20, alignItems: "center", marginBottom: 12 }}>
                <div>
                  <div style={{ color: T.dim, fontSize: 9, letterSpacing: 1 }}>EQUITY (v9 · v25 · v16)</div>
                  <div style={{ display: "flex", gap: 18, marginTop: 6, alignItems: "flex-end" }}>
                    <div>
                      <div style={{ color: T.green, fontSize: 10 }}>v9</div>
                      <Spark data={QD.equity.v9} color={T.green} />
                    </div>
                    <div>
                      <div style={{ color: T.amber, fontSize: 10 }}>v25</div>
                      <Spark data={QD.equity.v25} color={T.amber} />
                    </div>
                    <div>
                      <div style={{ color: T.red, fontSize: 10 }}>v16</div>
                      <Spark data={QD.equity.v16} color={T.red} />
                    </div>
                  </div>
                </div>
                <div style={{ flex: 1 }} />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(17, 1fr)", gap: 2, height: 36 }}>
                {wfWindows.map((s, i) => (
                  <div
                    key={i}
                    style={{
                      background: s >= 0.5 ? T.green : s > 0 ? "rgba(122,192,122,.4)" : T.red,
                      height: `${Math.min(100, Math.abs(s) * 100)}%`,
                      alignSelf: "end",
                    }}
                    title={`win ${i + 1}: ${s.toFixed(2)}`}
                  />
                ))}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", color: T.dim, fontSize: 9, marginTop: 4 }}>
                <span>WIN 01</span>
                <span>MEDIAN 0.53</span>
                <span>WIN 17</span>
              </div>
            </div>
          </section>

          {/* 05 — runs */}
          <section id="sec-05" style={{ marginBottom: 36 }}>
            <div style={{ color: T.dim, fontSize: 10 }}># 05 · LIVE / recent backtest runs</div>
            <h2 style={{ fontSize: 14, fontWeight: 500, margin: "4px 0 12px" }}>Last 8 runs logged by the control plane</h2>
            <div style={{ fontFamily: T.font, fontSize: 10.5 }}>
              {QD.runs.map((r) => (
                <div
                  key={r.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "110px 1fr 70px 70px 70px 70px",
                    gap: 8,
                    padding: "5px 6px",
                    borderBottom: `1px solid ${T.border}`,
                    alignItems: "center",
                  }}
                >
                  <span style={{ color: T.dim }}>{r.ts}</span>
                  <span>{r.name}</span>
                  <span style={{ textAlign: "right" }}>
                    <Pct v={r.ann} />
                  </span>
                  <span style={{ textAlign: "right" }}>{r.sharpe.toFixed(2)}</span>
                  <span style={{ textAlign: "right" }}>
                    <Pct v={r.mdd} />
                  </span>
                  <span style={{ textAlign: "right" }}>
                    <Chip tone={r.status === "success" ? "green" : "red"}>{r.status}</Chip>
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* 06 — signals */}
          <section id="sec-06" style={{ marginBottom: 36 }}>
            <div style={{ color: T.dim, fontSize: 10 }}># 06 · LIVE / signal ledger</div>
            <h2 style={{ fontSize: 14, fontWeight: 500, margin: "4px 0 10px" }}>Paper-trading signals · {QD.signals.length} recent</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8 }}>
              {QD.signals.map((s) => (
                <div key={s.date} style={{ padding: 10, border: `1px solid ${T.border}`, background: T.panel }}>
                  <div style={{ color: T.green, fontSize: 11 }}>{s.date}</div>
                  <div style={{ color: T.muted, fontSize: 10, marginTop: 2 }}>
                    {s.strat} · {s.n} holdings
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* 07 — journey */}
          <section id="sec-07" style={{ marginBottom: 36 }}>
            <div style={{ color: T.dim, fontSize: 10 }}># 07 · JOURNEY / phases</div>
            <h2 style={{ fontSize: 14, fontWeight: 500, margin: "4px 0 12px" }}>Roadmap — 6 phases complete, 3 in flight</h2>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {QD.phases.map((p) => (
                <div
                  key={p.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "60px 1fr 140px 60px",
                    gap: 10,
                    alignItems: "center",
                    fontSize: 11,
                  }}
                >
                  <span style={{ color: p.status === "done" ? T.green : T.amber }}>Phase {p.id}</span>
                  <span>{p.title}</span>
                  <div style={{ background: T.border, height: 6, position: "relative" }}>
                    <div
                      style={{
                        position: "absolute",
                        inset: 0,
                        width: `${(p.done / p.total) * 100}%`,
                        background: p.status === "done" ? T.green : T.amber,
                      }}
                    />
                  </div>
                  <span style={{ color: T.muted, textAlign: "right" }}>
                    {p.done}/{p.total}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {/* 08 — infra */}
          <section id="sec-08">
            <div style={{ color: T.dim, fontSize: 10 }}># 08 · INFRA / stack</div>
            <h2 style={{ fontSize: 14, fontWeight: 500, margin: "4px 0 12px" }}>Everything runs locally; one CLI, one dashboard.</h2>
            <pre
              style={{
                margin: 0,
                padding: 14,
                background: T.panel,
                border: `1px solid ${T.border}`,
                color: T.text,
                fontSize: 10.5,
                lineHeight: 1.6,
                overflow: "auto",
              }}
            >
{`data/              parquet cache · Tushare/AKShare ETL · 2005→today, A-share universe
factor_library/    ${QD.factorCounts.total} factors (${QD.factorCounts.withIcStats} with IC stats) — direction-aware, winsorized
backtest/          vectorized cross-sectional; T+1 execution; transaction cost 3bp
risk/              PSR, DSR, SPA test, walk-forward, bootstrap CIs
control_plane/     CLI: dojo run / dojo admit / dojo promote · this site is its dashboard
journal/           every version gets an eval.md — rejections documented`}
            </pre>
          </section>
        </main>
      </div>

      {/* Status bar */}
      <div
        style={{
          padding: "4px 14px",
          borderTop: `1px solid ${T.border}`,
          fontSize: 9.5,
          color: T.muted,
          display: "flex",
          gap: 14,
          background: T.panel,
        }}
      >
        <span>◀▶ nav</span>
        <span style={{ color: T.green }}>● live</span>
        <span style={{ flex: 1 }} />
        <span>prod {QD.meta.production}</span>
        <span>cand {QD.meta.candidate}</span>
        <span>{QD.meta.updated}</span>
      </div>
    </div>
  );
}
