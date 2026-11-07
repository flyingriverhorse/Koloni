"""Files the user adds to a chat message (slice 85b): kept by KOLONİ as the conversation's,
under `runtime/attachments/<conversation>/<id>` - never under the name they came with - and
gone with it. What a file is comes from its bytes, never its name: a name can only make
one a program. A program is kept by name and size alone; nothing here is ever run, and
nothing of it goes to a model."""

import html
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePath

from app.commands import OutputMask
from app.workspace import secret_in_project

MAX_BYTES = 25 * 2**20  # a file
# A larger video goes as its frames alone (slice 85c): the page sends its first bytes, to
# say it is a video, and its size; none of it is kept.
MAX_HEAD = 64 * 2**10
FRAMES_ONLY = f"frames only: larger than {MAX_BYTES // 2**20} MB, the video is not kept"
MAX_FILES = 10  # a message: a video's frames are not counted
MAX_FRAMES = 8  # of a video, taken by the page
MAX_NAME = 200
ISSUE = "content from a GitHub issue"  # what a GitHub issue added as a file is framed as
# What is read of a file's text (shortcut: the rest of a longer one is not read; page
# through it with read_attachment's `from` if that is ever not enough).
MAX_TEXT = 2_000_000
MAX_PAGES = 500  # a PDF's read
MAX_DOCUMENT = 50 * 2**20  # a .docx's word/document.xml, unpacked: a zip bomb is refused
KINDS = ("text", "image", "pdf", "docx", "video", "executable", "file")
# Named as a program or script runs: kept as one whatever its bytes are.
RUNS = frozenset({
    ".exe", ".dll", ".msi", ".com", ".scr", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe",
    ".wsf", ".sh", ".bash", ".zsh", ".command", ".app", ".apk", ".jar", ".lnk",
})
# A program's first bytes: Windows, Linux, macOS (and Java), a script with its interpreter.
PROGRAMS = (b"MZ", b"\x7fELF", b"\xfe\xed\xfa", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
            b"\xca\xfe\xba\xbe", b"#!")
