"""What an MCP server's package holds, seen without running it (slice 92, design A8), and
whether osv.dev lists it as malware (A6). The package npx or uvx is given is downloaded only
on the user's yes, from npm or PyPI as they list it, checked against their checksum, and
read in memory as text: never extracted, run or imported. Only what its text says outright
is told - what it may reach, the programs, addresses and variables it names, where it hides
what it does - and never that it is safe. The same reading is a skill's scripts'."""

import base64
import hashlib
import io
import json
import re
import stat
import tarfile
import time
import zipfile
import zlib
from pathlib import PurePosixPath
from urllib.parse import quote, urlsplit

import httpx2

HOSTS = frozenset({"registry.npmjs.org", "pypi.org", "files.pythonhosted.org", "api.osv.dev"})
OSV = "https://api.osv.dev/v1/query"
SECONDS = 30.0
MAX_META = 10 * 2**20
# shortcut: a package of more than 50 MB (100 MB unpacked) is not read at all; raise them if
# a server people use is seen to be larger.
MAX_ARCHIVE = 50 * 2**20
MAX_UNPACKED = 100 * 2**20
MAX_MEMBERS = 20_000
MAX_FILE = 4 * 2**20  # a bundled .js can be large
MAX_LIST = 40
CACHE_SECONDS = 3600.0

MAX_SECONDS = 120.0  # a whole download, however slowly it trickles in
NOT_A_PACKAGE = (
    "KOLONİ looks inside the package npx or uvx is given by its name (from npm or PyPI), "
    "with no option before it but -y or -q: in this command it cannot tell which package runs")
# What may stand before the package without changing which one runs.
QUIET = frozenset({"-y", "--yes", "-q", "--quiet"})
# (Upper case too: npm still serves its old names, JSONStream among them.)
NPM_NAME = re.compile(r"(@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]{0,213}")
PYPI_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")

JS = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx")
TYPES_ONLY = (".d.ts", ".d.mts", ".d.cts")
PY = (".py",)
SHELL = (".sh", ".bash", ".ps1", ".bat", ".cmd")
NATIVE = (".node", ".exe", ".dll", ".so", ".dylib", ".wasm", ".pyd")

# What a module lets a package reach, by the module's name (its first part for a package's).
REACHES = {
    "files": {"fs", "fs/promises", "fs-extra", "graceful-fs", "shutil", "pathlib", "tempfile"},
    "programs": {"child_process", "cross-spawn", "execa", "subprocess", "pty"},
    "network": {"http", "https", "http2", "net", "tls", "dgram", "dns", "undici", "axios",
                "node-fetch", "ws", "got", "fetch", "socket", "ssl", "urllib", "urllib3",
                "requests", "httpx", "aiohttp", "websockets", "ftplib", "smtplib"},
    "server": {"express", "fastify", "koa", "hono", "http.server", "socketserver", "flask",
               "fastapi", "uvicorn", "starlette"},
    "system": {"os", "ctypes", "cffi", "winreg"},
}
LIT = r"""(['"`])([^'"`\n]{1,200})\1"""
PYLIT = r"""[rbuf]{0,2}(['"])([^'"\n]{1,200})\1"""
JS_MODULE = [re.compile(p) for p in (
    rf"(?<![\w$.])require\s*\(\s*{LIT}\s*\)",
    r"""\bfrom\s*(['"])([^'"\n]{1,200})\1""",
    r"""(?<![\w$.])import\s*(?:\(\s*)?(['"])([^'"\n]{1,200})\1""",
)]
# (No pattern here may try a run of spaces from each place in it: a 4 MB file is read.)
PY_MODULE = [re.compile(p, re.MULTILINE) for p in (
    r"^[ \t]*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)",
    r"^[ \t]*from\s+([\w.]+)\s+import\b",
)]
JS_FETCH = re.compile(r"(?<![\w$.])fetch\s*\(")
JS_PROGRAM = re.compile(
    r"(?<![\w$])(?:spawn|spawnSync|exec|execSync|execFile|execFileSync|fork|execa|execaSync"
    rf"|execaCommand)\s*\(\s*{LIT}")
