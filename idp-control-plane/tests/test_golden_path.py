"""Phase 3: Golden Path validators. Plain directories only: no git, no database."""
import os
import sys

import pytest

from app.golden_path import (
    STATIC_MAX_BYTES,
    STATIC_MAX_FILES,
    FastAPIApp,
    StaticSite,
    _read_regular_file,
    validate,
    validate_fastapi,
    validate_static,
)
from app.models import ErrorCode, GoldenPath, PipelineError

VIOLATION = ErrorCode.GOLDEN_PATH_VIOLATION
TOO_LARGE = ErrorCode.STATIC_SITE_TOO_LARGE


def tree(root, files):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return root


def fails(validator, root, code=VIOLATION) -> str:
    with pytest.raises(PipelineError) as exc:
        validator(root)
    assert exc.value.code == code, exc.value.message
    return exc.value.message


# =================================================================== STATIC


def test_minimal_static_site(tmp_path):
    site = validate_static(tree(tmp_path, {"index.html": "<h1>hi</h1>"}))
    assert isinstance(site, StaticSite)
    assert [(f.path, f.size) for f in site.files] == [("index.html", 11)]
    assert site.total_bytes == 11


def test_nested_paths_are_preserved_and_sorted(tmp_path):
    tree(tmp_path, {
        "index.html": "x", "css/app.css": "body{}", "js/lib/util.js": "1",
        "data/items.json": "{}", "img/logo.svg": "<svg/>", "notes.txt": "n",
    })
    site = validate_static(tmp_path)
    assert [f.path for f in site.files] == [
        "css/app.css", "data/items.json", "img/logo.svg", "index.html", "js/lib/util.js", "notes.txt",
    ]


def test_extensions_are_case_insensitive(tmp_path):
    tree(tmp_path, {"index.html": "x", "style.CSS": "x", "Logo.SVG": "<svg/>"})
    assert len(validate_static(tmp_path).files) == 3


def test_repository_housekeeping_is_ignored_not_deployed(tmp_path):
    tree(tmp_path, {
        "index.html": "x", "README.md": "# docs", "LICENSE": "MIT", "license.txt": "MIT",
        "COPYING": "x", ".gitignore": "x", ".gitattributes": "x", ".nojekyll": "",
        ".github/workflows/ci.yml": "on: push", "docs/README.md": "more docs",
    })
    site = validate_static(tmp_path)
    assert [f.path for f in site.files] == ["index.html"]  # none of the above would be served


def test_ignored_files_do_not_count_toward_the_size_limit(tmp_path):
    tree(tmp_path, {"index.html": "x", "README.md": b"x" * (STATIC_MAX_BYTES * 2)})
    assert validate_static(tmp_path).total_bytes == 1


def test_unicode_bom_and_empty_files_are_fine(tmp_path):
    tree(tmp_path, {"index.html": "\ufeff<p>héllo – 世界</p>".encode(), "empty.txt": b""})
    assert validate_static(tmp_path).total_bytes > 0


def test_size_limit_is_900_kib_inclusive(tmp_path):
    tree(tmp_path, {"index.html": b"x" * STATIC_MAX_BYTES})
    assert validate_static(tmp_path).total_bytes == STATIC_MAX_BYTES
    (tmp_path / "extra.txt").write_text("y")
    msg = fails(validate_static, tmp_path, TOO_LARGE)
    assert "900 KiB" in msg


def test_too_many_files(tmp_path):
    tree(tmp_path, {"index.html": "x", **{f"f{i}.txt": "" for i in range(STATIC_MAX_FILES)}})
    assert str(STATIC_MAX_FILES) in fails(validate_static, tmp_path, TOO_LARGE)


# ---- index.html

def test_missing_index_html(tmp_path):
    msg = fails(validate_static, tree(tmp_path, {"about.html": "x", "README.md": "x"}))
    assert "index.html" in msg and "repository root" in msg


def test_empty_repository_has_no_index(tmp_path):
    assert "index.html" in fails(validate_static, tmp_path)


def test_index_in_a_subfolder_gets_a_hint(tmp_path):
    msg = fails(validate_static, tree(tmp_path, {"public/index.html": "x"}))
    assert "'public/index.html'" in msg and "move" in msg


def test_wrong_case_index_gets_a_hint(tmp_path):
    msg = fails(validate_static, tree(tmp_path, {"Index.html": "x"}))
    assert "'Index.html'" in msg and "rename" in msg


