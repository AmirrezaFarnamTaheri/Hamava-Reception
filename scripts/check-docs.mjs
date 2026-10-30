#!/usr/bin/env node
/** Enforce mirrored project Markdown and valid local documentation links. */
import { readdir, readFile, stat } from "node:fs/promises";
import { resolve, dirname, join, relative, sep, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
const roots = ["", "docs", "frontend", "fixtures/research"];
async function present(p) { try { await stat(p); return true; } catch(e) { if(e.code === "ENOENT") return false; throw e; } }
export async function check(root) {
  root = resolve(root);
  const names = [];
  for (const dir of roots) {
    if (!(await present(join(root,dir)))) continue;
    for (const ent of await readdir(join(root,dir),{withFileTypes:true})) {
      if(ent.isFile() && ent.name.endsWith(".md")) names.push(join(dir,ent.name));
    }
  }
  const all = new Set(names);
  const errors = [];
  for(const path of names) {
    const mate = path.endsWith(".fa.md") ? path.replace(/\.fa\.md$/, ".md") : path.replace(/\.md$/, ".fa.md");
    if(!all.has(mate)) errors.push(path+": missing mirror "+mate);
    const content = await readFile(join(root,path),"utf8");
    let fence = false;
    for(const line of content.split(/\r?\n/)) {
      if(/^\s*(```|~~~)/.test(line)){fence=!fence;continue;}
      if(fence) continue;
      for(const m of line.matchAll(/\[[^\]]+\]\(([^)]+)\)/g)){
        const target=m[1].trim().split(/\s+"/)[0];
        if(/^(?:[a-z][\w+.-]*:|\/\/|#)/i.test(target)) continue;
        let local;try{local=decodeURIComponent(target.split(/[?#]/)[0]);}catch{errors.push(path+": invalid link "+target);continue;}
        if(!local)continue;
        const absolute=resolve(root,dirname(path),local),rel=relative(root,absolute);
        if(isAbsolute(rel)||rel===".."||rel.startsWith(".."+sep)) errors.push(path+": escaping link "+target);
        else if(!(await present(absolute)))errors.push(path+": broken link "+target);
      }
    }
  }
  return errors.sort();
}
if (process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const errors=await check(fileURLToPath(new URL("../",import.meta.url)));
  for(const error of errors)console.error(error);
  if(errors.length)process.exitCode=1;
  else console.log("Bilingual documentation and local-link check passed.");
}