PY_PROGRAM = re.compile(
    r"\b(?:subprocess\.(?:run|Popen|call|check_call|check_output|getoutput|getstatusoutput)"
    r"|os\.(?:system|popen|exec[lv]p?e?|spawn[lv]p?e?)|asyncio\.create_subprocess_(?:exec|shell))"
    rf"\s*\(\s*(?:[\[(]\s*)?{PYLIT}")
ADDRESS = re.compile(r"""\b(?:https?|wss?)://[^\s'"`<>()\[\]{}\\,;]{1,300}""")
HOST = re.compile(r"[\w.-]+")
# Where code is sent to read, not what it calls: these hosts (and their subdomains), and a
# GitHub repository's own pages, are only counted.
DOCS = ("stackoverflow.com", "w3.org", "whatwg.org", "json-schema.org", "ietf.org",
        "rfc-editor.org", "tc39.es", "example.com", "example.org", "example.net", "mozilla.org",
        "developer.chrome.com", "web.dev", "nodejs.org", "github.io", "pptr.dev", "chromium.org",
        "googlesource.com", "crbug.com", "goo.gl", "goo.gle", "opensource.org", "spdx.org",
        "apache.org", "gnu.org", "creativecommons.org", "wikipedia.org",
        # B-135: Lighthouse's "learn more" links (chrome-devtools-mcp): documentation too.
        "amp.dev", "angular.io", "drupal.org", "gatsbyjs.com", "developers.google.com")
LOCAL = frozenset({"localhost", "127.0.0.1", "0.0.0.0"})
GITHUB_DOCS = frozenset({"issues", "blob", "tree", "pull", "pulls", "wiki", "discussions",
                         "commit", "compare"})
# A program's name, its path's last part: not a minified `a`, not a `${template}`.
PROGRAM_NAME = re.compile(r"[A-Za-z][\w.+-]+")
JS_ENV = re.compile(r"""process\.env(?:\.([A-Za-z_]\w*)|\[\s*(['"`])([A-Za-z_]\w*)\2\s*\])""")
JS_WHOLE_ENV = re.compile(
    r"""process\.env\b(?!\s*(?:\.[A-Za-z_]|\[\s*['"`][A-Za-z_]\w*['"`]\s*\]))""")
PY_ENV = re.compile(
    r"""(?:\benviron\[\s*|\b(?:environ\.get|getenv)\(\s*)[rbu]?(['"])([A-Za-z_]\w*)\1""")
PY_WHOLE_ENV = re.compile(r"""(?<!import )\benviron\b(?!\s*\[\s*[rbu]?['"]|\.get\(\s*[rbu]?['"])""")
# Where a package hides what it does: code made from text, and a module named while it runs.
JS_HIDDEN = [
    ("eval", re.compile(r"(?<![\w$.])eval\s*\(")),
    ("new Function", re.compile(r"(?<![\w$.])(?:new\s+)?Function\s*\(")),
    ("require of a name made while it runs",
     re.compile(r"""(?<![\w$.])require\s*\(\s*(?!['"][^'"\n]*['"]\s*\)|`[^`$]*`\s*\))""")),
    ("import of a name made while it runs",
     re.compile(r"""(?<![\w$.])import\s*\(\s*(?!['"][^'"\n]*['"]\s*\)|`[^`$]*`\s*\))""")),
]
PY_HIDDEN = [
    ("eval", re.compile(r"(?<![\w.])eval\s*\(")),
    ("exec", re.compile(r"(?<![\w.])exec\s*\(")),
    ("compile", re.compile(r"(?<![\w.])compile\s*\(")),
    ("__import__", re.compile(r"\b__import__\s*\(")),
    ("import_module of a name made while it runs",
     re.compile(r"""\bimport_module\s*\(\s*(?![rbu]?['"][^'"\n]*['"]\s*\))""")),
    ("marshal.loads", re.compile(r"\bmarshal\.loads\s*\(")),
]


