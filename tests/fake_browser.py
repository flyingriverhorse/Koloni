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
import html.parser
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
        return Path(
            urllib.request.url2pathname(url[5:].lstrip("/") if sys.platform == "win32" else url[7:])
        ).read_text(encoding="utf-8")
    # K-tarayici-disari: a site of a test's (site.test) is a server on loopback, as
    # --host-resolver-rules "MAP site.test 127.0.0.1" has it in Chrome.
    parts = urllib.parse.urlsplit(url)
    if (parts.hostname or "").endswith(".test"):
        url = parts._replace(netloc=f"127.0.0.1:{parts.port}").geturl()
    with urllib.request.urlopen(url, timeout=5) as answer:  # noqa: S310 (loopback: vetted by the driver)
        return answer.read().decode("utf-8", errors="replace")


def told(name: str, page: str) -> str | None:
    """What the page says of itself; None for a name that asks anything else."""
    if name == "url":
        return state["url"]
    if name == "title":
        return title_of(page)
    if name == "text":
        return text_of(page)
    if name == "scrolly":
        return str(state["scroll"])
    if name == "here":
        return f"{state['url']} {state['scroll']}"
    if name == "wide":  # (S5b: a test's page says from which width it fits: data-fits-from)
        fits = re.search(r'data-fits-from="(\d+)"', page)
        return bool(fits) and state.get("width", 1280) < int(fits[1])
    return None


# Pages accessibility (0.1.7): what `app.browser._A11Y` reads in a page, from a test page's own
# inline styles alone - an image with no text for it, a control with no name, each text's colour
# over the backgrounds of the elements it is in up to the first opaque one; a style that hides
# (display: none) or aria-hidden as Chrome would see it. Only what the tests' pages use.
_COLOURS = {"white": [255, 255, 255, 1.0], "black": [0, 0, 0, 1.0], "transparent": [0, 0, 0, 0.0]}
_VOID = {"img", "input", "br", "hr", "meta", "link", "source", "wbr", "area", "col", "embed"}
_UNREAD = {"script", "style", "title", "head", "noscript", "template", "option"}


def colour(value: str) -> list | None:
    value = value.strip().lower()
    if value in _COLOURS:
        return list(_COLOURS[value])
    if re.fullmatch(r"#[0-9a-f]{3}|#[0-9a-f]{6}", value):
        digits = value[1:] if len(value) == 7 else "".join(c * 2 for c in value[1:])
        return [int(digits[i : i + 2], 16) for i in (0, 2, 4)] + [1.0]
    if found := re.fullmatch(r"rgba?\(([^)]*)\)", value):
        parts = [float(p) for p in re.split(r"[\s,/]+", found[1].strip())]
        return parts[:3] + [parts[3] if len(parts) > 3 else 1.0]
    return None


