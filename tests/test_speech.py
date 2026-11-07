"""`app.speech`, the one thing that reaches Google, against a stand-in for it; and what the
voice endpoints do with the key Google is asked about."""

import asyncio
import base64
import json
import struct

import httpx2
import pytest

import app.speech as speech

KEY = "AIza-test-key-0123456789"
ORIGIN = {"Origin": "http://127.0.0.1:8790"}
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "


def answering(monkeypatch, status: int, body: dict) -> list[httpx2.Request]:
    asked: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        return httpx2.Response(status, json=body)

    monkeypatch.setattr(speech, "_transport", httpx2.MockTransport(handler))
    return asked


def unreachable(monkeypatch):
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    monkeypatch.setattr(speech, "_transport", httpx2.MockTransport(handler))


def audio(data: bytes, **more) -> dict:
    return {"type": "audio", "data": base64.b64encode(data).decode(), **more}


def sound(*items: dict) -> dict:
    return {"steps": [{"type": "user_input"}, {"type": "model_output", "content": list(items)}]}


def wav_of(pcm: bytes) -> bytes:
    """A whole WAV as Gemini's: 24 kHz, mono, 16 bit."""
    fmt = struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + fmt + b"data" + \
        struct.pack("<I", len(pcm)) + pcm


def say(style: str | None = "warm"):
    return asyncio.run(speech.synthesize(KEY, "gemini-3.8-flash-tts", "Merhaba!", "Kore", style))


def test_the_text_is_asked_for_in_the_voice_and_manner_with_the_key_in_its_header(monkeypatch):
    asked = answering(monkeypatch, 200, sound(audio(WAV)))
    assert say() == WAV
    (request,) = asked
    assert str(request.url) == speech.URL and KEY not in str(request.url)
    assert request.headers["x-goog-api-key"] == KEY
    assert json.loads(request.content) == {
        "model": "gemini-3.8-flash-tts",
        "input": [{"type": "user_input", "content": [{
            "type": "text", "text": "Merhaba!",
            "annotations": [{"type": "speech_metadata", "style": "warm"}],
        }]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": "Kore"}]},
    }


def test_with_no_manner_none_is_asked(monkeypatch):
    asked = answering(monkeypatch, 200, sound(audio(WAV)))
    say(None)
    assert "annotations" not in json.loads(asked[0].content)["input"][0]["content"][0]


def test_googles_refusal_is_said_without_the_key(monkeypatch):
    answering(monkeypatch, 400, {"error": {"message": f"API key not valid: {KEY}"}})
    with pytest.raises(speech.SpeechFailed) as failed:
        say()
    assert "Google answered 400" in str(failed.value) and KEY not in str(failed.value)


@pytest.mark.parametrize("body", [{"steps": []}, {"nothing": 1}, sound(audio(b"odd"))])
def test_an_answer_with_no_sound_in_it_is_a_failure(monkeypatch, body):
    answering(monkeypatch, 200, body)
    with pytest.raises(speech.SpeechFailed):
        say()


@pytest.mark.parametrize("item", [
    audio(b"\x01\x00\x02\x00", mime_type="audio/l16"),
    audio(b"\x01\x00\x02\x00", mimeType="audio/L16;codec=pcm;rate=24000"),
    audio(b"\x01\x00\x02\x00"),  # not RIFF/WAVE: taken for what L16 is
])
def test_bare_sound_is_given_a_wav_header(monkeypatch, item):
    answering(monkeypatch, 200, sound(item))
    assert say() == wav_of(b"\x01\x00\x02\x00")


def test_several_pieces_of_sound_are_joined_in_order(monkeypatch):
    answering(monkeypatch, 200, sound(
        audio(wav_of(b"\x01\x00")), audio(b"\x02\x00", mime_type="audio/l16"), audio(wav_of(b"\x03\x00")),
    ))
    assert say() == wav_of(b"\x01\x00\x02\x00\x03\x00")


def test_a_key_is_checked_by_one_models_list_with_the_key_in_its_header(monkeypatch):
    asked = answering(monkeypatch, 200, {"models": []})
    assert asyncio.run(speech.check_key(KEY)) is True
    (request,) = asked
    assert request.method == "GET" and request.url.path == "/v1beta/models"
    assert KEY not in str(request.url) and request.headers["x-goog-api-key"] == KEY


@pytest.mark.parametrize("status", [400, 401, 403])
def test_a_key_google_refuses_is_not_taken(monkeypatch, status):
    answering(monkeypatch, status, {"error": {"message": "API key not valid"}})
    assert asyncio.run(speech.check_key(KEY)) is False


def test_a_key_that_could_not_be_checked_is_said_so_without_the_key(monkeypatch):
    answering(monkeypatch, 500, {"error": {"message": f"oops {KEY}"}})
    with pytest.raises(speech.SpeechFailed) as failed:
        asyncio.run(speech.check_key(KEY))
    assert KEY not in str(failed.value)


def test_a_key_google_refuses_is_not_saved_and_not_repeated(make_client, monkeypatch):
    answering(monkeypatch, 400, {"error": {"message": f"API key not valid: {KEY}"}})
    client, _model = make_client([])
    refused = client.put("/api/voice/gemini", json={"api_key": KEY}, headers=ORIGIN)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "the key was not accepted by Google"
    assert client.get("/api/voice/gemini").json()["has_key"] is False


def test_a_key_that_could_not_be_checked_now_is_saved_and_said_so(make_client, monkeypatch):
    unreachable(monkeypatch)
    client, _model = make_client([])
    saved = client.put("/api/voice/gemini", json={"api_key": KEY}, headers=ORIGIN)
    assert saved.status_code == 200
    assert saved.json()["has_key"] is True
    assert "could not be checked now" in saved.json()["note"]
    assert KEY not in saved.text


def test_a_refusal_of_what_came_with_a_key_never_repeats_it_nor_saves_it(make_client):
    client, _model = make_client([])
    refused = client.put(
        "/api/voice/gemini", json={"api_key": KEY, "model": "gemini-bogus"}, headers=ORIGIN
    )
    assert refused.status_code == 422 and KEY not in refused.text
    assert client.get("/api/voice/gemini").json()["has_key"] is False


def test_geminis_own_manner_is_kept_and_used_when_a_text_asks_for_none(make_client, monkeypatch):
    heard = []

    async def synthesize(key, model, text, voice, style):
        heard.append(style)
        return WAV

    monkeypatch.setattr(speech, "synthesize", synthesize)
    client, _model = make_client([])
    saved = client.put(
        "/api/voice/gemini", json={"api_key": KEY, "style": "calm"}, headers=ORIGIN
    ).json()
    assert saved["style"] == "calm"
    assert client.get("/api/voice/gemini").json()["style"] == "calm"
    client.post("/api/voice/gemini/say", json={"text": "hi"}, headers=ORIGIN)
    client.post("/api/voice/gemini/say", json={"text": "hi", "style": "loud"}, headers=ORIGIN)
    assert heard == ["calm", "loud"]
    long = client.put("/api/voice/gemini", json={"style": "x" * 201}, headers=ORIGIN)
    assert long.status_code == 422
    client.put("/api/voice/gemini", json={"style": ""}, headers=ORIGIN)
    assert client.get("/api/voice/gemini").json()["style"] == ""


def test_a_saved_key_is_one_of_the_secrets_kept_out_of_what_a_cli_wrote(make_client):
    from app.main import known_secrets

    client, _model = make_client([])
    client.put("/api/voice/gemini", json={"api_key": KEY}, headers=ORIGIN)
    state = client.app.state
    assert KEY in known_secrets(state.session_factory, state.settings)