class LookError(ValueError):
    """Why a package could not be looked into, or osv.dev not asked; said to the user."""


def size_text(size: int) -> str:
    return f"{size / 2**20:.1f} MB" if size >= 2**20 else f"{size / 1024:.0f} KB"


def _dict(value: object) -> dict:
    """A part of a registry's answer that should be an object, or an empty one."""
    return value if isinstance(value, dict) else {}


def _too_large() -> str:
    return f"it is larger than {size_text(MAX_UNPACKED)} unpacked: it is not read"


def _registry(registry: str) -> str:
    return "npm" if registry == "npm" else "PyPI"


def fetch(url: str, limit: int, body: dict | None = None) -> bytes:
    """GET (or POST `body` to) one address of npm's, PyPI's or osv.dev's, at most `limit`
    bytes: the one place this module reaches out (a test puts its own in its place). No
    account, no redirect, a timeout. An address a registry gave is checked here too."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if (parts.scheme != "https" or parts.hostname not in HOSTS or port not in (None, 443)
            or parts.username is not None or parts.password is not None):
        raise LookError(f"KOLONİ asks only npm, PyPI and osv.dev, not {parts.netloc}")
    deadline = time.monotonic() + MAX_SECONDS
    try:
        with (httpx2.Client(timeout=SECONDS, follow_redirects=False, trust_env=False,
                            headers={"User-Agent": "KOLONI"}) as client,
              client.stream("GET" if body is None else "POST", url, json=body) as answer):
            if answer.status_code != 200:
                raise LookError(f"{parts.hostname} answered {answer.status_code}")
            data = bytearray()
            for chunk in answer.iter_bytes():
                data += chunk
                if len(data) > limit:
                    raise LookError(
                        f"{parts.hostname} sent more than KOLONİ reads ({size_text(limit)})")
                if time.monotonic() > deadline:
                    raise LookError(f"{parts.hostname} took longer than {MAX_SECONDS:.0f} s")
    except httpx2.HTTPError as exc:
        raise LookError(f"{parts.hostname} could not be reached: {exc}") from None
    return bytes(data)


def _json(url: str) -> dict:
    data = fetch(url, MAX_META)
    try:
        doc = json.loads(data)
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        raise LookError(f"{urlsplit(url).hostname} did not answer as it does")
    return doc


def _program(part: str) -> str:
    return re.sub(r"\.(cmd|exe)$", "", re.split(r"[\\/]", part)[-1].lower())


def package_of(command: list[str]) -> tuple[str, str, str | None] | None:
    """The package npx or uvx is given (behind cmd /c too), as paste.ts packageOf finds it:
    its registry, name and version (None: the latest). None for any other command, and for
    one with an option before the package that may change which one runs (--registry,
    --index-url, --with, -p, --python …).
    shortcut: a registry named in the server's variables (npm_config_registry, UV_INDEX_URL)
    or in the user's .npmrc / uv settings is not seen: what is read is the public one's."""
    if len(command) > 2 and _program(command[0]) == "cmd" and command[1].lower() == "/c":
        command = command[2:]
    launcher = _program(command[0]) if command else ""
    spec = next((arg for arg in command[1:] if arg not in QUIET), None)
    if launcher not in ("npx", "uvx") or spec is None or spec.startswith("-"):
        return None
    if launcher == "npx":
        at = spec.find("@", 1)
        name, version = (spec[:at], spec[at + 1:]) if at > 0 else (spec, None)
        registry, valid = "npm", NPM_NAME
    else:
        name, sep, version = spec.partition("==")
        if not sep:
            name, sep, version = spec.partition("@")
        registry, valid = "pypi", PYPI_NAME
    version = version or None  # (partition gives "" for none)
    if not valid.fullmatch(name) or (version is not None and not VERSION.fullmatch(version)):
        return None
    if registry == "pypi":  # its name as PyPI knows it (PEP 503): asked with no redirect
        name = re.sub(r"[-_.]+", "-", name).lower()
    return registry, name, version or None


def _listed(registry: str, name: str, version: str | None) -> dict:
    """What npm or PyPI lists of one version of the package (the latest without one): its
    version, licence, size, file and checksum. Only its name and version are sent."""
    if registry == "npm":
        doc = _json(f"https://registry.npmjs.org/{quote(name, safe='@')}/"
                    f"{quote(version or 'latest', safe='')}")
        dist = _dict(doc.get("dist"))
        licence = doc.get("license")
        integrity = str(dist.get("integrity") or "")
        digest = (("sha512", integrity[7:]) if integrity.startswith("sha512-")
                  else ("sha1", str(dist.get("shasum") or "")))
        found = {"url": dist.get("tarball"), "size": dist.get("unpackedSize"), "unpacked": True,
                 "digest": digest, "license": _dict(licence).get("type", licence)}
    else:
        at = f"{quote(version, safe='')}/" if version else ""
        doc = _json(f"https://pypi.org/pypi/{quote(name, safe='')}/{at}json")
        info = _dict(doc.get("info"))
        urls = doc.get("urls")
        files = [_dict(f) for f in urls] if isinstance(urls, list) else []
        # A wheel installs without running anything of it; an sdist's setup.py runs.
        file = next((f for f in files if str(f.get("filename", "")).endswith("-none-any.whl")),
                    next((f for f in files if f.get("packagetype") == "bdist_wheel"),
                         next((f for f in files if f.get("packagetype") == "sdist"), None)))
        if file is None:
            raise LookError(f"PyPI lists no file of {name} to look into")
        found = {"url": file.get("url"), "size": file.get("size"), "unpacked": False,
                 "digest": ("sha256", str(_dict(file.get("digests")).get("sha256") or "")),
                 "license": info.get("license_expression") or info.get("license")}
        doc = info
    licence = _label((str(found["license"] or "").strip().splitlines() or [""])[0][:100]) or None
    if not isinstance(found["url"], str) or not found["digest"][1]:
        raise LookError(f"{_registry(registry)} lists no file and checksum of {name}")
    return {**found, "license": licence, "registry": registry, "name": name,
            "version": _label(str(doc.get("version") or version or "")[:64]),
            "size": found["size"] if isinstance(found["size"], int) else None}


def about(command: list[str]) -> dict:
    """The command's package as its registry lists it, before anything of it is downloaded."""
    package = package_of(command)
    if package is None:
        raise LookError(NOT_A_PACKAGE)
    listed = _listed(*package)
    return {key: listed[key]
            for key in ("registry", "name", "version", "size", "unpacked", "license")}