class Read(html.parser.HTMLParser):
    def __init__(self, bounds: dict):
        super().__init__(convert_charrefs=True)
        self.bounds, self.seen, self.styles = bounds, 0, {}
        self.out = {
            "cut": False,
            "images": [],
            "imagesN": 0,
            "controls": [],
            "controlsN": 0,
            "texts": [],
        }
        self.open: list[dict] = []
        self.fields: list[tuple[int, dict, bool]] = []
        self.labelled: set[str] = set()
        self.unnamed: list[tuple[int, str]] = []  # (in the page's order, as Chrome's walk)

    def _listed(self, kind: str, what: str) -> None:
        self.out[kind + "N"] += 1
        if len(self.out[kind]) < self.bounds["listed"]:
            self.out[kind].append(what[:80])

    def _hidden(self) -> bool:
        return any(
            one["style"].get("display") == "none" or one["attrs"].get("aria-hidden") == "true"
            for one in self.open
        )

    def handle_starttag(self, tag: str, pairs: list) -> None:
        attrs = {k: v or "" for k, v in pairs}
        # (Counted from the body on, as Chrome's walk is.)
        self.seen += tag == "body" or any(one["tag"] == "body" for one in self.open)
        if self.seen > self.bounds["most"]:
            self.out["cut"] = True
        style = {
            k.strip().lower(): v.strip()
            for k, _, v in (one.partition(":") for one in attrs.get("style", "").split(";"))
            if v
        }
        up = self.open[-1] if self.open else {"colour": [0, 0, 0, 1.0], "px": 16.0, "weight": 400}
        one = {
            "tag": tag,
            "attrs": attrs,
            "style": style,
            "colour": colour(style.get("color", "")) or up["colour"],
            "px": float(style["font-size"].removesuffix("px"))
            if "font-size" in style
            else up["px"],
            "weight": 700
            if tag in ("b", "strong") or style.get("font-weight") in ("bold", "700")
            else up["weight"],
            "words": [],
            "at": self.seen,
        }
        if tag == "label" and attrs.get("for"):
            self.labelled.add(attrs["for"])
        if not self.out["cut"] and not self._hidden():
            self._start(tag, attrs)
        if tag not in _VOID:
            self.open.append(one)

    def _start(self, tag: str, attrs: dict) -> None:
        named = " ".join(attrs.get(k, "") for k in ("aria-label", "title", "aria-labelledby"))
        if tag == "img":
            for control in self.open:
                control["words"].append(attrs.get("alt", ""))
            told = attrs.get("aria-hidden") != "true" and attrs.get("role") not in (
                "none",
                "presentation",
            )
            if "alt" not in attrs and not named.strip() and told:
                src = re.split(r"[?#]", attrs.get("src", ""))[0].rsplit("/", 1)[-1]
                self._listed("images", src or "img")
        if tag == "input" and attrs.get("type") != "hidden" and "disabled" not in attrs:
            wrapped = any(one["tag"] == "label" for one in self.open)
            self.fields.append((self.seen, attrs, wrapped))

    def handle_endtag(self, tag: str) -> None:
        while self.open:
            one = self.open.pop()
            control = one["tag"] == "button" or one["tag"] == "a" and "href" in one["attrs"]
            if control and not self.out["cut"] and not self._hidden():
                words = " ".join(
                    [*one["words"], *(one["attrs"].get(k, "") for k in ("aria-label", "title"))]
                )
                if not words.strip() and "disabled" not in one["attrs"]:
                    how = f"[href={one['attrs']['href']}]" if one["tag"] == "a" else ""
                    ident = f"#{one['attrs']['id']}" if one["attrs"].get("id") else ""
                    self.unnamed.append((one["at"], one["tag"] + how + ident))
            if one["tag"] == tag:
                return

    def handle_data(self, data: str) -> None:
        for one in self.open:
            one["words"].append(data)
        words = " ".join(data.split())
        if not words or not self.open or self.out["cut"] or self._hidden():
            return
        if any(one["tag"] in _UNREAD or "disabled" in one["attrs"] for one in self.open):
            return
        top, layers, image = self.open[-1], [], False
        for one in reversed(self.open):
            back = one["style"].get("background-color") or one["style"].get("background", "")
            if "url(" in back or "gradient(" in back or one["style"].get("background-image"):
                image = True
                break
            if (under := colour(back)) is not None and under[3] > 0:
                layers.append(under)
                if under[3] >= 1:
                    break
        key = json.dumps([top["colour"], layers, image, top["px"], top["weight"]])
        if key not in self.styles:
            if len(self.styles) >= self.bounds["styles"]:
                self.out["cut"] = True
                return
            self.styles[key] = {
                "words": words[:80],
                "color": top["colour"],
                "under": None if image else layers,
                "px": top["px"],
                "weight": top["weight"],
                "n": 0,
            }
            self.out["texts"].append(self.styles[key])
        self.styles[key]["n"] += 1

    def close(self) -> None:
        super().close()
        for at, attrs, wrapped in self.fields:
            kind = attrs.get("type", "text")
            said = " ".join(attrs.get(k, "") for k in ("aria-label", "title", "placeholder"))
            said += attrs.get("value", "") if kind in ("submit", "reset", "button") else ""
            said += attrs.get("alt", "") if kind == "image" else ""
            if not (
                wrapped
                or attrs.get("id") in self.labelled
                or said.strip()
                or kind in ("submit", "reset")
            ):
                ident = f"#{attrs['id']}" if attrs.get("id") else ""
                self.unnamed.append((at, f"input[type={kind}]{ident}"))
        for _at, what in sorted(self.unnamed):
            self._listed("controls", what)


def accessed(page: str, bounds: dict) -> dict:
    read = Read(bounds)
    read.feed(page)
    read.close()
    return read.out