def test_index_html_must_be_a_file(tmp_path):
    (tmp_path / "index.html").mkdir()
    (tmp_path / "index.html" / "x.txt").write_text("x")
    assert "index.html" in fails(validate_static, tmp_path)


# ---- symlinks (a symlink could pull a server file into a public site)

@pytest.fixture
def outside(tmp_path_factory):
    path = tmp_path_factory.mktemp("outside") / "secret.txt"
    path.write_text("SERVER SECRET")
    return path


def test_symlink_to_outside_file_is_rejected(tmp_path, outside):
    tree(tmp_path, {"index.html": "x"})
    os.symlink(outside, tmp_path / "leak.txt")
    msg = fails(validate_static, tmp_path)
    assert "Symbolic links" in msg and "'leak.txt'" in msg
    assert "SERVER SECRET" not in msg and str(outside) not in msg


def test_symlink_to_a_file_inside_the_repo_is_rejected_too(tmp_path):
    tree(tmp_path, {"index.html": "x", "a.txt": "x"})
    os.symlink("a.txt", tmp_path / "b.txt")
    assert "Symbolic links" in fails(validate_static, tmp_path)


def test_symlinked_directory_is_rejected_and_not_followed(tmp_path, outside):
    tree(tmp_path, {"index.html": "x"})
    os.symlink(outside.parent, tmp_path / "assets")
    msg = fails(validate_static, tmp_path)
    assert "Symbolic links" in msg and "'assets'" in msg


def test_dangling_symlink_is_rejected(tmp_path):
    tree(tmp_path, {"index.html": "x"})
    os.symlink("/does/not/exist", tmp_path / "ghost.txt")
    assert "Symbolic links" in fails(validate_static, tmp_path)


def test_index_html_as_a_symlink_is_reported_as_a_symlink(tmp_path, outside):
    os.symlink(outside, tmp_path / "index.html")
    assert "Symbolic links" in fails(validate_static, tmp_path)  # not the vaguer "missing index.html"


def test_reading_helper_refuses_symlinks(tmp_path, outside):
    link = tmp_path / "l"
    os.symlink(outside, link)
    with pytest.raises(OSError):
        _read_regular_file(link, 100)


# ---- unsupported types / unsafe names

@pytest.mark.parametrize("name", [
    "logo.png", "photo.jpg", "font.woff2", "favicon.ico", "NOTES.md", "Makefile", "app.js.map", "page.php",
])
def test_unsupported_file_types(tmp_path, name):
    tree(tmp_path, {"index.html": "x", name: "x"})
    msg = fails(validate_static, tmp_path)
    assert "Unsupported file types" in msg and name in msg and ".html" in msg


def test_long_lists_are_truncated(tmp_path):
    tree(tmp_path, {"index.html": "x", **{f"img{i}.png": "x" for i in range(12)}})
    assert "and 7 more" in fails(validate_static, tmp_path)


@pytest.mark.parametrize("name", [
    "my page.html", "résumé.html", ".env", ".htaccess", "-flag.txt", "back\\slash.txt", "semi;colon.txt",
    "a" * 101 + ".txt",
])
def test_unsafe_names(tmp_path, name):
    tree(tmp_path, {"index.html": "x", name: "x"})
    assert "Unsafe file or folder names" in fails(validate_static, tmp_path)


def test_hidden_directories_other_than_housekeeping_are_unsafe(tmp_path):
    tree(tmp_path, {"index.html": "x", ".well-known/security.txt": "x"})
    msg = fails(validate_static, tmp_path)
    assert "Unsafe" in msg and "security.txt" not in msg  # reported once, at the directory


def test_overlong_paths_are_unsafe(tmp_path):
    deep = "/".join(["d" * 30] * 8) + "/page.html"
    tree(tmp_path, {"index.html": "x", deep: "x"})
    assert "Unsafe" in fails(validate_static, tmp_path)


def test_control_characters_in_names_never_reach_the_message(tmp_path):
    tree(tmp_path, {"index.html": "x", "bad\nname\x1b[31m.txt": "x"})
    msg = fails(validate_static, tmp_path)
    assert "\n" not in msg and "\x1b" not in msg and msg.isprintable()
    assert "\\n" in msg  # shown escaped instead


# ---- content must be UTF-8 text

@pytest.mark.parametrize("data", [b"\xff\xfe\x00bad", b"caf\xe9", b"ok\x00nul"])
def test_non_text_content_is_rejected(tmp_path, data):
    tree(tmp_path, {"index.html": "x", "app.js": data})
    msg = fails(validate_static, tmp_path)
    assert "UTF-8" in msg and "app.js" in msg