def look(command: list[str], version: str) -> dict:
    """The command's package at the version the user was shown, downloaded, checked against
    its registry's checksum and read in memory: what it was seen to do."""
    package = package_of(command)
    if package is None:
        raise LookError(NOT_A_PACKAGE)
    if not VERSION.fullmatch(version):
        raise LookError("not a version")
    registry, name, pinned = package
    # (pinned may be a tag - latest, next - that names another version tomorrow)
    listed = _listed(registry, name, pinned or version)
    if listed["version"] != version:
        raise LookError(f"{_registry(registry)} lists {name} {listed['version']} now, not the "
                        f"{version} shown: look again")
    data = fetch(listed["url"], MAX_ARCHIVE)
    # (npm's integrity is base64; its shasum and PyPI's sha256 are hex)
    algorithm, expected = listed["digest"]
    got = hashlib.new(algorithm, data)
    if expected not in (got.hexdigest(), base64.b64encode(got.digest()).decode()):
        raise LookError(
            f"what was downloaded is not what {_registry(registry)} lists for {name}: "
            "it is not read")
    filename = urlsplit(listed["url"]).path
    files, unread = members(data, filename)
    seen = scan(files)
    on_install, dependencies = _installs(registry, files, sdist=not filename.endswith(".whl"))
    return {**{key: listed[key] for key in ("registry", "name", "version", "license")},
            **seen, "size": len(data), "unread": unread + seen["unread"],
            "on_install": on_install, "dependencies": _capped(dependencies)}


