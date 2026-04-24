"use client";

import { useEffect, useState } from "react";

type Lang = "zh" | "en";

const STORAGE_KEY = "quantdojo-lang";

export function LanguageToggle() {
  const [lang, setLang] = useState<Lang>("zh");

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    const next = saved === "en" ? "en" : "zh";
    setLang(next);
    document.documentElement.dataset.lang = next;
    document.documentElement.lang = next === "zh" ? "zh" : "en";
  }, []);

  function choose(next: Lang) {
    setLang(next);
    window.localStorage.setItem(STORAGE_KEY, next);
    document.documentElement.dataset.lang = next;
    document.documentElement.lang = next === "zh" ? "zh" : "en";
  }

  return (
    <div className="ml-1 flex shrink-0 items-center rounded-md border border-[var(--border-soft)] p-0.5 font-mono text-[10px] text-[var(--text-tertiary)] md:ml-2">
      <button
        type="button"
        onClick={() => choose("zh")}
        className={`rounded px-2 py-1 transition-colors ${
          lang === "zh"
            ? "bg-[var(--bg-surface)] text-[var(--text-primary)]"
            : "hover:text-[var(--text-secondary)]"
        }`}
      >
        中文
      </button>
      <button
        type="button"
        onClick={() => choose("en")}
        className={`rounded px-2 py-1 transition-colors ${
          lang === "en"
            ? "bg-[var(--bg-surface)] text-[var(--text-primary)]"
            : "hover:text-[var(--text-secondary)]"
        }`}
      >
        EN
      </button>
    </div>
  );
}
