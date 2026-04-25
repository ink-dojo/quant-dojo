export const SITE = {
  title: "QuantDojo",
  subtitle: "A-share Quantitative Research Notebook",
  author: "jialong",
  repo: "https://github.com/ink-dojo/quant-dojo",
  started_at: "2026-03-13",
};

/** 计算当前周数和精确日期字符串。周 1 从 project started_at 算起。 */
export function projectWeek(today: Date = new Date()): { week: number; dateStr: string } {
  const start = new Date(SITE.started_at + "T00:00:00Z");
  const diff = today.getTime() - start.getTime();
  const days = Math.max(0, Math.floor(diff / (1000 * 60 * 60 * 24)));
  const week = Math.floor(days / 7) + 1;
  const dateStr = today.toISOString().slice(0, 10);
  return { week, dateStr };
}

export const NAV_ITEMS = [
  { href: "/live", label: "Live", zh: "状态" },
  { href: "/validation", label: "Validation", zh: "否决" },
  { href: "/research", label: "Research", zh: "研究" },
  { href: "/strategy", label: "Strategy", zh: "策略" },
  { href: "/infrastructure", label: "Infra", zh: "工程" },
  { href: "/source", label: "Source", zh: "源码" },
  { href: "/journey", label: "Journey", zh: "历程" },
  { href: "/glossary", label: "Glossary", zh: "术语" },
] as const;

export const FACTOR_CATEGORIES = {
  technical: { label: "技术", labelEn: "Technical", color: "var(--cat-technical)" },
  fundamental: { label: "基本面", labelEn: "Fundamental", color: "var(--cat-fundamental)" },
  microstructure: { label: "微观结构", labelEn: "Microstructure", color: "var(--cat-microstructure)" },
  behavioral: { label: "行为金融", labelEn: "Behavioral", color: "var(--cat-behavioral)" },
  chip: { label: "筹码", labelEn: "Chip", color: "var(--cat-chip)" },
  liquidity: { label: "流动性", labelEn: "Liquidity", color: "var(--cat-liquidity)" },
  extended: { label: "扩展", labelEn: "Extended", color: "var(--cat-extended)" },
} as const;

export type FactorCategory = keyof typeof FACTOR_CATEGORIES;
