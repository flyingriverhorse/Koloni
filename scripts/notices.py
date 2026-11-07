"""THIRD-PARTY-NOTICES.md from what KOLONİ ships or runs, read from the installed packages.

    .venv\\Scripts\\python.exe scripts\\notices.py [--out PATH]

Run with the backend .venv's Python, after `npm ci` in frontend/. Reads only files on disk:
pyproject.toml, frontend/package-lock.json, each package's own metadata and licence files.
"""

import argparse
import datetime
import json
import operator
import os
import platform
import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
LICENCE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE")
# Dev tools whose small runtime helpers the build puts into the bundle.
BUNDLED_DEV = {"vite", "rolldown"}
# Type-only, or replaced by a stub in vite.config.ts.
NOT_SHIPPED = {"csstype", "elkjs"}
# vite's LICENSE.md goes on with its Node build's own dependencies, not in the browser bundle.
TRIM = {"vite": "# Licenses of bundled dependencies"}
NOTES = {
    "dompurify": "MPL-2.0 **or** Apache-2.0: the package carries both texts (`LICENSE` is "
    "Apache-2.0, `LICENSE-MPL` is MPL-2.0), so a permissive option exists.",
    "khroma": "Its `package.json` names no licence; its licence file `license` is MIT.",
    "certifi": "MPL-2.0 is its only licence; the metadata and the licence file agree. MPL-2.0 "
    "is a file-level copyleft licence.",
    "d3-geo": "`package.json` says ISC; `LICENSE` is ISC and also MIT, for code from Charles "
    "Karney (`Copyright 2008-2012 Charles Karney`).",
    "d3-scale-chromatic": "`package.json` says ISC; `LICENSE` is ISC and also an "
    '"Apache-Style Software License for ColorBrewer software and ColorBrewer Color Schemes" '
    "under Apache-2.0.",
    "marked": "`package.json` says MIT; `LICENSE.md` is MIT and also BSD-3-Clause, for the "
    "original Markdown (`Copyright © 2004, John Gruber`).",
    "vite": "In the bundle: the module-preload helper. Its `LICENSE.md` is cut to the first "
    'section, "Vite core license"; the rest lists its Node build\'s own dependencies.',
    "rolldown": "In the bundle: the `rolldown-runtime-*.js` helper.",
}
MISMATCH = ("d3-geo", "d3-scale-chromatic", "khroma", "marked")
CHECK_NOTES = [
    "Not shipped: **elkjs**, `EPL-2.0`, is in mermaid's dependency tree. "
    "`frontend/vite.config.ts` replaces it, and mermaid's ELK layout module that alone imports "
    "it, with the stub `frontend/src/chat/no-elk.ts`; diagrams are laid out with dagre. It is "
    "not listed above.",
    "Not installed on Windows, so not listed when made there: on Linux and macOS "
    "`uvicorn[standard]` also installs **uvloop** (`sys_platform != 'win32'`). Run this script "
    "on those platforms before a release there.",
]
# OFL: derived fonts stay under it, and its text must go with the fonts.
COPYLEFT = re.compile(r"\b(A?GPL|LGPL|MPL|EPL|CDDL|EUPL|OSL|SSPL|CC-BY-SA|OFL)", re.I)
# "Copyright notice", "copyright holders"... are licence wording, not copyright lines; so is
# lodash's "Copyright and related rights for sample code are waived via CC0".
# Apache-2.0's appendix template "Copyright [yyyy] [name of copyright owner]" is not one either.
COPY_LINE = re.compile(
    r"^\s*(?:some contributions\s+)?copyright\b(?!\s+(?:notice|holders?|owners?|and\b|law|"
    r"licen|statement|protection)|\s*\[|\s*[,.:]?\s*$)", re.I)
REQ = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")
MARK = re.compile(r"""(\w+)\s*(==|!=|<=|>=|<|>|not in|in)\s*(['"])(.*?)\3""")
OPS = {"==": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le,
       ">": operator.gt, ">=": operator.ge, "in": lambda a, b: a in b,
       "not in": lambda a, b: a not in b}
ENV = {"python_version": ".".join(platform.python_version_tuple()[:2]),
       "python_full_version": platform.python_version(), "sys_platform": sys.platform,
       "platform_system": platform.system(), "platform_machine": platform.machine(),
       "platform_python_implementation": platform.python_implementation(),
       "implementation_name": sys.implementation.name, "os_name": os.name}
# requirements-dev.lock is resolved on Windows: a package only another system asks for (uvloop)
# is not installed there.
LOCKED_ON = {**ENV, "sys_platform": "win32", "platform_system": "Windows", "os_name": "nt"}


def version(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text))


