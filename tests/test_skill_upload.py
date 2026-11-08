"""Slice 45b: what an uploaded .zip or file list may not slip past (beside the acceptance set)."""

import base64
import io
import os
import zipfile

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
SKILL_MD = b"---\nname: tidy\ndescription: Keep changes small.\n---\n\nWrite the least code.\n"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def zipped(*entries: tuple[zipfile.ZipInfo | str, bytes], deflate=False) -> dict:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED) as z:
        for info, data in entries:
            z.writestr(info, data)
    return {"zip": b64(buffer.getvalue())}


def preview(client, upload):
    return client.post("/api/skills/preview", json={"upload": upload}, headers=ORIGIN)


def test_a_zip_without_a_top_folder_and_its_link_is_not_kept(client):
    link = zipfile.ZipInfo("notes.md")
    link.external_attr = 0o120777 << 16  # a symlink entry, to wherever its text says
    seen = preview(client, zipped(("SKILL.md", SKILL_MD), (link, b"/etc/passwd")))
    assert seen.status_code == 200, seen.text
    assert seen.json()["files"] == ["SKILL.md"] and seen.json()["skipped"] == ["notes.md"]
    assert seen.json()["source"] == "uploaded"


def test_left_out_folders_are_said_once_and_never_decoded(client):
    files = [("tidy/SKILL.md", b64(SKILL_MD)), ("tidy/.git/HEAD", "not base64!"),
             ("tidy/.git/config", "not base64!")]
    seen = preview(client, {"files": [{"path": p, "data": d} for p, d in files]})
    assert seen.status_code == 200, seen.text
    assert seen.json()["skipped"] == [".git/"] and seen.json()["source"] == "uploaded (tidy)"


def test_a_zip_that_says_it_is_too_large_is_refused_before_it_is_read(client):
    bomb = zipped(("SKILL.md", SKILL_MD), ("zeros.bin", bytes(6 * 1024 * 1024)), deflate=True)
    assert len(bomb["zip"]) < 100_000
    assert "MiB" in preview(client, bomb).json()["detail"]


def test_an_encrypted_or_broken_zip_or_bad_base64_or_a_twice_named_file_is_refused(client):
    locked = bytearray(base64.b64decode(zipped(("SKILL.md", SKILL_MD))["zip"]))
    central = locked.index(b"PK\x01\x02")
    locked[6] |= 1  # said to be encrypted, in both of its headers
    locked[central + 8] |= 1
    twice = [{"path": "SKILL.md", "data": b64(SKILL_MD)}] * 2
    for upload in ({"zip": b64(bytes(locked))}, {"zip": b64(b"not a zip")},
                   {"files": [{"path": "SKILL.md", "data": "@@@@"}]}, {"files": twice},
                   {"files": [], "zip": ""}):
        assert preview(client, upload).status_code == 422, upload


def test_a_file_and_a_folder_of_one_name_or_a_name_windows_refuses_is_refused_before_add(client):
    for clash in (("a", "A/b"), ("what?.md",), ("tab\t.md",)):
        files = [("SKILL.md", b64(SKILL_MD)), *((path, b64(b"x")) for path in clash)]
        upload = {"files": [{"path": p, "data": d} for p, d in files]}
        assert preview(client, upload).status_code == 422, clash
        added = client.post("/api/skills", json={"upload": upload}, headers=ORIGIN)
        assert added.status_code == 422, clash


def as_files(*files: tuple[str, bytes]) -> dict:
    return {"files": [{"path": path, "data": b64(data)} for path, data in files]}


def test_a_corrupted_zip_is_refused_not_failed_on(client):
    good = base64.b64decode(zipped(("tidy/SKILL.md", SKILL_MD))["zip"])
    moved = bytearray(good)  # the central directory said to start further on: a negative seek
    end = moved.rindex(b"PK\x05\x06")
    moved[end + 16:end + 20] = (int.from_bytes(moved[end + 16:end + 20], "little") + 100).to_bytes(4, "little")
    named = bytearray(good)  # a name said to be UTF-8 that is not
    central = named.index(b"PK\x01\x02")
    named[central + 9] |= 0x08  # (0x800 of the flags, in their high byte: "the name is UTF-8")
    named[central + 46] = 0xFF
    for broken in (moved, named):
        seen = preview(client, {"zip": b64(bytes(broken))})
        assert seen.status_code == 422 and "could not be read" in seen.json()["detail"], seen.text


