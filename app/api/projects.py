import asyncio
import base64
import binascii
import json
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, literal_column, select, text, update
from sqlalchemy.orm import Session

from app import (
    diagram,
    git,
    handoff,
    knowledge,
    knows,
    koloni,
    meaning,
    project_files,
    project_map,
    shared,
    views,
    web,
)
from app.agent import branch_held
from app.api.deps import get_session, keyed_if_read_by_the_app, require_origin, require_own_origin
from app.api.teams import chat_rows
from app.db.models import (
    FOLLOWED,
    SPAWN,
    Agent,
    AllowedCommand,
    AllowedWeb,
    AwayRun,
    BacklogTask,
    Base,
    Conversation,
    Memory,
    Project,
    ProjectKnowledge,
    Provider,
    Role,
    Run,
    ToolCall,
    Trigger,
    now,
)
from app.schemas import (
    AllowedWebOut,
    ChatRulesOut,
    DiagramPictureIn,
    FileChangeDiffOut,
    FileHistoryOut,
    GitChangeOut,
    GitOut,
    GitSwitchIn,
    KoloniUseIn,
    OthersInstructionsOut,
    PartTestIn,
    ProjectDeletePreviewOut,
    ProjectEntryOut,
    ProjectFileOut,
    ProjectIn,
    ProjectMapOut,
    ProjectOut,
    ProjectPatch,
    SharedFileOut,
    SharedPathIn,
)
from app.serialize import allowed_command_out, allowed_web_out, tell_chats
from app.triggers import local_day
from app.workspace import Workspace, WorkspaceError, far_or_device, listed_folder, not_a_project

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)):
    return session.scalars(select(Project).order_by(Project.created_at)).all()


@router.post(
    "", response_model=ProjectOut, status_code=201, dependencies=[Depends(require_origin)]
)
def create_project(body: ProjectIn, response: Response, session: Session = Depends(get_session)):
    root = Path(body.root_path).expanduser()
    # (A share or a device is refused before it is looked at on disk: a share is dialled.)
    if far_or_device(str(root)) or not root.is_absolute() or not root.is_dir():
        raise HTTPException(422, f"{body.root_path} is not an existing folder")
    root = root.resolve()
    if far_or_device(str(root)):  # (led there by a link)
        raise HTTPException(422, f"{body.root_path} leads to a network or device path")
    if why := not_a_project(root):
        raise HTTPException(422, f"{body.root_path} cannot be opened as a folder: {why}")
    existing = session.scalar(select(Project).where(Project.root_path == str(root)))
    if existing:
        response.status_code = 200
        return existing
    project = Project(name=body.name or root.name, root_path=str(root))
    session.add(project)
    session.commit()
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


@router.get("/{project_id}/delete-preview", response_model=ProjectDeletePreviewOut)
def delete_preview(project_id: str, session: Session = Depends(get_session)):
    """What a delete of the project takes from KOLONİ, counted for its dialog."""
    _project(session, project_id)

    def count(model) -> int:
        return session.scalar(select(func.count()).select_from(model).where(
            model.project_id == project_id)) or 0

    return {"chats": count(Conversation), "memory": count(Memory), "tasks": count(BacklogTask),
            "triggers": count(Trigger), "knowledge": count(ProjectKnowledge)}


