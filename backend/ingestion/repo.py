"""Code repository adapter (.zip of a repository, or a GitHub download).

Produces an explainable, traceable view of the codebase:
  Repository overview   README + docs
  Technology stack      dependency manifests (package.json, requirements, pyproject, go.mod, pom, Cargo, Docker)
  Key components        top-level modules: purpose (docstring/README/comment), files, key symbols
  Architecture          module dependency graph from real import statements  -> architecture diagram
  Workflow              modules ordered from the entry points                 -> pipeline diagram
  API endpoints         routes found in FastAPI / Flask / Express / Spring code
Nothing is executed; files are only read. Archive extraction is guarded against path traversal
and zip bombs.
"""
from __future__ import annotations

import ast
import json
import re
import zipfile
from collections import Counter, defaultdict, deque
from pathlib import Path, PurePosixPath

from backend.ingestion.base import DocumentAdapter, ExtractionError, clean_text, register_adapter
from backend.schemas import Block, ContentType, ExtractedDocument
from backend.utils.progress import report

IGNORE_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv", "env", "__pycache__", ".next", "target", "vendor",
               "coverage", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", "site-packages", "out", "bin", "obj", ".gradle"}
CODE_EXT = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
            ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rs": "Rust", ".cs": "C#", ".cpp": "C++", ".c": "C", ".rb": "Ruby",
            ".php": "PHP", ".swift": "Swift", ".scala": "Scala", ".vue": "Vue", ".svelte": "Svelte", ".sql": "SQL",
            ".sh": "Shell", ".ps1": "PowerShell", ".dart": "Dart"}
NON_ARCH = {"tests", "test", "__tests__", "spec", "docs", "doc", "examples", "example", "samples", "scripts", "tools",
            "benchmarks", "fixtures", ".github", "e2e"}
MAX_UNCOMPRESSED = 600 * 1024 * 1024
MAX_FILES = 25000
MAX_READ = 200_000
ROUTE_PATTERNS = [
    re.compile(r"@(?:app|router|api|bp|blueprint)\.(get|post|put|patch|delete|route)\(\s*[\"']([^\"']+)"),
    re.compile(r"\b(?:app|router)\.(get|post|put|patch|delete)\(\s*[\"'`]([^\"'`]+)"),
    re.compile(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:value\s*=\s*)?\"([^\"]+)"),
]


def safe_extract(archive: Path, dest: Path) -> Path:
    with zipfile.ZipFile(archive) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if len(members) > MAX_FILES:
            raise ExtractionError("The archive contains too many files to analyse.")
        if sum(m.file_size for m in members) > MAX_UNCOMPRESSED:
            raise ExtractionError("The archive is too large when unpacked (over 600 MB).")
        root = dest.resolve()
        for m in members:
            name = m.filename.replace("\\", "/")
            if name.startswith("/") or ".." in PurePosixPath(name).parts or (m.external_attr >> 16) & 0o170000 == 0o120000:
                continue  # absolute paths, traversal and symlinks are skipped
            target = (root / name).resolve()
            if root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(target, "wb") as out:
                out.write(src.read())
    entries = [p for p in dest.iterdir() if p.name not in ("__MACOSX",)]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else dest


