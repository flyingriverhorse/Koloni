"""Slice 51: the agent tries a page itself. Chrome or Edge already on this machine runs
headless, in an empty profile of its own under the project's scratch, driven over the DevTools
protocol on a websocket (`websockets`); nothing is downloaded, the user's own profile is never
touched. Only this machine's previews are opened (`allowed`): a loopback address on a port that
is neither KOLONİ's own nor a model server's, or a file of the project - and, in a browser of
its own (`Browser.away`), the sites the user allowed (K-tarayici-disari, `outside`).
Every other port on this machine is open to the page - that is the design (a preview and the
servers it calls); what the page loads by itself is judged the same way (`Browser._judge`).

Measured 3 Nov 2026 on this machine, Chrome 156.0.8078.73 and Edge 156.0.4314.58, both headless:
`DevToolsActivePort` (port, then the browser's websocket path) is in the profile within ~0.5 s;
one websocket to it takes Browser.getVersion, Target.createTarget / attachToTarget (flatten: the
page's calls carry its sessionId), Page.enable / navigate / loadEventFired / captureScreenshot,
Runtime.enable / evaluate / consoleAPICalled / exceptionThrown, Log.enable / entryAdded,
Accessibility.getFullAXTree, Emulation.setDeviceMetricsOverride, Input.dispatchMouseEvent /
insertText / dispatchKeyEvent, Browser.close (the process exits 0 within a second). `--version`
is no measure: with the user's Chrome open it prints "Opening in existing browser session."
"""

import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlsplit

import websockets

from app import web
from app.command_runner import port_of
from app.executors.host import SUSPENDED, ProcessCommand, _job_for, command_env
from app.koloni import SCRATCH
from app.workspace import Workspace, WorkspaceError, is_secret

NONE = "no Chrome or Edge on this machine: the browser tools cannot run"
# shortcut: a Chromium download (~150 MB) could be offered on a card with the user's yes
# (design §51); not before they say so.
NOT_HERE = ("only this machine's previews (51), and sites the user allows: browser_open asks "
            "for one")
ENDED = ("the browser ended (its connection to KOLONİ dropped, or a frame of the page could "
         "not be guarded): browser_open starts a new one")
BLANK = "about:blank"
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
# What a browser that went out never resolves (`Browser.start`): this machine and its network
# by name, or by address as Chrome writes one (an IPv6 one: none at all, "*::*" - Chrome
# matches a rule against host:port too, so "*:*" took every name, B-361, measured).
# shortcut: an IPv6 address with no "::" (fd00:1:2:3:4:5:6:7) passes this backstop; the
# judge (`site_of`) and the page's guard refuse it - a rule per private prefix if one is seen.
# The names a home or an office network gives its own machines: never a site (`site_of`).
NETWORK_NAMES = (".localhost", ".local", ".lan", ".internal", ".home.arpa", ".corp",
                 ".localdomain", ".intranet", ".home")
INSIDE = ("localhost", *(f"*{tail}" for tail in NETWORK_NAMES), "127.*", "10.*", "0.*",
          "192.168.*", "169.254.*", *(f"172.{n}.*" for n in range(16, 32)), "*::*")
WIDTH, HEIGHT = 1280, 720
MAX_READ = 20_000
MAX_CONSOLE = 100
LOAD_WAIT = 10.0
# A ceiling, not a pace: a cold start on a busy machine (a CI runner) went past 10 s.
START_WAIT = 30.0
# The keys Chrome needs a Windows key code for besides the name; Enter carries "\r" as its
# text so that a form takes it (measured: without the text the field keeps the focus and
# nothing is submitted).
KEYS = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "Delete": 46, "ArrowLeft": 37,
        "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40, "Home": 36, "End": 35, "PageUp": 33,
        "PageDown": 34, " ": 32}
# What of a page's accessibility tree is worth a line: what one can act on or read by.
AX_ROLES = frozenset({
    "heading", "link", "button", "textbox", "checkbox", "radio", "combobox", "listbox",
    "option", "menuitem", "tab", "switch", "slider", "searchbox", "spinbutton", "img",
    "RootWebArea", "dialog", "alert", "status", "cell", "columnheader", "row", "listitem",
})


class BrowserError(Exception):
    """The browser could not do it; the message goes back to the agent."""


def find_browser() -> list[str] | None:
    """The command that starts a browser: the stand-in KOLONI_BROWSER_FAKE names (a Python
    script, for tests), else Chrome, else Edge - where Windows installs them (Program Files,
    its x86, the user's own), or on PATH elsewhere. None: nothing to drive."""
    fake = os.environ.get("KOLONI_BROWSER_FAKE")
    if fake:
        return [sys.executable, fake]
    if sys.platform == "win32":
        roots = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for tail in (r"Google\Chrome\Application\chrome.exe",
                     r"Microsoft\Edge\Application\msedge.exe"):
            for root in filter(None, roots):
                if (exe := Path(root) / tail).is_file():
                    return [str(exe)]
        return None
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        if found := shutil.which(name):
            return [found]
    return None