def members(data: bytes, filename: str) -> tuple[dict[str, bytes], list[str]]:  # noqa: C901
    """The files of a package's archive (.tgz, .tar.gz, .whl, .zip) a reading needs, in
    memory: each name only a label, no link followed, nothing written. What was not read,
    in words."""
    files: dict[str, bytes] = {}
    large: list[str] = []
    held = 0  # the bytes read: never more than MAX_UNPACKED, whatever the headers say
    try:
        if filename.endswith((".whl", ".zip")):
            # (each entry is read before any is looked at)
            if data.count(b"PK\x01\x02") > MAX_MEMBERS:
                raise LookError(f"it holds more than {MAX_MEMBERS} files: it is not read")
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = [info for info in archive.infolist() if not info.is_dir()]
                if sum(info.file_size for info in infos) > MAX_UNPACKED:
                    raise LookError(_too_large())
                for info in infos:
                    if stat.S_ISLNK(info.external_attr >> 16):
                        continue
                    if not _wanted(info.filename):
                        files[info.filename] = b""  # (named, not read)
                    elif info.file_size > MAX_FILE:
                        large.append(info.filename)
                    else:
                        with archive.open(info) as member:
                            text = member.read(info.file_size + 1)
                        if len(text) != info.file_size:  # a zip bomb, or a broken one
                            raise LookError(
                                f"{_label(info.filename)} is not the size it says: it is not read")
                        files[info.filename] = text
                        held += len(text)
                        if held > MAX_UNPACKED:
                            raise LookError(_too_large())
        else:
            inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
            inflated = inflater.decompress(data, MAX_UNPACKED + 1)
            if len(inflated) > MAX_UNPACKED:
                raise LookError(_too_large())
            # (a second gzip stream after the first would hold files this reading never sees)
            if inflater.unused_data:
                raise LookError("it is more than one gzip stream: it is not read")
            with tarfile.open(fileobj=io.BytesIO(inflated), mode="r:") as archive:
                for count, member in enumerate(archive, 1):
                    if count > MAX_MEMBERS:
                        raise LookError(f"it holds more than {MAX_MEMBERS} files: it is not read")
                    if not member.isfile():  # (a link, a device, a folder)
                        continue
                    # (a sparse member's few bytes stand for as many as it says: not read)
                    if not _wanted(member.name) or member.issparse():
                        files[member.name] = b""  # (named, not read)
                    elif member.size > MAX_FILE:
                        large.append(member.name)
                    else:
                        opened = archive.extractfile(member)
                        files[member.name] = opened.read() if opened else b""
                        held += len(files[member.name])
                        if held > MAX_UNPACKED:
                            raise LookError(_too_large())
    except LookError:
        raise
    except (zipfile.BadZipFile, tarfile.TarError, zlib.error, EOFError, OSError, ValueError,
            RuntimeError, NotImplementedError) as exc:
        raise LookError(f"the package could not be read: {exc}") from None
    unread = [f"{len(large)} files larger than {size_text(MAX_FILE)}, not read: "
              + ", ".join(_capped([_label(name) for name in large]))] if large else []
    return files, unread


def _wanted(name: str) -> bool:
    """A file a reading reads: code, package.json, a wheel's or sdist's METADATA."""
    lower = name.lower()
    return ((lower.endswith(JS) and not lower.endswith(TYPES_ONLY)) or lower.endswith(PY)
            or PurePosixPath(lower).name in ("package.json", "metadata", "pkg-info"))


