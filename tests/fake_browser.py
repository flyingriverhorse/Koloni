"""A stand-in for Chrome (slice 51), for the tests and the e2e: KOLONI_BROWSER_FAKE names it and
`app.browser` starts it with Chrome's own flags. It writes DevToolsActivePort into the profile
`--user-data-dir` names and answers, on a websocket, the DevTools methods the driver uses. A
page it is sent to is really fetched (loopback http, or a file:// path) and its text and
buttons are what browser_read, browser_click and the accessibility tree see; a screenshot is
one small PNG. An expression it is asked to evaluate is told apart by its first line alone
(`app.browser._tag`): /*koloni:NAME ARG*/.
"""

import asyncio
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import websockets

PNG = bytes.fromhex(  # a 1x1 picture
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
profile = Path(next(a for a in sys.argv[1:] if a.startswith("--user-data-dir=")).split("=", 1)[1])
state = {"url": "about:blank", "html": "", "typed": {}, "scroll": 0.0}


def text_of(page: str) -> str:
    bare = re.sub(r"(?s)<(script|style|head)[^>]*>.*?</\1>", "", page)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", bare))).strip()


def title_of(page: str) -> str:
    found = re.search(r"(?s)<title>(.*?)</title>", page)
    return html.unescape(found[1].strip()) if found else ""


def fetch(url: str) -> str:
    if url == "about:blank":
        return ""
    if url.startswith("file:"):
        return Path(urllib.request.url2pathname(url[5:].lstrip("/") if sys.platform == "win32"
                                                else url[7:])).read_text(encoding="utf-8")
    # K-tarayici-disari: a site of a test's (site.test) is a server on loopback, as
    # --host-resolver-rules "MAP site.test 127.0.0.1" has it in Chrome.
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").endswith(".test"):
        url = parts._replace(netloc=f"127.0.0.1:{parts.port}").geturl()
    with urllib.request.urlopen(url, timeout=5) as answer:  # noqa: S310 (loopback: vetted by the driver)
        return answer.read().decode("utf-8", errors="replace")


def evaluate(expression: str) -> object:  # noqa: C901
    head = re.match(r"/\*koloni:(\w+) (.*?)\*/", expression)
    assert head, expression[:80]
    name, arg = head[1], json.loads(head[2])
    page = state["html"]
    if name == "url":
        return state["url"]
    if name == "title":
        return title_of(page)
    if name == "text":
        return text_of(page)
    if name == "scrolly":
        return str(state["scroll"])
    if name == "find":
        state["found"] = arg
        found = re.search(r"(?s)<(button|a)[^>]*>\s*" + re.escape(arg) + r"\s*</\1>", page)
        return json.dumps({"x": 10, "y": 20, "width": 80, "height": 30}) if found else None
    if name == "rect":
        return json.dumps({"x": 10, "y": 60, "width": 200, "height": 30}) if _has(arg) else None
    if name == "focus":
        if arg is not None and _has(arg):
            state["focused"] = arg
        if arg is None:
            return "input#focused"
        return f"input{arg}" if _has(arg) else None
    # K-tarayici-disari A2: what a click (at the last element found) or typing would reach.
    if name == "what":
        out = {"host": urllib.parse.urlsplit(state["url"]).hostname or "", "words": "",
               "password": False, "posts": False, "frame": False,
               "editable": False, "hidden": False}
        if "x" in arg:
            # (A mark's centre is its button's; any other point the last element found.)
            out["words"] = words = state.get("marks", {}).get(
                (arg["x"], arg["y"]), state.get("found", ""))
            out["posts"] = bool(words) and bool(re.search(
                r'(?is)<form[^>]*method="post".*?<button[^>]*>\s*' + re.escape(words), page))
        elif selector := arg.get("selector") or state.get("focused"):
            tag = re.search(r'<input[^>]*id="' + re.escape(selector[1:]) + r'"[^>]*>', page)
            out["password"] = bool(tag) and 'type="password"' in tag[0]
            out["editable"] = bool(tag)
        return json.dumps(out)
    # K-gorsel-motor: each button and link marked, one under the other; where the page is.
    if name == "marks":
        found = [text_of(words) for _tag, words in
                 re.findall(r"(?s)<(button|a)[^>]*>(.*?)</\1>", page)][:arg]
        state["marks"] = {(100, 100 + 40 * n): words for n, words in enumerate(found)}
        return json.dumps({"here": evaluate("/*koloni:here null*/"), "marks": [
            {"kind": "button", "words": words, "x": x, "y": y}
            for (x, y), words in state["marks"].items()]})
    if name == "here":
        return f"{state['url']} {state['scroll']}"
    if name == "unmark":
        return None
    # K-drawio (`app.diagram.draw`): the viewer's scripts, then the picture it draws.
    if name == "script":
        return None
    if name == "drawio":
        return ('<svg xmlns="http://www.w3.org/2000/svg"/>' if arg == "svg"
                else "data:image/png;base64," + __import__("base64").b64encode(PNG).decode())
    raise AssertionError(name)


def _has(selector: str) -> bool:
    return selector.startswith("#") and f'id="{selector[1:]}"' in state["html"]


async def serve(ws) -> None:  # noqa: C901
    async def event(method: str, params: dict, session: str | None = "s1") -> None:
        await ws.send(json.dumps({"method": method, "params": params,
                                  **({"sessionId": session} if session else {})}))

    # Each load is paused for the driver's judge, as Chrome does at the browser's own Fetch.enable
    # (no sessionId): continueRequest or failRequest decides it.
    verdicts: dict[str, asyncio.Future] = {}
    dialogs: list[asyncio.Future] = []

    async def paused(url: str, kind: str, frame: str = "t1") -> bool:
        request_id = f"r{len(verdicts)}"
        verdicts[request_id] = asyncio.get_running_loop().create_future()
        # (The page's own frame bears its target's id, as Chrome's does.)
        await event("Fetch.requestPaused", {"requestId": request_id, "resourceType": kind,
                                            "frameId": frame, "request": {"url": url}}, None)
        return await verdicts[request_id]

    async def navigate(url: str) -> None:
        await event("Page.frameStartedLoading", {"frameId": "f1"})
        if not await paused(url, "Document"):
            state["html"], state["url"] = "", "chrome-error://chromewebdata/"
        else:
            try:
                state["html"], state["url"] = fetch(url), url
            except OSError:
                state["html"], state["url"] = "", "chrome-error://chromewebdata/"
            state["scroll"] = 0.0
            for src in re.findall(r'<iframe[^>]*src="([^"]+)"', state["html"]):
                await paused(urllib.parse.urljoin(url, src), "Document", "f2")
            # A page's alert('...') holds its load till the dialog is answered, as Chrome's does.
            for said in re.findall(r"alert\('([^']*)'\)", state["html"]):
                dialogs.append(asyncio.get_running_loop().create_future())
                await event("Page.javascriptDialogOpening", {"message": said, "type": "alert"})
                state["dialog"] = await dialogs[-1]
            await event("Runtime.consoleAPICalled", {
                "type": "log", "args": [{"type": "string",
                                         "value": f"fake browser: loaded {state['url']}"}]})
        await event("Page.loadEventFired", {"timestamp": 1.0})

    async for raw in ws:
        message = json.loads(raw)
        method, params = message["method"], message.get("params", {})
        result: dict = {}
        if method == "Page.handleJavaScriptDialog":
            dialogs[-1].set_result(params.get("accept"))
            continue
        if method in ("Fetch.continueRequest", "Fetch.failRequest"):
            verdicts[params["requestId"]].set_result(method == "Fetch.continueRequest")
            continue  # (the driver waits for no answer to these)
        if method == "Browser.getVersion":
            result = {"product": "FakeChrome/1.0", "protocolVersion": "1.3"}
        elif method == "Target.createTarget":
            result = {"targetId": "t1"}
        elif method == "Target.attachToTarget":
            result = {"sessionId": "s1"}
        elif method == "Page.navigate":
            asyncio.ensure_future(navigate(params["url"]))
        elif method == "Page.createIsolatedWorld":
            result = {"executionContextId": 7}
        elif method == "Runtime.evaluate":
            result = {"result": {"value": evaluate(params["expression"])}}
        elif method == "Page.captureScreenshot":
            result = {"data": __import__("base64").b64encode(PNG).decode("ascii")}
        elif method == "Accessibility.getFullAXTree":
            nodes = [{"role": {"value": "RootWebArea"}, "name": {"value": title_of(state["html"])}}]
            for tag, words in re.findall(r"(?s)<(button|a)[^>]*>(.*?)</\1>", state["html"]):
                nodes.append({"role": {"value": "button" if tag == "button" else "link"},
                              "name": {"value": text_of(words)}})
            result = {"nodes": nodes}
        elif method == "Input.insertText":
            state["typed"]["last"] = params["text"]
        elif method == "Input.dispatchMouseEvent" and params["type"] == "mouseWheel":
            state["scroll"] += params["deltaY"]
        elif method == "Browser.close":
            await ws.send(json.dumps({"id": message["id"], "result": {}}))
            sys.exit(0)
        elif method == "Fake.huge":  # (a test's: one message over the limit, no close frame)
            await ws.send(json.dumps({"method": "Runtime.consoleAPICalled", "params": {
                "type": "log", "args": [{"type": "string", "value": "x" * params["size"]}]}}))
            continue
        elif method == "Fake.drop":  # (a test's: the connection drops, the browser runs on)
            await ws.close()
            return
        await ws.send(json.dumps({"id": message["id"], "result": result}))


async def main() -> None:
    # (No size limit: the draw.io viewer's script, K-drawio, is some 5 MB.)
    async with websockets.serve(serve, "127.0.0.1", 0, max_size=None) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        (profile / "DevToolsActivePort").write_text(f"{port}\n/devtools/browser/fake")
        await asyncio.Future()


asyncio.run(main())
