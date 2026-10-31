#!/usr/bin/env node
// Enforce mirrored Markdown, local links, and identical executable examples.
import { readdir, readFile, stat } from "node:fs/promises";
import { resolve, dirname, join, relative, sep, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";

const roots = ["", "docs", "frontend", "fixtures/research"];
const executable = new Set([
  "bash", "sh", "shell", "console", "http", "json", "jsonc", "python", "py",
  "js", "javascript", "typescript", "ts", "tsx", "sql", "powershell",
  "ps1", "yaml", "yml", "toml",
]);

async function present(path) {
  try { await stat(path); return true; }
  catch (error) { if (error.code === "ENOENT") return false; throw error; }
}

export async function check(root) {
  root = resolve(root);
  const names = [];
  for (const dir of roots) {
    if (!(await present(join(root, dir)))) continue;
    for (const entry of await readdir(join(root, dir), {withFileTypes: true})) {
      if (entry.isFile() && entry.name.endsWith(".md")) names.push(join(dir, entry.name));
    }
  }

  const all = new Set(names);
  const errors = [];
  const fences = new Map();
  for (const path of names) {
    const mate = path.endsWith(".fa.md") ? path.replace(/\.fa\.md$/, ".md") : path.replace(/\.md$/, ".fa.md");
    if (!all.has(mate)) errors.push(`${path}: missing mirror ${mate}`);

    const content = await readFile(join(root, path), "utf8");
    const blocks = [];
    let open = null;
    for (const [index, line] of content.split(/\r?\n/).entries()) {
      const marker = line.match(/^[ \t]{0,3}(`{3,}|~{3,})(.*)$/);
      if (marker) {
        const run = marker[1];
        if (!open) {
          open = {symbol: run[0], width: run.length,
            language: marker[2].trim().split(/\s+/)[0].toLowerCase(), body: [], line: index + 1};
          continue;
        }
        if (run[0] === open.symbol && run.length >= open.width && marker[2].trim() === "") {
          blocks.push(open);
          open = null;
          continue;
        }
      }
      if (open) { open.body.push(line); continue; }

      for (const match of line.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)) {
        const target = match[1].trim().split(/\s+"/)[0];
        if (/^(?:[a-z][\w+.-]*:|\/\/|#)/i.test(target)) continue;
        let local;
        try { local = decodeURIComponent(target.split(/[?#]/)[0]); }
        catch { errors.push(`${path}: invalid link ${target}`); continue; }
        if (!local) continue;
        const absolute = resolve(root, dirname(path), local), rel = relative(root, absolute);
        if (isAbsolute(rel) || rel === ".." || rel.startsWith(".." + sep)) errors.push(`${path}: escaping link ${target}`);
        else if (!(await present(absolute))) errors.push(`${path}: broken link ${target}`);
      }
    }
    if (open) errors.push(`${path}:${open.line}: unclosed code fence`);
    fences.set(path, blocks);
  }

  for (const path of names.filter(name => !name.endsWith(".fa.md"))) {
    const mate = path.replace(/\.md$/, ".fa.md");
    if (!fences.has(mate)) continue;
    const source = fences.get(path), translated = fences.get(mate);
    if (source.length !== translated.length) {
      errors.push(`${mate}: code fence count differs from ${path} (${translated.length} vs ${source.length})`);
    }
    for (let i = 0; i < Math.min(source.length, translated.length); i++) {
      if (source[i].language !== translated[i].language) {
        errors.push(`${mate}: code fence ${i + 1} language differs from ${path}`);
      } else if (executable.has(source[i].language) && source[i].body.join("\n") !== translated[i].body.join("\n")) {
        errors.push(`${mate}: executable code fence ${i + 1} differs from ${path}`);
      }
    }
  }
  return errors.sort();
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const errors = await check(fileURLToPath(new URL("../", import.meta.url)));
  for (const error of errors) console.error(error);
  if (errors.length) process.exitCode = 1;
  else console.log("Bilingual documentation, code examples, and local-link check passed.");
}