@router.delete("/{project_id}", status_code=204, dependencies=[Depends(require_own_origin)])
async def delete_project(project_id: str, request: Request,
                         session: Session = Depends(get_session)):
    """KOLONİ's record of the project gone for good, in one transaction: its chats with all
    of their turns, its memory, knowledge, To-do, triggers, nights, usage and vectors. Not
    while anything of it is at work (409, why in words). Its folder, files, git and .koloni/
    are never touched; KOLONİ's own files of its chats go as a chat's delete takes them
    (`_forget_files`: CLI sessions, attachments, kept sides of a commit). On the loop, as the
    trigger clock is.
    shortcut: KOLONİ's own model call after a turn that ended (the note of what it found) is
    not waited for; a row of the project it writes after the delete is refused by the foreign
    key, and a vector stays until the next start's `tidy_db`. Wait for it here if that bites."""
    from app.api.conversations import (  # (it imports this module)
        _cli_sessions,
        _delete_for_good,
        _forget_files,
        _remove,
    )

    project = _project(session, project_id)
    # A write first, that changes nothing: no other writer commits until this does, so
    # nothing starts in the project between the checks below and the delete.
    session.execute(update(Project).where(Project.id == project_id).values(name=Project.name))
    chats = list(session.scalars(select(Conversation.id).where(
        Conversation.project_id == project_id)))
    if why := _at_work(session, project, chats, request.app.state.runner):
        raise HTTPException(409, why)
    triggers = list(session.scalars(select(Trigger.id).where(Trigger.project_id == project_id)))
    learned = set(session.scalars(select(ProjectKnowledge.id).where(
        ProjectKnowledge.project_id == project_id)))
    kept = _cli_sessions(session, chats)
    if chats:
        _delete_for_good(session, chats)
    session.execute(text("DELETE FROM said_in_turns WHERE project_id = :p"), {"p": project_id})
    # Rows kept by the project's id alone (its vectors, its triggers' record, ...).
    for table in Base.metadata.sorted_tables:
        column = table.c.get("project_id")
        if column is not None and not column.foreign_keys:
            session.execute(delete(table).where(column == project_id))
    for role in session.scalars(select(Role)):
        if any(one["knowledge_id"] in learned for one in role.knows or []):
            role.knows = [one for one in role.knows if one["knowledge_id"] not in learned]
            role.updated_at = now()
    for other in session.scalars(select(Project).where(Project.id != project_id)):
        if project_id in (other.memory_links or []):
            # (Else the other's next save of its links is refused: one is not a project.)
            other.memory_links = [one for one in other.memory_links if one != project_id]
    _remove(session, Project.__table__, Project.id == project_id)
    session.commit()
    _forget_files(request, session, chats, kept)
    for trigger_id in triggers:
        request.app.state.triggers.removed(trigger_id, [])
    return Response(status_code=204)


def _at_work(session: Session, project: Project, chats: list[str], runner) -> str | None:
    """Why the project is not deleted now: a turn of it at work or waiting, a command it
    started still running, work of it waiting to be applied, a night of it, or knowledge of
    it learning."""
    if held := branch_held(session, project.id):
        return held[1]
    if any(runner.commands.live_outputs(cid) for cid in chats):
        # (Kept running past its turn - a dev server - it would go on with no card to stop it.)
        return "a command it started is still running: stop it first"
    if session.scalar(select(AwayRun.id).where(
            AwayRun.project_id == project.id, AwayRun.status == "running").limit(1)):
        return "its jobs are being worked on while you're away: stop them first"
    rows = session.scalars(select(ProjectKnowledge).where(
        ProjectKnowledge.project_id == project.id))
    if any(knowledge.learning(project.root_path, knows.knowledge_of(row)) for row in rows):
        return "its knowledge is learning: delete the project once that is done"
    return None


@router.get("/{project_id}/sites", response_model=list[AllowedWebOut])
def project_sites(project_id: str, session: Session = Depends(get_session)):
    """The sites the project's agents' browsers open (K-tarayici-disari A3), oldest first: read
    as a chat's rules are, from anywhere; changed only from the app's own page (web_requests)."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    return session.scalars(select(AllowedWeb).where(AllowedWeb.project_id == project_id)
                           .order_by(AllowedWeb.created_at, literal_column("allowed_web.rowid")))


@router.get("/{project_id}/allowed", response_model=list[ChatRulesOut])
def project_allowed(project_id: str, session: Session = Depends(get_session)):
    """What runs without asking in each chat of the project (tek-ev: Settings › This project): its
    "Always run" commands made here and its web rules, by chat, newest chat first; chats with
    none left out. Read as a chat's rules are, from anywhere; changed by their own endpoints.
    The sites, the project's, are `/sites`."""
    if session.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    chats = session.scalars(select(Conversation).where(Conversation.project_id == project_id)
                            .order_by(Conversation.updated_at.desc())).all()
    commands = session.scalars(select(AllowedCommand).where(
        AllowedCommand.project_id == project_id).order_by(
        AllowedCommand.created_at, literal_column("allowed_commands.rowid"))).all()
    web = session.scalars(select(AllowedWeb).where(
        AllowedWeb.conversation_id.in_([chat.id for chat in chats])).order_by(
        AllowedWeb.created_at, literal_column("allowed_web.rowid"))).all()
    listed = [{
        "conversation_id": chat.id, "title": chat.title,
        "commands": [allowed_command_out(rule) for rule in commands
                     if rule.conversation_id == chat.id],
        "web": [allowed_web_out(rule) for rule in web if rule.conversation_id == chat.id],
    } for chat in chats]
    return [chat for chat in listed if chat["commands"] or chat["web"]]


