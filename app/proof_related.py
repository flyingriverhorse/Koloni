"""Kanıtlı bitiş S6 (plan decision 10): the tests RELATED to a turn's changed files, run first at
its end while the user waits - the whole suite then goes on in the background, as a pull request's
CI does. Read from the test command's own words, where its runner can name them: pytest - the
changed test files and the ones named for a changed module; vitest - `vitest related`; jest -
`--findRelatedTests`; go - the changed packages; cargo - the changed crates; dotnet - the one test
project of the change. Elsewhere, or for a change it cannot place (a config file, `conftest.py`,
another language's file), none: the whole suite alone. No model; nothing is run here."""

import json
import os
import re
import tomllib
from pathlib import Path, PurePosixPath

from app.proof import NO_TESTS, TestRun, kind_of

# A file name put on the command line as it is - nothing for sh or PowerShell to read otherwise.
# (A changed file's name is an agent's word: one named otherwise gives no narrower run.)
SAFE = re.compile(r"\w[\w./-]*")
MOST = 40  # files on one command line at most
# More than one command, a redirection, an expansion: what is added would land elsewhere.
COMPOUND = re.compile(r"[;&|<>`$(){}\"']")
UNWALKED = {"node_modules", "venv", "__pycache__", "target", "dist", "build", "bin", "obj"}
JS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte"}
# The runners' options that take the next word as their value (else a bare word names tests).
PYTEST_VALUES = {"-k", "-m", "-n", "-p", "-c", "-o", "-W", "-r", "--tb", "--maxfail",
                 "--rootdir", "--import-mode", "--durations", "--timeout", "--dist",
                 "--basetemp", "--confcutdir", "--log-level"}
VITEST_VALUES = {"--config", "-c", "--project", "--root", "-r", "--dir", "--environment",
                 "--pool", "--reporter"}
JEST_VALUES = {"--config", "-c", "--selectProjects", "--maxWorkers", "-w"}
WATCHING = {"--watch", "--watchAll"}


def related(run: TestRun, paths: list[str], root: Path) -> TestRun | None:
    """`run` narrowed to the tests related to `paths` (the turn's changed files in the project,
    project-relative POSIX), in `root` (where the work is); None: no narrower run is known."""
    if COMPOUND.search(run.command):
        return None
    top = "" if run.cwd == "." else f"{run.cwd.rstrip('/')}/"
    mine = [path[len(top):] for path in paths
            if path.startswith(top) and kind_of(path) not in NO_TESTS]
    if not mine or len(mine) > MOST:
        return None
    words, cwd = run.command.split(), root / run.cwd
    for reader in (_pytest, _js, _go, _cargo, _dotnet):
        said = reader(words, mine, cwd)
        if said is not None:
            return None if said == words else TestRun(" ".join(said), run.cwd, run.yours)
    return None


def _named(word: str) -> str:
    return PurePosixPath(word.replace("\\", "/")).name.casefold().removesuffix(".exe")


def _runner(words: list[str], *names: str) -> int | None:
    return next((at for at, word in enumerate(words) if _named(word) in names), None)


def _options_only(tail: list[str], values: set[str]) -> bool:
    """Whether `tail` is options only - each that takes a value with it: no test named."""
    value = False
    for word in tail:
        if not value and not word.startswith("-"):
            return False
        value = not value and word in values
    return not value


def _files(paths: list[str], cwd: Path) -> list[str] | None:
    """The paths that are files in `cwd` now, sorted; None where one could not go on a command
    line as it is, or where there are too many."""
    found = sorted({path for path in paths if (cwd / path).is_file()})
    return found if len(found) <= MOST and all(SAFE.fullmatch(one) for one in found) else None


def _walk(cwd: Path, wanted) -> list[str]:
    """The files under `cwd` whose name `wanted` takes - not in dependencies, builds or a dot
    folder - as POSIX paths from it.
    shortcut: the whole tree is walked each time; keep the names if a huge one is seen slow."""
    found = []
    for at, folders, names in os.walk(cwd):
        folders[:] = [one for one in folders if one not in UNWALKED and not one.startswith(".")]
        found += [Path(at, name).relative_to(cwd).as_posix() for name in names if wanted(name)]
    return found


def _pytest(words: list[str], paths: list[str], cwd: Path) -> list[str] | None:
    """The changed test files, and the test files named for a changed module (`test_x.py`,
    `x_test.py`) anywhere in the part. Not for `conftest.py`, nor any change but Python's."""
    at = _runner(words, "pytest", "py.test")
    if at is None or not _options_only(words[at + 1:], PYTEST_VALUES):
        return None
    names = [PurePosixPath(path).name for path in paths]
    if any(not name.endswith(".py") or name == "conftest.py" for name in names):
        return None
    tests = {name for name in names if name.startswith("test_") or name.endswith("_test.py")}
    stems = {name[:-3] for name in names if name not in tests and name != "__init__.py"}
    wanted = {one for stem in stems for one in (f"test_{stem}.py", f"{stem}_test.py")}
    found = _files([path for path in paths if PurePosixPath(path).name in tests]
                   + (_walk(cwd, wanted.__contains__) if wanted else []), cwd)
    return [*words, *found] if found else None