def marker_true(marker: str, extras: set[str], env: dict = ENV) -> bool:
    # shortcut: only `variable op 'value'` forms, which is all the installed packages use;
    # a value-first marker raises NameError here. Use packaging.markers if one ever appears.
    def one(m: re.Match) -> str:
        var, op, value = m[1], m[2], m[4]
        if var == "extra":
            return str((value in extras) == (op == "=="))
        left = env.get(var, "")
        if "version" in var and "in" not in op:
            return str(OPS[op](version(left), version(value)))
        return str(OPS[op](left, value))

    return bool(eval(MARK.sub(one, marker), {"__builtins__": {}}))  # only True/False/and/or


def python_packages() -> tuple[list[dict], list[str]]:
    """Each package's entry, and the requirements skipped: asked for on this system alone,
    not installed (`LOCKED_ON`). Any other package missing raises."""
    try:
        metadata.distribution("koloni-agent")
    except metadata.PackageNotFoundError:
        sys.exit("notices.py: run it with the backend .venv's Python (koloni-agent not found)")
    roots = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    todo = [(r, set()) for r in roots["dependencies"]]
    extras_of: dict[str, set[str]] = {}
    dists, skipped = {}, []
    while todo:
        req, parent_extras = todo.pop()
        marker = req.split(";", 1)[1] if ";" in req else ""
        if marker and not marker_true(marker, parent_extras):
            continue
        m = REQ.match(req)
        assert m, req
        key = re.sub(r"[-_.]+", "-", m[1]).lower()
        extras = {e.strip() for e in (m[2] or "").split(",") if e.strip()}
        if key in extras_of and extras <= extras_of[key]:
            continue
        extras_of[key] = extras_of.get(key, set()) | extras
        try:
            dists[key] = dist = metadata.distribution(key)
        except metadata.PackageNotFoundError:
            if not marker or marker_true(marker, parent_extras, LOCKED_ON):
                raise
            skipped.append(req.strip())
            continue
        todo += [(r, extras_of[key]) for r in dist.requires or []]
    return ([python_entry(d) for d in sorted(dists.values(), key=lambda d: d.name.lower())],
            sorted(skipped))


def python_entry(dist) -> dict:
    meta = dist.metadata
    licence, source = meta.get("License-Expression"), "METADATA License-Expression"
    if not licence and meta.get("License") and "\n" not in meta["License"].strip():
        licence, source = meta["License"].strip(), "METADATA License"
    if not licence:
        found = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or []
                 if c.startswith("License :: ")]
        licence, source = " / ".join(found) or None, "METADATA classifier"
    files, sbom = [], []
    for f in dist.files or []:
        parts = f.parts
        if len(parts) < 2 or not parts[0].endswith(".dist-info"):
            continue
        if parts[1] == "licenses" or parts[1].upper().startswith(LICENCE_NAMES):
            files.append(("/".join(parts[1:]), Path(dist.locate_file(f)).read_text("utf-8-sig")))
        elif parts[1] == "sboms" and f.suffix == ".json":
            bom = json.loads(Path(dist.locate_file(f)).read_text("utf-8"))
            sbom.append(("/".join(parts[1:]), [
                (c["name"], c.get("version", ""), " / ".join(
                    x.get("expression") or x.get("license", {}).get("id")
                    or x.get("license", {}).get("name", "") for x in c.get("licenses", [])))
                for c in sorted(bom.get("components", []),
                                key=lambda c: (c["name"], c.get("version", "")))]))
    return {"name": meta["Name"], "version": dist.version, "licence": licence,
            "source": source, "files": sorted(files), "sbom": sbom}


def frontend_packages() -> list[dict]:
    lock = json.loads((FRONT / "package-lock.json").read_text("utf-8"))["packages"]
    out = []
    for path, info in lock.items():
        name = path.rsplit("node_modules/", 1)[-1]
        if (not path or (info.get("dev") and name not in BUNDLED_DEV)
                or name.startswith("@types/") or name in NOT_SHIPPED):
            continue
        folder = FRONT / path
        if not (folder / "package.json").exists():
            print(f"notices.py: {path} is in the lock but not installed; skipped", file=sys.stderr)
            continue
        pkg = json.loads((folder / "package.json").read_text("utf-8"))
        licence = pkg.get("license") or " OR ".join(
            x.get("type", "") for x in pkg.get("licenses", []) if isinstance(x, dict))
        if isinstance(licence, dict):
            licence = licence.get("type")
        files = []
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.name.upper().startswith(LICENCE_NAMES):
                text = f.read_text("utf-8-sig")
                label = f.name
                if name in TRIM and TRIM[name] in text:
                    text, label = text.split(TRIM[name])[0], f"{f.name} (its first section)"
                files.append((label, text))
        out.append({"name": pkg["name"], "version": pkg["version"], "licence": licence or None,
                    "source": "package.json", "files": files, "sbom": []})
    return sorted(out, key=lambda p: (p["name"], version(p["version"])))


