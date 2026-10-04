"""Golden Path repository validation (spec sections 8, 11, 33).

Layer 2 validation: takes a directory that was already cloned (see clone.py)
and decides whether it satisfies the Golden Path contract. It only *looks*:
files are stat'ed and read as bytes, Python source is parsed into a syntax
tree with `ast.parse`. Nothing from the repository is ever imported,
executed, compiled to bytecode, or built.

    validate(GoldenPath.STATIC, root)  -> StaticSite     (what to deploy)
    validate(GoldenPath.FASTAPI, root) -> FastAPIApp
Failures raise PipelineError:
    GOLDEN_PATH_VIOLATION   contract not met (message says what to fix)
    STATIC_SITE_TOO_LARGE   static content over the platform limits
Messages are shown to developers, so file names that come from the repository
are escaped (they can contain control characters) and lists are truncated, and
absolute server paths never appear.
"""
import ast
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .models import ErrorCode, GoldenPath, PipelineError

# ----------------------------------------------------------------- constants

# Spec 8.1: supported deployable extensions, and ~900 KiB of ConfigMap content
# (the Kubernetes object limit is 1 MiB; the rest is headroom for keys/metadata).
STATIC_ALLOWED_EXTENSIONS = frozenset({".html", ".css", ".js", ".json", ".svg", ".txt"})
STATIC_MAX_BYTES = 900 * 1024
# Not in the spec: every file becomes one volume item in the generated
# Deployment, so an unbounded file count could blow the object-size limit later
# with an opaque error. Rejecting early gives a clear message instead.
STATIC_MAX_FILES = 500

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # also excludes hidden files
_MAX_COMPONENT_LEN = 100
_MAX_PATH_LEN = 200

# Repository housekeeping: never deployed, never an error, at any depth.
_IGNORED_DIRS = frozenset({".git", ".github"})
_IGNORED_FILES = frozenset({".gitignore", ".gitattributes", ".gitkeep", ".nojekyll"})
_IGNORED_DOCS = re.compile(r"^(readme|licen[sc]e|copying)(\.[a-z0-9]+)?$", re.IGNORECASE)

FASTAPI_MAIN_MAX_BYTES = 1024 * 1024
FASTAPI_REQUIREMENTS_MAX_BYTES = 256 * 1024
_REPORT_LIMIT = 5


# ------------------------------------------------------------------- results


@dataclass(frozen=True)
class StaticFile:
    path: str  # repository-relative, forward slashes, already proven safe
    size: int


@dataclass(frozen=True)
class StaticSite:
    """The authoritative deploy list: Phase 4 renders exactly these files."""

    files: tuple[StaticFile, ...]  # sorted by path
    total_bytes: int


@dataclass(frozen=True)
class FastAPIApp:
    target: str = "main:app"  # what the platform's uvicorn command will load


# ------------------------------------------------------------------- helpers


def _violation(message: str) -> PipelineError:
    return PipelineError(ErrorCode.GOLDEN_PATH_VIOLATION, message)


def _quote(text: str, limit: int = 80) -> str:
    """Quote repository-controlled text safely (escapes control/non-ASCII chars)."""
    shown = ascii(text)
    return shown if len(shown) <= limit else shown[: limit - 3] + "..."


def _listing(items: list[str]) -> str:
    shown = ", ".join(_quote(item) for item in items[:_REPORT_LIMIT])
    extra = len(items) - _REPORT_LIMIT
    return f"{shown} and {extra} more" if extra > 0 else shown


