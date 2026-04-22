"use client";

import { useMemo, useState } from "react";
import { FactorCard } from "@/components/cards/FactorCard";
import { FACTOR_CATEGORIES, type FactorCategory } from "@/lib/constants";
import type { FactorIndex, FactorIndexItem } from "@/lib/types";

type SortKey = "icir" | "name" | "coverage";
type StrategyFilter = "all" | "v7" | "v16";

interface Props {
  index: FactorIndex;
  heroSlugs: Set<string>;
  intros?: Record<string, string>;
}

/**
 * Client-side filter/sort for the 66-factor library. Dataset is small
 * enough that everything fits in memory — no pagination, no virtualization.
 */
export function FactorLibrary({ index, heroSlugs, intros }: Props) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<FactorCategory | "all">("all");
  const [strategy, setStrategy] = useState<StrategyFilter>("all");
  const [sort, setSort] = useState<SortKey>("icir");
  const [onlyWithIc, setOnlyWithIc] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = index.factors.filter((f) => {
      if (category !== "all" && f.category !== category) return false;
      if (strategy === "v7" && !f.in_v7) return false;
      if (strategy === "v16" && !f.in_v16) return false;
      if (onlyWithIc && f.icir === null) return false;
      if (!q) return true;
      return (
        f.name.toLowerCase().includes(q) ||
        f.docstring.toLowerCase().includes(q)
      );
    });
    rows = [...rows].sort(compare(sort));
    return rows;
  }, [index.factors, query, category, strategy, sort, onlyWithIc]);

  const categoryEntries = Object.entries(index.by_category_counts) as [
    FactorCategory,
    number
  ][];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索因子名或描述…"
          className="flex-1 min-w-[200px] max-w-sm px-3 py-2 rounded-md bg-[var(--bg-surface)] border border-[var(--border-soft)] text-sm text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:outline-none focus:border-[var(--blue)] transition-colors"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="px-3 py-2 rounded-md bg-[var(--bg-surface)] border border-[var(--border-soft)] text-sm text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--blue)]"
        >
          <option value="icir">Sort: ICIR ↓</option>
          <option value="coverage">Sort: Coverage ↓</option>
          <option value="name">Sort: Name ↑</option>
        </select>
        <label className="flex items-center gap-2 text-xs font-mono text-[var(--text-secondary)] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={onlyWithIc}
            onChange={(e) => setOnlyWithIc(e.target.checked)}
            className="accent-[var(--blue)]"
          />
          仅带 IC 统计
        </label>
        <FilterGroup
          value={strategy}
          onChange={setStrategy}
          options={[
            { id: "all", label: "全部" },
            { id: "v7", label: "v7", color: "var(--purple)" },
            { id: "v16", label: "v16", color: "var(--blue)" },
          ]}
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
        <CategoryChip
          active={category === "all"}
          onClick={() => setCategory("all")}
        >
          全部 <span className="ml-1 text-[var(--text-tertiary)]">{index.total}</span>
        </CategoryChip>
        {categoryEntries.map(([cat, n]) => (
          <CategoryChip
            key={cat}
            active={category === cat}
            onClick={() => setCategory(cat)}
            color={FACTOR_CATEGORIES[cat]?.color}
          >
            {FACTOR_CATEGORIES[cat]?.label ?? cat}{" "}
            <span className="ml-1 text-[var(--text-tertiary)]">{n}</span>
          </CategoryChip>
        ))}
      </div>

      <div className="text-xs font-mono text-[var(--text-tertiary)] flex flex-wrap gap-3">
        <span>显示 {filtered.length} / {index.total} 个因子</span>
        {query && <span>· 关键词 &quot;{query}&quot;</span>}
      </div>

      {filtered.length === 0 ? (
        <div className="p-8 rounded-lg border border-dashed border-[var(--border-soft)] text-center text-xs font-mono text-[var(--text-tertiary)]">
          没有匹配的因子 — 换个关键词或重置筛选
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {filtered.map((f) => (
            <FactorCard
              key={f.name}
              factor={f}
              href={`/research/${f.name}`}
              intro={intros?.[f.name]}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function compare(sort: SortKey) {
  return (a: FactorIndexItem, b: FactorIndexItem): number => {
    if (sort === "name") return a.name.localeCompare(b.name);
    if (sort === "coverage") return b.coverage_score - a.coverage_score;
    // icir desc, nulls last
    const av = a.icir;
    const bv = b.icir;
    if (av === null && bv === null) return a.name.localeCompare(b.name);
    if (av === null) return 1;
    if (bv === null) return -1;
    return bv - av;
  };
}

function FilterGroup<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (next: T) => void;
  options: { id: T; label: string; color?: string }[];
}) {
  return (
    <div className="inline-flex rounded-md border border-[var(--border-soft)] overflow-hidden">
      {options.map((opt) => {
        const active = opt.id === value;
        return (
          <button
            key={opt.id}
            onClick={() => onChange(opt.id)}
            className="px-3 py-2 text-xs font-mono transition-colors"
            style={{
              color: active ? opt.color ?? "var(--blue)" : "var(--text-tertiary)",
              background: active ? "var(--bg-surface)" : "transparent",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function CategoryChip({
  children,
  active,
  onClick,
  color,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
  color?: string;
}) {
  return (
    <button
      onClick={onClick}
      className="text-xs font-mono px-2.5 py-1 rounded border transition-all"
      style={{
        borderColor: active ? color ?? "var(--blue)" : "var(--border-soft)",
        color: active ? color ?? "var(--blue)" : "var(--text-secondary)",
        background: active ? "var(--bg-surface)" : "transparent",
      }}
    >
      {children}
    </button>
  );
}