# ---- ordering and hygiene of messages

def test_missing_index_is_reported_before_other_problems(tmp_path):
    tree(tmp_path, {"public/index.html": "x", "logo.png": "x", "bad name.txt": "x"})
    assert "No index.html" in fails(validate_static, tmp_path)


def test_unsupported_types_are_reported_before_size(tmp_path):
    tree(tmp_path, {"index.html": "x", "huge.png": b"x" * (STATIC_MAX_BYTES * 2)})
    assert "Unsupported file types" in fails(validate_static, tmp_path)  # actionable beats "too big"


@pytest.mark.parametrize("files", [
    {"about.html": "x"},                          # missing index.html
    {"index.html": "x", "a.png": "x"},            # unsupported type
    {"index.html": "x", "b c.txt": "x"},          # unsafe name
    {"index.html": b"\xff\xfe"},                  # not text
    {"index.html": "x", "nested/dir/x.png": "x"},  # problem in a subdirectory
])
def test_messages_never_contain_server_paths(tmp_path, files):
    msg = fails(validate_static, tree(tmp_path, files))
    assert str(tmp_path) not in msg and tmp_path.name not in msg


# ================================================================== FASTAPI

REQS = "fastapi\nuvicorn\n"


def py(root, source, requirements=REQS):
    files = {"main.py": source}
    if requirements is not None:
        files["requirements.txt"] = requirements
    return tree(root, files)


# The old demo app, verbatim: the real-world shape this must accept.
DEMO_MAIN = '''import os
from fastapi import FastAPI

app = FastAPI(title="demo-web-service")


@app.get("/")
def root():
    return {"hello": "from the Golden Path", "app": os.getenv("PLATFORM_APP_NAME")}
'''


@pytest.mark.parametrize("source", [
    DEMO_MAIN,
    "from fastapi import FastAPI\napp = FastAPI()\n",
    "import fastapi\napp = fastapi.FastAPI(title='x')\n",
    "from fastapi import FastAPI\napp: FastAPI = FastAPI()\n",
    "from fastapi import FastAPI\ndef create_app():\n    return FastAPI()\napp = create_app()\n",
    "from fastapi import FastAPI\napplication = FastAPI()\napp = application\n",
    "from fastapi import FastAPI\nif True:\n    app = FastAPI()\n",
    "from fastapi import FastAPI\ntry:\n    app = FastAPI()\nexcept Exception:\n    app = FastAPI()\n",
    "from fastapi import FastAPI\nclient, app = make_pair()\n",
    "from backend.api import app\n",  # re-export: cannot be verified, trusted
    "from backend.api import router as app\n",
    "# -*- coding: latin-1 -*-\nfrom fastapi import FastAPI\napp = FastAPI(title='caf\xe9')\n".encode("latin-1"),
])
def test_valid_fastapi_apps(tmp_path, source):
    assert validate_fastapi(py(tmp_path, source)) == FastAPIApp(target="main:app")


@pytest.mark.parametrize("source, expected", [
    ("from fastapi import FastAPI\napplication = FastAPI()\n", "does not define `app`"),
    ("from fastapi import FastAPI\napi = FastAPI()\n", "does not define `app`"),
    ("from fastapi import FastAPI\ndef make():\n    app = FastAPI()\n    return app\n", "does not define `app`"),
    ("from fastapi import FastAPI\nclass Holder:\n    app = FastAPI()\n", "does not define `app`"),
    ("from fastapi import FastAPI\napp: FastAPI\n", "does not define `app`"),  # annotation only binds nothing
    ("from backend import *\n", "does not define `app`"),  # star imports cannot be trusted
    ("", "does not define `app`"),
    ("from fastapi import FastAPI\ndef app():\n    return FastAPI()\n", "is a function"),
    ("class app:\n    pass\n", "is a class"),
    ("import app\n", "is a module"),
    ("import backend as app\n", "is a module"),
    ("from fastapi import FastAPI\napp = FastAPI()\ndef app():\n    pass\n", "is a function"),  # last binding wins
    ("app = None\n", "literal"),
    ("app = {}\n", "literal"),
    ("app = 'x'\n", "literal"),
    ("from fastapi import FastAPI\napp = [FastAPI()]\n", "literal"),
])
def test_invalid_app_contract(tmp_path, source, expected):
    assert expected in fails(validate_fastapi, py(tmp_path, source))


