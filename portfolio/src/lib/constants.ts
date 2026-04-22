export const SITE = {
  title: "QuantDojo",
  subtitle: "A-share Quantitative Research",
  author: "jialong",
  repo: "https://github.com/ink-dojo/quant-dojo",
};

export const NAV_ITEMS = [
  { href: "/research", label: "Research", zh: "研究" },
  { href: "/strategy", label: "Strategy", zh: "策略" },
  { href: "/validation", label: "Validation", zh: "验证" },
  { href: "/live", label: "Live", zh: "实盘" },
  { href: "/infrastructure", label: "Infra", zh: "工程" },
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
