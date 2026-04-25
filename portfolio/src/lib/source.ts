export function sourceHref(path: string, line?: number | null) {
  const clean = path.split("::")[0].trim().replace(/^\/+/, "").replace(/\/+$/, "");
  const href = `/source/${sourceSlug(clean)}`;
  return line ? `${href}#L${line}` : href;
}

export function sourceLabel(path: string) {
  return path.split("::")[0].trim();
}

export function sourceSlug(path: string) {
  return path
    .replace(/^\/+/, "")
    .replace(/[^A-Za-z0-9._-]+/g, "__")
    .replace(/^_+|_+$/g, "");
}
