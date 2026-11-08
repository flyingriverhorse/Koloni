"""Reading aloud with Gemini's voices (slice 32e). The key is given once, from the app's own
page, and stays here: no answer, error or log carries it."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from app import speech
from app.api.deps import require_own_origin
from app.api.providers import _key
from app.db.models import Flag
from app.schemas import GeminiSayIn, GeminiVoiceIn, GeminiVoiceOut

router = APIRouter(prefix="/api/voice", tags=["voice"])

# Rows of `flags`: one setting each.
NAMES = KEY, MODEL, VOICE, STYLE = "gemini_key", "gemini_model", "gemini_voice", "gemini_style"


# (Sessions of their own, closed before Google is asked: a slow answer holds no database.)
def _read(request: Request) -> dict[str, str]:
    with request.app.state.session_factory() as session:
        rows = session.scalars(select(Flag).where(Flag.name.in_(NAMES)))
        return {row.name: row.value for row in rows}


def _write(request: Request, changes: dict[str, str | None]) -> None:
    with request.app.state.session_factory() as session:
        for name, value in changes.items():
            row = session.get(Flag, name)
            if value is None:
                if row:
                    session.delete(row)
            elif row:
                row.value = value
            else:
                session.add(Flag(name=name, value=value))
        session.commit()


def _shown(saved: dict[str, str], note: str | None = None) -> GeminiVoiceOut:
    return GeminiVoiceOut(
        has_key=KEY in saved,
        model=saved.get(MODEL, speech.MODELS[0]),
        voice=saved.get(VOICE, "Kore"),
        style=saved.get(STYLE, ""),
        note=note,
    )


def _voice(name: str) -> str:
    if name not in speech.VOICES:
        raise HTTPException(422, "not one of Gemini's voices")
    return name


@router.get("/gemini", response_model=GeminiVoiceOut)
def gemini(request: Request):
    return _shown(_read(request))


@router.put("/gemini", response_model=GeminiVoiceOut, dependencies=[Depends(require_own_origin)])
async def set_gemini(body: GeminiVoiceIn, request: Request):
    # All of it is checked before anything is kept, and before Google is asked.
    changes: dict[str, str | None] = {}
    if body.model is not None:
        if body.model not in speech.MODELS:
            raise HTTPException(422, "not one of Gemini's speech models")
        changes[MODEL] = body.model
    if body.voice is not None:
        changes[VOICE] = _voice(body.voice)
    if body.style is not None:
        changes[STYLE] = body.style.strip() or None
    note = None
    if body.api_key is not None:
        key = _key(body.api_key)
        if key and len(key) > 200:
            raise HTTPException(422, "the key is too long; paste it again")
        if key:
            try:
                if not await speech.check_key(key):
                    raise HTTPException(422, "the key was not accepted by Google")
            except speech.SpeechFailed:
                note = "The key is saved, but it could not be checked now: Google was not reached."
        changes[KEY] = key
    _write(request, changes)
    return _shown(_read(request), note)


@router.post(
    "/gemini/say",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {}}}},
    dependencies=[Depends(require_own_origin)],
)
async def say(body: GeminiSayIn, request: Request):
    saved = _read(request)
    key = saved.get(KEY)
    if key is None:
        raise HTTPException(409, "Gemini could not read it: no key is saved")
    shown = _shown(saved)
    voice = _voice(body.voice) if body.voice else shown.voice
    style = body.style if body.style is not None else shown.style
    try:
        wav = await speech.synthesize(key, shown.model, body.text, voice, style or None)
    except Exception as exc:  # whatever went wrong out there, said without the key
        said = str(exc).replace(key, "…")
        raise HTTPException(502, f"Gemini could not read it: {said}") from None
    return Response(wav, media_type="audio/wav")