def _walk(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and not any(part in IGNORE_DIRS or part.startswith(".") and part not in (".github",)
                                   for part in p.relative_to(root).parts[:-1]):
            yield p


def _read(p: Path) -> str:
    try:
        if p.stat().st_size > MAX_READ:
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _first_comment(text: str) -> str:
    m = re.match(r'\s*(?:#![^\n]*\n)?\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\'|/\*\*?(.*?)\*/|((?:\s*(?://|#)[^\n]*\n)+))', text, re.S)
    if not m:
        return ""
    raw = next(g for g in m.groups() if g)
    raw = re.sub(r"^\s*(//|#|\*)\s?", "", raw, flags=re.M)
    return " ".join(clean_text(raw).split())[:260]


class RepoScan:
    def __init__(self, root: Path):
        self.root = root
        self.files = list(_walk(root))
        self.code = [f for f in self.files if f.suffix.lower() in CODE_EXT]

    def languages(self) -> list[tuple[str, int]]:
        return Counter(CODE_EXT[f.suffix.lower()] for f in self.code).most_common(6)

    def modules(self) -> dict[str, list[Path]]:
        """Top-level code directories (descending into src/ or a single package dir)."""
        groups: dict[str, list[Path]] = defaultdict(list)
        for f in self.code:
            parts = f.relative_to(self.root).parts
            if len(parts) == 1:
                groups["(root)"].append(f)
                continue
            key = parts[0]
            if key.lower() in NON_ARCH:
                continue  # tests, docs, examples, scripts are not part of the runtime architecture
            if key in ("src", "lib", "app", "packages", "apps", "services") and len(parts) > 2:
                key = f"{parts[0]}/{parts[1]}"
            groups[key].append(f)
        # one package holding most of the code: describe its sub-packages instead
        total = sum(len(v) for v in groups.values()) or 1
        for key in list(groups):
            files = groups[key]
            subs = defaultdict(list)
            for f in files:
                rel = f.relative_to(self.root / key).parts
                if len(rel) > 1:
                    subs[f"{key}/{rel[0]}"].append(f)
            if len(files) / total >= 0.5 and len(subs) >= 3:
                del groups[key]
                groups.update(subs)
            elif len(files) / total >= 0.6 and not subs and len(groups) <= 2:
                # a flat package (app/api.py, app/pricing.py ...): its files are the components
                flat = {f"{key}/{f.stem}": [f] for f in files if f.stem not in ("__init__", "index", "mod")}
                if len(flat) >= 3:
                    del groups[key]
                    groups.update(flat)
        return dict(sorted(groups.items(), key=lambda kv: -len(kv[1]))[:12])

    def module_description(self, name: str, files: list[Path]) -> str:
        base = self.root / name if name != "(root)" else self.root
        for cand in ("README.md", "readme.md", "__init__.py", "index.ts", "index.js", "main.py", "main.go", "mod.rs"):
            p = base / cand
            if p.exists():
                text = _read(p)
                if cand.lower() == "readme.md":
                    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
                    if lines:
                        return lines[0][:260]
                else:
                    c = _first_comment(text)
                    if c:
                        return c
        for f in sorted(files, key=lambda x: len(x.parts))[:5]:
            c = _first_comment(_read(f))
            if c:
                return c
        return ""

    def symbols(self, files: list[Path], limit: int = 6) -> list[str]:
        out: list[str] = []
        for f in files[:40]:
            text = _read(f)
            if f.suffix == ".py":
                try:
                    tree = ast.parse(text)
                    out += [n.name for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                            and not n.name.startswith("_")]
                except SyntaxError:
                    pass
            else:
                out += re.findall(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|interface)\s+([A-Za-z_]\w*)", text)
                out += re.findall(r"^\s*(?:public\s+)?(?:class|interface)\s+([A-Z]\w*)", text, re.M)
            if len(out) >= limit * 3:
                break
        return list(dict.fromkeys(out))[:limit]

    def imports_of(self, f: Path, modules: dict[str, list[Path]]) -> set[str]:
        """Modules imported by file f (Python imports, JS/TS relative and bare imports)."""
        names = {m.split("/")[-1]: m for m in modules if m != "(root)"}
        text = _read(f)
        targets: set[str] = set()
        if f.suffix == ".py":
            for m in re.findall(r"^\s*(?:from|import)\s+([\w\.]+)", text, re.M):
                for part in m.split("."):
                    if part in names:
                        targets.add(names[part])
                        break
            # from package import a, b  ->  a and b may be modules themselves
            for pkg, what in re.findall(r"^\s*from\s+([\w\.]+)\s+import\s+\(?([\w ,]+)", text, re.M):
                for name in (w.strip().split(" as ")[0] for w in what.split(",")):
                    if name in names and pkg.split(".")[-1] != name:
                        targets.add(names[name])
        else:
            for spec in re.findall(r"(?:import\s[^'\"]*from\s*|require\()\s*['\"]([^'\"]+)['\"]", text):
                if spec.startswith("."):
                    try:
                        rel = (f.parent / spec).resolve().relative_to(self.root.resolve()).parts
                    except ValueError:
                        continue
                    for m in modules:
                        if tuple(m.split("/")) == rel[: len(m.split("/"))]:
                            targets.add(m)
                else:
                    head = spec.split("/")[0].lstrip("@")
                    if head in names:
                        targets.add(names[head])
        return targets

    def dependencies(self, modules: dict[str, list[Path]]) -> list[tuple[str, str]]:
        """Edges A -> B when code in module A imports code from module B."""
        owner = {f: m for m, fs in modules.items() for f in fs}
        edges: Counter[tuple[str, str]] = Counter()
        for f in self.code:
            a = owner.get(f)
            if not a:
                continue
            for b in self.imports_of(f, modules):
                if b != a:
                    edges[(a, b)] += 1
        return [e for e, _ in edges.most_common(20)]

    def stack(self) -> list[str]:
        out: list[str] = []
        pj = self.root / "package.json"
        if pj.exists():
            try:
                data = json.loads(_read(pj) or "{}")
                deps = list((data.get("dependencies") or {}).keys())[:12]
                if deps:
                    out.append("JavaScript/TypeScript dependencies: " + ", ".join(deps))
            except json.JSONDecodeError:
                pass
        for req in ("requirements.txt", "requirements/base.txt"):
            p = self.root / req
            if p.exists():
                pk = [re.split(r"[<>=~!\[; ]", l.strip())[0] for l in _read(p).splitlines() if l.strip() and not l.startswith(("#", "-"))]
                if pk:
                    out.append("Python dependencies: " + ", ".join(pk[:14]))
        pp = self.root / "pyproject.toml"
        if pp.exists():
            m = re.search(r"dependencies\s*=\s*\[(.*?)\]", _read(pp), re.S)
            if m:
                pk = [re.split(r"[<>=~!\[; ]", d.strip().strip("\"'"))[0] for d in m.group(1).split(",") if d.strip()]
                out.append("Python project dependencies: " + ", ".join(x for x in pk[:14] if x))
        for fname, label, pat in (("go.mod", "Go modules", r"^\s*([\w\.\-/]+)\s+v"), ("Cargo.toml", "Rust crates", r"^(\w[\w-]*)\s*="),
                                  ("pom.xml", "Maven artifacts", r"<artifactId>([^<]+)</artifactId>")):
            p = self.root / fname
            if p.exists():
                found = re.findall(pat, _read(p), re.M)[:12]
                if found:
                    out.append(f"{label}: " + ", ".join(dict.fromkeys(found)))
        docker = self.root / "Dockerfile"
        if docker.exists():
            bases = re.findall(r"^FROM\s+(\S+)", _read(docker), re.M)
            if bases:
                out.append("Container base images: " + ", ".join(bases[:4]))
        compose = next((self.root / n for n in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml") if (self.root / n).exists()), None)
        if compose:
            svcs = re.findall(r"^\s{2}([a-zA-Z][\w-]*):\s*$", _read(compose), re.M)
            if svcs:
                out.append("Docker Compose services: " + ", ".join(svcs[:10]))
        return out

    def routes(self) -> list[str]:
        found: list[str] = []
        for f in self.code:
            text = _read(f)
            for pat in ROUTE_PATTERNS:
                for method, path in pat.findall(text):
                    found.append(f"{method.upper().replace('MAPPING', '').replace('ROUTE', 'ANY')} {path}  ({f.relative_to(self.root).as_posix()})")
            if len(found) > 40:
                break
        return list(dict.fromkeys(found))[:25]

    def entry_points(self) -> list[str]:
        names = {"main.py", "app.py", "manage.py", "server.py", "wsgi.py", "asgi.py", "cli.py", "index.js", "server.js",
                 "main.ts", "index.ts", "main.go", "Program.cs", "Main.java", "main.rs"}
        return [f.relative_to(self.root).as_posix() for f in self.code if f.name in names][:6]


def _workflow(modules: list[str], edges: list[tuple[str, str]], entry_mods: list[str]) -> list[str]:
    """Order modules from the entry points along dependency edges (BFS); remaining modules follow."""
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    order, seen = [], set()
    q = deque([m for m in entry_mods if m in modules] or ([modules[0]] if modules else []))
    while q:
        m = q.popleft()
        if m in seen:
            continue
        seen.add(m)
        order.append(m)
        q.extend(adj[m])
    return order + [m for m in modules if m not in seen]


@register_adapter
class RepoAdapter(DocumentAdapter):
    extensions = (".zip",)
    format_name = "repository"

    def extract(self, path: Path, document_id: str, work_dir: Path) -> ExtractedDocument:
        report("Unpacking the repository")
        dest = work_dir / "repo"
        if not dest.exists():
            try:
                root = safe_extract(path, dest)
            except zipfile.BadZipFile as exc:
                raise ExtractionError("The ZIP file could not be opened.") from exc
        else:
            entries = list(dest.iterdir())
            root = entries[0] if len(entries) == 1 and entries[0].is_dir() else dest
        scan = RepoScan(root)
        if not scan.files:
            raise ExtractionError("The archive is empty.")
        report(f"Analysing {len(scan.code)} code files")
        name = root.name if root != dest else Path(path).stem
        out = ExtractedDocument(document_id=document_id, filename=path.name, format="repository", page_count=1,
                                metadata={"repository": name})
        B = out.blocks

        def h(text, level=1):
            B.append(Block(type=ContentType.heading, text=text, page=1, level=level))

        def p(text):
            if text.strip():
                B.append(Block(type=ContentType.paragraph, text=clean_text(text), page=1))

        def li(text):
            B.append(Block(type=ContentType.list_item, text=clean_text(text), page=1))

        # ---- overview (README)
        h("Repository overview")
        langs = scan.languages()
        p(f"The repository {name} contains {len(scan.files)} files, including {len(scan.code)} source files"
          + (f" written mainly in {', '.join(l for l, _ in langs[:3])}." if langs else "."))
        readme = next((f for f in (root / n for n in ("README.md", "readme.md", "README.rst", "README.txt", "README")) if f.exists()), None)
        if readme:
            from backend.ingestion.markdown import MarkdownAdapter

            try:
                md = MarkdownAdapter().extract(readme, document_id, work_dir)
                for b in md.blocks[:80]:
                    if b.type == ContentType.heading:
                        b.level = min(4, b.level + 1)
                    b.page = 1
                    if b.type != ContentType.code:
                        B.append(b)
                out.title = md.title if md.title and len(md.title) < 90 else name
            except ExtractionError:
                pass
        out.title = out.title or name

        # ---- technology stack
        stack = scan.stack()
        if stack or langs:
            h("Technology stack")
            for s in stack:
                li(s)
            if langs:
                li("Languages by file count: " + ", ".join(f"{l} ({n})" for l, n in langs))

        # ---- components + architecture graph
        modules = scan.modules()
        edges = scan.dependencies(modules)
        mods = list(modules)
        h("Key components")
        descriptions = {}
        for m, files in modules.items():
            desc = scan.module_description(m, files)
            descriptions[m] = desc
            syms = scan.symbols(files)
            li(f"{m}: " + (desc + " " if desc else "") + f"({len(files)} source files"
               + (f"; key elements: {', '.join(syms)}" if syms else "") + ")")
        h("Architecture")
        if edges:
            p("Module dependencies found in the source code: " + "; ".join(f"{a} uses {b}" for a, b in edges) + ".")
        else:
            p("The source code has no cross-module imports between the top-level components listed above.")
        nodes = [{"id": re.sub(r"\W", "_", m), "label": m.split("/")[-1][:28],
                  "group": m.split("/")[0] if "/" in m else ""} for m in mods if m != "(root)"][:8]
        ids = {n["id"] for n in nodes}
        graph_edges = [{"source": re.sub(r"\W", "_", a), "target": re.sub(r"\W", "_", b), "label": ""} for a, b in edges
                       if re.sub(r"\W", "_", a) in ids and re.sub(r"\W", "_", b) in ids]
        out.metadata["architecture_graph"] = {"nodes": nodes, "edges": graph_edges}

        # ---- workflow (pipeline)
        entries = scan.entry_points()
        entry_mods: list[str] = []
        for e in entries:
            parts = tuple(e.split("/"))
            inside = [m for m in mods if m != "(root)" and tuple(m.split("/")) == parts[: len(m.split("/"))]]
            # an entry file outside every module starts the flow at the modules it imports
            entry_mods += inside or sorted(scan.imports_of(root / e, modules))
        flow = [m for m in _workflow(mods, edges, entry_mods) if m != "(root)"][:6]
        if flow:
            h("Workflow")
            if entries:
                p("Entry points: " + ", ".join(entries) + ".")
            for m in flow:
                li(f"{m.split('/')[-1]}: " + (descriptions.get(m) or f"component in {m}"))

        # ---- API
        routes = scan.routes()
        if routes:
            h("API endpoints")
            for r in routes:
                li(r)
        out.metadata.update({"entry_points": entries, "languages": langs, "modules": mods})
        return out
