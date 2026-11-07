"""Copilot headless's Content-Length framing (`model_native._framed`), slice 89c."""

import asyncio
import json

import pytest

from app.model_native import _framed


def framed(message: dict) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


async def read_all(*chunks: bytes) -> list[dict]:
    """What `_framed` reads of these chunks, fed one after another as they arrive."""
    stream = asyncio.StreamReader()

    async def feed() -> None:
        for chunk in chunks:
            stream.feed_data(chunk)
            await asyncio.sleep(0)
        stream.feed_eof()

    feeding = asyncio.ensure_future(feed())
    read = []
    while (message := await _framed(stream)) is not None:
        read.append(message)
    await feeding
    return read


def test_messages_split_anywhere_and_run_together_are_each_read_whole():
    one, two = {"id": 1, "result": {"ok": True}}, {"method": "session.event", "params": {}}
    data = framed(one) + framed(two)
    assert asyncio.run(read_all(data)) == [one, two]  # in one chunk
    assert asyncio.run(read_all(*(data[i:i + 3] for i in range(0, len(data), 3)))) == [one, two]


def test_its_length_counts_bytes_not_characters():
    said = {"method": "x", "params": {"text": "KOLONİ şöyle — ✓"}}
    assert asyncio.run(read_all(framed(said), framed({"id": 2}))) == [said, {"id": 2}]


def test_a_message_cut_off_at_its_end_is_the_end():
    assert asyncio.run(read_all(framed({"id": 1})[:-2])) == []


@pytest.mark.parametrize("data, why", [
    (b"Content-Length: lots\r\n\r\n{}", "not a number"),
    (b"Content-Length: 0\r\n\r\n", "empty"),
    (b"Content-Length: 5\r\n\r\nnot j", "not JSON"),
    (b"Content-Length: 99999999999\r\n\r\n", "longer than"),
])
def test_a_bad_frame_says_what_was_wrong(data, why):
    with pytest.raises(ValueError, match=why):
        asyncio.run(read_all(data))
