"""Tree-sitter source parsing producing per-file structural facts.

Extracted facts feed the NetworkX graph builder: modules, functions, classes,
imports, call sites, inheritance, and test declarations. Python is fully
supported; JavaScript/TypeScript are best-effort. A regex fallback keeps the
pipeline alive if tree-sitter grammars are unavailable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MAX_FILE_BYTES = 400 * 1024
SKIP_SUFFIXES = {".min.js", ".min.css", ".map", ".lock", ".pb.go", "_pb2.py", "_pb2_grpc.py"}
PARSE_LANGS = {".py": "python", ".js": "javascript", ".jsx": "javascript",
               ".ts": "typescript", ".tsx": "tsx"}

_parser_cache: dict[str, object] = {}
_language_pack_ok: Optional[bool] = None


@dataclass
class SymbolDecl:
    name: str
    qualname: str
    kind: str                 # "function" | "class"
    file: str
    start_line: int
    end_line: int
    doc: str = ""
    parent: str = ""          # qualname of enclosing class ("" at module level)


@dataclass
class CallSite:
    caller_qualname: str      # enclosing symbol qualname ("" for module scope)
    callee_name: str
    qualifier: str = ""       # e.g. "self", "orders.utils" when present
    line: int = 0


@dataclass
class ImportFact:
    module: str               # dotted module target ("" for plain `import x` -> recorded in names)
    names: list[str] = field(default_factory=list)
    kind: str = "import"      # "import" | "from"
    level: int = 0            # relative import levels for `from . import x`
    line: int = 0


@dataclass
class FileFacts:
    file: str
    language: str
    symbols: list[SymbolDecl] = field(default_factory=list)
    imports: list[ImportFact] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    inherits: list[tuple[str, str]] = field(default_factory=list)  # (class qualname, base name)
    is_test_file: bool = False


def _get_parser(lang: str):
    global _language_pack_ok
    if lang in _parser_cache:
        return _parser_cache[lang]
    parser = None
    if _language_pack_ok is not False:
        try:
            from tree_sitter_language_pack import get_parser as _gp
            parser = _gp(lang)
            _language_pack_ok = True
        except Exception:
            _language_pack_ok = False
    if parser is None:
        _parser_cache[lang] = None
        return None
    _parser_cache[lang] = parser
    return parser


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _first_comment(node, src: bytes) -> str:
    """Docstring / leading comment for a declaration."""
    body = node.child_by_field_name("body")
    if body is not None and body.type in {"block", "class_body", "statement_block"}:
        first = body.children[0] if body.children else None
        if first is not None and first.type == "expression_statement":
            expr = first.children[0] if first.children else None
            if expr is not None and expr.type == "string":
                return _text(expr, src).strip("\"'").strip()[:400]
        if first is not None and first.type in {"comment", "string"}:
            return _text(first, src).lstrip("/#* ").strip()[:400]
    return ""


def _decorated(node):
    """Return the outermost decorated_definition wrapper, if any."""
    parent = node.parent
    while parent is not None and parent.type == "decorated_definition":
        node = parent
        parent = node.parent
    return node


# --------------------------------------------------------------------------- #
# Python
# --------------------------------------------------------------------------- #

def parse_python(path: str, src: bytes) -> FileFacts:
    facts = FileFacts(file=path, language="python",
                      is_test_file=_is_test_path(path))
    parser = _get_parser("python")
    if parser is None:
        return _parse_python_regex(path, src)
    tree = parser.parse(src)
    root = tree.root_node

    def line_of(n) -> int:
        return n.start_point[0] + 1

    def add_import(n, level: int = 0):
        if n.type == "import_statement":
            for child in n.children:
                if child.type == "dotted_name":
                    facts.imports.append(ImportFact(module=_text(child, src), kind="import",
                                                    line=line_of(child)))
                elif child.type == "alias" or child.type == "wildcard_import":
                    target = child.child_by_field_name("name")
                    if target is not None:
                        facts.imports.append(ImportFact(module=_text(target, src), kind="import",
                                                        line=line_of(child)))
        elif n.type == "import_from_statement":
            mod_node = n.child_by_field_name("module_name")
            module = _text(mod_node, src) if mod_node is not None else ""
            lvl = 0
            for child in n.children:
                if child.type == "relative_import":
                    lvl = _text(child, src).count(".")
                elif child.type == "import_prefix":
                    lvl += _text(child, src).count(".")
            names = []
            for child in n.children:
                if child.type == "wildcard_import":
                    names.append("*")
                elif child.type == "alias":
                    nm = child.child_by_field_name("name")
                    if nm is not None:
                        names.append(_text(nm, src))
            facts.imports.append(ImportFact(module=module, names=names, kind="from",
                                            level=lvl, line=line_of(n)))

    def visit_block(node, scope: str):
        """Generic descent: capture imports anywhere, attach declarations to scope."""
        for n in node.children:
            if n.type in {"import_statement", "import_from_statement"}:
                add_import(n)
            elif n.type == "function_definition":
                visit_function(n, scope)
            elif n.type == "class_definition":
                visit_class(n, scope)
            elif n.type == "decorated_definition":
                inner = n.child_by_field_name("definition")
                if inner is not None:
                    if inner.type == "function_definition":
                        visit_function(inner, scope)
                    elif inner.type == "class_definition":
                        visit_class(inner, scope)
            elif n.type not in {"function_definition", "class_definition"}:
                visit_block(n, scope)

    def visit_function(n, scope: str):
        name_node = n.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        qualname = f"{scope}.{name}" if scope else name
        facts.symbols.append(SymbolDecl(
            name=name, qualname=qualname, kind="function", file=path,
            start_line=line_of(n), end_line=n.end_point[0] + 1,
            doc=_first_comment(n, src), parent=scope))
        body = n.child_by_field_name("body")
        if body is not None:
            collect_calls(body, qualname)
            visit_block(body, scope)  # nested defs belong to enclosing class scope

    def visit_class(n, scope: str):
        name_node = n.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node, src)
        qualname = f"{scope}.{name}" if scope else name
        facts.symbols.append(SymbolDecl(
            name=name, qualname=qualname, kind="class", file=path,
            start_line=line_of(n), end_line=n.end_point[0] + 1,
            doc=_first_comment(n, src), parent=scope))
        sup = n.child_by_field_name("superclasses")
        if sup is not None:
            for base in sup.children:
                base_text = _text(base, src)
                if base.type == "attribute" or "." in base_text:
                    base_text = base_text.split(".")[-1]
                if base.type in {"identifier", "attribute", "dotted_name"} and base_text:
                    facts.inherits.append((qualname, base_text.split(".")[-1]))
        body = n.child_by_field_name("body")
        if body is not None:
            visit_block(body, qualname)
            collect_calls(body, qualname)

    def collect_calls(node, scope: str):
        """Collect call sites in `node`'s subtree, excluding nested definitions
        (those are visited separately with their own scope)."""
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur.type in {"function_definition", "class_definition", "decorated_definition"}:
                continue
            if cur.type == "call":
                fn = cur.child_by_field_name("function")
                if fn is not None:
                    if fn.type == "identifier":
                        facts.calls.append(CallSite(scope, _text(fn, src), "", line_of(cur)))
                    elif fn.type == "attribute":
                        attr = fn.child_by_field_name("attribute")
                        obj = fn.child_by_field_name("object")
                        attr_name = _text(attr, src) if attr is not None else _text(fn, src).split(".")[-1]
                        qual = _text(obj, src) if obj is not None else ""
                        facts.calls.append(CallSite(scope, attr_name, qual, line_of(cur)))
                    elif fn.type == "call":
                        stack.append(fn)  # e.g. get_factory()() — inspect inner call
                stack.extend(cur.children)
                continue
            stack.extend(cur.children)

    visit_block(root, "")
    return facts


def _parse_python_regex(path: str, src: bytes) -> FileFacts:
    """Regex fallback used only when tree-sitter grammars are unavailable."""
    facts = FileFacts(file=path, language="python", is_test_file=_is_test_path(path))
    text = src.decode("utf-8", errors="replace")
    lines = text.splitlines()
    scope_stack: list[tuple[int, str]] = []  # (indent, qualname)
    current_caller = ""
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        while scope_stack and indent <= scope_stack[-1][0]:
            scope_stack.pop()
        current_caller = scope_stack[-1][1] if scope_stack else ""
        m = re.match(r"^(async\s+)?def\s+([A-Za-z_]\w*)\s*\(", stripped)
        if m:
            name = m.group(2)
            qual = f"{current_caller}.{name}" if current_caller else name
            facts.symbols.append(SymbolDecl(name=name, qualname=qual, kind="function",
                                            file=path, start_line=i, end_line=len(lines)))
            scope_stack.append((indent, qual))
            continue
        m = re.match(r"^class\s+([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?:", stripped)
        if m:
            name = m.group(1)
            qual = f"{current_caller}.{name}" if current_caller else name
            facts.symbols.append(SymbolDecl(name=name, qualname=qual, kind="class",
                                            file=path, start_line=i, end_line=len(lines)))
            if m.group(2):
                for base in m.group(2).split(","):
                    base = base.strip().split(".")[-1]
                    if base:
                        facts.inherits.append((qual, base))
            scope_stack.append((indent, qual))
            continue
        m = re.match(r"^(from\s+([\.\w]+)\s+import\s+(.+)|import\s+(.+))$", stripped)
        if m:
            if m.group(2) is not None:
                names = [a.split(" as ")[0].strip() for a in m.group(3).split(",")]
                facts.imports.append(ImportFact(module=m.group(2), names=names, kind="from", line=i))
            else:
                for part in m.group(4).split(","):
                    part = part.strip().split(" as ")[0].strip()
                    if part:
                        facts.imports.append(ImportFact(module=part, kind="import", line=i))
        for call in re.finditer(r"(?<![\w.])([A-Za-z_]\w*)\s*\(", stripped):
            callee = call.group(1)
            if callee in {"if", "for", "while", "return", "print", "len", "range", "str",
                          "int", "float", "list", "dict", "set", "tuple", "super", "isinstance"}:
                continue
            facts.calls.append(CallSite(current_caller, callee, "", i))
    return facts


# --------------------------------------------------------------------------- #
# JavaScript / TypeScript (best effort)
# --------------------------------------------------------------------------- #

def parse_javascript(path: str, src: bytes, lang: str) -> FileFacts:
    facts = FileFacts(file=path, language=lang, is_test_file=_is_test_path(path))
    parser = _get_parser(lang)
    if parser is None:
        return facts
    tree = parser.parse(src)
    root = tree.root_node

    def line_of(n) -> int:
        return n.start_point[0] + 1

    def find(node, wanted: str, field: Optional[str] = None):
        if field:
            child = node.child_by_field_name(field)
            if child is not None and child.type == wanted:
                return child
        for i in range(node.child_count):
            child = node.child(i)
            if child.type == wanted:
                return child
        return None

    def scope_of(node) -> str:
        cur = node.parent
        while cur is not None:
            if cur.type in {"function_declaration", "method_definition", "class_declaration",
                            "arrow_function", "generator_function_declaration"}:
                nm = cur.child_by_field_name("name") or find(cur, "property_identifier")
                if nm is not None:
                    return _text(nm, src)
            cur = cur.parent
        return ""

    def visit(node):
        t = node.type
        if t in {"import_statement", "import"}:
            source = find(node, "string", "source")
            if source is None:
                for c in node.children:
                    if c.type == "string":
                        source = c
                        break
            if source is not None:
                mod = _text(source, src).strip("\"'")
                facts.imports.append(ImportFact(module=mod, kind="from", line=line_of(node)))
        elif t in {"function_declaration", "class_declaration"}:
            nm = node.child_by_field_name("name")
            if nm is not None:
                name = _text(nm, src)
                kind = "class" if t == "class_declaration" else "function"
                facts.symbols.append(SymbolDecl(name=name, qualname=name, kind=kind, file=path,
                                                start_line=line_of(node),
                                                end_line=node.end_point[0] + 1))
                if t == "class_declaration":
                    heritage = None
                    for c in node.children:
                        if c.type == "class_heritage":
                            heritage = c
                    if heritage is not None:
                        for base in re.finditer(r"extends\s+([\w$.]+)", _text(heritage, src)):
                            facts.inherits.append((name, base.group(1).split(".")[-1]))
        elif t in {"variable_declarator"}:
            value = node.child_by_field_name("value")
            name = node.child_by_field_name("name")
            if value is not None and name is not None and value.type in {"arrow_function", "function_expression"}:
                nm = _text(name, src)
                facts.symbols.append(SymbolDecl(name=nm, qualname=nm, kind="function", file=path,
                                                start_line=line_of(node),
                                                end_line=node.end_point[0] + 1))
        elif t == "method_definition":
            nm = node.child_by_field_name("name")
            if nm is not None:
                name = _text(nm, src)
                parent_class = ""
                cur = node.parent
                while cur is not None:
                    if cur.type == "class_declaration" and cur.child_by_field_name("name") is not None:
                        parent_class = _text(cur.child_by_field_name("name"), src)
                        break
                    cur = cur.parent
                qual = f"{parent_class}.{name}" if parent_class else name
                facts.symbols.append(SymbolDecl(name=name, qualname=qual, kind="function", file=path,
                                                start_line=line_of(node),
                                                end_line=node.end_point[0] + 1, parent=parent_class))
        elif t == "call_expression":
            fn = node.child_by_field_name("function")
            caller = scope_of(node)
            if fn is not None:
                if fn.type == "identifier":
                    facts.calls.append(CallSite(caller, _text(fn, src), "", line_of(node)))
                elif fn.type == "member_expression":
                    prop = fn.child_by_field_name("property")
                    obj = fn.child_by_field_name("object")
                    if prop is not None:
                        facts.calls.append(CallSite(caller, _text(prop, src),
                                                    _text(obj, src) if obj is not None else "",
                                                    line_of(node)))
        for child in node.children:
            visit(child)

    visit(root)
    return facts


def _is_test_path(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return (name.startswith("test_") or name.endswith("_test.py") or
            name.endswith(".test.js") or name.endswith(".test.ts") or
            name.endswith(".spec.js") or name.endswith(".spec.ts") or
            "tests" in parts or "test" in parts or "__tests__" in parts)


# --------------------------------------------------------------------------- #

def should_skip(path: str) -> bool:
    p = Path(path)
    if p.suffix.lower() not in PARSE_LANGS:
        return True
    lowered = str(p).lower()
    return any(lowered.endswith(s) for s in SKIP_SUFFIXES)


def parse_file(rel_path: str, abs_path: Path) -> Optional[FileFacts]:
    if should_skip(rel_path):
        return None
    try:
        if abs_path.stat().st_size > MAX_FILE_BYTES:
            return None
        src = abs_path.read_bytes()
    except OSError:
        return None
    lang = PARSE_LANGS[Path(rel_path).suffix.lower()]
    if lang == "python":
        return parse_python(rel_path, src)
    ts_lang = "typescript" if lang in {"typescript", "tsx"} else "javascript"
    if lang == "tsx":
        ts_lang = "tsx"
    try:
        return parse_javascript(rel_path, src, ts_lang)
    except Exception:
        return FileFacts(file=rel_path, language=lang)
