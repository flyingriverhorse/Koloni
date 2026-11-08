"""Skills for roles (slice 45): a folder in the shape Claude Code reads - a SKILL.md with
`name` and `description` up top and the instructions below, and files beside it - read
from a folder of this machine or listed from GitHub (`app.skill_github`), then kept whole in
KOLONİ's own store, which no agent writes (`app.workspace.never`)."""

import hashlib
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import injection, package_look
from app.db.models import Skill, new_id
from app.roles import BROWSER, READ, WEB, WRITE
from app.workspace import SKIP_DIRS, WorkspaceError, opened

MAX_FILES = 200
MAX_BYTES = 5 * 1024 * 1024
MAX_SKILL_MD = 256 * 1024
# An upload's base64 (`app.skill_upload`): 4 characters for 3 bytes, with room for padding
# and a .zip's own headers.
MAX_ENCODED = (MAX_BYTES + 64 * 1024) * 4 // 3
# A .zip's own bytes may be more: its .git, node_modules and __MACOSX/ are left out unread,
# and only what is kept counts to MAX_BYTES (by its headers, before it is read).
# shortcut: 25 MiB of .zip at most, held in memory while it is read; raise it if a skill's
# .zip with its .git is seen to be larger.
MAX_ZIP_ENCODED = (25 * 1024 * 1024 + 64 * 1024) * 4 // 3
# How much of each script the user is shown before saying yes to it.
MAX_SHOWN = 16 * 1024
SHOWN_CUT = "\n[cut short here: the script is longer]"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# A script is run by its path, in a shell: no part of it may be anything a shell reads.
SAFE_PART = re.compile(r"[A-Za-z0-9 _.-]+")
LICENSES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
NOT_A_SKILL = (
    "this is not a skill: a folder with a SKILL.md that names it (a `name:` line up top of "
    "letters, digits, '.', '_' and '-')")
# shortcut: secrets are known by their name only (a key file, .env, a credentials file);
# widen the lists when a skill brings another kind.
SECRET_FILES = re.compile(
    r"\.env(\..*)?|.*\.env|\.envrc|[._]netrc|\.git-credentials|\.pgpass|\.my\.cnf|\.htpasswd"
    r"|auth\.json|\.npmrc|\.pypirc|\.yarnrc\.yml|token.*|.*\.tfstate(\..*)?|kubeconfig"
    r"|application_default_credentials\.json|service-account.*\.json|\.?credentials(\..*)?"
    r"|secrets?(\..*)?|id_(rsa|dsa|ecdsa|ed25519)(\..*)?"
    r"|.*\.(pem|key|p12|pfx|jks|keystore|ppk|kdbx|asc|gpg|keytab)",
    re.IGNORECASE,
)
SECRET_DIRS = frozenset({
    ".ssh", ".aws", ".gnupg", ".docker", ".kube", "kubeconfig", ".azure", "gcloud",
    ".terraform.d", ".config"})
# What a script is run with, by its ending; a file with none of these is not a script.
# shortcut: a .ps1 runs only where the execution policy lets it, and a .sh needs a bash on
# the PATH (Git Bash's, or WSL's); say so on the card when users trip over it.
RUNNERS = {
    ".py": "python -B", ".js": "node", ".mjs": "node", ".cjs": "node", ".sh": "bash",
    ".ps1": "powershell -NoProfile -File",
}
# Slice 92's card: files that run as programs though KOLONİ does not run them as a skill's
# scripts (by their ending, a #! line, or a Windows or ELF program's header), so an agent's
# command would. shortcut: package.json scripts, a Makefile and an archive's insides are not
# looked into; name them on the card when a skill is seen to bring one.
PROGRAMS = frozenset({
    ".bat", ".cmd", ".exe", ".com", ".vbs", ".vbe", ".jse", ".wsf", ".hta", ".lnk", ".jar",
    ".psm1", ".rb", ".pl", ".php", ".bash", ".zsh", ".pyw", ".ts", ".mts"})
