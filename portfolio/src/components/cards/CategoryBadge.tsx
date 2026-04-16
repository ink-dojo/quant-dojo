import { FACTOR_CATEGORIES, type FactorCategory } from "@/lib/constants";

interface Props {
  category: FactorCategory | string;
  size?: "sm" | "md";
}

export function CategoryBadge({ category, size = "sm" }: Props) {
  const cfg = (FACTOR_CATEGORIES as Record<string, { label: string; labelEn: string; color: string }>)[
    category
  ];
  const color = cfg?.color ?? "var(--text-tertiary)";
  const label = cfg?.label ?? category;
  const labelEn = cfg?.labelEn ?? "";
  const text = size === "md" ? "text-xs" : "text-[10px]";
  const pad = size === "md" ? "px-2 py-0.5" : "px-1.5 py-0.5";
  return (
    <span
      className={`${text} ${pad} rounded-full font-mono inline-flex items-center gap-1 border`}
      style={{
        color,
        borderColor: `${color}55`,
        background: `${color}14`,
      }}
    >
      <span>{label}</span>
      {labelEn && (
        <span className="opacity-60">· {labelEn}</span>
      )}
    </span>
  );
}