def fence(text: str) -> str:
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def block(text: str) -> list[str]:
    f = fence(text)
    return [f"{f}text", text, f, ""]


def render(today: datetime.date, out: Path) -> None:  # noqa: C901
    (py, skipped), js = python_packages(), frontend_packages()
    fonts = [p for p in js if p["name"].startswith("@fontsource/")]
    js = [p for p in js if p not in fonts]
    brand = sorted(f.name for f in (FRONT / "public" / "brand").iterdir() if f.name != "README.md")
    assets = [
        {"name": "KOLONİ bee logo", "version": "", "licence": "the user's own work",
         "source": "frontend/public/brand/README.md", "files": [], "sbom": [],
         "note": f"`frontend/public/brand/` ({', '.join(brand)}) is KOLONİ's bee, the user's "
         "own work; `frontend/public/favicon.svg`, `apple-touch-icon.png` and `icon-512.png` "
         "are made from it."},
        {"name": "models.dev data trimmed copy", "version": "", "licence": "MIT",
         "source": "app/models_dev.LICENSE", "sbom": [],
         "files": [("app/models_dev.LICENSE",
                    (ROOT / "app" / "models_dev.LICENSE").read_text("utf-8-sig"))],
         "note": "`app/models_dev.json` is a trimmed copy of the models.dev data "
         "(github.com/anomalyco/models.dev) that KOLONİ ships."},
        {"name": "draw.io viewer (viewer-static.min.js)", "version": "32.6.9",
         "licence": "Apache-2.0", "source": "frontend/public/drawio/LICENSE", "sbom": [],
         "files": [("frontend/public/drawio/LICENSE",
                    (FRONT / "public" / "drawio" / "LICENSE").read_text("utf-8-sig"))],
         "note": "`frontend/public/drawio/viewer-static.min.js` is the draw.io static viewer "
         "(github.com/jgraph/drawio, v32.6.9), unchanged; KOLONİ's own `koloni.js` beside it "
         "keeps it from every address of its own. It draws `.drawio` files in the Workspace and "
         "for the agents' `diagram_image`."},
    ]
    every = js + fonts + py + assets
    found = {p["name"] for p in every}
    for key in NOTES:
        if key not in found:
            print(f"notices.py: note for {key}, which is not listed", file=sys.stderr)

    texts: dict[str, dict] = {}  # licence text without copyright lines -> number, users
    for p in every:
        p["refs"] = []
        for label, raw in p["files"]:
            lines = raw.replace("\r\n", "\n").replace("\r", "\n").splitlines()
            copy = [x.strip() for x in lines if COPY_LINE.match(x)]
            body = "\n".join(x.rstrip() for x in lines if not COPY_LINE.match(x))
            body = re.sub(r"\n{3,}", "\n\n", body).strip()
            # The same text wrapped at another width is the same text.
            t = texts.setdefault(" ".join(body.split()), {
                "n": len(texts) + 1, "body": body, "users": [], "licences": set()})
            t["users"].append(f"{p['name']} {p['version']}".strip())
            t["licences"].add(p["licence"] or "none declared")
            p["refs"].append((label, t["n"], copy))

    def section(title: str, items: list[dict], intro: str = "") -> list[str]:
        lines = [f"## {title}", ""] + ([intro, ""] if intro else [])
        for p in items:
            lines += [f"### {p['name']} {p['version']}".rstrip(), ""]
            lines.append(f"- Licence: `{p['licence']}` ({p['source']})" if p["licence"]
                         else f"- Licence: none ({p['source']})")
            if "Apache-2.0" in (p["licence"] or "") and not any(
                    Path(lb).name.upper().startswith("NOTICE") for lb, _ in p["files"]):
                lines.append("- Apache-2.0: no NOTICE file in the package.")
            for note in (NOTES.get(p["name"]), p.get("note")):
                if note:
                    lines.append(f"- {note}")
            if not p["files"] and p["source"] != "frontend/public/brand/README.md":
                lines.append("- No licence file in the package.")
            lines.append("")
            for label, n, copy in p["refs"]:
                lines += [f"Licence file `{label}`: text [L{n}](#l{n}).", ""]
                lines += block("\n".join(copy)) if copy else [
                    "_No copyright line in the licence file._", ""]
            for label, crates in p["sbom"]:
                lines += [f"Rust crates compiled into the wheel, from its CycloneDX SBOM "
                          f"`{label}` ({len(crates)}; name, version, licence; the SBOM may "
                          "also count build-only crates; their licence texts are not in the "
                          "wheel):", ""]
                lines += block("\n".join(f"{n} {v}  {lic}" for n, v, lic in crates))
        return lines

    def check_line(where: str, name: str, lic: str | None) -> str | None:
        if lic and not COPYLEFT.search(lic):
            return None
        either = lic and " OR " in lic and not all(COPYLEFT.search(x) for x in lic.split(" OR "))
        note = NOTES.get(name, "Permissive options exist." if either else "")
        return f"- {where}: **{name}**: `{lic or 'no licence declared'}`. {note}".rstrip()

    flagged = [check_line("Frontend (bundled)", p["name"], p["licence"]) for p in js + fonts]
    flagged += [check_line("Backend (Python)", p["name"], p["licence"]) for p in py]
    flagged += [check_line(f"Backend (Python), Rust crate in {p['name']}'s SBOM", f"{n} {v}", lic)
                for p in py for _, crates in p["sbom"] for n, v, lic in crates]

    doc = [
        "# Third-party notices", "",
        "This file lists the third-party software and assets that KOLONİ ships or runs for the "
        "user, with each one's licence, its copyright lines and the licence texts. KOLONİ's own "
        "licence, AGPL-3.0-or-later, is in [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).", "",
        f"Generated on {today.day} {today:%B %Y} by `scripts/notices.py` from the installed "
        f"versions: `frontend/node_modules` and the backend `.venv` ({platform.system()}, Python "
        f"{ENV['python_version']}). Licence texts and copyright lines are copied from the licence "
        "files in the installed packages; the declared licence is the `license` of the "
        "package's own `package.json`, or the `License-Expression` / `License` / classifier of "
        "its `METADATA`. To make it again, after a dependency changes and before a release: "
        "`.venv\\Scripts\\python.exe scripts\\notices.py` (or `.venv/bin/python "
        "scripts/notices.py`).", "",
        "- **Frontend (bundled)**: the `dependencies` of `frontend/package.json` and everything "
        "they bring in at run time, from `frontend/package-lock.json`. This is a superset of "
        "the bundle: a few Node-only parts are listed although the browser build does not use "
        "them (for example `@antfu/install-pkg`, `package-manager-detector`, `tinyexec`, "
        "`import-meta-resolve`, and d3-dsv's command-line `commander`, `iconv-lite`, "
        "`safer-buffer`, `rw`). Type-only packages (`@types/*`, `csstype`) and the dev tools "
        "are not listed, except `vite` and `rolldown`: the build puts their small runtime "
        "helpers (the module-preload helper, `rolldown-runtime-*.js`) into the bundle. "
        "`elkjs` is not shipped (see Check).",
        "- **Backend (Python)**: the `[project] dependencies` of `pyproject.toml` (with "
        "`uvicorn[standard]`) and what they require on this machine, from each package's "
        "`Requires-Dist`. The dev extra (`pytest`, `ruff`, `ty`, ...) is not listed.",
        "- A package that appears twice is installed in two versions; each is listed.",
        "- Each licence text is printed once, under **Licence texts**, without its copyright "
        "lines; each package names the text it uses and shows its own copyright lines.", "",
        f"Counts: Frontend (bundled) {len(js)}, Fonts {len(fonts)}, Backend (Python) {len(py)}, "
        f"Assets in the repository {len(assets)}.", "",
    ]
    doc += section("Frontend (bundled)", js)
    doc += section("Fonts", fonts, "IBM Plex Sans (400, 500, 600) and IBM Plex Mono (400, "
                   "500) are shipped as the "
                   "`.woff` / `.woff2` files of the `@fontsource` packages: "
                   "`frontend/src/main.tsx` imports their CSS and the build copies the fonts "
                   "into `dist/assets`. Nothing is loaded from a font service. The SIL Open "
                   "Font License asks that its text goes with the fonts.")
    doc += section("Backend (Python)", py)
    doc += section("Assets in the repository", assets)
    doc += ["## Licence texts", ""]
    for t in texts.values():
        users = sorted(set(t["users"]), key=str.lower)
        doc += [f"### L{t['n']}", "", f"Used by {len(users)} (declared: "
                f"{', '.join(sorted(t['licences']))}): {', '.join(users)}.", ""]
        doc += block(t["body"])
    doc += ["## Check", "", "Facts gathered for the choice of KOLONİ's own licence "
            "(AGPL-3.0-or-later, chosen on 6 November 2026).", "",
            "### Copyleft or unknown licence", ""]
    doc += [x for x in flagged if x] + [f"- {x}" for x in CHECK_NOTES]
    doc += [f"- Required on this system but not installed, so not listed: `{req}` "
            "(requirements-dev.lock is resolved on Windows)." for req in skipped] + [""]
    doc += ["### Declared licence differs from the licence file", ""]
    doc += [f"- **{n}**: {NOTES[n]}" for n in MISMATCH if n in found] + [""]
    out.write_text("\n".join(doc).rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"{out}: frontend {len(js)}, fonts {len(fonts)}, python {len(py)}, "
          f"assets {len(assets)}, licence texts {len(texts)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "THIRD-PARTY-NOTICES.md")
    render(datetime.date.today(), parser.parse_args().out)