HEADERS = (b"#!", b"MZ", b"\x7fELF")
# Measured on Claude Code 2.1.311 (27 Oct 2026): a skill's !`command` line runs as the skill
# loads, past KOLONİ's hook and can_use_tool (`model_native.claude_plugin` leaves it out).
RUNS_AS_IT_LOADS = "!`"
# shortcut: a SKILL.md's commands are known by its fenced shell blocks only; one it tells
# in plain words ("run npm test") is not counted, so the card never says "none".
SHELL_BLOCK = re.compile(
    r"^\s*```\s*(?:bash|sh|shell|zsh|console|powershell|pwsh|ps1|cmd|bat)\b", re.M | re.I)
# One tool of an `allowed-tools` line, with its rule in brackets if it has one.
TOOL_WORD = re.compile(r"[^\s,\[\]'\"()]+(?:\([^)]*\))?")
# K-skill-uyum: the tools a SKILL.md names (Claude Code's, which the Agent Skills form uses),
# as the groups of KOLONİ's tools a role must have; an agent holding none of a group's lacks it.
GROUPS = {"shell": ("run_command",), "read files": READ, "write files": WRITE, "web": WEB,
          "browser": BROWSER}
NAMED = {
    "Bash": "shell", "BashOutput": "shell", "KillShell": "shell",
    "Read": "read files", "Glob": "read files", "Grep": "read files", "LS": "read files",
    "Write": "write files", "Edit": "write files", "MultiEdit": "write files",
    "NotebookEdit": "write files", "WebFetch": "web", "WebSearch": "web",
}


class SkillError(ValueError):
    """Why something cannot be taken as a skill; said to the user, or to the agent."""


def left_out_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.casefold() in SECRET_DIRS


def left_out_file(name: str) -> bool:
    return bool(SECRET_FILES.fullmatch(name))


def one_case(rel: str) -> str:
    """A path as NTFS compares it, or wider: upper case first ("ı" and "i" are both "I")."""
    return rel.upper().casefold()


def blob_id(data: bytes) -> str:
    """A file's id as git has it: what GitHub lists, and what is checked on download."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@dataclass(frozen=True)
class Found:
    """A skill as it was listed: every file it keeps with its git id and size, and the bytes
    read so far - all of them from a folder; from GitHub its SKILL.md, licence and scripts,
    the rest on the user's yes (`whole`)."""

    name: str
    description: str
    license: str | None
    text: str
    source: str
    listed: dict[str, tuple[str, int]]
    contents: dict[str, bytes]
    skipped: list[str]
    # Where the rest is downloaded from: owner, repository, commit, folder in it.
    repo: tuple[str, str, str, str] | None = None

    @property
    def files(self) -> list[str]:
        return list(self.listed)

    @property
    def size(self) -> int:
        return sum(size for _id, size in self.listed.values())

    @property
    def scripts(self) -> list[str]:
        return [rel for rel in self.listed if Path(rel).suffix.lower() in RUNNERS]

    @property
    def programs(self) -> list[str]:
        """Files besides its scripts that run as programs. shortcut: from GitHub only its
        SKILL.md, licence and scripts are read before the yes, so a #! line in another file
        is not seen there (`read_whole`); look again once the rest is downloaded if needed."""
        return [rel for rel in self.listed if rel not in self.scripts and (
            Path(rel).suffix.lower() in PROGRAMS
            or self.contents.get(rel, b"").startswith(HEADERS))]

    @property
    def digest(self) -> str:
        """One sum over what is kept: what was shown is what is added."""
        return hashlib.sha256("".join(
            f"{rel}\0{blob}\n" for rel, (blob, _size) in sorted(self.listed.items())
        ).encode()).hexdigest()

    def shown(self) -> dict:
        from app.mcp_client import visible  # (it builds on what imports this module)

        texts = {}
        for rel in self.scripts:
            text = self.contents[rel].decode("utf-8", "replace")
            texts[rel] = text if len(text) <= MAX_SHOWN else text[:MAX_SHOWN] + SHOWN_CUT
        return {
            "name": self.name, "description": self.description, "license": self.license,
            "text": self.text, "files": list(map(visible, self.files)), "size": self.size,
            "scripts": self.scripts,
            "script_texts": texts, "skipped": self.skipped, "sha256": self.digest,
            "source": self.source,
            # (Its scripts only: from GitHub nothing else is downloaded before the yes.)
            "seen": package_look.scan({rel: self.contents[rel] for rel in self.scripts}),
            # What of its SKILL.md reads like orders to keep from the user (93-A4): a skill
            # is instructions, so only these phrases, never that it gives any.
            "injection_rules": injection.scan(self.text),
            # Slice 92: what it says it may use and run, beside what it holds.
            "allowed_tools": declared(self.text), "programs": list(map(visible, self.programs)),
            "read_whole": len(self.contents) == len(self.listed),
            "runs_as_it_loads": [visible(line.strip()[:200]) for line in self.text.splitlines()
                                 if RUNS_AS_IT_LOADS in line][:20],
            "shell_blocks": len(SHELL_BLOCK.findall(self.text)),
        }


