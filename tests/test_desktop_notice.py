"""herdr's idea (28 Nov 2026): a desktop notice on macOS (terminal-notifier, else osascript) and on a
Linux desktop (notify-send) - the words as arguments of their own, never through a shell, never in
the script; none where the program or the desktop is not there. All stood in for: no notice is
shown, whatever system runs this."""

import pytest

from app import web
from tests.test_web import SAID, TITLE, powershell


def system(monkeypatch, platform, found=(), env=None, osascript=True):
    """`platform` with the programs `found` on its PATH and its desktop's `env`."""
    started = powershell(monkeypatch)
    monkeypatch.setattr(web.sys, "platform", platform)
    monkeypatch.setattr(
        web.shutil, "which", lambda name: f"/opt/bin/{name}" if name in found else None
    )
    monkeypatch.setattr(
        web.os.path, "exists", lambda path: osascript and path == "/usr/bin/osascript"
    )
    for name in ("DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    return started


def shown(started):
    ((argv, how),) = started
    assert "shell" not in how  # (never a shell: each word an argument of its own)
    return argv


def test_on_macos_terminal_notifier_shows_it_with_the_words_as_arguments(monkeypatch):
    started = system(monkeypatch, "darwin", found=("terminal-notifier",))
    assert web.has_desktop()
    web.desktop(TITLE, "-rf the note")
    title = TITLE  # (as `plain` keeps it: no control character there)
    assert shown(started) == [
        "/opt/bin/terminal-notifier",
        "-title",
        title,
        "-message",
        " -rf the note",
    ]


def test_on_macos_without_it_osascript_is_handed_the_words_as_its_argv_never_its_script(
    monkeypatch,
):
    started = system(monkeypatch, "darwin")
    assert web.has_desktop()
    web.desktop(TITLE, SAID)
    argv = shown(started)
    assert argv[:7] == [
        "/usr/bin/osascript",
        "-e",
        "on run argv",
        "-e",
        "display notification (item 2 of argv) with title (item 1 of argv)",
        "-e",
        "end run",
    ]
    assert argv[7] == TITLE and "`whoami`" in argv[8] and "\x00" not in argv[8]
    assert not any(TITLE in one or "whoami" in one for one in argv[:7])  # (never in the script)


def test_on_macos_with_neither_there_is_none(monkeypatch):
    started = system(monkeypatch, "darwin", osascript=False)
    assert not web.has_desktop()
    with pytest.raises(web.WebError, match="not available on this system"):
        web.desktop(TITLE, SAID)
    assert started == []


@pytest.mark.parametrize("env", [{"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "wayland-0"}])
def test_on_a_linux_desktop_notify_send_shows_it_after_its_options(monkeypatch, env):
    started = system(monkeypatch, "linux", found=("notify-send",), env=env)
    assert web.has_desktop()
    web.desktop(TITLE, "--urgency=critical")
    assert shown(started) == [
        "/opt/bin/notify-send",
        "--app-name",
        "KOLONİ",
        "--",
        TITLE,
        " --urgency=critical",
    ]


@pytest.mark.parametrize(
    ("found", "env"),
    [(("notify-send",), {}), ((), {"DISPLAY": ":0"})],
    ids=["no desktop (a server, SSH)", "no notify-send"],
)
def test_on_linux_with_no_desktop_or_no_notify_send_there_is_none(monkeypatch, found, env):
    started = system(monkeypatch, "linux", found=found, env=env)
    assert not web.has_desktop()
    with pytest.raises(web.WebError, match="not available on this system"):
        web.desktop(TITLE, SAID)
    assert started == []


def test_a_program_that_fails_or_hangs_is_said_without_the_words(monkeypatch):
    system(monkeypatch, "linux", found=("notify-send",), env={"DISPLAY": ":0"})

    def hangs(argv, **_how):
        raise web.subprocess.TimeoutExpired(argv, web.TOAST_SECONDS)

    monkeypatch.setattr(web.subprocess, "run", hangs)
    with pytest.raises(web.WebError, match="no answer within") as failed:
        web.desktop(TITLE, SAID)
    assert "whoami" not in str(failed.value)
    monkeypatch.setattr(
        web.subprocess, "run", lambda argv, **_how: web.subprocess.CompletedProcess(argv, 2)
    )
    with pytest.raises(web.WebError, match=r"\(notify-send ended with 2\)"):
        web.desktop(TITLE, SAID)


def test_a_program_gone_since_it_was_looked_for_is_said_as_none(monkeypatch):
    started = system(monkeypatch, "linux", env={"DISPLAY": ":0"})
    monkeypatch.setattr(web, "has_desktop", lambda: True)  # (there a moment ago)
    with pytest.raises(web.WebError, match="not available on this system"):
        web.desktop(TITLE, SAID)
    assert started == []


def test_on_linux_its_body_is_said_never_read_as_markup(monkeypatch):
    # (A daemon that reads the body as markup would follow an agent's link or fetch its image.)
    started = system(monkeypatch, "linux", found=("notify-send",), env={"DISPLAY": ":0"})
    web.desktop("<b>KOLONİ</b>", 'see <a href="http://x/">here</a> <img src="http://x/i"> & "so"')
    assert shown(started)[-2:] == [
        "<b>KOLONİ</b>",  # (the summary is no markup)
        'see &lt;a href="http://x/"&gt;here&lt;/a&gt; &lt;img src="http://x/i"&gt; &amp; "so"',
    ]
