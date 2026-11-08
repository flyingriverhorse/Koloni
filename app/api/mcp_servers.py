"""The MCP servers the user connects: adding one is starting a program as the user, so
every route that changes one, or starts one, is taken only from the app's own page."""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import literal_column, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app import mcp_client, package_look
from app.api.deps import get_session, require_own_origin
from app.db.models import McpServer, Role, now
from app.schemas import (
    McpReadIn,
    McpReadOut,
    McpServerIn,
    McpServerOut,
    McpServerPatch,
    PackageIn,
    PackageOut,
    PackageSeenOut,
)

router = APIRouter(prefix="/api/mcp-servers", tags=["mcp servers"])
OWN = [Depends(require_own_origin)]


UNSHOWN = "What was kept of its tools cannot be shown: read its tools again."
# (Shown as "Not offered: …." beside the tool.)
STALE = ("its server's command or variables changed since it was read: read its tools again "
         "(and say again which run without asking)")
CHANGED_WHILE_READ = "The server's command or variables changed while it was read: read it again."


def shown(server: McpServer) -> dict:
    """A server as clients see it: of its variables only the names. It does not fail on
    whatever is kept of the server's tools: where that cannot be checked and written as
    an answer is (kept before a reading cleaned what it keeps), the server is shown
    without tools and says so - it can still be read again, and deleted."""
    row = {
        "id": server.id, "name": server.name,
        "command": mcp_client.command_shown(server.command),
        "env_names": server.env_names, "read_at": server.read_at,
        "read_error": server.read_error, "trusted": server.trusted,
        "enabled": server.enabled,
    }
    try:
        tools = [{**tool, "chars": None if tool["unusable"] else len(json.dumps(
            mcp_client.schema(server.name, tool), ensure_ascii=False))}
            for tool in server.tools]
        whole = McpServerOut.model_validate({**row, "tools": tools}).model_dump(mode="json")
        json.dumps(whole, ensure_ascii=False).encode("utf-8")
    except Exception:
        # (Where the last reading failed, why it did is what is said.)
        return {**row, "tools": [], "read_error": server.read_error or UNSHOWN}
    return whole


def _server(session: Session, server_id: str) -> McpServer:
    server = session.get(McpServer, server_id)
    if server is None:
        raise HTTPException(404, "server not found")
    return server


def _command(command: list[str], saved: list[str] | None = None) -> list[str]:
    """A command checked. One with a key hidden in it (MASK) is the saved one only where it
    was sent back exactly as it was shown: a saved key never goes to another program,
    package or address."""
    if any(mcp_client.MASK in part for part in command):
        if saved is None or command != mcp_client.command_shown(saved):
            raise HTTPException(
                422, "the command changed and a key in it is hidden: type the key again")
        command = list(saved)
    if not 1 <= len(command) <= 1 + mcp_client.MAX_ARGUMENTS:
        raise HTTPException(
            422, f"a command is a program and at most {mcp_client.MAX_ARGUMENTS} arguments")
    if not all(
        part.strip() and len(part) <= mcp_client.MAX_ARGUMENT and part.isprintable()
        for part in command
    ):
        raise HTTPException(
            422, "the program and each argument is one line of 1 to "
            f"{mcp_client.MAX_ARGUMENT} characters")
    # Said here, where the user can change it, and not first when an agent calls a tool:
    # what the Windows command interpreter would act on, for a program it runs.
    why = mcp_client.not_startable([mcp_client.found(command[0]) or command[0], *command[1:]])
    if why:
        raise HTTPException(422, f"this command cannot be started: {why}")
    return command