def _label(name: str) -> str:
    """A name from inside a package, as it may be shown: printable, not too long."""
    shown = "".join(c for c in name if c.isprintable())
    return shown if len(shown) <= 120 else "…" + shown[-119:]


def _capped(items: list[str]) -> list[str]:
    """What is shown of a list read from a package: each as _label has it, each once."""
    items = list(dict.fromkeys(map(_label, items)))
    if len(items) <= MAX_LIST:
        return items
    return [*items[:MAX_LIST], f"and {len(items) - MAX_LIST} more"]


def _module(name: str) -> str:
    """A module as REACHES knows it: node:fs is fs, a package's own path is the package."""
    name = name.removeprefix("node:")
    if name in ("fs/promises", "http.server"):
        return name
    parts = re.split(r"[/.]", name)
    return "/".join(parts[:2]) if name.startswith("@") else parts[0]


def scan(files: dict[str, bytes]) -> dict:  # noqa: C901
    """What the code among `files` names outright (path to bytes; anything else is only
    counted): what it may reach, the programs, addresses and variables it names, whether it
    reads the whole environment, and where it hides what it does."""
    reaches: dict[str, set[str]] = {}
    programs, addresses, env, hidden, shells, native = [], [], [], [], [], []
    whole_env, read = False, 0
    for path, data in files.items():
        lower = path.lower()
        if lower.endswith(SHELL):
            shells.append(_label(path))
        if lower.endswith(NATIVE):
            native.append(_label(path))
        is_js = lower.endswith(JS) and not lower.endswith(TYPES_ONLY)
        if not (is_js or lower.endswith(PY)) or not data:
            continue
        read += 1
        text = data.decode("utf-8", "replace")
        if is_js:
            modules = [m.group(2) for pattern in JS_MODULE for m in pattern.finditer(text)
                       if "${" not in m.group(2)]
            modules += ["fetch"] if JS_FETCH.search(text) else []
            program, names, whole, hides = JS_PROGRAM, JS_ENV, JS_WHOLE_ENV, JS_HIDDEN
        else:
            modules = [name.strip() for pattern in PY_MODULE for m in pattern.finditer(text)
                       for name in m.group(1).split(",")]
            program, names, whole, hides = PY_PROGRAM, PY_ENV, PY_WHOLE_ENV, PY_HIDDEN
        for module in map(_module, modules):
            for kind, known in REACHES.items():
                if module in known:
                    reaches.setdefault(kind, set()).add(module)
        for m in program.finditer(text):
            word = _label((m.group(2).split() or [""])[0])
            if PROGRAM_NAME.fullmatch(re.split(r"[\\/]", word)[-1]):
                programs.append(word)
        addresses += [m.group(0).rstrip(".") for m in ADDRESS.finditer(text)]
        env += [m.group(m.lastindex or 0) for m in names.finditer(text)]
        whole_env = whole_env or bool(whole.search(text))
        hidden += [f"{what} in {_label(path)}" for what, pattern in hides if pattern.search(text)]
    unread = []
    if native:
        unread.append("native code, which cannot be read as text: "
                      + ", ".join(_capped(native)))
    if shells:
        unread.append("the programs its shell scripts run (not listed): "
                      + ", ".join(_capped(shells)))
    return {"read": read, "reaches": {kind: sorted(found) for kind, found in reaches.items()},
            "programs": _capped(programs), "addresses": _addresses(addresses),
            "env": _capped(env), "whole_env": whole_env, "hidden": _capped(hidden),
            "unread": unread}


