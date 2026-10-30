#!/usr/bin/env python3
"""Conservative module-reachability audit. It lists review candidates, not automatic deletions."""
from __future__ import annotations

import argparse
import ast
from collections import deque
import json
from pathlib import Path
import re

SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".venv", "artifacts", "__pycache__"}
JS_EXTS = (".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs", ".css")


def files(root: Path, directory: str, suffixes: tuple[str, ...]) -> list[Path]:
    folder = root / directory
    if not folder.is_dir():
        return []
    return sorted(p.relative_to(root) for p in folder.rglob("*")
                  if p.is_file() and p.suffix in suffixes
                  and not SKIP_DIRS.intersection(p.relative_to(root).parts))


def reachable(edges: dict[str, set[str]], roots: set[str]) -> set[str]:
    visited = set()
    queue = deque(sorted(roots))
    while queue:
        current = queue.popleft()
        if current in visited or current not in edges:
            continue
        visited.add(current)
        queue.extend(sorted(edges[current] - visited))
    return visited


def py_imports(source: str, module: str, is_package: bool, known: set[str]) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for part in range(1, len(alias.name.split(".")) + 1):
                    candidate = ".".join(alias.name.split(".")[:part])
                    if candidate in known:
                        found.add(candidate)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".") if package else []
                trim = node.level - 1
                if trim > len(parts):
                    continue
                parts = parts[:len(parts) - trim] if trim else parts
                base = ".".join(parts + (node.module.split(".") if node.module else []))
            else:
                base = node.module or ""
            if base in known:
                found.add(base)
            for alias in node.names:
                target = (base + "." + alias.name).strip(".")
                if target in known:
                    found.add(target)
    return found


def python_inventory(root: Path) -> dict:
    modules: dict[str, str] = {}
    for path in files(root, "backend/receptionist", (".py",)):
        stem = path.with_suffix("").relative_to("backend").parts
        name = ".".join(stem[:-1] if stem[-1] == "__init__" else stem)
        modules[str(path)] = name
    known = set(modules.values())
    edges: dict[str, set[str]] = {}
    for path, name in modules.items():
        edges[name] = py_imports((root / path).read_text(encoding="utf8"), name,
                                 path.endswith("/__init__.py"), known)
    roots = {"receptionist.main", "receptionist.worker", "receptionist.media.audiosocket",
             "receptionist.media.livekit_worker"}
    for path in (files(root, "scripts", (".py",)) + files(root, "deploy/asterisk", (".py",))
                 + files(root, "services", (".py",))):
        roots.update(py_imports((root / path).read_text(encoding="utf8"), "", False, known))
    production = reachable(edges, roots)
    test_roots = set()
    for path in files(root, "backend/tests", (".py",)):
        test_roots |= py_imports((root / path).read_text(encoding="utf8"), "", False, known)
    tests = reachable(edges, test_roots)
    return {"scanned": len(modules),
            "unreachable": sorted(path for path, name in modules.items()
                                  if name not in production | tests and not path.endswith("/__init__.py")),
            "test_only": sorted(path for path, name in modules.items()
                                if name in tests - production and not path.endswith("/__init__.py")),
            "entrypoint_reachable": len(production), "test_reachable": len(tests)}


def js_imports(source: str, path: Path, known: set[str]) -> set[str]:
    matches = re.findall(r"(?:\bfrom\s*|\bimport\s*\(|\brequire\s*\(|\bimport\s*|@import\s*)[\s]*['\"]([^'\"]+)['\"]", source)
    out = set()
    for spec in matches:
        if not spec.startswith("."):
            continue
        full = (path.parent / spec).as_posix()
        parts = []
        for item in full.split("/"):
            if item == "..":
                if parts:
                    parts.pop()
            elif item != ".":
                parts.append(item)
        base = "/".join(parts)
        for candidate in (base, *(base + ext for ext in JS_EXTS), *(base + "/index" + ext for ext in JS_EXTS)):
            if candidate in known:
                out.add(candidate)
    return out


def javascript_inventory(root: Path) -> dict:
    locations = ["frontend/src", "frontend/scripts", "apps/desktop/src",
                 "apps/desktop/scripts", "apps/mobile/scripts"]
    paths = [p for loc in locations for p in files(root, loc, JS_EXTS)]
    known = {p.as_posix() for p in paths}
    edges = {p.as_posix(): js_imports((root / p).read_text(encoding="utf8"), p, known) for p in paths}
    roots = {"frontend/src/main.tsx", "apps/desktop/src/main.cjs"}
    for pkg in ("frontend/package.json", "apps/desktop/package.json", "apps/mobile/package.json"):
        config = root / pkg
        if not config.is_file():
            continue
        scripts = json.loads(config.read_text(encoding="utf8")).get("scripts", {})
        base = str(Path(pkg).parent)
        for command in scripts.values():
            for match in re.findall(r"(?:scripts/)[\w./-]+\.(?:mjs|cjs|js)", command):
                entry = (Path(base) / match).as_posix()
                if entry in known:
                    roots.add(entry)
    roots |= {p for p in known if p.endswith((".test.mjs", ".test.cjs"))}
    workflow_files = files(root, ".github/workflows", (".yml", ".yaml"))
    for wf in workflow_files:
        content = (root / wf).read_text(encoding="utf8")
        roots |= {p for p in known if p in content}
    active = reachable(edges, roots)
    return {"scanned": len(paths),
            "unreachable_application": sorted(p for p in known if p.startswith("frontend/src/") and p not in active),
            "unreferenced_tooling": sorted(p for p in known if p.startswith(("frontend/scripts/", "apps/desktop/scripts/", "apps/mobile/scripts/")) and p not in active),
            "unreachable_desktop": sorted(p for p in known if p.startswith("apps/desktop/src/") and p not in active),
            "reachable": len(active)}


def audit(root: Path) -> dict:
    return {"schema_version": 1, "python": python_inventory(root), "javascript": javascript_inventory(root),
            "native_java": {"files": len(files(root, "apps/mobile/android/app/src/main", (".java",))),
                            "entrypoint": "AndroidManifest.xml/MainActivity.java",
                            "note": "Android manifests, resources and Capacitor plugin registration need runtime-aware review; no auto-pruning."}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="Fail on unreachable application modules, but not on manually invokable tooling")
    args = parser.parse_args()
    report = audit(args.root.resolve())
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf8")
    print(text)
    failures = (report["python"]["unreachable"] + report["javascript"]["unreachable_application"]
                + report["javascript"]["unreachable_desktop"])
    return int(bool(args.check and failures))


if __name__ == "__main__":
    raise SystemExit(main())
