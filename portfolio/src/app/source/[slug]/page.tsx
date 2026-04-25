import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/PageHeader";
import { Lang } from "@/components/layout/LanguageText";
import { readData } from "@/lib/data";
import type { SourceFile, SourceManifest } from "@/lib/types";

export const dynamicParams = false;

export async function generateStaticParams() {
  const manifest = await readData<SourceManifest>("source/manifest.json");
  return manifest.files.map((file) => ({ slug: file.slug }));
}

export default async function SourcePage({
  params,
}: {
  params: { slug: string };
}) {
  const manifest = await readData<SourceManifest>("source/manifest.json");
  const item = manifest.files.find((file) => file.slug === params.slug);
  if (!item) notFound();

  const source = await readData<SourceFile>(`source/${item.data_file}`);
  const lines = source.content.split("\n");

  return (
    <>
      <PageHeader
        eyebrow={<Lang zh="源码" en="Source" />}
        title={source.path}
        subtitle={
          <Lang
            zh={`${source.kind} · ${source.lines} 行 · ${(source.bytes / 1024).toFixed(1)} KB`}
            en={`${source.kind} · ${source.lines} lines · ${(source.bytes / 1024).toFixed(1)} KB`}
          />
        }
        description={
          <Lang
            zh="这是构建时从 repo 导出的只读快照，用来把研究结论追溯到具体实现。"
            en="A read-only build-time snapshot exported from the repo so research claims can be traced to implementation."
          />
        }
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Source", href: "/source" },
          { label: source.path },
        ]}
        actions={
          <Link
            href={`https://github.com/ink-dojo/quant-dojo/blob/main/${source.path}`}
            className="rounded-md border border-[var(--border-soft)] px-3 py-2 font-mono text-xs text-[var(--text-secondary)] hover:border-[var(--blue)]/45 hover:text-[var(--blue)]"
          >
            <Lang zh="在 GitHub 打开" en="GitHub" />
          </Link>
        }
      />

      <section className="max-w-content mx-auto px-6 pb-24">
        {source.truncated && (
          <div className="mb-4 rounded-lg border border-[var(--gold)]/35 bg-[var(--gold)]/[0.05] p-3 text-xs text-[var(--text-secondary)]">
            <Lang
              zh="文件较大，站内只展示前半部分；完整文件可点 GitHub。"
              en="Large file: this page shows the first section only; use GitHub for the full file."
            />
          </div>
        )}
        <div className="overflow-x-auto rounded-xl border border-[var(--border-soft)] bg-[#060b14]">
          <pre className="min-w-full py-4 text-xs leading-6 text-[var(--text-secondary)]">
            <code>
              {lines.map((line, i) => {
                const n = i + 1;
                return (
                  <span
                    key={n}
                    id={`L${n}`}
                    className="source-line grid grid-cols-[4rem_1fr] px-4 target:bg-[var(--blue)]/10"
                  >
                    <Link
                      href={`#L${n}`}
                      className="select-none pr-4 text-right font-mono text-[var(--text-tertiary)] hover:text-[var(--blue)]"
                    >
                      {n}
                    </Link>
                    <span className="whitespace-pre font-mono text-[var(--text-primary)]">
                      {line || " "}
                    </span>
                  </span>
                );
              })}
            </code>
          </pre>
        </div>
      </section>
    </>
  );
}