def front(text: str) -> tuple[dict[str, str], str]:
    """A SKILL.md's frontmatter as plain `key: value` lines, and the body below it. A value
    folded over the lines after it (`>`, `|`) is joined into one line."""
    lines = text.removeprefix(chr(0xFEFF)).splitlines()  # (a byte order mark first)
    if not lines or lines[0].strip() != "---":
        return {}, text
    found: dict[str, str] = {}
    last = None
    for at, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return found, "\n".join(lines[at + 1:]).strip()
        if line[:1].isspace() and last:
            found[last] = f"{found[last]} {line.strip()}".strip()
            continue
        key, sep, value = line.partition(":")
        if sep:
            last = key.strip()
            value = value.strip()
            # (a block scalar's marker: its value is on the lines below)
            found[last] = "" if value in (">", "|", ">-", "|-") else value.strip("\"'")
    return {}, text  # never closed: no frontmatter


def declared(text: str) -> list[str]:
    """The tools a SKILL.md's frontmatter says it may use (`allowed-tools`), as written: a
    line of them (`Read, Grep`, `[Read, Grep]`, or the Agent Skills form `Read Grep`) or a list
    below it (`- Read`); a rule in brackets stays with its tool (`Bash(git add:*)`). KOLONİ
    gives a skill no tool: Claude Code is given one without the line
    (`model_native.claude_plugin`)."""
    lines = text.removeprefix(chr(0xFEFF)).splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    found: list[str] | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if found is None:
            key, sep, value = line.partition(":")
            if sep and key.strip() == "allowed-tools":
                found = TOOL_WORD.findall(value)
        elif line.lstrip().startswith("- "):
            found.append(line.lstrip()[2:].strip().strip("\"'"))
        else:
            break
    return found or []


def needs(text: str) -> dict[str, list[str]]:
    """What a skill's `allowed-tools` asks of a role, by rule and never by guess: KOLONİ's
    groups of tools (`GROUPS`), MCP servers by name, and the names it does not know - which
    keep it from no role. Nothing at all for a skill with no such line."""
    found: dict[str, list[str]] = {"groups": [], "mcp": [], "unknown": []}
    for written in declared(text):
        name = written.split("(", 1)[0]
        if name.startswith("mcp__playwright") or name.lower().startswith("browser"):
            kind, one = "groups", "browser"
        elif name.startswith("mcp__") and (server := name.split("__")[1]):
            kind, one = "mcp", server
        elif name in NAMED:
            kind, one = "groups", NAMED[name]
        else:
            kind, one = "unknown", written
        if one not in found[kind]:
            found[kind].append(one)
    return found


def lacking(found: dict[str, list[str]], tools: set[str], mcp: set[str]) -> list[str]:
    """What of `needs` an agent with these tools and MCP servers does not have."""
    return [group for group in found["groups"] if not tools & set(GROUPS[group])] + [
        f"MCP server {server}" for server in found["mcp"] if server not in mcp]


