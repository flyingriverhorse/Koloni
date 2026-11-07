"""Slice 32e's acceptance set, the backend's part: reading aloud with Gemini's voices. Written
before the code.

The user gives a Google AI Studio key once, from the app's own page; it stays on the server and
is never shown again, nor written in an answer, an error or a log. The page asks the app to say a
text; the app asks Google and hands back the sound (WAV). With no key there is no Gemini voice and
the browser's own reads, as in 32a. Google is never reached in these tests: `app.speech.synthesize`
is stood in for.

Contract:
- `GET /api/voice/gemini` → {has_key, model, voice}; `PUT /api/voice/gemini` (own origin)
  {api_key?, model?, voice?} — an empty api_key removes it.
- `POST /api/voice/gemini/say` (own origin) {text, voice?, style?} → 200 `audio/wav`; 409 with no
  key; a failure from Google → 502 whose text never holds the key.
- `app.speech.synthesize(key, model, text, voice, style) -> bytes` (async) is what reaches Google.
"""

import importlib.util

import pytest

if importlib.util.find_spec("app.speech") is None:
    pytest.skip("slice 32e is not built yet", allow_module_level=True)  # written before the code

import app.speech as speech  # noqa: E402

ORIGIN = {"Origin": "http://127.0.0.1:8790"}
KEY = "AIza-test-key-0123456789"
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "


@pytest.fixture
def heard(monkeypatch):
    asked = []

    async def synthesize(key, model, text, voice, style):
        asked.append({"key": key, "model": model, "text": text, "voice": voice, "style": style})
        return WAV

    monkeypatch.setattr(speech, "synthesize", synthesize)
    return asked


def test_the_key_is_kept_on_the_server_and_never_shown(make_client):
    client, _model = make_client([])
    assert client.get("/api/voice/gemini").json()["has_key"] is False
    assert client.put("/api/voice/gemini", json={"api_key": KEY}).status_code == 403  # no Origin
    saved = client.put("/api/voice/gemini", json={"api_key": KEY, "voice": "Kore"}, headers=ORIGIN)
    assert saved.status_code == 200, saved.text
    assert KEY not in saved.text
    shown = client.get("/api/voice/gemini")
    assert shown.json()["has_key"] is True and shown.json()["voice"] == "Kore"
    assert KEY not in shown.text
    gone = client.put("/api/voice/gemini", json={"api_key": ""}, headers=ORIGIN)
    assert gone.json()["has_key"] is False


def test_a_text_is_said_in_the_voice_and_manner_asked(make_client, heard):
    client, _model = make_client([])
    client.put("/api/voice/gemini", json={"api_key": KEY, "voice": "Kore"}, headers=ORIGIN)
    said = client.post(
        "/api/voice/gemini/say", json={"text": "Merhaba!", "style": "sıcak ve kısa"}, headers=ORIGIN
    )
    assert said.status_code == 200, said.text
    assert said.headers["content-type"].startswith("audio/wav")
    assert said.content == WAV
    (asked,) = heard
    assert (asked["key"], asked["text"], asked["voice"], asked["style"]) == (
        KEY,
        "Merhaba!",
        "Kore",
        "sıcak ve kısa",
    )
    assert asked["model"]  # a TTS model is chosen


def test_with_no_key_nothing_is_asked_of_google(make_client, heard):
    client, _model = make_client([])
    said = client.post("/api/voice/gemini/say", json={"text": "hi"}, headers=ORIGIN)
    assert said.status_code == 409
    assert heard == []


def test_saying_is_asked_from_the_apps_own_page(make_client, heard):
    client, _model = make_client([])
    client.put("/api/voice/gemini", json={"api_key": KEY}, headers=ORIGIN)
    assert client.post("/api/voice/gemini/say", json={"text": "hi"}).status_code == 403
    assert heard == []


def test_a_failure_from_google_never_carries_the_key(make_client, monkeypatch):
    async def refused(key, model, text, voice, style):
        raise RuntimeError(f"403 from Google: API key {key} is not valid")

    monkeypatch.setattr(speech, "synthesize", refused)
    client, _model = make_client([])
    client.put("/api/voice/gemini", json={"api_key": KEY}, headers=ORIGIN)
    said = client.post("/api/voice/gemini/say", json={"text": "hi"}, headers=ORIGIN)
    assert said.status_code == 502
    assert KEY not in said.text