def checked_folders(given: list[str], root: str | None = None) -> list[str]:
    """Folders to work in besides a project, as they really are - or 422 with why not.
    Never the project's own folder `root`, nor one in it (B-93: listed, it seemed added). One
    that holds it may be (slice 75): an agent in a working copy is refused the project's
    files through it (`OF_THE_PROJECT`), so its work still goes in by Take in only."""
    try:
        folders = [listed_folder(folder) for folder in given]
    except WorkspaceError as exc:
        raise HTTPException(422, str(exc)) from None
    own = Path(root).resolve() if root else None
    for entry, folder in zip(given, folders, strict=True):
        if own and folder.is_relative_to(own):
            raise HTTPException(422, f"{entry} is the project's own folder, or in it: its agents "
                                     "work there already, so it is not added")
    return list(dict.fromkeys(str(folder) for folder in folders))


def _root(session: Session, project_id: str) -> str:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project.root_path


def _answer(read, *args):
    try:
        return read(*args)
    except project_files.Refused as refused:
        raise HTTPException(refused.status, str(refused)) from None


# shortcut: the latest reports only, one per branch or folder; page them if users ask for more.
MOST_REPORTS = 20


def _reports(session: Session, project: Project, seen: dict) -> list[dict]:
    """What agents of the project said with report_git, latest first and one per branch or
    worktree, each with whether git shows it now. The agent's words, as text."""
    root = Path(project.root_path)
    folders = {git.folder_key(one["path"], root) for one in seen["worktrees"]}
    found, had = [], set()
    for arguments, at, agent in session.execute(
        select(ToolCall.arguments, ToolCall.started_at, Agent.name)
        .join(Agent, Agent.id == ToolCall.agent_id)
        .join(Run, Run.id == ToolCall.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(Conversation.project_id == project.id, ToolCall.name == "report_git",
               ToolCall.status == "succeeded")
        .order_by(ToolCall.started_at.desc()).limit(MOST_REPORTS * 5)
    ):
        try:
            said = git.reported(json.loads(arguments), root)
        except (ValueError, TypeError, AttributeError):
            continue  # (not JSON, not an object, or refused when it was said)
        branch, worktree = said.get("branch"), said.get("worktree")
        if (branch, worktree) in had or not (branch or worktree):
            continue
        had.add((branch, worktree))
        found.append({
            "branch": branch, "worktree": worktree, "merge_into": said.get("merge_into"),
            "why": said.get("why"), "commits": said.get("commits"), "agent": agent, "at": at,
            "seen": (not branch or branch in seen["names"])
            and (not worktree or git.folder_key(worktree, root) in folders),
        })
        if len(found) == MOST_REPORTS:
            break
    return found


@router.get("/{project_id}/git", response_model=GitOut | None,
            dependencies=[Depends(require_origin)])
def project_git(project_id: str, session: Session = Depends(get_session)):
    """The project's git for the top bar and its map (slice 70), read with git only: null
    where the project is not a repository's top folder, or git does not answer in time."""
    project = _project(session, project_id)
    root = Path(project.root_path)
    seen = git.look(root)
    return _git_out(session, project, seen, git.unsaved(root) if seen else None)


@router.get("/{project_id}/pull-request", dependencies=[Depends(require_origin)])
def pull_request_ready(project_id: str, session: Session = Depends(get_session)) -> dict:
    """D2, for Settings › This project: whether a finished branch can go as a pull request - null -
    or why not (gh not installed or not logged in, no GitHub remote). Runs gh, not git's push."""
    return {"why_not": git.pr_ready(Path(_project(session, project_id).root_path))[1]}


@router.post("/{project_id}/github-issues", dependencies=[Depends(require_own_origin)])
def github_issues(project_id: str, session: Session = Depends(get_session)) -> dict:
    """Item 57, "From a GitHub issue…": the open issues of the project's GitHub repository, read
    with the user's own gh - or none, and why (gh not installed or logged in, no GitHub remote).
    A POST from the app's own page only: it reads GitHub as the user."""
    found, why = git.issues(Path(_project(session, project_id).root_path))
    return {"why_not": why, "issues": found}


def _git_out(session: Session, project: Project, seen: dict | None, unsaved: str | None):
    if seen is None:
        return None
    held = branch_held(session, project.id)
    return {**seen, "reports": _reports(session, project, seen), "commit": project.git_commit,
            "switch_blocked": held[1] if held else unsaved}


@router.post("/{project_id}/git/switch", response_model=GitOut | None,
             dependencies=[Depends(require_own_origin)])
async def switch_branch(project_id: str, body: GitSwitchIn, request: Request,
                        session: Session = Depends(get_session)):
    """K-dallar: the git map's Switch to, or New branch from here - from the app's own page
    only (an agent's request must not move the project under another's work). Not while a
    turn of the project runs, a Take in or a kept copy waits, or the working tree holds what
    is not committed (409, why in words); a turn that starts meanwhile waits for it
    (`AgentRunner.switching`). The project's git as it is afterwards."""
    project = _project(session, project_id)
    root = Path(project.root_path)
    async with request.app.state.runner.switching(project.root_path):
        held = branch_held(session, project.id)
        if why := held[1] if held else await asyncio.to_thread(git.unsaved, root):
            raise HTTPException(409, why)
        try:
            await asyncio.to_thread(git.switch, root, body.name, body.new,
                                    request.app.state.settings.runtime_root)
        except git.Refused as refused:
            raise HTTPException(422, str(refused)) from None
    seen = await asyncio.to_thread(git.look, root)
    unsaved = await asyncio.to_thread(git.unsaved, root) if seen else None
    return _git_out(session, project, seen, unsaved)


# The Files window (slice 42c): the project's tree one level at a time, and a file read only.
# K-dallar: `ref`, a branch's full name from the git map, reads that branch from git instead -
# without switching to it - and Changes is what it changed since it left the project's branch.
@router.get("/{project_id}/files", response_model=list[ProjectEntryOut],
            dependencies=[Depends(require_origin)])
def project_files_of(project_id: str, path: str = "", ref: str | None = None,
                     session: Session = Depends(get_session)):
    root = _root(session, project_id)
    return _answer(project_files.listing_at, root, ref, path) if ref else _answer(
        project_files.listing, root, path)


@router.get("/{project_id}/file", response_model=ProjectFileOut,
            dependencies=[Depends(require_origin)])
def project_file(project_id: str, path: str, ref: str | None = None,
                 session: Session = Depends(get_session)):
    root = _root(session, project_id)
    return _answer(project_files.text_at, root, ref, path) if ref else _answer(
        project_files.text_of, root, path)


# K-degisenler: the Workspace's Changes tab - what git says is changed, and one file's diff.
@router.get("/{project_id}/changes", response_model=list[GitChangeOut] | None,
            dependencies=[Depends(require_origin)])
def project_changes(project_id: str, ref: str | None = None,
                    session: Session = Depends(get_session)):
    """null where the project shows no git: the tab lists KOLONİ's own record then."""
    root = _root(session, project_id)
    return _answer(project_files.changes_at, root, ref) if ref else git.changes(Path(root))


@router.get("/{project_id}/changes/diff", response_model=FileChangeDiffOut,
            dependencies=[Depends(require_origin)])
def project_change_diff(project_id: str, path: str, ref: str | None = None,
                        session: Session = Depends(get_session)):
    root = _root(session, project_id)
    return _answer(project_files.diff_at, root, ref, path) if ref else _answer(
        project_files.diff_of, root, path)


# K-devir-4: the last works KOLONİ has on record of one file, for the line over it in the
# Workspace; the path vetted as the file endpoints vet theirs (a secret: 404, nothing said).
@router.get("/{project_id}/file-history", response_model=list[FileHistoryOut] | None,
            dependencies=[Depends(require_origin)])
def project_file_history(project_id: str, path: str, session: Session = Depends(get_session)):
    root = Path(_root(session, project_id)).resolve()
    if not path or _answer(project_files._where, root, path) == root:
        raise HTTPException(404, "no such file")
    return handoff.on_file(session, project_id, path)


# K-ortak-klasor: the teams' shared folder, on the canvas; a file of it taken into the project
# (the user's word: from the app's own page only).
@router.get("/{project_id}/shared", response_model=list[SharedFileOut],
            dependencies=[Depends(require_origin)])
def shared_files(project_id: str, session: Session = Depends(get_session)):
    return shared.listing(_root(session, project_id))


@router.post("/{project_id}/shared/take", dependencies=[Depends(require_own_origin)])
def take_shared(project_id: str, body: SharedPathIn,
                session: Session = Depends(get_session)) -> SharedPathIn:
    try:
        return SharedPathIn(path=_answer(shared.take, _root(session, project_id), body.path))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


# K-drawio: the user's "Save as PNG / SVG" in the Workspace - their own write, no card (as the
# attachments they save): the picture the viewer drew, beside the diagram, by its name.
@router.post("/{project_id}/diagram-picture", response_model=SharedPathIn,
             dependencies=[Depends(require_own_origin)])
def save_diagram_picture(project_id: str, body: DiagramPictureIn,
                         session: Session = Depends(get_session)) -> SharedPathIn:
    root = Path(_root(session, project_id)).resolve()
    # (Vetted as a file the Workspace reads - and there: no picture of a diagram that is not.)
    if not _answer(project_files._where, root, body.path).is_file():
        raise HTTPException(404, "no such diagram")
    try:
        data = base64.b64decode(body.data, validate=True)
        return SharedPathIn(path=diagram.write_picture(Workspace(root), body.path, body.format,
                                                       data))
    except (binascii.Error, WorkspaceError) as exc:
        raise HTTPException(422, str(exc) if isinstance(exc, WorkspaceError)
                            else "the picture is not base64") from None


# K-yabanci-talimat: said on Settings › This project. In a thread: the walk may take its 2 s.
@router.get("/{project_id}/others-instructions", response_model=OthersInstructionsOut,
            dependencies=[Depends(require_origin)])
def others_instructions(project_id: str, session: Session = Depends(get_session)):
    return project_files.others_instructions(_root(session, project_id))


# K-buyuk-proje: the project map in Settings (This folder), with the user's test commands.
# In a thread: a scan may take its seconds (`project_map`).
def _map(project: Project, fresh: bool = False) -> dict:
    return project_map.edited(project_map.scan(project.root_path, fresh), project.test_commands)


def _project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


@router.get("/{project_id}/map", response_model=ProjectMapOut,
            dependencies=[Depends(require_origin)])
def project_map_of(project_id: str, session: Session = Depends(get_session)):
    return _map(_project(session, project_id))


@router.post("/{project_id}/map/refresh", response_model=ProjectMapOut,
             dependencies=[Depends(require_origin)])
def refresh_map(project_id: str, session: Session = Depends(get_session)):
    return _map(_project(session, project_id), fresh=True)


@router.put("/{project_id}/map/test", response_model=ProjectMapOut,
            dependencies=[Depends(require_own_origin)])
def set_part_test(project_id: str, body: PartTestIn, session: Session = Depends(get_session)):
    """The user's test command for a part, from the app's own page only: a later slice runs it
    without asking at Full auto, so an agent's request must not set it. Empty: no test. A part
    the map no longer has may still be changed where the user set one for it."""
    project = _project(session, project_id)
    if body.path not in project.test_commands and body.path not in {
            part["path"] for part in _map(project)["parts"]}:
        raise HTTPException(422, f"{body.path} is not a part of the project's map")
    project.test_commands = {**project.test_commands, body.path: body.command.strip()}
    session.commit()
    return _map(project)


@router.delete("/{project_id}/map/test", response_model=ProjectMapOut,
               dependencies=[Depends(require_own_origin)])
def reset_part_test(project_id: str, path: str, session: Session = Depends(get_session)):
    """KOLONİ's guess again for a part: the user's test command for it is forgotten."""
    project = _project(session, project_id)
    project.test_commands = {
        key: value for key, value in project.test_commands.items() if key != path}
    session.commit()
    return _map(project)


# A page, a drawing or a picture of the project, previewed in a frame by slice 39's policy. No
# origin is asked for: the frame's own requests come from an origin of their own ("null").
@router.get("/{project_id}/raw/{path:path}", include_in_schema=False)
def project_raw(project_id: str, path: str, request: Request,
                session: Session = Depends(get_session)):
    data, kind = _answer(project_files.raw, _root(session, project_id), path)
    keyed_if_read_by_the_app(request, kind)
    return Response(data, media_type=kind, headers=views.headers_of(kind))


# On the event loop, as everything that reaches the runner is.
@router.patch("/{project_id}", response_model=ProjectOut, dependencies=[Depends(require_origin)])
async def patch_project(  # noqa: C901
    project_id: str, body: ProjectPatch, request: Request, session: Session = Depends(get_session)
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    before = {name: getattr(project, name) for name in koloni.SETTINGS}
    if body.docker_image is not None:
        project.docker_image = body.docker_image.strip() or None
    if body.docker_network is not None:
        project.docker_network = body.docker_network
    if body.exec_location is not None:
        if body.exec_location == "docker" and not project.docker_image:
            raise HTTPException(422, "choose a Docker image first")
        project.exec_location = body.exec_location
    users_own = ("search_order", "search_url", "search_agy", "notify_url", "notify_format",
                    "notify_desktop", "check_command", "measure_command", "git_commit",
                    "finish_way", "auto_notes", "observe_reports", "suggest_tasks", "suggest_tier",
                    "hide_secrets", "pass_env",
                    "canary", "lead_work", "continue_steps", "memory_links", "embedding_model",
                    "when_away", "away_minutes", *SPAWN)
    limited = "turn_token_limit" in body.model_fields_set  # null takes the limit away
    # tek-ev: what a discussion and a room may spend; null: no limit.
    spends = {"discussion_budget", "room_posts", "room_tokens", "room_minutes"} & (
        body.model_fields_set)
    crowded = "max_agents" in body.model_fields_set  # the same: null takes it away
    noted = "day_note_at" in body.model_fields_set  # the same: null sends it no more
    budgeted = "monthly_budget" in body.model_fields_set  # the same
    gated = "finish_tests" in body.model_fields_set  # the same: null is automatic again
    embedded = "embedding_provider_id" in body.model_fields_set  # the same: null is off
    if limited or crowded or noted or budgeted or gated or embedded or spends or any(
        getattr(body, name) is not None for name in users_own
    ):
        # Where a search and a notification go, how much a turn or a month may spend, how many
        # agents may work at once is the user's to say, from the app's own page: not a
        # command's that an agent runs against the app's address. And so is the command
        # that checks or scores an agent's work (KOLONİ runs it), whether what is taken may be
        # committed (it writes into the user's repository), and whether a model is asked
        # after every turn what the turn found, or after every sub-agent's report what the
        # record shows of it (requests KOLONİ makes and the user pays). And so is what of
        # its secrets its commands see: a command must not hand itself one, nor take away the
        # test key planted to catch one sent out (101). And whether a new
        # chat's Lead writes files itself, or answers for the user while they are away (a
        # request of their plan, K-cli-vekil), or its agents finish only once KOLONİ ran the tests.
        # And so are its chats' sub-agent settings and what their discussions and rooms spend.
        require_own_origin(request)
    if body.teams_mode is not None or body.teams is not None:
        # The teams its new chats work with: the user's to say, as a chat's are (slice 84b).
        require_own_origin(request)
        project.teams_mode = body.teams_mode or project.teams_mode
        rows = chat_rows(session, project.teams_mode, body.teams)
        if rows is not None or project.teams_mode != "manual":
            project.teams = rows or []
    for name in ("also_in", "read_in"):
        if getattr(body, name) is not None:
            # Where its agents work without asking to go there: the user's to say, from the
            # app's own page - not a command's that an agent runs against the app's address.
            require_own_origin(request)
            setattr(project, name, checked_folders(getattr(body, name), project.root_path))
    if body.check_command is not None:
        project.check_command = body.check_command.strip() or None
    if body.measure_command is not None:
        project.measure_command = body.measure_command.strip() or None
    if body.git_commit is not None:
        project.git_commit = body.git_commit
    if body.finish_way is not None:
        # D2: a pull request is the user's consent to push its branches - only where gh can
        # open one (greyed out with this why in Settings › This project).
        if body.finish_way == "pull_request" and (why := (await asyncio.to_thread(
                git.pr_ready, Path(project.root_path)))[1]):
            raise HTTPException(422, f"a pull request cannot be opened: {why}")
        project.finish_way = body.finish_way
    if body.pass_env is not None:
        project.pass_env = body.pass_env.strip() or None
    if gated:
        project.finish_tests = body.finish_tests
    if limited:
        project.turn_token_limit = body.turn_token_limit
    if crowded:
        project.max_agents = body.max_agents
    if budgeted:
        project.monthly_budget = body.monthly_budget
    if body.notify_desktop and not web.has_desktop():
        raise HTTPException(422, web.NO_DESKTOP)  # as the tool would say each time
    for name in ("search_order", "search_agy", "notify_format", "notify_desktop", "auto_notes",
                 "observe_reports", "suggest_tasks", "suggest_tier", "hide_secrets", "canary",
                 "lead_work", "continue_steps", "when_away", "away_minutes", *SPAWN):
        if getattr(body, name) is not None:
            setattr(project, name, getattr(body, name))
    for name in spends:
        setattr(project, name, getattr(body, name))
    if body.memory_links is not None:
        # 22c: whose memory its recall also reads - projects of this KOLONİ, never itself.
        others = list(dict.fromkeys(body.memory_links))
        known = set(session.scalars(select(Project.id).where(Project.id.in_(others))))
        if project.id in others or set(others) - known:
            raise HTTPException(
                422, "a project to look in is another project of this KOLONİ")
        project.memory_links = others
    if embedded:
        # 22c: the server that embeds for a search by meaning: any provider with an address.
        if body.embedding_provider_id is not None and not (
                (chosen := session.get(Provider, body.embedding_provider_id))
                and chosen.base_url):
            raise HTTPException(
                422, "the search by meaning needs a provider with a server address")
        project.embedding_provider_id = body.embedding_provider_id
    if body.embedding_model is not None:
        project.embedding_model = body.embedding_model.strip() or meaning.DEFAULT_MODEL
    for name in ("search_url", "notify_url"):
        value = getattr(body, name)
        if value is None:
            continue
        address = value.strip()
        if address and not web.settable(address):
            # Said without the address: the notification address is a secret.
            raise HTTPException(
                422, f"{name} must be an http or https address, without a user name or password"
            )
        setattr(project, name, address or None)
    if noted:
        if body.day_note_at and not project.day_note_at:
            # Switched on: a day it was off is no day to send late (`Triggers.day_notes`).
            yesterday = local_day(now(), request.app.state.triggers.zone) - timedelta(days=1)
            project.day_note_sent = max(project.day_note_sent or yesterday, yesterday)
        project.day_note_at = body.day_note_at
    # As the project is after this change: a time with nowhere to send it is never kept.
    if project.day_note_at and not (project.notify_url or project.notify_desktop):
        raise HTTPException(
            422, "the day's summary is sent to the notification address or the desktop "
            "notification: keep one, or empty the summary's time")
    changed = {name: getattr(project, name) for name in koloni.SETTINGS
               if getattr(project, name) != before[name]}
    # Into the folder's .koloni/ (slice 86c) only from the app's own page: a command an agent
    # runs against the app's address changes what is saved here, never a file of the repository.
    if changed and request.headers.get("origin") in request.app.state.settings.allowed_origins:
        try:
            koloni.save_settings(project.root_path, changed)
        except project_files.Refused as refused:
            raise HTTPException(refused.status, str(refused)) from None
    session.commit()
    if crowded:
        request.app.state.runner.let_in()  # there may be room now for agents that wait
    if {*FOLLOWED, "lead_work"} & body.model_fields_set:
        tell_chats(session, request.app.state.bus, project.id)
    return project


@router.post("/{project_id}/koloni/use", response_model=ProjectOut,
             dependencies=[Depends(require_own_origin)])
def use_koloni(project_id: str, body: KoloniUseIn, session: Session = Depends(get_session)):
    """The user's yes to the settings the folder's .koloni/settings.json asks for (slice 86c),
    which may come from another machine: where its commands run is the user's to say. Only
    to what the page showed (`body.asks`): a script, a pull or a checkout may have changed
    the file since, and what it says now has not been seen."""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    values, why = koloni.settings(project.root_path)
    if values is None:
        raise HTTPException(422, why or f"{koloni.SETTINGS_FILE} is not there")
    asks = {name: value for name, value in values.items() if getattr(project, name) != value}
    if dict(body.asks) != asks:
        raise HTTPException(409, "the folder's settings changed since they were shown: look at "
                                 "them again")
    for name, value in asks.items():
        setattr(project, name, value)
    if project.exec_location == "docker" and not project.docker_image:
        raise HTTPException(422, "choose a Docker image first")
    session.commit()
    return project