def allowed(url: object, ws: Workspace, closed: set[int]) -> str:  # noqa: C901
    """The address as the browser is given it, if it is on this machine: http(s) on loopback
    on a port that is neither KOLONİ's own nor a model server's (`closed`), or a file of the
    project (file://, or a path in it). BrowserError says why not."""
    if not isinstance(url, str) or not url.strip():
        raise BrowserError("missing required argument: url")
    url = url.strip()
    if url == BLANK:
        return url
    parts = urlsplit(url)
    if parts.scheme in ("http", "https"):
        # Python and Chrome read a backslash, a user part and an escaped @ apart (measured:
        # Chrome opened 127.0.0.1:47003 where Python saw :47000): none in an address here.
        if "\\" in url or "@" in parts.netloc or "%" in parts.netloc:
            raise BrowserError(f"{url}: an address with \\, @ or % before its path; {NOT_HERE}")
        if (parts.hostname or "") not in LOOPBACK:
            raise BrowserError(f"{url} is not on this machine: {NOT_HERE}")
        port = port_of(url)
        if port is None:  # (not a port Python can read: it would be judged as none)
            raise BrowserError(f"{url}: no port that can be read; {NOT_HERE}")
        if port in closed:
            raise BrowserError(
                f"port {port} is KOLONİ's own or a model server's: not opened; {NOT_HERE}")
        return url
    if parts.scheme and parts.scheme != "file":
        raise BrowserError(f"{url}: not a web address of this machine; {NOT_HERE}")
    path = url
    if parts.scheme == "file":
        if parts.netloc not in ("", "localhost"):
            raise BrowserError(f"{url} is not a file of the project; {NOT_HERE}")
        # (file:///C:/x is the path /C:/x: the drive comes after the slash)
        path = unquote(parts.path)
        path = path[1:] if sys.platform == "win32" and re.match(r"/[A-Za-z]:", path) else path
    try:
        target = ws.resolve(path)
    except WorkspaceError as exc:
        raise BrowserError(f"{url}: {exc}; {NOT_HERE}") from None
    # (Resolvable is not enough: a folder the user granted, or a CLI's file, is no page here.)
    if not ws.is_own(target) or not target.is_file():
        raise BrowserError(f"{url} is not a file of the project; {NOT_HERE}")
    # The browser's own profile (its cookies, its cache) is no page; its screenshots are.
    held = ws.rel(target).casefold()
    if held.startswith(f"{SCRATCH}/browser/") and not held.startswith(f"{SCRATCH}/browser/shots/"):
        raise BrowserError(f"{url} is the browser's own profile: it is never opened")
    if is_secret(ws.rel(target)):  # (as `app.views`: a secret is never put on a page)
        raise BrowserError(f"{url} is a secret file (keys, passwords): it is never opened")
    return target.as_uri()