def _env(env: dict[str, str]) -> dict[str, str]:
    """A server's variables, checked. A refusal never repeats a value."""
    if len(env) > mcp_client.MAX_VARIABLES:
        raise HTTPException(422, f"a server has at most {mcp_client.MAX_VARIABLES} variables")
    if not all(mcp_client.VARIABLE.fullmatch(name) for name in env):
        raise HTTPException(
            422, "a variable's name is letters, digits and _, does not start with a digit "
            "and has at most 100 characters")
    if len({name.upper() for name in env}) != len(env):
        # (Windows knows a variable by its name whatever its case.)
        raise HTTPException(422, "two variables have the same name, but for its case")
    if any(len(value) > mcp_client.MAX_VALUE or "\x00" in value for value in env.values()):
        raise HTTPException(
            422, f"a variable's value has at most {mcp_client.MAX_VALUE} characters, and "
            "no NUL among them")
    return env


@router.get("", response_model=list[McpServerOut])
def list_servers(session: Session = Depends(get_session)):
    servers = session.scalars(
        select(McpServer).order_by(McpServer.created_at, literal_column("mcp_servers.rowid")))
    return [shown(server) for server in servers]


@router.post("", response_model=McpServerOut, status_code=201, dependencies=OWN)
def create_server(body: McpServerIn, session: Session = Depends(get_session)):
    if not mcp_client.NAME.fullmatch(body.name):
        raise HTTPException(
            422, "a server's name starts with a letter and is 1 to 16 of a-z, 0-9 and -")
    if session.scalar(select(McpServer).where(McpServer.name == body.name)) is not None:
        raise HTTPException(409, f"there is already a server named {body.name}")
    server = McpServer(name=body.name, command=_command(body.command), env=_env(body.env))
    session.add(server)
    session.commit()
    return shown(server)


@router.patch("/{server_id}", response_model=McpServerOut, dependencies=OWN)
def patch_server(server_id: str, body: McpServerPatch, session: Session = Depends(get_session)):
    server = _server(session, server_id)
    tools = [dict(tool) for tool in server.tools]
    started_as = (server.command, server.env)
    if body.command is not None:
        server.command = _command(body.command, server.command)
    # shortcut: a changed command keeps the saved variables' values (a token too), as it
    # did before keys in arguments were hidden; ask for them again if that is a concern.
    if body.env is not None:
        server.env = _env({
            **{name: value for name, value in server.env.items() if name not in body.env},
            **{name: value for name, value in body.env.items() if value is not None},
        })
    if (server.command, server.env) != started_as:
        # Another program, or the same with other variables: its tools are not the ones
        # read until they are read again (by the user, who sees what is started), and
        # what the user said of the other's tools was not said of its.
        tools = [{**tool, "unusable": STALE,
                  "mark": "ask" if tool["mark"] == "free" else tool["mark"]} for tool in tools]
    # Another program, or other variables by name, is not what the user trusted (a value may
    # change: a token); trusted in the same request as the change, it is still watched.
    # shortcut: trust is in the command line, not in the code behind it - `npx -y pkg` with no
    # version may run other code later (the Tools page says so on the button).
    if server.command != started_as[0] or set(server.env) != set(started_as[1]):
        server.trusted = False
    elif body.trusted:
        server.trusted = True
    if body.enabled is not None:
        server.enabled = body.enabled
    for name, mark in (body.marks or {}).items():
        tool = next((tool for tool in tools if tool["name"] == name), None)
        if tool is None:
            raise HTTPException(422, f"this server has no tool named {name[:60]}")
        tool["mark"] = mark
    server.tools = tools
    session.commit()
    return shown(server)


@router.delete("/{server_id}", status_code=204, dependencies=OWN)
def delete_server(server_id: str, session: Session = Depends(get_session)):
    server = _server(session, server_id)
    # No role is left naming a server that is gone - or one added later under its name.
    for role in session.scalars(select(Role)):
        if server.name in role.mcp:
            role.mcp = [name for name in role.mcp if name != server.name]
    session.delete(server)
    session.commit()
    return Response(status_code=204)


