"""Reading aloud with Gemini's voices (slice 32e): the one place that reaches Google.

From Google's page `ai.google.dev/gemini-api/docs/speech-generation` (read 18 October 2026):
one request to the Interactions endpoint, the key in the `x-goog-api-key` header; the answer's
sound is base64 WAV (24 kHz, mono, 16 bit) in `steps[type=model_output].content[type=audio]`,
or bare 16-bit PCM (audio/l16) of the same rate. Nothing is kept: the sound goes back to the
page and is gone.
"""

import base64
import os
import struct

import httpx2

# The end-to-end tests point it at their stand-in server: nothing leaves the machine there.
BASE = (os.environ.get("KOLONI_GEMINI_URL") or "https://generativelanguage.googleapis.com").rstrip("/")
URL = f"{BASE}/v1beta/interactions"
MODELS = ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts")
# The 30 prebuilt voices, in the page's order.
VOICES = (
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe",
    "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib",
    "Rasalgethi", "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima",
    "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
)
SECONDS = 60.0
RATE = 24000
# A test hands in httpx2.MockTransport here; None is the network.
_transport: httpx2.AsyncBaseTransport | None = None


class SpeechFailed(Exception):
    """Google gave no sound, or could not be asked; the message never holds the key."""


def _client(seconds: float) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=_transport, timeout=httpx2.Timeout(seconds, connect=5.0))


def _said(response: httpx2.Response) -> str:
    """What Google said was wrong: its status and its own message, nothing of the request."""
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.reason_phrase
    return f"Google answered {response.status_code}: {message}"


def _wav(pcm: bytes) -> bytes:
    """A 44-byte WAV header before bare 16-bit PCM, 24 kHz, mono."""
    fmt = struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + fmt + b"data" + \
        struct.pack("<I", len(pcm)) + pcm


def _is_wav(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _pcm(data: bytes) -> bytes:
    """The samples of a piece of sound: a WAV's `data` chunk, or bare PCM as it is."""
    if not _is_wav(data):
        return data
    at = 12
    while at + 8 <= len(data):
        size = struct.unpack("<I", data[at + 4:at + 8])[0]
        if data[at:at + 4] == b"data":
            return data[at + 8:at + 8 + size]
        at += 8 + size + (size & 1)
    raise SpeechFailed("Google's sound had no samples in it")


def _sound(pieces: list[bytes]) -> bytes:
    """One WAV of all the pieces, in order. A single WAV is passed on as it came."""
    if len(pieces) == 1 and _is_wav(pieces[0]):
        return pieces[0]
    pcm = b"".join(_pcm(piece) for piece in pieces)
    if not pcm or len(pcm) % 2:
        raise SpeechFailed("Google's sound was not 16-bit sound")
    return _wav(pcm)


async def synthesize(key: str, model: str, text: str, voice: str, style: str | None) -> bytes:
    """`text` said in `voice`, in the manner `style` asks for, as WAV."""
    content: dict = {"type": "text", "text": text}
    if style:
        content["annotations"] = [{"type": "speech_metadata", "style": style}]
    body = {
        "model": model,
        "input": [{"type": "user_input", "content": [content]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    try:
        async with _client(SECONDS) as http:
            response = await http.post(URL, json=body, headers={"x-goog-api-key": key})
    except httpx2.TimeoutException:
        raise SpeechFailed("Google did not answer in time") from None
    except httpx2.HTTPError as exc:
        raise SpeechFailed(f"Google could not be reached ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise SpeechFailed(_said(response).replace(key, "…"))
    try:
        # (Every piece, in order: the page's own example keeps only the last, which is all
        # of it when there is one.)
        pieces = [
            base64.b64decode(item["data"])
            for step in response.json()["steps"] if step.get("type") == "model_output"
            for item in step.get("content", []) if item.get("type") == "audio"
        ]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise SpeechFailed("Google answered with no sound") from None
    if not pieces:
        raise SpeechFailed("Google answered with no sound")
    return _sound(pieces)


async def check_key(key: str) -> bool:
    """Whether Google takes the key: a list of one model, which spends nothing. Raises
    SpeechFailed when Google could not be asked."""
    try:
        async with _client(10.0) as http:
            response = await http.get(
                f"{BASE}/v1beta/models", params={"pageSize": 1}, headers={"x-goog-api-key": key}
            )
    except httpx2.HTTPError:
        raise SpeechFailed("Google could not be reached") from None
    # (Google says a key it does not know with a 400, one it will not serve with 401/403.)
    if response.status_code in (400, 401, 403):
        return False
    if response.status_code != 200:
        raise SpeechFailed(_said(response).replace(key, "…"))
    return True