def _js(words: list[str], paths: list[str], cwd: Path) -> list[str] | None:
    """vitest's `related`, jest's `--findRelatedTests`, of the changed sources - named in the
    command, or `npm test`'s script. shortcut: jest is not measured on this machine (vitest
    5.0.3 is, 22 Nov: `related --run` ends, no watch); pnpm / yarn test give none - add theirs
    when met."""
    if any(PurePosixPath(path).suffix not in JS for path in paths):
        return None
    files = _files(paths, cwd)
    if not files:
        return None
    if words in (["npm", "test"], ["npm", "t"], ["npm", "run", "test"]):
        return _npm_test(words, files, cwd)
    at = _runner(words, "vitest", "jest")
    if at is None:
        return None
    return _vitest(words[:at + 1], words[at + 1:], files) if _named(words[at]) == "vitest" else (
        _jest(words, files))


def _vitest(launcher: list[str], tail: list[str], files: list[str]) -> list[str] | None:
    tail = [word for word in tail if word not in ("run", "--run")]
    if not _options_only(tail, VITEST_VALUES):
        return None
    return [*launcher, "related", *tail, "--run", "--passWithNoTests", *files]


def _jest(words: list[str], files: list[str]) -> list[str] | None:
    at = _runner(words, "jest") or 0
    if WATCHING & set(words) or not _options_only(words[at + 1:], JEST_VALUES):
        return None
    return [*words, "--passWithNoTests", "--findRelatedTests", *files]


def _npm_test(words: list[str], files: list[str], cwd: Path) -> list[str] | None:
    """`npm test` whose script is vitest or jest alone. vitest through `npx --no` - only where
    the project's own vitest is installed (the one its script runs; `--no`: never an install);
    jest through the script itself."""
    try:
        script = json.loads((cwd / "package.json").read_text(encoding="utf-8"))["scripts"]["test"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    said = script.split() if isinstance(script, str) and not COMPOUND.search(script) else []
    if said and said[0] == "vitest":
        # (as npx finds it: in a node_modules/.bin here or above - a workspace's root)
        own = any(next((at / "node_modules" / ".bin").glob("vitest*"), None)
                  for at in (cwd, *cwd.parents))
        return _vitest(["npx", "--no", "vitest"], said[1:], files) if own else None
    if said and said[0] == "jest" and _jest(said, files) is not None:
        return [*words, "--", "--passWithNoTests", "--findRelatedTests", *files]
    return None


def _go(words: list[str], paths: list[str], cwd: Path) -> list[str] | None:
    """`go test ./...` with plain flags: the packages of the changed `.go` files that still
    have some. shortcut: not measured here (no go on this machine); a flag with its value apart
    (`-run X`) gives none."""
    tail = words[2:]
    if words[:2] != ["go", "test"] or "./..." not in tail or any(
            not path.endswith(".go") for path in paths):
        return None
    flags = [word for word in tail if word != "./..."]
    if not all(word.startswith("-") for word in flags):
        return None
    folders = sorted({PurePosixPath(path).parent.as_posix() for path in paths})
    packages = ["." if one == "." else f"./{one}" for one in folders
                if next((cwd / one).glob("*.go"), None) is not None
                and (one == "." or SAFE.fullmatch(one))]
    return ["go", "test", *flags, *packages] if packages else None


def _cargo(words: list[str], paths: list[str], cwd: Path) -> list[str] | None:
    """`cargo test` in a workspace: `-p` each changed crate. A crate of one gives none: the
    whole of it is the suite. shortcut: not measured here (no cargo on this machine)."""
    tail = words[2:]
    if words[:2] != ["cargo", "test"] or not all(word.startswith("-") for word in tail) or {
            "-p", "--package", "--workspace", "--all", "--manifest-path"} & set(tail):
        return None
    names = set()
    for path in paths:
        name = _crate(cwd, PurePosixPath(path).parent) if path.endswith(".rs") else None
        if name is None:
            return None
        names.add(name)
    return ["cargo", "test", *(part for name in sorted(names) for part in ("-p", name)), *tail]


def _crate(cwd: Path, folder: PurePosixPath) -> str | None:
    """The name of the crate `folder` is in, below `cwd`; None: none, or the one crate there is."""
    for at in (folder, *folder.parents):
        try:
            found = tomllib.loads((cwd / at / "Cargo.toml").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = found.get("package", {}).get("name")
        alone = at == PurePosixPath(".") and "workspace" not in found
        return name if isinstance(name, str) and SAFE.fullmatch(name) and not alone else None
    return None


def _dotnet(words: list[str], paths: list[str], cwd: Path) -> list[str] | None:
    """`dotnet test` of the whole: the one test project of the changed `.cs` files - their
    own, or the one that references theirs. shortcut: not measured here (no test project on this
    machine); a change two test projects share gives none."""
    tail = words[2:]
    if words[:2] != ["dotnet", "test"] or not all(word.startswith("-") for word in tail) or any(
            not path.endswith(".cs") for path in paths):
        return None
    projects = {_project_of(cwd, PurePosixPath(path).parent) for path in paths}
    if None in projects:
        return None
    tests = [found for found in _walk(cwd, lambda name: name.endswith(".csproj"))
             if _is_test(cwd / found)]
    wanted = {found for found in tests if found in projects or any(
        PurePosixPath(one).name in (cwd / found).read_text(encoding="utf-8", errors="replace")
        for one in projects if one is not None)}
    return ["dotnet", "test", *wanted, *tail] if len(wanted) == 1 and all(
        SAFE.fullmatch(one) for one in wanted) else None


def _project_of(cwd: Path, folder: PurePosixPath) -> str | None:
    for at in (folder, *folder.parents):
        found = sorted((cwd / at).glob("*.csproj"))
        if found:
            return (at / found[0].name).as_posix()
    return None


def _is_test(csproj: Path) -> bool:
    try:
        text = csproj.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "Microsoft.NET.Test.Sdk" in text or "<IsTestProject>true" in text