def split(kept: list[Skill], tools: set[str], mcp: set[str],
          no_tool_calls: bool) -> tuple[list[Skill], dict[str, str]]:
    """A role's skills, those its agent is given and why each other one is left out: off on
    the Tools page, a model that makes no tool calls (the catalogue says so), or a group of
    tools it needs that the agent has not."""
    given, left = [], {}
    for skill in kept:
        if not skill.enabled:
            left[skill.name] = "off on the Tools page"
        elif no_tool_calls:
            left[skill.name] = "its model makes no tool calls"
        elif missing := lacking(needs(skill.text), tools, mcp):
            left[skill.name] = "no " + ", no ".join(missing)
        else:
            given.append(skill)
    return given, left


def first_line(data: bytes | None) -> str | None:
    lines = (data or b"").decode("utf-8", "replace").strip().splitlines()
    return lines[0].strip() if lines else None


def capped(listed: dict[str, tuple[str, int]]) -> None:
    """SkillError when a listing is more than a skill may hold."""
    if len(listed) > MAX_FILES:
        raise SkillError(f"a skill has at most {MAX_FILES} files")
    if sum(size for _id, size in listed.values()) > MAX_BYTES:
        raise SkillError(f"a skill holds at most {MAX_BYTES // (1024 * 1024)} MiB")


def made(
    source: str, listed: dict[str, tuple[str, int]], contents: dict[str, bytes],
    skipped: list[str], licence: str | None = None, repo: tuple | None = None,
) -> Found:
    """A skill from its listing and what is read of it (its SKILL.md, licence and scripts at
    least); SkillError says why it is none. `licence`: the first line of one from elsewhere
    (the repository's root), for a skill with none of its own."""
    capped(listed)
    if len({one_case(rel) for rel in listed}) != len(listed):
        raise SkillError("two of its files have the same name but for its case")
    folders = {"/".join(one_case(rel).split("/")[:at]) for rel in listed
               for at in range(1, rel.count("/") + 1)}
    if any(one_case(rel) in folders for rel in listed):  # (a .zip may hold both)
        raise SkillError("one of its files has the name of one of its folders")
    for rel in listed:
        if Path(rel).suffix.lower() in RUNNERS and not all(
                SAFE_PART.fullmatch(part) for part in rel.split("/")):
            raise SkillError(
                f"its script {rel!r} has a name a shell would read: a script's path is "
                "letters, digits, spaces, '_', '.' and '-' only")
    if "SKILL.md" not in contents:
        raise SkillError(NOT_A_SKILL)
    if len(contents["SKILL.md"]) > MAX_SKILL_MD:
        raise SkillError(f"its SKILL.md is larger than {MAX_SKILL_MD // 1024} KiB")
    try:
        text = contents["SKILL.md"].decode("utf-8")
    except UnicodeDecodeError:
        raise SkillError(NOT_A_SKILL) from None
    meta, _body = front(text)
    if not NAME.fullmatch(meta.get("name", "")):
        raise SkillError(NOT_A_SKILL)
    own = first_line(next((contents[file] for file in LICENSES if file in contents), None))
    return Found(
        meta["name"], meta.get("description", "")[:1024],
        own or licence or meta.get("license") or None, text, source, listed, contents,
        skipped, repo)


def _bytes(root: Path, path: Path, left: int) -> bytes | None:
    """A file's bytes, read on its own handle and judged there; None for one that is a link
    of any kind (a link, or a file with another name, may lead to a secret anywhere)."""
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or path.is_symlink():
        return None
    if not path.resolve().is_relative_to(root):
        return None
    with open(path, "rb") as file:
        status = os.fstat(file.fileno())
        if status.st_nlink != 1 or not stat.S_ISREG(status.st_mode):
            return None
        if status.st_size > left:
            raise SkillError(f"a skill holds at most {MAX_BYTES // (1024 * 1024)} MiB")
        data = file.read(left + 1)
    if len(data) > left:  # (it grew while it was read)
        raise SkillError(f"a skill holds at most {MAX_BYTES // (1024 * 1024)} MiB")
    return data