def focus(arg: str | None) -> str | None:
    if arg is not None and _has(arg):
        state["focused"] = arg
    if arg is None:
        return "input#focused"
    return f"input{arg}" if _has(arg) else None


def what(arg: dict, page: str) -> str:
    out = {
        "host": urllib.parse.urlsplit(state["url"]).hostname or "",
        "words": "",
        "password": False,
        "posts": False,
        "frame": False,
        "editable": False,
        "hidden": False,
    }
    if "x" in arg:
        # (A mark's centre is its button's; any other point the last element found.)
        out["words"] = words = state.get("marks", {}).get(
            (arg["x"], arg["y"]), state.get("found", "")
        )
        out["posts"] = bool(words) and bool(
            re.search(r'(?is)<form[^>]*method="post".*?<button[^>]*>\s*' + re.escape(words), page)
        )
    elif selector := arg.get("selector") or state.get("focused"):
        tag = re.search(r'<input[^>]*id="' + re.escape(selector[1:]) + r'"[^>]*>', page)
        out["password"] = bool(tag) and 'type="password"' in tag[0]
        out["editable"] = bool(tag)
    return json.dumps(out)


def evaluate(expression: str) -> object:
    head = re.match(r"/\*koloni:(\w+) (.*?)\*/", expression)
    assert head, expression[:80]
    name, arg = head[1], json.loads(head[2])
    page = state["html"]
    if (said := told(name, page)) is not None:
        return said
    if name == "find":
        state["found"] = arg
        found = re.search(r"(?s)<(button|a)[^>]*>\s*" + re.escape(arg) + r"\s*</\1>", page)
        return json.dumps({"x": 10, "y": 20, "width": 80, "height": 30}) if found else None
    if name == "rect":
        return json.dumps({"x": 10, "y": 60, "width": 200, "height": 30}) if _has(arg) else None
    if name == "focus":
        return focus(arg)
    if name == "a11y":  # (a test's page that says it hangs: as a script that keeps Chrome busy)
        return "hung" if "data-a11y-hangs" in page else accessed(page, arg)
    # K-tarayici-disari A2: what a click (at the last element found) or typing would reach.
    if name == "what":
        return what(arg, page)
    # K-gorsel-motor: each button and link marked, one under the other; where the page is.
    if name == "marks":
        found = [
            text_of(words) for _tag, words in re.findall(r"(?s)<(button|a)[^>]*>(.*?)</\1>", page)
        ][:arg]
        state["marks"] = {(100, 100 + 40 * n): words for n, words in enumerate(found)}
        return json.dumps(
            {
                "here": evaluate("/*koloni:here null*/"),
                "marks": [
                    {"kind": "button", "words": words, "x": x, "y": y}
                    for (x, y), words in state["marks"].items()
                ],
            }
        )
    if name == "unmark":
        return None
    # K-drawio (`app.diagram.draw`): the viewer's scripts, then the picture it draws.
    if name == "script":
        return None
    if name == "drawio":
        return (
            '<svg xmlns="http://www.w3.org/2000/svg"/>'
            if arg == "svg"
            else "data:image/png;base64," + __import__("base64").b64encode(PNG).decode()
        )
    raise AssertionError(name)


def _has(selector: str) -> bool:
    return selector.startswith("#") and f'id="{selector[1:]}"' in state["html"]


def answer(method: str, params: dict) -> dict:
    """What a method that only reads the page, or sets what is typed or scrolled, answers."""
    result: dict = {}
    if method == "Browser.getVersion":
        result = {"product": "FakeChrome/1.0", "protocolVersion": "1.3"}
    elif method == "Target.createTarget":
        result = {"targetId": "t1"}
    elif method == "Target.attachToTarget":
        result = {"sessionId": "s1"}
    elif method == "Page.createIsolatedWorld":
        result = {"executionContextId": 7}
    elif method == "Runtime.evaluate":
        result = {"result": {"value": evaluate(params["expression"])}}
    elif method == "Page.captureScreenshot":
        result = {"data": __import__("base64").b64encode(PNG).decode("ascii")}
    elif method == "Accessibility.getFullAXTree":
        nodes = [{"role": {"value": "RootWebArea"}, "name": {"value": title_of(state["html"])}}]
        for tag, words in re.findall(r"(?s)<(button|a)[^>]*>(.*?)</\1>", state["html"]):
            nodes.append(
                {
                    "role": {"value": "button" if tag == "button" else "link"},
                    "name": {"value": text_of(words)},
                }
            )
        result = {"nodes": nodes}
    elif method == "Emulation.setDeviceMetricsOverride":
        state["width"] = params["width"]
    elif method == "Input.insertText":
        state["typed"]["last"] = params["text"]
    elif method == "Input.dispatchMouseEvent" and params["type"] == "mouseWheel":
        state["scroll"] += params["deltaY"]
    return result


