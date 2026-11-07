"""Slice 45b's acceptance set: a skill uploaded from the browser - a chosen folder or a .zip. Written
before the code.

The user picks a folder (or a .zip) in the browser instead of typing a path. Its files go to the app
in the request itself; the app reads them with the same rules as a folder of this machine: secrets
and links are not kept, the caps hold, an unsafe path or script name is refused, and nothing is kept
before the user adds what the card showed (same sum). Only from the app's own page. No new
dependency: the files are base64 in JSON, a .zip is opened with the standard library.

Contract: `SkillIn.upload` / the preview's body `upload`:
`{"files": [{"path": "<relative, forward slashes>", "data": "<base64>"}]}` or `{"zip": "<base64>"}`;
exactly one of folder / github / upload.
"""

import base64
import io
import zipfile

import pytest

from app.schemas import SkillIn

if "upload" not in SkillIn.model_fields:
    pytest.skip("slice 45b is not built yet", allow_module_level=True)  # written before the code

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
SKILL_MD = b"---\nname: tidy\ndescription: Keep changes small.\n---\n\nWrite the least code.\n"
FILES = {
    "tidy/SKILL.md": SKILL_MD,
    "tidy/scripts/check.py": b"print('ok')\n",
    "tidy/.env": b"TOKEN=s3cr3t-value\n",
}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def as_files(files=FILES):
    return {"files": [{"path": p, "data": b64(d)} for p, d in files.items()]}


def as_zip(files=FILES):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for path, data in files.items():
            z.writestr(path, data)
    return {"zip": b64(buffer.getvalue())}


def preview(client, upload, **headers):
    return client.post("/api/skills/preview", json={"upload": upload}, headers=headers or ORIGIN)


@pytest.mark.parametrize("upload", [as_files(), as_zip()], ids=["folder", "zip"])
def test_an_uploaded_skill_is_read_like_a_folder_and_kept_only_as_shown(client, upload):
    seen = preview(client, upload)
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert (body["name"], body["description"]) == ("tidy", "Keep changes small.")
    assert ".env" not in body["files"] and any(".env" in s for s in body["skipped"])
    assert "s3cr3t-value" not in seen.text
    assert client.get("/api/skills").json() == []  # nothing kept by a look
    added = client.post(
        "/api/skills", json={"upload": upload, "sha256": body["sha256"]}, headers=ORIGIN
    )
    assert added.status_code == 201, added.text
    assert added.json()["scripts"] == ["scripts/check.py"]


@pytest.mark.parametrize(
    "path", ["../evil/SKILL.md", "/abs/SKILL.md", "C:/x/SKILL.md", "tidy/scripts/$(x).py"]
)
def test_an_unsafe_path_or_script_name_is_refused(client, path):
    files = {**FILES, path: b"print(1)\n"}
    assert preview(client, as_files(files)).status_code == 422


def test_the_caps_hold_for_an_upload(client):
    big = {**FILES, "tidy/huge.bin": b"x" * (5 * 1024 * 1024 + 1)}
    assert preview(client, as_files(big)).status_code == 422


def test_an_upload_is_taken_only_from_the_apps_own_page(client):
    assert client.post("/api/skills/preview", json={"upload": as_files()}).status_code == 403
    assert client.post("/api/skills", json={"upload": as_files()}).status_code == 403


def test_exactly_one_source(client, tmp_path):
    both = {"upload": as_files(), "folder": str(tmp_path)}
    assert client.post("/api/skills", json=both, headers=ORIGIN).status_code == 422