def site_of(url: object) -> str | None:
    """K-tarayici-disari: the host of the outside site `url` names (lower case) - None for
    anything else, which `allowed` judges (this machine's preview, a file). BrowserError for an
    address of this machine or its network written another way, and for one Python and Chrome
    could read apart."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or (parts.hostname or "") in LOOPBACK:
        return None
    if "\\" in url or "@" in parts.netloc or "%" in parts.netloc:
        raise BrowserError(f"{url}: an address with \\, @ or % before its path; {NOT_HERE}")
    # shortcut: a name in letters beyond ASCII is kept as written, and Chrome's punycode of it
    # is then no site on the list (refused, never let through); write both if that is seen.
    try:
        host = web.host_of(url)
    except web.WebError as exc:
        raise BrowserError(f"{url}: {exc}") from None
    # A name of one word (a printer, this machine's own) or of a home network's is inside.
    if "." not in host or host.endswith(NETWORK_NAMES):
        raise BrowserError(f"{url}: {host} {web.INSIDE}")
    return host


async def looked_up(url: str) -> None:
    """A site's page is opened only where its name stands for addresses out on the internet
    alone, as a web request is (`web.check`): a public name of a private address - wildcard
    DNS, a rebinding name - is refused. Looked up only after the user's yes.
    shortcut: Chrome looks the name up again itself; a name that rebinds between the two
    still reaches inside (for a page over http: a preview over https does not answer TLS).
    Pin the address (a resolver rule per name) if that is seen."""
    # The e2e run (start-backend.mjs): its stand-in browser takes a test's own name (.test is
    # reserved, never a real site) to loopback itself; no DNS server is asked of it. Never with
    # a real Chrome, which a hosts entry for a .test name would take inside.
    if os.environ.get("KOLONI_E2E_NAMES") and os.environ.get("KOLONI_BROWSER_FAKE") and (
            urlsplit(url).hostname or "").endswith(".test"):
        return
    try:
        await asyncio.wait_for(web.check(url), LOAD_WAIT)
    except web.WebError as exc:
        raise BrowserError(f"{url}: {exc}") from None
    except TimeoutError:
        raise BrowserError(f"{url}: its name was not looked up in {LOAD_WAIT:.0f} s") from None


def outside(url: str, sites: frozenset[str], closed: set[int], main: bool) -> None:
    """What a browser that went out (`Browser.away`) loads: the page itself (`main`) only from
    a site the user allowed, over http(s) on any port; anything the page loads besides over
    https from any host out on the internet - modern pages need their CDNs. Never this machine
    nor its network, a file, or a closed port (KOLONİ's own, a model server's): a name that
    stands for one of those still resolves to it (DNS rebinding).
    shortcut: judged by the name, not by what it resolves to - a public name of a private
    address reaches it over https (a preview over http does not answer TLS); resolve and judge
    the address in a proxy of KOLONİ's own if that is seen.
    shortcut: https from any host is a way out for what the page holds (`fetch` to anywhere);
    the user trusted the site - limit to the site and a CDN list if that is seen to matter.
    BrowserError says why not."""
    host = site_of(url)
    if host is None:
        raise BrowserError(f"{url}: a site's page does not reach this machine or a file")
    if port_of(url) in closed:
        raise BrowserError(f"{url}: a closed port (KOLONİ's own or a model server's)")
    if main and host not in sites:
        raise BrowserError(f"{host} is not a site the user allowed: browser_open asks for it")
    if not main and not url.startswith("https:"):
        raise BrowserError(f"{url}: only https is loaded by a site's page")


def _tag(name: str, arg: object = None) -> str:
    """The first line of every expression the driver evaluates names what it asks, with its
    argument as JSON: the stand-in browser (tests/fake_browser.py) answers by that line alone."""
    return f"/*koloni:{name} {json.dumps(arg)}*/\n"


def _find_js(text: str) -> str:
    """Finds the first element that reads as `text` (a button's, link's or label's words, a
    field's placeholder or title) and gives its box, scrolled into view; null if none."""
    return _tag("find", text) + """
(function (want) {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const all = document.querySelectorAll('button, a, [role], input, select, textarea, label, '
    + 'summary, option, li, td, th, h1, h2, h3, h4, span, div, p');
  for (const el of all) {
    const words = [el.innerText, el.value, el.getAttribute('aria-label'), el.placeholder,
      el.title, el.alt].map(norm).filter(Boolean);
    const acts = el.matches('button, a, input, select, textarea, label, summary, option, [role]');
    if (words.some(w => w === want) || (acts && words.some(w => w.includes(want)))) {
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect();
      if (r.width || r.height) {
        return JSON.stringify({ x: r.x, y: r.y, width: r.width, height: r.height });
      }
    }
  }
  return null;
})(""" + json.dumps(text) + ")"


def _rect_js(selector: str) -> str:
    return _tag("rect", selector) + """
(function (sel) {
  const el = document.querySelector(sel);
  if (!el) return null;
  el.scrollIntoView({ block: 'center' });
  const r = el.getBoundingClientRect();
  return JSON.stringify({ x: r.x, y: r.y, width: r.width, height: r.height });
})(""" + json.dumps(selector) + ")"


def _focus_js(selector: str | None) -> str:
    """Puts the focus in the field (the one already focused if none is named) and selects what
    is in it, so that what is typed takes its place; the field's name, or null if none."""
    return _tag("focus", selector) + """
(function (sel) {
  const el = sel ? document.querySelector(sel) : document.activeElement;
  if (!el || el === document.body) return null;
  el.focus();
  if (typeof el.select === 'function') el.select();
  return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
    + (el.name ? '[name=' + el.name + ']' : '');
})(""" + json.dumps(selector) + ")"


# K-gorsel-motor: where the page is - its address and scroll - as marks were taken there
# (`Browser.point`: a mark of another page or scroll is refused).
_HERE = "location.href + ' ' + scrollX + ' ' + scrollY"
_HERE_JS = _tag("here") + _HERE
MAX_MARKS = 60
_UNMARK_JS = _tag("unmark") + (
    "document.querySelectorAll('[data-koloni-marks]').forEach(e => e.remove())")


def _marks_js() -> str:
    """Stamps a numbered label on each element `_find_js` looks through that is seen in the
    viewport and not covered - what one acts on first (an icon's button has no words), then
    what has words of its own outside them - at most MAX_MARKS; their kinds, words and centres,
    and where the page is (`_HERE`), as JSON. Nothing is scrolled: the picture is as it was.
    shortcut: the page's own document only - a frame's or a shadow root's elements are clicked
    by x, y."""
    return _tag("marks", MAX_MARKS) + """
(function (most) {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const acts = 'button, a, input, select, textarea, label, summary, option, [role]';
  const fields = ['text', 'search', 'email', 'url', 'tel', 'number', 'password'];
  const kinds = { a: 'link', select: 'combobox', textarea: 'textbox' };
  const layer = document.createElement('div');
  layer.setAttribute('data-koloni-marks', '');
  const marks = [];
  const take = el => {
    const r = el.getBoundingClientRect();
    const left = Math.max(r.left, 0), top = Math.max(r.top, 0);
    const right = Math.min(r.right, innerWidth), bottom = Math.min(r.bottom, innerHeight);
    if (right <= left || bottom <= top) return;
    const x = (left + right) / 2, y = (top + bottom) / 2, at = document.elementFromPoint(x, y);
    if (!at || !(at === el || el.contains(at))) return;
    const kind = el.getAttribute('role') || (el.localName === 'input'
      ? (fields.includes(el.type) ? 'textbox' : el.type) : kinds[el.localName] || el.localName);
    const words = [el.innerText, el.type === 'password' ? '' : el.value,
      el.getAttribute('aria-label'), el.placeholder, el.title, el.alt].map(norm).find(Boolean);
    marks.push({ kind, words: (words || '').slice(0, 40), x, y });
    const tag = layer.appendChild(document.createElement('span'));
    tag.textContent = marks.length;
    tag.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;'
      + 'background:#ffd400;color:#000;border:1px solid #000;font:bold 11px/12px sans-serif;'
      + 'padding:0 2px;left:' + left + 'px;top:' + top + 'px';
  };
  for (const el of document.querySelectorAll(acts)) {
    if (marks.length >= most) break;
    take(el);
  }
  const own = el => [...el.childNodes].some(n => n.nodeType === 3 && norm(n.textContent));
  for (const el of document.querySelectorAll('li, td, th, h1, h2, h3, h4, span, div, p')) {
    if (marks.length >= most) break;
    if (!el.matches(acts) && own(el) && !el.parentElement.closest(acts)) take(el);
  }
  document.documentElement.appendChild(layer);
  return JSON.stringify({ here: """ + _HERE + """, marks });
})(""" + json.dumps(MAX_MARKS) + ")"


# Run in every document of every page and frame before its own scripts (Page.
# addScriptToEvaluateOnNewDocument, on each target as it is attached). Measured (Chrome 156):
# WebRTC sends STUN over UDP to any address whatever the resolver rule, a proxy or
# --force-webrtc-ip-handling-policy say; with these gone a page - and an iframe it makes with no
# address - has no RTCPeerConnection, and no UDP is sent. Fetch does not see a WebSocket, nor
# does Network.setBlockedURLs stop one (measured): a page's to a closed port is refused here,
# the original constructor hidden from its prototype too.
# A browser that went out (`away`) refuses a socket as `outside` does a load: wss to a name or
# a public address only.
# shortcut: carrier NAT (100.64/10) and IPv4-mapped forms are refused by `outside` for a load,
# not by this guard nor the resolver backstop; add them if a socket there is seen.
# A dedicated worker is given it too, before its script (`_attached`). Chrome refuses its
# DevTools socket to any page or worker (measured).
# shortcut: a service worker is not attached waiting (measured), so it is not guarded: its
# WebSocket reaches a closed port - KOLONİ's own, a model server's - a GET it cannot read the
# answer of; and, gone out, a name that resolves inside. Guard it (Target.setAutoAttach at the
# browser) if that is seen. A shared worker is guarded as a worker, unmeasured.
# The closed ports here are those at the browser's start (Fetch's are kept fresh): restart the
# browser on a provider's change if a socket to a new one is seen to matter.
GUARD = """
delete globalThis.RTCPeerConnection; delete globalThis.webkitRTCPeerConnection;
delete globalThis.RTCDataChannel;
(() => {
  const Socket = globalThis.WebSocket, closed = %s, away = %s;
  // (One word, an IPv6 address, a home network's name - as `site_of` - or a private address.)
  const named = /^([^.]*|\\[.*\\])$/;
  const homes = /\\.(localhost|local|lan|internal|home\\.arpa|corp|localdomain|intranet|home)$/;
  const numbered = /^(127|10|0|192\\.168|169\\.254|172\\.(1[6-9]|2[0-9]|3[01]))\\./;
  const inside = h => named.test(h) || homes.test(h) || numbered.test(h);
  globalThis.WebSocket = function (url, protocols) {
    url = String(url);  // (once: a value whose toString changes is judged as it is sent)
    const at = new URL(url, location.href);
    if (closed.includes(+(at.port || (at.protocol === 'wss:' ? 443 : 80))))
      throw new DOMException('refused by KOLONI: a closed port', 'SecurityError');
    if (away && (at.protocol !== 'wss:' || inside(at.hostname)))
      throw new DOMException('refused by KOLONI: a site has wss out only', 'SecurityError');
    return new Socket(url, protocols);
  };
  globalThis.WebSocket.prototype = Socket.prototype;
  Object.defineProperty(Socket.prototype, 'constructor', { value: globalThis.WebSocket });
})();
"""
# What reaches nothing and is never paused for a judge (Chrome's own extensions' scripts too).
LOCAL = ("data:", "blob:", "about:", "chrome-extension:")
MAX_REFUSED = 8
# The largest message from Chrome the driver reads (a screenshot, a page's text); a larger one
# (a page logging 70 MB) ends the browser.
MAX_MESSAGE = 64 * 1024 * 1024
MAX_DIALOG = 200
SHOTS_KEPT = 7 * 24 * 3600
_URL_JS = _tag("url") + "location.href"
_TITLE_JS = _tag("title") + "document.title"
_TEXT_JS = _tag("text") + "document.body ? document.body.innerText : ''"
_SCROLL_JS = _tag("scrolly") + "String(window.scrollY)"

# K-tarayici-disari A2: on a site, what waits for the user's yes at every level - a form sent,
# a password typed, a click on words like these (case aside).
# shortcut: English and Turkish words only; a button in another language is not stopped (its
# form still is, if it posts).
SIGN_WORDS = re.compile(
    r"\b(sign ?in|sign ?up|log ?in|log ?on|pay|checkout|check out|buy|subscribe|place order|"
    r"purchase|delete account|giriş yap|oturum aç|öde|satın al|abone ol|sipariş ver|hesabı sil)"
    r"\b", re.IGNORECASE)
FORM_HELD = ("{url}: the page tried to send a form; it was not sent - a form goes only after "
             "the user's yes: browser_click its submit button, or browser_key Enter in its "
             "field, and they are asked")


def _what_js(arg: dict) -> str:
    """What an action would reach: the element at a click's point ({x, y}), or the field
    typed into ({selector}, null: the one with the focus) - inside shadow roots too. Its
    words (never a password field's value), whether it is a password field or any field one
    can see into (`editable`) or one hidden in a closed shadow root, whether it sends
    a form by POST (a submit button of one, or a field Enter sends it from), whether it is a
    frame (whose inside cannot be seen), and the page's host. Run in a world of its own
    (`Browser.what`): the page's scripts cannot change what it calls."""
    return _tag("what", arg) + """
(function (arg) {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 200);
  let el;
  if ('x' in arg) {
    el = document.elementFromPoint(arg.x, arg.y);
    while (el && el.shadowRoot && el.shadowRoot.elementFromPoint(arg.x, arg.y)
           && el.shadowRoot.elementFromPoint(arg.x, arg.y) !== el)
      el = el.shadowRoot.elementFromPoint(arg.x, arg.y);
  } else {
    el = arg.selector ? document.querySelector(arg.selector) : document.activeElement;
    while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  }
  const out = { host: location.hostname, words: '', password: false, posts: false, frame: false,
    editable: false, hidden: false };
  if (!el) return JSON.stringify(out);
  out.frame = el.matches('iframe, frame, object, embed');
  // (A host of a closed shadow root - a custom element with no open one - hides its field.)
  out.hidden = el.tagName.includes('-') && !el.shadowRoot;
  out.editable = el.matches('input, textarea, select') || el.isContentEditable;
  const act = el.closest('button, a, [role=button], [role=link], input, select, textarea, '
    + 'summary, label') || el;
  out.password = act.matches('input[type=password]');
  out.words = [act.innerText, out.password ? '' : act.value, act.getAttribute('aria-label'),
    act.title, act.alt].map(norm).filter(Boolean).join(' / ');
  const form = act.form || null;
  const submits = 'x' in arg
    ? act.matches('button:not([type]), button[type=submit], input[type=submit], input[type=image]')
    : act.matches('input, button:not([type]), button[type=submit]');
  const method = ('x' in arg && act.formMethod) || (form && form.method) || 'get';
  out.posts = !!form && submits && String(method).toLowerCase() === 'post';
  return JSON.stringify(out);
})(""" + json.dumps(arg) + ")"


def stop(found: object, action: str) -> tuple[str, str, str] | None:
    """A2: whether an action on a site's page waits for the user's yes - and as what: the
    card's kind, what it says, and the host. `action` is "click", "type" or "press" (Enter
    or Space on the field or button with the focus, which may send or click it); `found`
    what `_what_js` gave. Fails closed: what cannot be read, or a frame, waits too.
    shortcut: a field a page masks itself (no type=password) is not seen as one; the page can
    change the element between this look and the action."""
    if not isinstance(found, dict) or not found.get("host"):
        return ("sign", f"{action} on the page: KOLONİ could not tell what it reaches", "")
    # (The host apart - the card shows it as a tag - from the page's words, named as its own.)
    host, words = str(found["host"]), str(found.get("words") or "")
    says = f" - the page's own words on it: {words!r}" if words else ""
    if found.get("frame"):
        return ("sign", f"{action} inside a frame of the page (its inside is not seen)", host)
    if action == "type":
        if found.get("password"):
            return ("password", "type into a password field", host)
        if found.get("hidden") or not found.get("editable"):
            return ("field", "type into a field KOLONİ cannot see into", host)
        return None
    if found.get("posts"):
        return ("form", "send a form" + says, host)
    if SIGN_WORDS.search(words):
        return ("sign", f"{action} a button or link{says}", host)
    return None


def keys_held(found: object) -> bool:
    """A2: whether a single key may not go to what has the focus on a site's page - a password
    field, or what cannot be seen into: text goes there only through browser_type, asked."""
    return not isinstance(found, dict) or bool(
        found.get("password") or found.get("frame") or found.get("hidden"))


class Browser:
    """One headless browser of one agent: started at its first browser tool, ended with the
    agent (`close`). Its process is in KOLONİ's job (Windows) or process group, as a command's
    is, so that a crash of KOLONİ's leaves no browser behind."""

    def __init__(self, scratch: Path, agent_id: str):
        self.profile = scratch / f"profile-{agent_id}"
        self.version: str | None = None
        self._process: ProcessCommand | None = None
        self._ws: Any = None
        self._reader: asyncio.Task | None = None
        self._next = 0
        self._waiting: dict[int, asyncio.Future] = {}
        self._session: str | None = None
        self._page: str | None = None
        self._loading, self._loaded = asyncio.Event(), asyncio.Event()
        self._console: list[str] = []
        self._dropped = 0
        self.port: int | None = None
        # What every load is judged by (`allowed`): set at start, `closed` kept fresh by the
        # agent before each tool.
        self._project: Workspace | None = None
        self.closed: set[int] = set()
        # K-tarayici-disari: `away` - started for the sites the user allowed (`outside`), never
        # for a preview: the two never share a browser. `sites` is kept fresh as `closed` is.
        self.away = False
        self.sites: frozenset[str] = frozenset()
        self.once: set[str] = set()  # (sites the user said yes to on a card, for this browser)
        # A2: till when the page's own POST may go - a yes on a card for the action that sends it.
        self.posting = 0.0
        # K-gorsel-motor: the last marked screenshot's - where the page was (`_HERE`), and
        # each mark's centre.
        self.marked: tuple[str, list[tuple[float, float]]] = ("", [])
        self._refused: list[str] = []
        self.gone = False

    async def start(self, command: list[str], project: Workspace | None, closed: set[int],
                    away: bool = False, resolver: str = "") -> None:
        """`project` None (K-drawio, `app.diagram`): nothing but data: and blob: is loaded at
        all - no preview, no file - and no name resolves, loopback's neither: a WebSocket, which
        Fetch does not pause, reaches nothing either. `away`: for the sites the user allowed -
        names resolve, but not this machine's nor its network's (`resolver`, rules before
        those: a test's own name for a local server)."""
        shutil.rmtree(self.profile, ignore_errors=True)
        self.profile.mkdir(parents=True, exist_ok=True)
        # Nothing outside this machine resolves - a page's own links and assets included.
        # Measured (Chrome 156): the rule reaches IP literals too, so loopback's are excluded
        # by name; every other name or address ends in ERR_NAME_NOT_RESOLVED.
        rules = "MAP * ~NOTFOUND" + ("" if project is None else
                                     ", EXCLUDE localhost, EXCLUDE 127.0.0.1, EXCLUDE ::1")
        if away:
            # Out: every name resolves but this machine's and its network's, by name or
            # address as written - a backstop behind `outside` and the guard for what neither
            # sees (a worker's WebSocket).
            rules = resolver + ", ".join(f"MAP {name} ~NOTFOUND" for name in INSIDE)
        argv = [
            *command, "--headless=new", f"--user-data-dir={self.profile}",
            "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check",
            # (Chrome's own traffic - its updates, its safe-browsing lists - is none of a page's.)
            "--disable-background-networking", "--disable-component-update",
            f"--host-resolver-rules={rules}",
            # A system proxy (a PAC script, one on loopback) would carry names out past the
            # rule above: none (measured, it wins over a set proxy).
            "--no-proxy-server",
            # A sandboxed frame (allow-scripts, no same origin) put in a process of its own
            # starts before it can be guarded, with WebRTC (measured): kept in its page's
            # process it has the page's guard (measured: no RTCPeerConnection, no UDP). No
            # browser-wide WebRTC switch held (measured: a dead HTTP or SOCKS proxy with
            # disable_non_proxied_udp, --enforce-webrtc-ip-permission-check, CSP webrtc 'block').
            "--disable-features=IsolateSandboxedIframes",
            BLANK,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=sys.platform != "win32",
                env=command_env(),  # what a page could reach through it, a command could
                **SUSPENDED)  # (in its job before it starts its own processes, `_job_for`)
        except OSError as exc:
            raise BrowserError(f"the browser could not start: {exc.strerror or exc}") from None
        self._process = ProcessCommand(process, _job_for(process))
        active = self.profile / "DevToolsActivePort"
        waited = 0.0
        while True:
            # (Written in one go, but read between its two lines once: both are waited for. Chrome
            # holds it open while it writes, so a read then is refused on Windows: not yet.)
            try:
                lines = active.read_text(encoding="ascii").split()
            except OSError:
                lines = []
            if len(lines) == 2:
                break
            if process.returncode is not None:
                raise BrowserError("the browser ended before it listened")
            if waited >= START_WAIT:
                await self.close()
                raise BrowserError(f"the browser did not start in {START_WAIT:.0f} s")
            await asyncio.sleep(0.05)
            waited += 0.05
        # Its own port is closed to its pages: /json/version names the socket that drives it.
        self.port, self._project, self.away = int(lines[0]), project, away
        self.closed = set(closed) | {self.port}
        # No limit and no ping of the library's own: either would close the socket first, and
        # Chrome lets every paused request go on ~60 ms after a close (measured in the review:
        # 5 held POSTs reached a closed port 1 ms after it). The size is judged in `_read`.
        self._ws = await websockets.connect(
            f"ws://127.0.0.1:{lines[0]}{lines[1]}", max_size=None, ping_interval=None,
            open_timeout=LOAD_WAIT)  # (the library's own default, 10 s, is LOAD_WAIT)
        self._reader = asyncio.create_task(self._read())
        self.version = (await self._send("Browser.getVersion"))["product"]
        # Every load of every target - a redirect, a meta refresh, an iframe, a worker's or a
        # service worker's fetch - is paused and judged (`_judge`): measured (Chrome 156), the
        # browser's own Fetch.enable pauses them all; the URL judged is Chrome's own.
        await self._send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
        # A download would land in the user's Downloads, outside the project, unasked.
        await self._send("Browser.setDownloadBehavior", {"behavior": "deny"})
        target = await self._send("Target.createTarget", {"url": BLANK})
        self._page = target["targetId"]
        self._session = (await self._send("Target.attachToTarget", {
            "targetId": self._page, "flatten": True}))["sessionId"]
        for method, params in self._guarded():
            await self._call(method, params)
        for method in ("Runtime.enable", "Log.enable"):
            await self._call(method)
        await self._call("Emulation.setDeviceMetricsOverride", {
            "width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False})
        # A new window the page opens is attached before its first script runs (measured:
        # --block-new-web-contents does not stop one): it is closed (`_attached`).
        await self._send("Target.setAutoAttach", {
            "autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})

    def _guarded(self) -> list[tuple[str, dict]]:
        """What a page or frame is given before it runs: the guard, and the same for the
        out-of-process frames it opens (measured: a localhost iframe in a 127.0.0.1 page)."""
        return [("Page.enable", {}),
                ("Page.addScriptToEvaluateOnNewDocument", {
                    "source": self._guard()}),
                ("Target.setAutoAttach", {
                    "autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})]

    def _guard(self) -> str:
        return GUARD % (json.dumps(sorted(self.closed)), json.dumps(self.away))

    async def close(self) -> None:
        """Ends the browser and takes its profile away; never raises."""
        if self._reader is not None:
            self._reader.cancel()
            self._reader = None
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._process is not None:
            with contextlib.suppress(Exception):
                await self._process.kill()
                # (Its files are held until its last process is gone: measured, Chrome's
                # profile would not go for a rmtree right after the kill.)
                await asyncio.wait_for(self._process.wait(), 5)
            self._process = None
        for _ in range(20):
            shutil.rmtree(self.profile, ignore_errors=True)
            if not self.profile.exists():
                break
            await asyncio.sleep(0.1)

    # --- the protocol -------------------------------------------------------------------

    async def _read(self) -> None:  # noqa: C901
        try:
            async for raw in self._ws:
                if len(raw) > MAX_MESSAGE:
                    # Killed while its session - and so the Fetch rule - still holds.
                    await self._die()
                    break
                message = json.loads(raw)
                if (future := self._waiting.pop(message.get("id"), None)) is not None:
                    if not future.done():
                        future.set_result(message)
                elif message.get("method") == "Fetch.requestPaused":
                    await self._judge(message)
                elif message.get("method") == "Target.attachedToTarget":
                    await self._attached(message)
                elif message.get("method") == "Page.javascriptDialogOpening":
                    # An alert would hold every later call till its 30 s are up: dismissed.
                    said = " ".join(str(message.get("params", {}).get("message", "")).split())
                    self._note(f"the page showed a dialog: {said[:MAX_DIALOG]}; it was dismissed")
                    await self._tell("Page.handleJavaScriptDialog", {"accept": False},
                                     message.get("sessionId"))
                elif message.get("method") == "Page.frameStartedLoading":
                    self._loading.set()
                elif message.get("method") == "Page.loadEventFired":
                    self._loaded.set()
                elif (line := _console_line(message)) is not None:
                    if len(self._console) >= MAX_CONSOLE:
                        self._console.pop(0)
                        self._dropped += 1
                    self._console.append(line)
        except Exception:
            pass  # the connection is gone (a message over max_size, a missed ping, a crash)
        # Chrome drops the session's Fetch rule and guard with the connection and runs on
        # (measured in the review: a POST then reached a closed port, WebRTC came back): it is
        # ended at once. (A Stop cancels the reader instead: `close` ends it then.)
        await self._die()

    async def _die(self) -> None:
        """End the browser where its fence no longer holds; every later call says so."""
        self.gone = True
        for future in self._waiting.values():
            if not future.done():
                future.set_exception(BrowserError(ENDED))
        if self._process is not None:
            with contextlib.suppress(Exception):
                await self._process.kill()

    async def _tell(self, method: str, params: dict, session: str | None) -> None:
        """A call whose answer nobody waits for: sent from the reader, which is what ends
        every wait - an awaited call there would never return."""
        self._next += 1
        message: dict = {"id": self._next, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        with contextlib.suppress(websockets.ConnectionClosed):  # (the reader ends it then)
            await self._ws.send(json.dumps(message))

    async def _judge(self, message: dict) -> None:
        """A paused load goes on if it is this machine's preview or a file of the project
        (`allowed`) - or, in a browser that went out, what `outside` lets a site load; else it
        fails, and is said in the next tool's result. Fails closed."""
        params = message.get("params", {})
        url = str(params.get("request", {}).get("url", ""))
        try:
            if not url.startswith(LOCAL) and self._project is None:
                raise BrowserError(f"{url}: nothing is loaded while a diagram is drawn")
            if not url.startswith(LOCAL) and self.away:
                document = params.get("resourceType") == "Document"
                # (The page's own frame bears its target's id: measured, Chrome 156.)
                main = document and params.get("frameId") == self._page
                outside(url, self.sites, self.closed, main)
                if main:  # (what it is out there; a frame and a load are judged by name)
                    await looked_up(url)
                # A2: a form a page or a frame of it sends (a navigation that is not a GET)
                # goes once, right after the user's yes for the action that sends it. A
                # page's own fetch/XHR POST is not asked.
                # shortcut: a sign-in by fetch (most single-page sites) is not stopped here;
                # its password field and its button are (`stop`).
                method = str(params.get("request", {}).get("method", "GET")).upper()
                if document and method not in ("GET", "HEAD"):
                    # (Only the page's own: a yes was for an action on it, not a frame's.)
                    if not main or time.monotonic() > self.posting:
                        raise BrowserError(FORM_HELD.format(url=url))
                    self.posting = 0.0
            elif not url.startswith(LOCAL):
                allowed(url, cast(Workspace, self._project), self.closed)
        except Exception as exc:
            why = str(exc) if isinstance(exc, BrowserError) else f"{url}: it could not be judged"
            self._note(f"refused: {why}")
            await self._tell("Fetch.failRequest", {"requestId": params.get("requestId"),
                                                   "errorReason": "BlockedByClient"},
                             message.get("sessionId"))
            return
        await self._tell("Fetch.continueRequest", {"requestId": params.get("requestId")},
                         message.get("sessionId"))

    async def _attached(self, message: dict) -> None:
        """A target that waits to start: a window the page opened is closed; any other (an
        out-of-process frame) is given the guard first."""
        params = message.get("params", {})
        info, child = params.get("targetInfo", {}), params.get("sessionId")
        if not params.get("waitingForDebugger"):
            # A frame of the page's that runs already was not guarded: the browser ends. A
            # backstop behind --disable-features=IsolateSandboxedIframes (honoured on Chrome and
            # Edge 156, measured): it does not stop what the frame sent before this came
            # (measured in the review: a WebSocket GET ~7 ms before the attach event).
            if message.get("sessionId") and info.get("type") == "iframe":
                await self._die()
            return
        for method, call in self._guarded():
            await self._tell(method, call, child)
        if info.get("type") in ("worker", "shared_worker"):
            # A worker has no document for the guard to run in: it is run in the worker
            # before its own script (measured, Chrome 156: a dedicated worker comes here,
            # waiting).
            await self._tell("Runtime.evaluate", {"expression": self._guard()}, child)
        await self._tell("Runtime.runIfWaitingForDebugger", {}, child)
        if info.get("type") == "page" and info.get("targetId") != self._page:
            self._note("the page tried to open a window; it was closed")
            await self._tell("Target.closeTarget", {"targetId": info.get("targetId")}, None)

    def refused(self) -> str:
        """What the browser refused to load since the last call, as the end of a tool's
        result."""
        said, self._refused = self._refused, []
        return "".join(f"\n{line}" for line in said)

    def _note(self, line: str) -> None:
        """A line for the end of the next tool's result: each once, at most MAX_REFUSED."""
        if len(self._refused) < MAX_REFUSED and line not in self._refused:
            self._refused.append(line)

    async def _send(self, method: str, params: dict | None = None,
                    session: str | None = None) -> dict:
        if self._ws is None or self.gone:
            raise BrowserError(ENDED if self.gone else "the browser is not running")
        self._next += 1
        message: dict = {"id": self._next, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        future = self._waiting[self._next] = asyncio.get_running_loop().create_future()
        try:
            await self._ws.send(json.dumps(message))
        except websockets.ConnectionClosed:
            self._waiting.pop(message["id"], None)
            raise BrowserError(ENDED) from None
        try:
            answer = await asyncio.wait_for(future, LOAD_WAIT * 3)
        except TimeoutError:
            self._waiting.pop(message["id"], None)
            raise BrowserError(f"the browser did not answer {method} in 30 s") from None
        if "error" in answer:
            raise BrowserError(f"{method}: {answer['error'].get('message', answer['error'])}")
        return answer.get("result", {})

    async def _call(self, method: str, params: dict | None = None) -> dict:
        """A call of the page's own."""
        return await self._send(method, params, self._session)

    async def _eval(self, expression: str, wait: bool = False) -> Any:
        """`wait`: the expression gives a promise, and its value is what it resolves to."""
        found = await self._call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": wait})
        if "exceptionDetails" in found:
            details = found["exceptionDetails"]
            raise BrowserError("the page refused it: " + str(
                details.get("exception", {}).get("description") or details.get("text")))
        return found.get("result", {}).get("value")

    async def _world(self, expression: str) -> Any:
        """An expression's value in a world of KOLONİ's own, where the page's scripts cannot
        change what it calls; None where it threw."""
        world = await self._call("Page.createIsolatedWorld", {
            "frameId": self._page, "worldName": "koloni"})
        found = await self._call("Runtime.evaluate", {
            "expression": expression, "contextId": world.get("executionContextId"),
            "returnByValue": True})
        return found.get("result", {}).get("value")

    # --- the tools ------------------------------------------------------------------------

    async def open(self, url: str) -> str:
        """Goes to `url` (already `allowed`) and waits for the page to load, at most
        LOAD_WAIT seconds."""
        self.marked = ("", [])
        self._loading.clear()
        self._loaded.clear()
        gone = await self._call("Page.navigate", {"url": url})
        if gone.get("errorText"):
            raise BrowserError(f"{url}: {gone['errorText']}")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._loaded.wait(), LOAD_WAIT)
        return await self.where()

    async def where(self) -> str:
        """Where the page is, and its title: "http://127.0.0.1:5173/ - Vite App"."""
        url, title = await self._eval(_URL_JS), await self._eval(_TITLE_JS)
        return f"{url} - {title}" if title else str(url)

    async def screenshot(self, marks: bool = False) -> tuple[bytes, str]:
        """The picture, and with `marks` the list of the numbers stamped on it for that picture
        alone (`_marks_js`), kept for a click at one (`point`).
        shortcut: no zoom or crop on the coordinate path; if small targets miss, add
        browser_screenshot {zoom: [x, y, w, h]}."""
        self.marked, listed = ("", []), ""
        try:
            if marks:
                try:
                    found = json.loads(await self._world(_marks_js()))
                    self.marked = (found["here"], [(m["x"], m["y"]) for m in found["marks"]])
                    listed = " · ".join(
                        f"{n}: {m['kind']}" + (f" {m['words']!r}" if m["words"] else "")
                        + f" ({m['x']:.0f},{m['y']:.0f})"
                        for n, m in enumerate(found["marks"], 1)) or "none in view"
                except (ValueError, KeyError, TypeError):
                    raise BrowserError("the page could not be marked: browser_read lists "
                                       "what is on it") from None
            shot = await self._call("Page.captureScreenshot", {"format": "png"})
        finally:
            if marks:
                await self._world(_UNMARK_JS)
        return base64.b64decode(shot["data"]), listed

    async def point(self, selector: str | None, text: str | None, x: float | None,
                    y: float | None, mark: float | None = None) -> tuple[tuple[float, float], str]:
        """Where a click goes, and how it is named in the result."""
        if selector:
            box, named = await self._eval(_rect_js(selector)), selector
        elif text:
            box, named = await self._eval(_find_js(text)), f"{text!r}"
        elif mark is not None:
            here, points = self.marked
            if not 1 <= mark <= len(points) or mark != int(mark) or (
                    here != await self._world(_HERE_JS)):
                raise BrowserError(f"no mark {mark:g} on the page as it is now: take a new "
                                   "screenshot with marks")
            return points[int(mark) - 1], f"mark {mark:g}"
        elif x is not None and y is not None:
            box, named = json.dumps({"x": x, "y": y, "width": 0, "height": 0}), f"({x}, {y})"
        else:
            raise BrowserError("give a selector, a text, x and y, or a mark")
        if not box:
            raise BrowserError(f"nothing on the page reads as {named}: browser_read lists what is")
        try:
            rect = json.loads(box)
            return (rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2), named
        except (ValueError, KeyError, TypeError):  # (a page that broke what reads its box)
            raise BrowserError(f"{named}: the page gave no box for it") from None

    async def click_at(self, at: tuple[float, float], named: str) -> str:
        self._loading.clear()
        self._loaded.clear()
        for kind in ("mousePressed", "mouseReleased"):
            await self._call("Input.dispatchMouseEvent", {
                "type": kind, "x": at[0], "y": at[1], "button": "left", "clickCount": 1})
        return f"clicked {named} at ({at[0]:.0f}, {at[1]:.0f}); now at {await self._settled()}"

    async def what(self, at: tuple[float, float] | None = None,
                   selector: str | None = None) -> object:
        """A2: what a click at `at`, or typing into `selector` (None: the field with the
        focus), would reach (`_what_js`) - looked at in a world of KOLONİ's own, where the
        page's scripts cannot change what it calls. None where it cannot be read."""
        value = await self._world(
            _what_js({"x": at[0], "y": at[1]} if at else {"selector": selector}))
        with contextlib.suppress(ValueError, TypeError):
            return json.loads(value)
        return None

    async def type(self, selector: str | None, text: str,
                   judge: Callable[[object], Awaitable[None]] | None = None) -> str:
        """`judge` (A2, on a site): given what has the focus once it is focused - looked at in
        KOLONİ's own world (`what`), so a page that names another field, or turns this one
        into a password field as it is focused, is seen as it is - before a letter goes in."""
        field = await self._eval(_focus_js(selector))
        if not field:
            raise BrowserError(f"no field {selector!r} on the page" if selector
                               else "no field has the focus: give a selector, or click one first")
        if judge is not None:
            await judge(await self.what())
        await self._call("Input.insertText", {"text": text})
        return f"typed into {field}"

    async def key(self, key: str) -> str:
        code = KEYS.get(key)
        if code is None and len(key) != 1:
            raise BrowserError(f"unknown key {key!r}: one character, or one of "
                               + ", ".join(k for k in KEYS if k != " "))
        self.marked = ("", [])  # (a key may scroll a box inside the page: `scroll`)
        self._loading.clear()
        self._loaded.clear()
        for kind in ("keyDown", "keyUp"):
            params: dict = {"type": kind, "key": key, "code": key if code else f"Key{key.upper()}"}
            if code:
                params["windowsVirtualKeyCode"] = code
            if kind == "keyDown" and key == "Enter":
                params["text"] = "\r"
            elif kind == "keyDown" and code is None:
                params["text"] = key
            await self._call("Input.dispatchKeyEvent", params)
        return f"pressed {key}; now at {await self._settled()}"

    async def scroll(self, dy: float) -> str:
        # (A box inside the page may scroll where the window does not: `_HERE` would not see it.)
        self.marked = ("", [])
        await self._call("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": WIDTH / 2, "y": HEIGHT / 2, "deltaX": 0, "deltaY": dy})
        await asyncio.sleep(0.1)
        return f"scrolled {dy:+.0f}; the page is at y={await self._eval(_SCROLL_JS)}"

    async def read(self) -> str:
        """The page's visible text, then an outline of its accessibility tree, within MAX_READ."""
        text = str(await self._eval(_TEXT_JS) or "")
        tree = await self._call("Accessibility.getFullAXTree")
        lines = []
        for node in tree.get("nodes", []):
            role = node.get("role", {}).get("value", "")
            name = node.get("name", {}).get("value", "")
            value = node.get("value", {}).get("value", "")
            if role in AX_ROLES and (name or value):
                lines.append(f"{role}: {name}" + (f" = {value!r}" if value else ""))
        head = f"{await self.where()}\n\n"
        outline = "\n".join(lines)[: MAX_READ // 3]
        room = MAX_READ - len(head) - len(outline) - 40
        if len(text) > room:
            text = text[:room] + "\n[cut: the page's text goes on]"
        return f"{head}{text}\n\nOutline:\n{outline}" if outline else f"{head}{text}"

    def console(self) -> str:
        """The console's messages and the page's errors since the last call."""
        lines, self._console = self._console, []
        dropped, self._dropped = self._dropped, 0
        if not lines:
            return "nothing in the console since the last call"
        head = f"({dropped} older messages dropped)\n" if dropped else ""
        return head + "\n".join(lines)

    async def _settled(self) -> str:
        """Where the page is once the navigation the last action started, if any, is through
        (at most LOAD_WAIT seconds)."""
        await asyncio.sleep(0.2)
        if self._loading.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._loaded.wait(), LOAD_WAIT)
        return await self.where()


def sweep(folder: Path, keep: set[str]) -> None:
    """Profiles a browser left when KOLONİ was killed (`profile-<agent>`): taken away, but
    not one of a browser at work now (`keep`, by agent); and screenshots older than
    SHOTS_KEPT (the user's call, 3 Nov: a site's page may show what is theirs)."""
    for profile in folder.glob("profile-*"):
        if profile.name.removeprefix("profile-") not in keep:
            shutil.rmtree(profile, ignore_errors=True)
    old = time.time() - SHOTS_KEPT
    for shot in folder.glob("shots/*.png"):
        with contextlib.suppress(OSError):
            if shot.stat().st_mtime < old:
                shot.unlink()


def _console_line(message: dict) -> str | None:
    """One line of what the page said or threw, as the agent is shown it; None for any
    other event."""
    params = message.get("params", {})
    method = message.get("method")
    if method == "Runtime.consoleAPICalled":
        words = " ".join(
            str(arg.get("value")) if "value" in arg else arg.get("description", arg.get("type", ""))
            for arg in params.get("args", []))
        return f"console.{params.get('type', 'log')}: {words}"
    if method == "Runtime.exceptionThrown":
        details = params.get("exceptionDetails", {})
        said = details.get("exception", {}).get("description") or details.get("text", "error")
        where = (f" ({details['url']}:{details.get('lineNumber', 0) + 1})"
                 if details.get("url") else "")
        return f"error: {said.splitlines()[0]}{where}"
    if method == "Log.entryAdded":
        entry = params.get("entry", {})
        where = f" ({entry['url']})" if entry.get("url") else ""
        return (f"{entry.get('source', 'log')} {entry.get('level', '')}: "
                f"{entry.get('text', '')}{where}")
    return None


SHOT = re.compile(r"\.koloni/tmp/browser/shots/[\w.-]+\.png")
