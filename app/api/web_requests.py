import asyncio
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import browser, web
from app.api.commands import DECISION_TIMEOUT, ApproveIn
from app.api.deps import get_session, require_own_origin
from app.commands import new_web_rule, web_rules_here
from app.db.models import AllowedWeb, Conversation, Project, WebRequest
from app.schemas import AllowedHostIn, AllowedWebOut, AskFirstIn, WebRequestOut
from app.serialize import web_request_out

# What goes out of this machine unasked is the user's to say, from the app's own page: a
# request that does not say where it is from - a command an agent runs - is not the user.
router = APIRouter(
    prefix="/api", tags=["web requests"], dependencies=[Depends(require_own_origin)]
)


async def _decide(request_id: str, decision: str, request: Request, session: Session) -> dict:
    asked = session.get(WebRequest, request_id)
    if asked is None:
        raise HTTPException(404, "web request not found")
    if not request.app.state.runner.decide(request_id, decision):
        raise HTTPException(409, "this request is no longer waiting for a decision")
    # The agent task acts on the decision; answer once it has.
    deadline = asyncio.get_running_loop().time() + DECISION_TIMEOUT
    while True:
        await asyncio.sleep(0.01)
        session.refresh(asked)
        if asked.status != "proposed" or asyncio.get_running_loop().time() > deadline:
            return web_request_out(asked)


@router.post("/web-requests/{request_id}/approve", response_model=WebRequestOut)
async def approve(
    request_id: str, body: ApproveIn, request: Request, session: Session = Depends(get_session)
):
    """Let a search or a request go out. `remember`: also from now on without asking, in
    this conversation - searching, or GET from that host (nothing is kept for a request
    that is not a GET, or is one with a body or headers of the agent's own)."""
    return await _decide(request_id, "always" if body.remember else "once", request, session)


@router.post("/web-requests/{request_id}/reject", response_model=WebRequestOut)
async def reject(request_id: str, request: Request, session: Session = Depends(get_session)):
    return await _decide(request_id, "reject", request, session)


def _site_named(written: str) -> str:
    """A site's host, judged as `browser.site_of` judges it when an agent opens it: refused,
    with why, for this machine, its network, a name of one word."""
    address = written if "://" in written else f"https://{written}"
    try:
        host = browser.site_of(address)
    except browser.BrowserError as exc:
        raise HTTPException(422, str(exc).removesuffix(f"; {browser.NOT_HERE}")) from None
    if host is None:
        raise HTTPException(422, f"{written}: not a site out on the internet (http or https)")
    if len(host) > 253:  # (what a name can be, and the column holds)
        raise HTTPException(422, "a site's name is at most 253 characters")
    return host


def _keep(request: Request, session: Session, found: AllowedWeb | None,
          make: Callable[[], AllowedWeb], mark: bool) -> AllowedWeb:
    """The rule asked for: `found` as it is - marked Ask first if that is asked - or `make()`."""
    rule = found or make()
    if found is None or mark and not found.ask_first:
        rule.ask_first = bool(rule.ask_first) or mark
        session.add(rule)
        session.commit()
        request.app.state.runner.emit_web_rules(rule.conversation_id, rule.project_id)
    return rule


@router.post("/conversations/{conversation_id}/allowed-web", response_model=AllowedWebOut)
async def allow_host(
    conversation_id: str, body: AllowedHostIn, request: Request,
    session: Session = Depends(get_session),
):
    """Let GET requests to a host go without asking in this conversation, as a yes to
    "Always allow GET to …" does. The host is kept as a rule names it (`web.rule_of`);
    one that is already allowed stays the one rule it was. `kind` "page": a site the agents'
    browsers open, in every chat of the project - its bare name, whatever the scheme or port
    (K-tarayici-disari), marked Ask first if `ask_first`."""
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    written = body.host.strip()
    address = written if "://" in written else f"https://{written}"
    if body.kind == "page":
        host = _site_named(written)
    else:
        try:
            web.host_of(address)  # not this machine, nor its network: no leave covers those
            host = web.host_name(web.rule_of(address))
        except (web.NotReachable, ValueError) as exc:
            raise HTTPException(422, str(exc)) from None
    found = session.scalar(web_rules_here(conversation).where(
        AllowedWeb.kind == body.kind, AllowedWeb.host == host))
    return _keep(request, session, found, lambda: new_web_rule(conversation, body.kind, host),
                 body.kind == "page" and body.ask_first)


@router.post("/projects/{project_id}/sites", response_model=AllowedWebOut)
async def add_site(project_id: str, body: AllowedHostIn, request: Request,
                   session: Session = Depends(get_session)):
    """A site the project's agents' browsers open, added on Settings › This project as "Allow this
    site" on a card adds it; `kind` is not read (a site)."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    host = _site_named(body.host.strip())
    found = session.scalar(select(AllowedWeb).where(
        AllowedWeb.project_id == project_id, AllowedWeb.kind == "page", AllowedWeb.host == host))
    return _keep(request, session, found,
                 lambda: AllowedWeb(project_id=project_id, kind="page", host=host), body.ask_first)


@router.patch("/allowed-web/{rule_id}", response_model=AllowedWebOut)
async def ask_first(
    rule_id: str, body: AskFirstIn, request: Request, session: Session = Depends(get_session),
):
    """Mark a site Ask first, or take the mark off: a marked site is asked about every time
    an agent opens it, at every level (K-tarayici-disari)."""
    rule = session.get(AllowedWeb, rule_id)
    if rule is None or rule.kind != "page":
        raise HTTPException(404, "site not found")
    rule.ask_first = body.ask_first
    session.commit()
    request.app.state.runner.emit_web_rules(rule.conversation_id, rule.project_id)
    return rule


@router.delete("/allowed-web/{rule_id}", status_code=204)
async def remove_rule(rule_id: str, request: Request, session: Session = Depends(get_session)):
    """Take back a "search without asking" or "GET from this host" of a conversation, or a
    site of a project."""
    rule = session.get(AllowedWeb, rule_id)
    if rule is None:
        raise HTTPException(404, "rule not found")
    held_by = rule.conversation_id, rule.project_id
    session.delete(rule)
    session.commit()
    request.app.state.runner.emit_web_rules(*held_by)
    return Response(status_code=204)
