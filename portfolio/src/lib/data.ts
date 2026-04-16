/**
 * Data loading helpers. All JSON lives in /public/data/ and is produced by
 * scripts/export_data.py in the parent quant-dojo repo.
 *
 * Since this site is SSG, we read from the filesystem at build time rather than
 * fetching at runtime. `readData` resolves paths relative to public/data.
 */

import path from "path";
import { promises as fs } from "fs";

const DATA_ROOT = path.join(process.cwd(), "public", "data");

export async function readData<T>(relativePath: string): Promise<T> {
  const fullPath = path.join(DATA_ROOT, relativePath);
  const raw = await fs.readFile(fullPath, "utf-8");
  return JSON.parse(raw) as T;
}

export async function readDataOrNull<T>(relativePath: string): Promise<T | null> {
  try {
    return await readData<T>(relativePath);
  } catch (e: unknown) {
    if ((e as NodeJS.ErrnoException)?.code === "ENOENT") return null;
    throw e;
  }
}

export async function listDataFiles(subdir: string): Promise<string[]> {
  const dir = path.join(DATA_ROOT, subdir);
  try {
    const files = await fs.readdir(dir);
    return files.filter((f) => f.endsWith(".json"));
  } catch (e: unknown) {
    if ((e as NodeJS.ErrnoException)?.code === "ENOENT") return [];
    throw e;
  }
}