def _read_regular_file(path: Path, limit: int) -> bytes:
    """Read a regular file without following symlinks. Caller already lstat'ed it."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            return handle.read(limit + 1)
    finally:
        os.close(fd)


# -------------------------------------------------------------------- static


@dataclass
class _Scan:
    files: list[tuple[str, int]]
    symlinks: list[str]
    special: list[str]
    unsafe: list[str]
    unsupported: list[str]
    index_lookalikes: list[str]


def _scan_static(root: Path) -> _Scan:
    scan = _Scan([], [], [], [], [], [])
    stack: list[tuple[str, str]] = [(str(root), "")]  # (directory, relative prefix)
    while stack:
        directory, prefix = stack.pop()
        with os.scandir(directory) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            name, rel = entry.name, f"{prefix}{entry.name}"
            is_dir = entry.is_dir(follow_symlinks=False)
            if is_dir and name in _IGNORED_DIRS:
                continue
            if not is_dir and (name in _IGNORED_FILES or _IGNORED_DOCS.match(name)):
                continue
            if entry.is_symlink():  # checked before anything that could follow it
                scan.symlinks.append(rel)
                continue
            if len(name) > _MAX_COMPONENT_LEN or len(rel) > _MAX_PATH_LEN or not _SAFE_COMPONENT.match(name):
                scan.unsafe.append(rel)
                continue  # do not descend into a directory we are rejecting
            if is_dir:
                stack.append((entry.path, rel + "/"))
            elif entry.is_file(follow_symlinks=False):
                if name.lower() == "index.html" and (prefix or name != "index.html"):
                    scan.index_lookalikes.append(rel)
                if os.path.splitext(name)[1].lower() in STATIC_ALLOWED_EXTENSIONS:
                    scan.files.append((rel, entry.stat(follow_symlinks=False).st_size))
                else:
                    scan.unsupported.append(rel)
            else:
                scan.special.append(rel)
    return scan


def validate_static(root: Path) -> StaticSite:
    scan = _scan_static(root)

    if scan.symlinks or scan.special:
        raise _violation(
            "Symbolic links and special files are not allowed in a static site: "
            f"{_listing(scan.symlinks + scan.special)}."
        )

    if "index.html" not in {rel for rel, _ in scan.files}:
        hint = ""
        if scan.index_lookalikes:
            hint = (
                f" Found {_quote(scan.index_lookalikes[0])} instead; "
                "move or rename it so it is index.html at the repository root."
            )
        raise _violation(
            "No index.html at the repository root. The static Golden Path serves the "
            "repository root, so index.html must be there." + hint
        )

    if scan.unsafe:
        raise _violation(
            f"Unsafe file or folder names: {_listing(scan.unsafe)}. Names may contain only "
            "letters, digits, '.', '_' and '-', must not start with '.', and are limited in length."
        )

    if scan.unsupported:
        raise _violation(
            f"Unsupported file types: {_listing(scan.unsupported)}. The static Golden Path "
            f"supports only {', '.join(sorted(STATIC_ALLOWED_EXTENSIONS))} files."
        )

    total = sum(size for _, size in scan.files)
    if len(scan.files) > STATIC_MAX_FILES:
        raise PipelineError(
            ErrorCode.STATIC_SITE_TOO_LARGE,
            f"The site has {len(scan.files)} files; the limit is {STATIC_MAX_FILES}.",
        )
    if total > STATIC_MAX_BYTES:
        raise PipelineError(
            ErrorCode.STATIC_SITE_TOO_LARGE,
            f"The site is {total / 1024:.0f} KiB; the limit is {STATIC_MAX_BYTES // 1024} KiB.",
        )

    not_text: list[str] = []
    for rel, size in scan.files:
        try:
            data = _read_regular_file(root / rel, size)
            data.decode("utf-8")  # strict
            if b"\x00" in data:
                raise ValueError("NUL byte")
        except (OSError, UnicodeDecodeError, ValueError):
            not_text.append(rel)
    if not_text:
        raise _violation(f"Files must be UTF-8 text: {_listing(not_text)} is not valid UTF-8 text.")

    files = tuple(StaticFile(rel, size) for rel, size in sorted(scan.files))
    return StaticSite(files=files, total_bytes=total)


# ------------------------------------------------------------------- fastapi

_LITERAL_NODES = (
    ast.Constant, ast.List, ast.Dict, ast.Set, ast.Tuple, ast.ListComp,
    ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.JoinedStr, ast.Lambda,
)

_NO_APP = (
    "main.py does not define `app` at module level. The platform runs "
    "`uvicorn main:app`, so main.py needs something like `app = FastAPI()`."
)


def _module_level(statements):
    """Statements that run when the module is imported, in source order.

    Descends into if/try/with/for/while/match, but not into function or class
    bodies (a name bound there is not a module attribute).
    """
    for node in statements:
        yield node
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            yield from _module_level(node.body)
            yield from _module_level(node.orelse)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            yield from _module_level(node.body)
        elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            yield from _module_level(node.body)
            for handler in node.handlers:
                yield from _module_level(handler.body)
            yield from _module_level(node.orelse)
            yield from _module_level(node.finalbody)
        elif isinstance(node, ast.Match):
            for case in node.cases:
                yield from _module_level(case.body)


def _binds_app(target: ast.expr) -> bool:
    if isinstance(target, ast.Name):
        return target.id == "app"
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_binds_app(element) for element in target.elts)
    if isinstance(target, ast.Starred):
        return _binds_app(target.value)
    return False


def _callee_name(value: ast.expr) -> str | None:
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name):
            return value.func.id
        if isinstance(value.func, ast.Attribute):
            return value.func.attr
    return None


def _imports_fastapi(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "fastapi" for a in node.names):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.split(".")[0] == "fastapi"
        ):
            return True
    return False


def _check_app_contract(source: bytes) -> str | None:
    """Return a problem description, or None if main.py plausibly exposes main:app.

    Static inspection can't prove the object's type, so the rule is: `app` must
    be bound at module level (the *last* binding wins, as at runtime), must not
    be a function/class/module/literal, and unless it is created by a call to
    `FastAPI(...)` or imported from elsewhere, main.py must at least import
    fastapi. That catches the usual mistakes (wrong variable name, Flask app,
    factory function) without running anything.
    """
    try:
        tree = ast.parse(source, filename="main.py", mode="exec")
    except SyntaxError as exc:
        return f"main.py has a syntax error on line {exc.lineno or '?'}: {_quote(exc.msg or 'invalid syntax', 100)}."
    except (ValueError, RecursionError, MemoryError):
        return "main.py could not be parsed as Python source."

    binding: tuple[str, ast.expr | None] | None = None
    for node in _module_level(tree.body):
        if isinstance(node, ast.Assign) and any(_binds_app(t) for t in node.targets):
            binding = ("assign", node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
            and node.target.id == "app"
        ):
            binding = ("assign", node.value)
        elif isinstance(node, ast.ImportFrom):
            if any(a.name != "*" and (a.asname or a.name) == "app" for a in node.names):
                binding = ("import", None)
        elif isinstance(node, ast.Import):
            if any((a.asname or a.name.split(".")[0]) == "app" for a in node.names):
                binding = ("module", None)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "app":
            binding = ("function", None)
        elif isinstance(node, ast.ClassDef) and node.name == "app":
            binding = ("class", None)

    if binding is None:
        return _NO_APP
    kind, value = binding
    if kind in {"function", "class", "module"}:
        return (
            f"`app` in main.py is a {kind}, not a FastAPI instance. The platform runs "
            "`uvicorn main:app`, so use `app = FastAPI()` (factory functions are not supported)."
        )
    if kind == "import":
        return None  # re-exported from another module; cannot be verified statically
    if isinstance(value, _LITERAL_NODES):
        return "`app` in main.py is assigned a literal value; it must be a FastAPI instance (`app = FastAPI()`)."
    callee = _callee_name(value)
    if callee == "FastAPI":
        return None
    if not _imports_fastapi(tree):
        found = f" (it is created by {_quote(callee, 40)})" if callee else ""
        return (
            f"main.py defines `app` but never imports fastapi{found}. "
            "The FastAPI Golden Path requires a FastAPI application."
        )
    return None


def _check_required_file(root: Path, name: str, max_bytes: int) -> tuple[bytes | None, str | None]:
    """Return (content, None) or (None, problem). Never follows symlinks."""
    path = root / name
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None, f"{name} was not found at the repository root."
    if stat.S_ISLNK(info.st_mode):
        return None, f"{name} must be a regular file, not a symbolic link."
    if not stat.S_ISREG(info.st_mode):
        return None, f"{name} must be a regular file."
    if info.st_size > max_bytes:
        return None, f"{name} is larger than the {max_bytes // 1024} KiB limit."
    try:
        return _read_regular_file(path, max_bytes), None
    except OSError:
        return None, f"{name} could not be read."


def validate_fastapi(root: Path) -> FastAPIApp:
    problems: list[str] = []

    main_src, problem = _check_required_file(root, "main.py", FASTAPI_MAIN_MAX_BYTES)
    if problem:
        problems.append(problem)
    requirements, problem = _check_required_file(root, "requirements.txt", FASTAPI_REQUIREMENTS_MAX_BYTES)
    if problem:
        problems.append(problem)

    if requirements is not None:
        try:
            requirements.decode("utf-8")
        except UnicodeDecodeError:
            problems.append("requirements.txt is not valid UTF-8 text.")
    if main_src is not None:
        problem = _check_app_contract(main_src)
        if problem:
            problems.append(problem)

    if problems:
        raise _violation(" ".join(problems))
    return FastAPIApp()


# ------------------------------------------------------------------ dispatch


def validate(golden_path: GoldenPath, root: Path) -> StaticSite | FastAPIApp:
    if golden_path == GoldenPath.STATIC:
        return validate_static(root)
    if golden_path == GoldenPath.FASTAPI:
        return validate_fastapi(root)
    raise ValueError(f"unknown golden path: {golden_path!r}")