def _addresses(found: list[str]) -> list[str]:
    """The addresses code may call, whole, first; documentation links only counted."""
    local, calls, docs = [], [], 0
    for address in dict.fromkeys(found):
        try:
            parts = urlsplit(address)
        except ValueError:  # (a netloc that normalises to a / ? # or @)
            continue
        host = parts.hostname or ""
        # Broken text, or a template filled in while it runs (`https://${host}` reads `https://$`).
        if "\ufffd" in address or address.endswith("$") or not HOST.fullmatch(host):
            continue
        segments = parts.path.strip("/").split("/")
        if (any(host == doc or host.endswith("." + doc) for doc in DOCS)
                or (host == "github.com" and (len(segments) <= 2 or segments[2] in GITHUB_DOCS))):
            docs += 1
        else:  # (cut at its end, not as _label cuts: its host is what matters)
            shown = address if len(address) <= 120 else address[:119] + "…"
            (local if host in LOCAL else calls).append(shown)  # (local first: never cut off)
    return _capped(local + calls) + ([f"{docs} documentation link{'s' * (docs != 1)}"]
                                     if docs else [])


def _installs(registry: str, files: dict[str, bytes], sdist: bool) -> tuple[list[str], list[str]]:
    """What runs when the package is installed, and the packages it brings with it, as its
    package.json (npm) or METADATA (a wheel) says; for PyPI, whether it is built (`sdist`)."""
    if registry == "npm":
        top = min((path for path in files if PurePosixPath(path).name == "package.json"),
                  key=lambda path: path.count("/"), default=None)
        try:
            manifest = _dict(json.loads(files[top]) if top else {})
        except ValueError:
            manifest = {}
        scripts = _dict(manifest.get("scripts"))
        on_install = [_label(f"{hook}: {str(scripts[hook])[:200]}")
                      for hook in ("preinstall", "install", "postinstall") if hook in scripts]
        # Without its own install script, npm builds a binding.gyp beside package.json.
        gyp = top is not None and str(PurePosixPath(top).with_name("binding.gyp")) in files
        if gyp and not {"preinstall", "install"} & set(scripts):
            on_install.insert(0, "binding.gyp: npm runs node-gyp rebuild, which builds native code")
        dependencies = [name for key in ("dependencies", "optionalDependencies")
                        for name in _dict(manifest.get(key))]
        return on_install, dependencies
    on_install = ["a source package: it is built when it is installed, which runs its build "
                  "code (setup.py, or the build backend its pyproject.toml names)"] if sdist else []
    metadata = next((data for path, data in files.items()
                     if PurePosixPath(path).name.lower() in ("metadata", "pkg-info")), b"")
    dependencies = [re.split(r"[\s;<>=!~\[(]", line.split(":", 1)[1].strip())[0]
                    for line in metadata.decode("utf-8", "replace").splitlines()
                    if line.startswith("Requires-Dist:")]
    return on_install, [name for name in dependencies if name]


_checked: dict[tuple[str, str, str | None], tuple[float, list[str]]] = {}


def malware(registry: str, name: str, version: str | None) -> list[str]:
    """The ids of osv.dev's known-malware records (MAL-…) of the package: only its name, its
    registry and its version are sent. An answer is kept an hour; LookError when osv.dev
    cannot be asked.
    shortcut: osv.dev's first page of answers only; follow `next_page_token` if a package
    is seen with more records than one page holds."""
    key = (registry, name, version)
    kept = _checked.get(key)
    if kept is not None and time.monotonic() - kept[0] < CACHE_SECONDS:
        return kept[1]
    query: dict = {"package": {"name": name, "ecosystem": "npm" if registry == "npm" else "PyPI"}}
    if version:
        query["version"] = version
    data = fetch(OSV, MAX_META, query)
    try:
        vulns = json.loads(data).get("vulns") or []
        ids = sorted({str(v["id"]) for v in vulns if str(v.get("id", "")).startswith("MAL-")})
    except (ValueError, AttributeError, TypeError, KeyError):
        raise LookError("osv.dev did not answer as it does") from None
    _checked[key] = (time.monotonic(), ids)
    return ids