def test_a_zip_s_path_out_of_its_folder_is_refused(client):
    for path in ("../x", r"..\x"):
        out = zipfile.ZipInfo("x")
        out.filename = path  # (as written, not as this machine would turn it)
        assert preview(client, zipped(("SKILL.md", SKILL_MD), (out, b"x"))).status_code == 422, path


def test_two_names_of_one_file_here_are_refused(client):
    for twins in (("a.md", "A.md"), ("docs/longreference.md", "docs/LONGRE~1.MD"),
                  ("ınfo.md", "info.md")):
        upload = as_files(("SKILL.md", SKILL_MD), *((path, b"x") for path in twins))
        assert preview(client, upload).status_code == 422, twins


def test_a_chosen_folder_that_is_a_secret_one_is_refused(client):
    for top in (".kube", ".docker", ".aws", ".config"):
        upload = as_files((f"{top}/SKILL.md", SKILL_MD), (f"{top}/config", b"token: s3cr3t"))
        seen = preview(client, upload)
        assert seen.status_code == 422 and "s3cr3t" not in seen.text, top


def test_a_zip_s_left_out_members_are_never_read_nor_counted(client):
    zeros = zipfile.ZipInfo("tidy/.git/objects/pack")
    zeros.flag_bits |= 1  # said to be encrypted: refused, were it read
    upload = zipped(("tidy/SKILL.md", SKILL_MD), ("tidy/.git/big", bytes(6 * 1024 * 1024)),
                    (zeros, b"x"), ("__MACOSX/tidy/._SKILL.md", b"\x00\x05\x16\x07"), deflate=True)
    seen = preview(client, upload)
    assert seen.status_code == 200, seen.text
    assert seen.json()["files"] == ["SKILL.md"] and seen.json()["skipped"] == [".git/"]
    assert seen.json()["source"] == "uploaded (tidy)"  # (Finder's __MACOSX/ beside it is not a top)


def test_a_zip_larger_than_a_skill_for_its_git_alone_is_read(client):
    # a packfile does not compress: the .zip itself is over 5 MiB, what it keeps is not
    upload = zipped(("tidy/SKILL.md", SKILL_MD),
                    ("tidy/.git/objects/pack/p.pack", os.urandom(6 * 1024 * 1024)))
    assert len(upload["zip"]) * 3 // 4 > 6 * 1024 * 1024
    seen = preview(client, upload)
    assert seen.status_code == 200, seen.text
    assert seen.json()["files"] == ["SKILL.md"] and seen.json()["skipped"] == [".git/"]


def test_an_upload_of_more_files_than_any_skill_leaves_out_is_refused_unread(client):
    upload = {"files": [{"path": f"f{n}.md", "data": "eA=="} for n in range(1001)]}
    seen = preview(client, upload)
    assert seen.status_code == 422 and seen.json()["detail"][0]["type"] == "too_long", seen.text


def test_an_upload_changed_since_its_preview_is_not_added(client):
    upload = as_files(("SKILL.md", SKILL_MD))
    added = client.post("/api/skills", json={"upload": upload, "sha256": "0" * 64}, headers=ORIGIN)
    assert added.status_code == 409 and client.get("/api/skills").json() == []


def test_a_skill_that_cannot_be_written_whole_leaves_nothing_behind(client, settings, monkeypatch):
    from app import skills

    monkeypatch.setattr(skills, "new_id", lambda: "fixed")
    folder = settings.runtime_root / "skills" / "fixed"
    folder.mkdir(parents=True)
    (folder / "notes.md").write_bytes(b"there first")  # SKILL.md is written, then this fails
    upload = as_files(("SKILL.md", SKILL_MD), ("notes.md", b"mine"))
    added = client.post("/api/skills", json={"upload": upload}, headers=ORIGIN)
    assert added.status_code == 409 and "could not be written" in added.json()["detail"]
    assert not folder.exists() and client.get("/api/skills").json() == []
