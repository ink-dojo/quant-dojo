import type { Metadata } from "next";
import "./globals.css";
import "katex/dist/katex.min.css";
import { Navbar } from "@/components/layout/Navbar";
import { SITE } from "@/lib/constants";

export const metadata: Metadata = {
  title: `${SITE.title} — ${SITE.subtitle}`,
  description:
    "A-share quantitative research workbench: 66 alpha factors, multi-factor strategy construction, walk-forward validation, and live paper trading.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh" data-lang="zh" suppressHydrationWarning>
      <body>
        <Navbar />
        <main className="min-h-screen pt-16">{children}</main>
        <footer className="border-t border-[var(--border-soft)] mt-24 py-10 text-center text-xs text-[var(--text-tertiary)]">
          <p className="font-mono">
            {SITE.title} · {SITE.author} ·{" "}
            <a
              href={SITE.repo}
              target="_blank"
              rel="noreferrer"
              className="hover:text-[var(--blue)]"
            >
              source on github
            </a>
          </p>
        </footer>
      </body>
    </html>
  );
}