async def navigate(url: str, event, paused, dialogs: list[asyncio.Future]) -> None:
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
        await event(
            "Runtime.consoleAPICalled",
            {
                "type": "log",
                "args": [{"type": "string", "value": f"fake browser: loaded {state['url']}"}],
            },
        )
        # S5b: a page's console.error('...') is said as Chrome says it; a script it loads is
        # paused and judged as Chrome's are - one refused is a failed load in its log.
        for said in re.findall(r"console\.error\('([^']*)'\)", state["html"]):
            await event(
                "Runtime.consoleAPICalled",
                {"type": "error", "args": [{"type": "string", "value": said}]},
            )
        for src in re.findall(r'<script[^>]*src="([^"]+)"', state["html"]):
            if not await paused(urllib.parse.urljoin(url, src), "Script"):
                await event(
                    "Log.entryAdded",
                    {
                        "entry": {
                            "source": "network",
                            "level": "error",
                            "url": src,
                            "text": "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT",
                        }
                    },
                )
    await event("Page.loadEventFired", {"timestamp": 1.0})


async def serve(ws) -> None:
    async def event(method: str, params: dict, session: str | None = "s1") -> None:
        await ws.send(
            json.dumps(
                {"method": method, "params": params, **({"sessionId": session} if session else {})}
            )
        )

    # Each load is paused for the driver's judge, as Chrome does at the browser's own Fetch.enable
    # (no sessionId): continueRequest or failRequest decides it.
    verdicts: dict[str, asyncio.Future] = {}
    dialogs: list[asyncio.Future] = []

    async def paused(url: str, kind: str, frame: str = "t1") -> bool:
        request_id = f"r{len(verdicts)}"
        verdicts[request_id] = asyncio.get_running_loop().create_future()
        # (The page's own frame bears its target's id, as Chrome's does.)
        await event(
            "Fetch.requestPaused",
            {
                "requestId": request_id,
                "resourceType": kind,
                "frameId": frame,
                "request": {"url": url},
            },
            None,
        )
        return await verdicts[request_id]

    async for raw in ws:
        message = json.loads(raw)
        method, params = message["method"], message.get("params", {})
        if method == "Page.handleJavaScriptDialog":
            dialogs[-1].set_result(params.get("accept"))
            continue
        if method in ("Fetch.continueRequest", "Fetch.failRequest"):
            verdicts[params["requestId"]].set_result(method == "Fetch.continueRequest")
            continue  # (the driver waits for no answer to these)
        if method == "Page.navigate":
            asyncio.ensure_future(navigate(params["url"], event, paused, dialogs))
        elif method == "Browser.close":
            await ws.send(json.dumps({"id": message["id"], "result": {}}))
            sys.exit(0)
        elif method == "Fake.huge":  # (a test's: one message over the limit, no close frame)
            await ws.send(
                json.dumps(
                    {
                        "method": "Runtime.consoleAPICalled",
                        "params": {
                            "type": "log",
                            "args": [{"type": "string", "value": "x" * params["size"]}],
                        },
                    }
                )
            )
            continue
        elif method == "Fake.drop":  # (a test's: the connection drops, the browser runs on)
            await ws.close()
            return
        await ws.send(json.dumps({"id": message["id"], "result": answer(method, params)}))


async def main() -> None:
    # (No size limit: the draw.io viewer's script, K-drawio, is some 5 MB.)
    async with websockets.serve(serve, "127.0.0.1", 0, max_size=None) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        (profile / "DevToolsActivePort").write_text(f"{port}\n/devtools/browser/fake")
        await asyncio.Future()


asyncio.run(main())