IMAGES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
          (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"))
SHOWN = ("image", "video", "pdf")  # served as what they are; the rest only as a download
# HEIC and AVIF photos: an `ftyp` box as a video has, but no model or page here shows them.
PHOTOS = (b"heic", b"heix", b"heim", b"heis", b"hevc", b"mif1", b"msf1", b"avif", b"avis")
MAX_ENTRIES = 10_000  # a .docx's files


class Refused(ValueError):
    """Why a file is not taken, for the user."""


def clean_name(name: str) -> str:
    """The name shown for a file: its last part only, printable, not too long."""
    last = PurePath(name.replace("\\", "/")).name.strip()
    last = "".join(c for c in last if c.isprintable())[:MAX_NAME]
    if last in ("", ".", ".."):
        raise Refused("the file needs a name")
    return last


def secret_name(name: str) -> bool:
    """Whether an attached file is a secret by its name (`secret_in_project`) - also as a
    chat's second one is named: ".env (2)", "credentials (2).json" (`api.attachments`)."""
    return secret_in_project(name) or secret_in_project(
        re.sub(r"( \(\d+\))+(?=\.[^.]*$|$)", "", name))


def kind_of(data: bytes, name: str) -> tuple[str, str]:  # noqa: C901
    """What a file is, and its media type, by its first bytes."""
    if data.startswith(PROGRAMS) or Path(name).suffix.lower() in RUNS:
        return "executable", "application/octet-stream"
    for magic, mime in IMAGES:
        if data.startswith(magic):
            return "image", mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if data.startswith(b"%PDF-"):
        return "pdf", "application/pdf"
    if data[4:8] == b"ftyp" and data[8:12] in PHOTOS:
        return "file", f"image/{'avif' if data[8:11] == b'avi' else 'heic'}"  # (no model, no page)
    if data[4:8] == b"ftyp":
        return "video", "video/quicktime" if data[8:10] == b"qt" else "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", "video/webm"
    if data.startswith(b"PK\x03\x04") and _document(data) is not None:
        return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text", "text/plain; charset=utf-8"
    return "file", "application/octet-stream"


def image_size(data: bytes) -> tuple[int, int] | None:
    """An image's width and height from its header (PNG, GIF, JPEG, WebP); None where it does
    not say (28e: told to a model that takes no images)."""
    if data.startswith(b"\x89PNG") and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data.startswith(b"GIF8"):
        return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk, body = data[12:16], data[20:]
        if chunk == b"VP8X":
            return (int.from_bytes(body[4:7], "little") + 1,
                    int.from_bytes(body[7:10], "little") + 1)
        if chunk == b"VP8L" and len(body) >= 5:
            bits = int.from_bytes(body[1:5], "little")
            return (bits & 0x3FFF) + 1, (bits >> 14 & 0x3FFF) + 1
        if chunk == b"VP8 " and len(body) >= 10:
            return (int.from_bytes(body[6:8], "little") & 0x3FFF,
                    int.from_bytes(body[8:10], "little") & 0x3FFF)
        return None
    at = 2  # a JPEG: its segments, to the frame's (SOF0-SOF15, not DHT, JPG or DAC)
    while data.startswith(b"\xff\xd8") and at + 9 <= len(data) and data[at] == 0xFF:
        marker = data[at + 1]
        if marker == 0xFF or marker == 0x01 or 0xD0 <= marker <= 0xD8:
            at += 1 if marker == 0xFF else 2  # (a fill byte, or a marker with no length)
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return (int.from_bytes(data[at + 7:at + 9], "big"),
                    int.from_bytes(data[at + 5:at + 7], "big"))
        at += 2 + int.from_bytes(data[at + 2:at + 4], "big")
    return None


def _document(data: bytes) -> zipfile.ZipInfo | None:
    if data.count(b"PK\x01\x02") > MAX_ENTRIES:  # (each entry is read before any is looked at)
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        return None


def _docx_text(data: bytes) -> str:
    """A Word file's words, paragraph by paragraph: only as much of it as its header says,
    and never past MAX_DOCUMENT; read with no XML parser, so no entity is ever expanded."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > MAX_DOCUMENT:
            raise Refused("its text is bigger than KOLONİ reads")
        with archive.open(info) as member:
            xml = member.read(info.file_size + 1)
    if len(xml) != info.file_size:
        raise Refused("it is not the size it says")
    text = xml.decode("utf-8", "replace")
    if "<!DOCTYPE" in text:
        raise Refused("it declares its own entities")
    paragraphs = re.split(r"</w:p>", text)
    # ([^<>]*, not [^>]*: one that runs across "<" makes "<w:t <w:t <w:t ..." quadratic.)
    lines = ["".join(re.findall(r"<w:t(?:\s[^<>]*)?>([^<]*)</w:t>", p)) for p in paragraphs]
    return html.unescape("\n".join(line for line in lines if line.strip()))


# A PDF is read in a Python of its own (`-I`: nothing of the app's folder or environment):
# pypdf holds the interpreter while it decodes, and a hostile file could stop every chat. It
# decodes no stream past `most` bytes, stops past `seconds` or `chars` - saying so - and is
# killed past PDF_SECONDS; pypdf's own logging goes nowhere.
PDF_SECONDS = 20
PDF_LIMITS = {"most": 10_000_000, "seconds": 10.0, "chars": MAX_TEXT, "pages": MAX_PAGES}
PDF_SCRIPT = r"""
import io, json, logging, sys, time
logging.disable(logging.CRITICAL)
from pypdf import PdfReader, overwrite_configuration
limits = json.loads(sys.argv[1])
overwrite_configuration(**{name: limits["most"] for name in (
    "maximum_declared_stream_length", "array_based_stream_maximum_output_length",
    "lzw_maximum_output_length", "run_length_maximum_output_length",
    "zlib_maximum_output_length", "brotli_maximum_output_length", "image_maximum_buffer_size",
    "jbig2_maximum_output_length")})
reader = PdfReader(io.BytesIO(sys.stdin.buffer.read()))
told = {"locked": False, "count": 0, "pages": [], "stopped": None}
if reader.is_encrypted and not reader.decrypt(""):
    told["locked"] = True
else:
    told["count"] = len(reader.pages)
    began, done = time.monotonic(), 0
    for page in reader.pages[:limits["pages"]]:
        late = time.monotonic() - began > limits["seconds"]
        if told["pages"] and (done > limits["chars"] or late):
            told["stopped"] = "too large"
            break
        said = (page.extract_text() or "").strip()
        told["pages"].append(said)
        done += len(said)
sys.stdout.write(json.dumps(told))
"""


def _pdf_text(data: bytes, limits: dict | None = None) -> tuple[str, str]:
    """A PDF's text, page by page, and what to say of it."""
    try:
        ran = subprocess.run(
            [sys.executable, "-I", "-c", PDF_SCRIPT, json.dumps(limits or PDF_LIMITS)],
            input=data, capture_output=True, timeout=PDF_SECONDS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise Refused("it took too long") from None
    if ran.returncode != 0:
        raise Refused("it is not a PDF KOLONİ can read")
    told = json.loads(ran.stdout)
    if told["locked"]:
        return "", "locked with a password: no text taken out"
    count, pages = told["count"], told["pages"]
    empty = [at for at, said in enumerate(pages, 1) if not said]
    text = "\n\n".join(f"--- page {at} ---\n{said or f'no text on page {at}'}"
                       for at, said in enumerate(pages, 1))
    summary = f"{count} page{'s' * (count != 1)}, text taken out"
    if empty:
        shown = ", ".join(map(str, empty[:10])) + (" …" if len(empty) > 10 else "")
        summary += f"; no text on page{'s' * (len(empty) > 1)} {shown}"
    if told["stopped"]:
        summary += f"; the rest of this PDF was not read: {told['stopped']}"
    elif len(pages) < count:
        summary += f"; only its first {len(pages)} pages read"
    return text, summary


def read(data: bytes, name: str) -> tuple[str, str, str, str | None]:
    """A file as KOLONİ keeps it: its kind, media type, what to say of it, and its text
    (None where none goes to a model)."""
    kind, mime = kind_of(data, name)
    if kind == "executable":
        return kind, mime, "a program or script: only its name and size are kept", None
    if kind in ("text", "docx", "pdf") and secret_name(name):
        # (the secret rule of slice 88: what it holds is never sent unasked)
        return kind, mime, "a secret file (keys, passwords): what it holds is not sent", None
    if kind == "text":
        text = data.decode("utf-8")
        lines = text.count("\n") + (not text.endswith("\n"))
        return kind, mime, f"{lines} line{'s' * (lines != 1)}", text
    if kind == "image":
        return kind, mime, f"{mime.split('/')[1].upper()} image", None
    if kind == "video":
        return kind, mime, f"{mime.split('/')[1].upper().replace('QUICKTIME', 'MOV')} video", None
    try:
        if kind == "pdf":
            text, summary = _pdf_text(data)
            return kind, mime, summary, text
        if kind == "docx":
            text = _docx_text(data)
            words = len(text.split())
            return kind, mime, f"Word, {words} word{'s' * (words != 1)}, text taken out", text
    except Refused as exc:
        return kind, mime, f"its text could not be read: {exc}", None
    except Exception as exc:  # pypdf and zipfile raise many kinds for a broken file
        return kind, mime, f"its text could not be read ({type(exc).__name__})", None
    if mime.startswith("image/"):
        return kind, mime, "a photo (HEIC or AVIF) KOLONİ cannot show: kept as a file", None
    return kind, mime, "kept as a file: KOLONİ cannot read it", None


READ_LINES = 400  # what read_attachment gives at once
READ_CHARS = 60_000
LISTED = (
    "Files the user attached{to} (kept by KOLONİ, not in the project; {read}hand one to a "
    "sub-agent by its name in spawn_agent's or message_agent's attachments, which the "
    "receiver reads in its own work):"
)
# (Not said while read_attachment is switched off on the Tools page, slice 61.)
READ_HOW = "read one with read_attachment by its name; "
NOT_SEEN = ("your model is not known to see {what}: say so to the user, and hand it to a role "
            "whose model sees {what} (the guide of models says which)")
NOT_GIVEN = ("{cli} has no way KOLONİ can give it {what}, so your model was not shown it: say so "
             "to the user, and hand it to a role on Claude Code, Codex or an API whose model "
             "sees {what} (the guide of models says which)")
REFUSED = ("KOLONİ sent your model the {what} as it is and the model refused it; it was sent "
           "again {instead}. Say so to the user")
TOO_LARGE = ("KOLONİ sent your model the {what} as it is and the request was refused as too "
             "large; it was sent again as its name and summary. Say so to the user")
# The most of a picture (or video) sent to a model as it is: Anthropic's limit, the lowest.
MAX_SENT = 5 * 2**20
ONE_LINE = ("End your reply with one line for each file: its name, what you saw in it, and "
            "whom you handed it to - or that you kept it as context, or could not look at it.")
LINKS = ("Links in the message are not read by KOLONİ: an agent that needs one reads it with "
         "http_request, which asks the user as it always does.")


def size_text(size: int) -> str:
    return (f"{size} B" if size < 1024 else f"{size / 1024:.0f} KB" if size < 2**20
            else f"{size / 2**20:.1f} MB")


def line_of(name: str, kind: str, size: int, summary: str, shown: str) -> str:
    """One file as an agent is told of it: name, kind, size, what it holds, what to do."""
    what = "a program or script" if kind == "executable" else kind
    named = json.dumps(name, ensure_ascii=False)
    return f"- {named} ({what}, {size_text(size)}): {summary}. {shown}".rstrip()


def page(text: str, start: int = 1) -> str:
    """Part of a file's text for read_attachment: from line `start`, as much as fits, and
    where the rest is - a big file's first and last lines are what is seen first."""
    lines = text.splitlines()
    begin = max(1, start) - 1
    taken, size = [], 0
    for line in lines[begin:begin + READ_LINES]:
        size += len(line) + 1
        if size > READ_CHARS and taken:
            break
        taken.append(line)
    end = begin + len(taken)
    head = f"(lines {begin + 1}-{end} of {len(lines)})"
    rest = (f"\n(…{len(lines) - end} more lines: read again with start {end + 1})"
            if end < len(lines) else "")
    if start <= 1 and rest:
        rest += "\n(its last lines:)\n" + "\n".join(lines[-20:])
    return f"{head}\n" + "\n".join(taken) + rest


def folder(runtime_root: Path, cid: str) -> Path:
    return runtime_root / "attachments" / cid


def keep(runtime_root: Path, cid: str, aid: str, data: bytes | None, text: str | None) -> None:
    """The file (none for a program) and its text, beside each other."""
    where = folder(runtime_root, cid)
    where.mkdir(parents=True, exist_ok=True)
    if data is not None:
        (where / aid).write_bytes(data)
    if text is not None:
        # (newline="": as it came - on Windows "\r\n" would be written "\r\r\n" and read
        # back as two line ends: B-105)
        (where / f"{aid}.txt").write_text(text[:MAX_TEXT], encoding="utf-8", newline="")


def path_of(runtime_root: Path, cid: str, aid: str) -> Path | None:
    """An attached file KOLONİ keeps, by its id: only one in the conversation's own folder - a
    name with a drive (`D:x`) or a way up, as a restored record could hold, is none."""
    where = folder(runtime_root, cid)
    found = where / aid
    # (`C:x` joins as `x` on the folder's own drive: a name changed by its joining is none either)
    if found.parent != where or found.name != aid or aid == "..":
        return None
    return found if found.is_file() else None


def text_of(runtime_root: Path, cid: str, aid: str) -> str | None:
    """The text taken out of a file, with every secret KOLONİ knows - and any of a secret's
    shape - masked, as a command's output is; None where none was."""
    found = folder(runtime_root, cid) / f"{aid}.txt"
    if not found.is_file():
        return None
    return OutputMask(()).hide(found.read_text(encoding="utf-8"))


def forget(runtime_root: Path, cid: str, aid: str | None = None) -> None:
    """One file's (or with no id, the whole conversation's), only inside KOLONİ's store."""
    store = (runtime_root / "attachments").resolve()
    where = folder(runtime_root, cid).resolve()
    if not where.is_relative_to(store) or where == store:
        return
    if aid is None:
        shutil.rmtree(where, ignore_errors=True)
        return
    for one in (where / aid, where / f"{aid}.txt"):
        one.unlink(missing_ok=True)