def read(folder: Path) -> Found:
    """Read a skill's folder whole - SkillError says why it is not one. Nothing is kept."""
    if not folder.is_dir():
        raise SkillError(NOT_A_SKILL)
    root = folder.resolve()
    contents: dict[str, bytes] = {}
    skipped: list[str] = []
    left = MAX_BYTES
    for top, dirs, names in os.walk(folder, followlinks=False):
        here = Path(top)
        for name in list(dirs):
            if left_out_dir(name) or (here / name).is_symlink() or (here / name).is_junction():
                dirs.remove(name)
                skipped.append(f"{(here / name).relative_to(folder).as_posix()}/")
        dirs.sort()
        for name in sorted(names):
            rel = (here / name).relative_to(folder).as_posix()
            data = None if left_out_file(name) else _bytes(root, here / name, left)
            if data is None:
                skipped.append(rel)
                continue
            if len(contents) == MAX_FILES:
                raise SkillError(f"a skill has at most {MAX_FILES} files")
            contents[rel] = data
            left -= len(data)
    listed = {rel: (blob_id(data), len(data)) for rel, data in contents.items()}
    return made(str(folder), listed, contents, skipped)


def local(raw: str) -> Path:
    """A folder named for a skill, as it really is: absolute, on this machine, and in no
    place KOLONİ never opens - for the user as for an agent (design 9)."""
    if not Path(raw).is_absolute():
        raise SkillError(f"{raw!r} is not a full path to a folder")
    try:
        return opened(raw)
    except WorkspaceError as exc:
        raise SkillError(str(exc)) from None


def take(folder: str | None, github: str | None) -> Found:
    """A skill's listing from a folder or a GitHub address - exactly one of them."""
    if (folder is None) == (github is None):
        raise SkillError("name either a folder or a GitHub address")
    if github is not None:
        from app import skill_github  # (it builds on this module)

        return skill_github.listing(github)
    try:
        return read(local(folder or ""))
    except OSError as exc:
        raise SkillError(f"the folder could not be read: {exc.strerror or exc}") from None


def whole(found: Found) -> Found:
    """A skill with every listed file read: from GitHub the rest is downloaded now."""
    if found.repo is None or len(found.contents) == len(found.listed):
        return found
    from app import skill_github

    return skill_github.rest(found)


def named(session: Session, name: str) -> Skill | None:
    return session.scalar(select(Skill).where(func.lower(Skill.name) == name.lower()))


def keep(found: Found, folder: Path) -> dict[str, str]:
    """Write a skill's files into its new place in the store; each file's sha256."""
    for rel, data in found.contents.items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "xb") as file:  # (two names of one file overwrite nothing)
            file.write(data)
    return {rel: hashlib.sha256(data).hexdigest() for rel, data in found.contents.items()}


def script_line(folder: str, script: str) -> str:
    """The command that runs a script of a kept skill: by its full path, in quotes. (Its
    name is safe in a shell: `made`.)"""
    path = Path(folder, script)
    return f'{RUNNERS[path.suffix.lower()]} "{path}"'


def unchanged(folder: str, hashes: dict[str, str]) -> bool:
    """Whether every file of a kept skill is still what was copied."""
    try:
        return all(
            hashlib.sha256(Path(folder, rel).read_bytes()).hexdigest() == sha
            for rel, sha in hashes.items())
    except OSError:
        return False


def add(session: Session, runtime_root: Path, found: Found, unasked: bool,
        enabled: bool = True) -> Skill:
    """Keep a skill whole (`whole`), in the store under `runtime_root`; SkillError when
    there is one of its name already (a role names its skills by name)."""
    taken = named(session, found.name)
    if taken is not None:
        raise SkillError(f"there is already a skill named {taken.name}")
    assert len(found.contents) == len(found.listed), "only a whole skill is kept"
    skill_id = new_id()
    folder = runtime_root / "skills" / skill_id
    try:
        hashes = keep(found, folder)
    except OSError as exc:  # (no half-written skill is left behind)
        shutil.rmtree(folder, ignore_errors=True)
        raise SkillError(f"it could not be written: {exc.strerror or exc}") from None
    skill = Skill(
        id=skill_id, name=found.name, description=found.description, source=found.source,
        license=found.license, text=found.text, folder=str(folder), files=found.files,
        size=found.size, scripts=found.scripts, hashes=hashes, scripts_run_unasked=unasked,
        enabled=enabled,
    )
    session.add(skill)
    session.commit()
    return skill
