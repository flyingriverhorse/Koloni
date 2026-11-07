"""A skill uploaded from the app's page (slice 45b, design 10): a chosen folder's files or a
.zip, base64 in the request. Read in memory with a folder's rules (`app.skills.made`) and
GitHub's path check; nothing is kept before the user adds what the card showed."""

import base64
import binascii
import io
import lzma
import stat
import zipfile
import zlib

from app.schemas import SkillUpload
from app.skill_github import safe_path
from app.skills import (
    Found,
    SkillError,
    blob_id,
    capped,
    left_out_dir,
    left_out_file,
    made,
    one_case,
)


def _bytes(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)  # (else junk is dropped unsaid)
    except binascii.Error:
        raise SkillError("the upload could not be read: it is not base64") from None


def _size(payload: str) -> int:
    """A file's size, from its base64 before it is decoded."""
    return len(payload) * 3 // 4 - payload[-2:].count("=")


def _chosen[T](entries: list[tuple[str, T | None]]) -> tuple[str | None, dict[str, T], list[str]]:
    """Which of an upload's files are kept (by their path in the skill) and what is left out
    (a payload of None: a link); its top folder, the chosen folder's name first in every path,
    is not part of the skill. SkillError for a path no file here may have."""
    rels = [rel for rel, _payload in entries]
    for rel in rels:
        if not safe_path(rel):
            raise SkillError(f"{rel!r} is a path no file of this machine may have")
    if len({one_case(rel) for rel in rels}) != len(rels):
        raise SkillError("two of its files have the same name but for its case")
    tops = {rel.split("/")[0] for rel in rels}
    top = tops.pop() if len(tops) == 1 and all("/" in rel for rel in rels) else None
    if top and left_out_dir(top):
        raise SkillError(f"{top} is a folder whose files are never copied: choose the skill's own")
    kept: dict[str, T] = {}
    skipped: list[str] = []
    for rel, payload in entries:
        parts = rel.split("/")[1:] if top else rel.split("/")
        out = next((at for at, part in enumerate(parts[:-1]) if left_out_dir(part)), None)
        if out is not None:
            skipped.append("/".join(parts[:out + 1]) + "/")
        elif payload is None or left_out_file(parts[-1]):
            skipped.append("/".join(parts))
        else:
            kept["/".join(parts)] = payload
    return top, kept, list(dict.fromkeys(skipped))  # (a left-out folder is said once)


def _unzipped(data: str) -> tuple[str | None, dict[str, bytes], list[str]]:
    """A .zip's skill: only its kept files are read, each only as far as its header says, and
    refused when it holds another size than that (a zip bomb)."""
    try:
        with zipfile.ZipFile(io.BytesIO(_bytes(data))) as archive:
            # (__MACOSX/: what macOS's Finder puts beside the folder it zipped, not the skill)
            infos = [info for info in archive.infolist()
                     if not info.is_dir() and not info.filename.startswith("__MACOSX/")]
            top, kept, skipped = _chosen([
                (info.filename, None if stat.S_ISLNK(info.external_attr >> 16) else info)
                for info in infos])
            capped({rel: ("", info.file_size) for rel, info in kept.items()})  # (as it says)
            contents: dict[str, bytes] = {}
            for rel, info in kept.items():
                with archive.open(info) as member:
                    contents[rel] = member.read(info.file_size + 1)
                if len(contents[rel]) != info.file_size:
                    raise SkillError(f"{info.filename!r} in the .zip is not the size it says")
            return top, contents, skipped
    except SkillError:
        raise
    # (an encrypted member: RuntimeError; an unknown compression: NotImplementedError; a
    # broken bzip2 / lzma member: OSError / LZMAError; a broken header: ValueError - a name
    # that is not the UTF-8 it says among them)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError,
            OSError, lzma.LZMAError, ValueError) as exc:
        raise SkillError(f"the .zip could not be read: {exc}") from None


def listing(upload: SkillUpload) -> Found:
    """A skill from an upload; SkillError says why it is none."""
    if upload.zip is not None:
        top, contents, skipped = _unzipped(upload.zip)
    else:
        top, sent, skipped = _chosen([(file.path, file.data) for file in upload.files or []])
        capped({rel: ("", _size(payload)) for rel, payload in sent.items()})  # before decoding
        contents = {rel: _bytes(payload) for rel, payload in sent.items()}
    listed = {rel: (blob_id(data), len(data)) for rel, data in contents.items()}
    return made(f"uploaded ({top})" if top else "uploaded", listed, contents, skipped)