def test_flask_app_is_recognised_and_named(tmp_path):
    msg = fails(validate_fastapi, py(tmp_path, "from flask import Flask\napp = Flask(__name__)\n"))
    assert "never imports fastapi" in msg and "'Flask'" in msg


# ---- required files

def test_missing_main_py(tmp_path):
    msg = fails(validate_fastapi, tree(tmp_path, {"requirements.txt": REQS}))
    assert msg == "main.py was not found at the repository root."


def test_missing_requirements_txt(tmp_path):
    msg = fails(validate_fastapi, tree(tmp_path, {"main.py": DEMO_MAIN}))
    assert msg == "requirements.txt was not found at the repository root."


def test_both_missing_are_reported_together(tmp_path):
    (tmp_path / "app.py").write_text("print('hello')")  # the old "noncompliant" demo
    msg = fails(validate_fastapi, tmp_path)
    assert "main.py was not found" in msg and "requirements.txt was not found" in msg


def test_required_files_must_be_regular_files(tmp_path, outside):
    (tmp_path / "main.py").mkdir()
    os.symlink(outside, tmp_path / "requirements.txt")
    msg = fails(validate_fastapi, tmp_path)
    assert "main.py must be a regular file" in msg
    assert "requirements.txt must be a regular file, not a symbolic link" in msg
    assert "SERVER SECRET" not in msg


def test_symlinked_main_py_is_never_read(tmp_path, outside):
    outside.write_text("from fastapi import FastAPI\napp = FastAPI()\n")  # would be valid if followed!
    (tmp_path / "requirements.txt").write_text(REQS)
    os.symlink(outside, tmp_path / "main.py")
    assert "symbolic link" in fails(validate_fastapi, tmp_path)


def test_size_limits(tmp_path):
    msg = fails(validate_fastapi, py(tmp_path, b"#" * (1024 * 1024 + 1)))
    assert "main.py is larger" in msg
    (tmp_path / "main.py").write_text(DEMO_MAIN)
    (tmp_path / "requirements.txt").write_bytes(b"#" * (256 * 1024 + 1))
    assert "requirements.txt is larger" in fails(validate_fastapi, tmp_path)


def test_requirements_must_be_text(tmp_path):
    assert "not valid UTF-8" in fails(validate_fastapi, py(tmp_path, DEMO_MAIN, b"fastapi\n\xff\xfe"))


def test_requirements_contents_are_not_judged_in_phase_3(tmp_path):
    # Pip options, includes, indexes: what is acceptable depends on the Phase 5
    # Dockerfile template, so Phase 3 deliberately does not rule on them.
    validate_fastapi(py(tmp_path, DEMO_MAIN, "-r other.txt\n--index-url https://example.com/simple\n"))


# ---- parsing hostile or broken source

def test_syntax_error_reports_a_line_but_never_echoes_source(tmp_path):
    msg = fails(validate_fastapi, py(tmp_path, "import os\npassword = 'SECRET123' +\n"))
    assert "syntax error on line 2" in msg and "SECRET123" not in msg


@pytest.mark.parametrize("source", [
    "x = " + "(" * 50000 + ")" * 50000,
    "x = " + "[" * 100000,
    "x = 1\x00\n",
])
def test_parser_bombs_fail_cleanly(tmp_path, source):
    fails(validate_fastapi, py(tmp_path, source))  # a violation, not a crash or a hang


def test_the_repository_code_is_never_executed_or_imported(tmp_path):
    marker = tmp_path / "PWNED"
    py(tmp_path, f'''
import os
open({str(marker)!r}, "w").write("executed")
os.system("touch {marker}.sys")
raise SystemExit("import-time side effect")
from fastapi import FastAPI
app = FastAPI()
''')
    assert validate_fastapi(tmp_path) == FastAPIApp()  # passes on structure alone...
    assert not marker.exists() and not (tmp_path / "PWNED.sys").exists()  # ...without running anything
    assert "main" not in sys.modules


# ================================================================ dispatcher

def test_validate_dispatches_by_golden_path(tmp_path):
    site = tree(tmp_path / "site", {"index.html": "x"})
    api = tree(tmp_path / "api", {"main.py": DEMO_MAIN, "requirements.txt": REQS})
    assert isinstance(validate(GoldenPath.STATIC, site), StaticSite)
    assert isinstance(validate(GoldenPath.FASTAPI, api), FastAPIApp)
    # Each Golden Path judges by its own rules: a FastAPI repo is not a static site.
    with pytest.raises(PipelineError):
        validate(GoldenPath.STATIC, api)
    with pytest.raises(ValueError):
        validate("node", site)
