#!/usr/bin/env node
// Verify documented HTTP requests and explicit CLI commands against source.
import { readFile, readdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const docDirs = ['', 'docs', 'frontend', 'fixtures/research'];
const shellLanguages = new Set(['sh', 'bash', 'shell', 'console']);

async function readIfPresent(path) {
  try { return await readFile(path, 'utf8'); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

async function fileNames(dir, suffix) {
  try {
    return (await readdir(dir, { withFileTypes: true }))
      .filter(entry => entry.isFile() && entry.name.endsWith(suffix))
      .map(entry => entry.name);
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

function routePattern(path) {
  const sections = path.split('/').map(segment =>
    /^\{[^}]+\}$/.test(segment) ? '[^/]+' : segment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  return new RegExp('^' + sections.join('/') + '/?$');
}

async function routes(root) {
  const registered = [];
  const folder = join(root, 'backend/receptionist');
  for (const name of await fileNames(folder, '.py')) {
    const code = await readFile(join(folder, name), 'utf8');
    const prefix = code.match(/\brouter\s*=\s*APIRouter\(\s*prefix\s*=\s*["']([^"']+)["']/)?.[1] ?? '';
    for (const match of code.matchAll(/@\s*(router|app)\.(get|post|put|patch|delete)\(\s*["'](\/[^"']*)["']/g)) {
      registered.push({ method: match[2].toUpperCase(), path: (match[1] === 'router' ? prefix : '') + match[3] });
    }
  }
  return registered.map(r => ({ ...r, pattern: routePattern(r.path) }));
}

async function checkShell(root, contents, place, errors) {
  const lines = contents.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const match of line.matchAll(/\bpython(?:3(?:\.\d+)?)?\s+scripts\/([\w.-]+\.py)\b/g)) {
      const relativeScript = 'scripts/' + match[1];
      const script = await readIfPresent(join(root, relativeScript));
      if (script === null) {
        errors.push(`${place}: missing Python script ${relativeScript}`);
        continue;
      }
      let command = line.slice(match.index);
      let k = i;
      while (/\\\s*$/.test(lines[k]) && k + 1 < lines.length) {
        command += '\n' + lines[++k];
      }
      const subparsers = new Map([...script.matchAll(/(\w+)\s*=\s*\w+\.add_parser\(\s*["']([\w-]+)["']/g)]
        .map(m => [m[2], m[1]]));
      const subcommand = command.slice(match[0].length).trim().match(/^([a-z][\w-]*)\b/)?.[1];
      const selectedParser = subparsers.get(subcommand);
      const parserVariables = new Set(subparsers.values());
      const supported = new Set([...script.matchAll(/(\w+)\.add_argument\(\s*["'](--[\w-]+)["']/g)]
        .filter(m => !selectedParser || !parserVariables.has(m[1]) || m[1] === selectedParser)
        .map(m => m[2]));
      for (const flag of command.matchAll(/(?<![\w-])(--[a-z][a-z0-9-]*)\b/g)) {
        if (flag[1] !== '--help' && !supported.has(flag[1]))
          errors.push(`${place}: ${relativeScript} does not accept ${flag[1]}`);
      }
    }
    for (const match of line.matchAll(/\bnpm\s+--prefix\s+([\w./-]+)\s+(?:run\s+)?(\S+)/g)) {
      const packagePath = match[1], operation = match[2];
      if (['ci', 'install', 'i', 'test', 'run'].includes(operation) && operation !== 'test') continue;
      const raw = await readIfPresent(join(root, packagePath, 'package.json'));
      if (raw === null) { errors.push(`${place}: missing npm package ${packagePath}`); continue; }
      const scripts = JSON.parse(raw).scripts ?? {};
      if (!Object.hasOwn(scripts, operation)) errors.push(`${place}: npm --prefix ${packagePath} has no ${operation} script`);
    }
  }
}

export async function checkContracts(root) {
  root = resolve(root);
  const registered = await routes(root);
  const errors = [];
  for (const dir of docDirs) {
    for (const name of await fileNames(join(root, dir), '.md')) {
      const file = join(dir, name);
      const content = await readFile(join(root, file), 'utf8');
      let opening = null;
      let lines = [];
      const rows = content.split(/\r?\n/);
      for (let row = 0; row < rows.length; row++) {
        const marker = rows[row].match(/^[ \t]{0,3}(`{3,}|~{3,})(.*)$/);
        if (marker) {
          if (opening === null) {
            opening = { char: marker[1][0], width: marker[1].length,
              lang: marker[2].trim().split(/\s+/)[0].toLowerCase(), start: row + 1 };
            lines = [];
            continue;
          }
          if (marker[1][0] === opening.char && marker[1].length >= opening.width && !marker[2].trim()) {
            const location = `${file}:${opening.start}`;
            if (opening.lang === 'http') {
              for (const line of lines) {
                const request = line.match(/^\s*(GET|POST|PUT|PATCH|DELETE)\s+(\/\S+)/);
                if (!request) continue;
                const path = request[2].split('?')[0].replace(/<[^>]+>/g, 'example');
                if (!registered.some(route => route.method === request[1] && route.pattern.test(path))) {
                  errors.push(`${location}: no registered HTTP route for ${request[1]} ${request[2]}`);
                }
              }
            }
            if (shellLanguages.has(opening.lang)) await checkShell(root, lines.join('\n'), location, errors);
            opening = null;
            lines = [];
            continue;
          }
        }
        if (opening !== null) lines.push(rows[row]);
      }
    }
  }
  return errors.sort();
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const errors = await checkContracts(fileURLToPath(new URL('../', import.meta.url)));
  errors.forEach(error => console.error(error));
  if (errors.length) process.exitCode = 1;
  else console.log('Documented HTTP and explicit CLI examples match current source contracts.');
}