# (Sync routes, as a skill's preview: a download never holds up the app's loop.)
@router.post("/package", response_model=PackageOut, dependencies=OWN)
def about_package(body: PackageIn):
    """The package a command's npx or uvx is given, as npm or PyPI lists it: its version,
    size and licence. Only its name is sent; nothing of it is downloaded."""
    try:
        return package_look.about(body.command)
    except package_look.LookError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/package/look", response_model=PackageSeenOut, dependencies=OWN)
def look_inside(body: PackageIn):
    """The package downloaded at the version the user was shown and read as text, never
    run: what it was seen to do. The server need not be added yet."""
    if body.version is None:
        raise HTTPException(422, "say which version was shown")
    try:
        return package_look.look(body.command, body.version)
    except package_look.LookError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/{server_id}/read", response_model=McpReadOut, dependencies=OWN)
async def read_server(request: Request, server_id: str, body: McpReadIn | None = None,
                      session: Session = Depends(get_session)):
    """Start the server once, in an empty folder, and keep the tools it lists: what
    agents are offered from here on. One that cannot be read says why (`read_error`),
    and what was kept of it before stays as it was. Asked to (`osv`), osv.dev is asked
    first whether its package is known malware: one it lists is not started and no tool of
    it is offered, and one it could not be asked about is started all the same.

    One that runs a file from a folder agents write in (97) is not started until the page
    sends back those files as it was told them (`in_project`), unchanged since: the user's
    yes, kept for agents' starts too (`trusted_files`)."""
    server = _server(session, server_id)
    files = await asyncio.to_thread(
        mcp_client.in_project, server.command, mcp_client.agents_folders(session))
    if not mcp_client.trusted(server.trusted_files, files) and (
            body is None or body.in_project != files):
        return {"server": shown(server), "new": [], "changed": [], "gone": [],
                "in_project": files}
    found: dict[str, list[str]] = {"new": [], "changed": [], "gone": []}
    listed, failed, malware, refused = None, None, None, None
    started_as = (list(server.command), dict(server.env))
    package = package_look.package_of(server.command) if body and body.osv else None
    if package is not None:
        registry, name, version = package
        try:
            records = await asyncio.to_thread(package_look.malware, registry, name, version)
            malware = {"package": name, "records": records, "error": None}
        except package_look.LookError as exc:
            records, malware = [], {"package": name, "records": [], "error": str(exc)}
        if records:
            refused = f"osv.dev lists {name} as malware ({', '.join(records)})"
            failed = f"{refused}: it was not started."
    try:
        if failed is None:
            listed = await mcp_client.read_tools(
                *started_as, request.app.state.settings.mcp_home)
    except mcp_client.McpError as exc:
        failed = f"The server {exc}."
    # As it stands now: while it was read the user may have marked a tool - a mark they
    # took back is not put back by this - or deleted the server.
    try:
        session.refresh(server)
    except InvalidRequestError:
        raise HTTPException(404, "server not found") from None
    if (server.command, server.env) != started_as:
        # What was read is the program before's: its tools stay not offered (STALE).
        listed, failed = None, CHANGED_WHILE_READ
    if listed is not None:
        server.tools, found = mcp_client.kept(server.name, server.tools, listed)
        # The yes kept once it started: not before osv.dev is asked, nor for a failed start.
        server.trusted_files = {path: digest for path, digest in files.items() if digest}
        if found["new"] or found["changed"]:
            # What the user trusted was the tools they had read (92): a new or changed one is
            # watched again - and every tool of a first reading is new.
            server.trusted = False
    elif refused and failed != CHANGED_WHILE_READ:
        # Kept from a reading before, its tools would start it for an agent: none is
        # offered until a reading finds it no longer listed.
        server.tools = [{**tool, "unusable": refused,
                         "mark": "ask" if tool["mark"] == "free" else tool["mark"]}
                        for tool in server.tools]
    server.read_at, server.read_error = now(), failed
    session.commit()
    return {"server": shown(server), **found, "malware": malware}
