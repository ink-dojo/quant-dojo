import { PageHeader } from "@/components/layout/PageHeader";
import { Lang } from "@/components/layout/LanguageText";
import { SourceLink } from "@/components/source/SourceLink";
import { readData } from "@/lib/data";
import type { SourceManifest } from "@/lib/types";

const KIND_ORDER = [
  "backtest",
  "validation",
  "research",
  "factor",
  "live",
  "risk",
  "pipeline",
  "tests",
  "journal",
  "site",
  "other",
];

const KIND_ZH: Record<string, string> = {
  backtest: "回测",
  validation: "验证",
  research: "研究",
  factor: "因子",
  live: "模拟盘",
  risk: "风控",
  pipeline: "管线",
  tests: "测试",
  journal: "日志",
  site: "站点",
  other: "其他",
};

export default async function SourceIndexPage() {
  const manifest = await readData<SourceManifest>("source/manifest.json");
  const byKind = new Map<string, typeof manifest.files>();
  for (const file of manifest.files) {
    const bucket = byKind.get(file.kind) ?? [];
    bucket.push(file);
    byKind.set(file.kind, bucket);
  }

  const kinds = Array.from(byKind.keys()).sort((a, b) => {
    const ai = KIND_ORDER.includes(a) ? KIND_ORDER.indexOf(a) : KIND_ORDER.length;
    const bi = KIND_ORDER.includes(b) ? KIND_ORDER.indexOf(b) : KIND_ORDER.length;
    return ai - bi || a.localeCompare(b);
  });

  return (
    <>
      <PageHeader
        eyebrow={<Lang zh="源码索引" en="Source index" />}
        title={<Lang zh="研究证据可以追到代码" en="Evidence traces back to code" />}
        subtitle={
          <Lang
            zh={`${manifest.total} 个源码 / 文档快照`}
            en={`${manifest.total} source and document snapshots`}
          />
        }
        description={
          <Lang
            zh="这里不是完整 GitHub 替代品，而是站内证据层：回测、walk-forward、测试、模拟盘、因子研究都可以从页面直接打开实现。"
            en="This is not a GitHub replacement; it is the site's evidence layer. Backtests, walk-forward code, tests, paper trading, and factor research can be opened directly."
          />
        }
        crumbs={[{ label: "Home", href: "/" }, { label: "Source" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="space-y-4">
          {kinds.map((kind) => {
            const files = byKind.get(kind) ?? [];
            return (
              <article
                key={kind}
                className="rounded-xl border border-[var(--border-soft)] bg-[var(--bg-surface)]/35 p-5"
              >
                <div className="mb-3 flex items-baseline justify-between gap-3">
                  <h2 className="font-mono text-sm uppercase tracking-[0.16em] text-[var(--text-primary)]">
                    <Lang zh={KIND_ZH[kind] ?? kind} en={kind} />
                  </h2>
                  <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                    {files.length}
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {files.map((file) => (
                    <SourceLink key={file.path} path={file.path} />
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </>
  );
}
