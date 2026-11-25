"""Full auto's judge (0.1.9), its gate: at Full auto, before a command the list does not stop runs,
a small model is asked once whether it is risky (`app.risk_judge`) - `RiskJudgeMixin`."""

import re
from pathlib import Path

from sqlalchemy import func, literal_column, select

from app import ledger, proof, proof_style
from app.commands import _INTERPRETER, _SHELLS, _program, _words
from app.db.models import Conversation, FileChange, Run

# An option word of an interpreter's or a shell's after which the line holds its code itself
# (`python -c`, `-m`, `node -e`, `bash -c`, PowerShell's `-Command` / `-EncodedCommand` cut short
# as it takes them): no file of its own runs. ...and PowerShell's `-File`, which names the file.
_INLINE = re.compile(r"-(?:c|m.*|e|p|r|-eval|-print)|(?i:-co\w*|-en\w*|-ec)")
_FILE = re.compile(r"(?i)-f(?:i(?:le?)?)?")
# Their options that take a value: the word after one is no script.
_VALUED = frozenset(
    {"-X", "-W", "--require", "--import", "--loader", *("-executionpolicy", "-ep", "-ex")}
    | {"-windowstyle", "-version", "-workingdirectory", "-wd", "-configurationname"}
)


def _script(words: list[str]) -> str:
    """The file a line runs by its name: the script an interpreter or a shell is handed - its
    first word that is no option, or the value of PowerShell's `-File` -, "" where the line holds
    its code (`_INLINE`); else the program itself."""
    program = _program(words[0])
    if not (_INTERPRETER.fullmatch(program) or program in _SHELLS):
        return words[0]
    rest = iter(words[1:])
    for word in rest:
        if _INLINE.fullmatch(word):
            return ""
        if program in ("powershell", "pwsh") and _FILE.fullmatch(word):
            return next(rest, "")
        if word.startswith("-") or program == "cmd" and word.startswith("/"):
            if word in _VALUED or word.lower() in _VALUED:
                next(rest, None)
            continue
        return word
    return ""


def planted_program(factory, cid: str, root: Path, command: str, cwd: str) -> Path | None:
    """The file `command` (run in `cwd` of `root`: the project, or a copy of it) runs by its name
    (`_script`: `node x.js`, `python -u x.py`, `./x.sh`, `bash x.sh`, `powershell -File x.ps1`,
    `x.cmd`) where an agent wrote it - its write on record, of any turn of the project's, as it
    still stands (`proof_style.still_written`): its full path. None: no such file, one out of
    `root`, or the user's own (none on record, or changed since). Blocking: off the event loop.
    shortcut: by the line's first file alone - one it imports, or a tool an agent changed but
    did not write, is not seen (the judge's known limits)."""
    words = [word.strip("'\"") for word in _words(command)]
    words = words[1:] if words[:1] in (["&"], ["."]) else words  # (PowerShell's call)
    name = _script(words) if words else ""
    if not name:
        return None
    home = root.resolve()
    try:
        path = (root / cwd / name).resolve()
        if not path.is_relative_to(home) or not path.is_file():
            return None
    except (OSError, ValueError):
        return None
    rel = path.relative_to(home).as_posix()
    with factory() as session:
        found = session.execute(
            select(FileChange.path, FileChange.after_sha)
            .join(Run, Run.id == FileChange.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(
                Conversation.project_id
                == select(Conversation.project_id).where(Conversation.id == cid).scalar_subquery(),
                FileChange.status.in_((*ledger.KEPT, proof.MERGED)),
                func.lower(FileChange.path) == rel.lower(),
            )
            .order_by(FileChange.created_at, literal_column("file_changes.rowid"))
        ).all()
    newest = dict(found)  # (the last write of each spelling)
    return path if proof_style.still_written(root, newest.items()) else None
