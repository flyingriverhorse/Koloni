"""The optional image (0.1.0-docker): what goes into it and how it runs, read from the files -
no image is built here (CI builds one when started by hand)."""

import re

from app.config import REPO_ROOT

NEVER_IN_IMAGE = ("runtime", ".venv", "node_modules", ".git", ".env*")
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSW|CREDENTIAL", re.IGNORECASE)


def instructions() -> list[tuple[str, str]]:
    """The Dockerfile's instructions, each (WORD, rest) with its continued lines joined."""
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    joined = re.sub(r"\\\n", " ", "\n".join(lines))
    return [(word.upper(), rest.strip()) for word, _, rest in
            (line.strip().partition(" ") for line in joined.splitlines() if line.strip())]


def test_dockerignore_keeps_the_checkouts_own_out():
    lines = [line.strip() for line in
             (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    assert lines[0] == "*"  # an allowlist: an untracked file never reaches the build
    last_allowed = max(i for i, line in enumerate(lines) if line.startswith("!"))
    for name in NEVER_IN_IMAGE:
        # Later lines win: each one after the last "!", so nothing allowed brings it back.
        assert name in lines[last_allowed + 1:], name
    assert "**/node_modules" in lines and "**/.env*" in lines


def test_the_image_runs_as_its_own_user_on_its_port():
    steps = instructions()
    last_stage = max(i for i, (word, _) in enumerate(steps) if word == "FROM")
    users = [rest for word, rest in steps[last_stage:] if word == "USER"]
    assert users and users[-1].split(":")[0] not in ("root", "0")
    assert ("EXPOSE", "8790") in steps
    env = " ".join(rest for word, rest in steps if word == "ENV")
    assert "KOLONI_PORT=8790" in env and "KOLONI_HOST=0.0.0.0" in env
    assert "KOLONI_RUNTIME_ROOT=/data" in env
    assert "KOLONI_IN_CONTAINER=1" in env  # the one place 0.0.0.0 is let through (main.run)


def test_no_secret_is_put_into_the_image():
    for word, rest in instructions():
        if word in ("ENV", "ARG"):
            for name in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=", rest) or [rest.split()[0]]:
                assert not SECRET_NAME.search(name), f"{word} {name}"
        if word in ("COPY", "ADD"):
            assert not re.search(r"\.env|\.claude|\.codex|\.copilot|\.gemini|\.qoder|runtime",
                                 rest), rest
            assert not re.match(r"(--\S+\s+)*\.\s", rest), "the whole folder is not copied"
