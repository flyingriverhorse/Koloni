"""Undo a turn, or put the conversation back to before one (slice 50). The turns' applied
changes are reverted latest first by the one revert there is; a file changed since is
skipped and said so, never written over. Working copies kept from them are discarded, their
folders deleted. What their commands did, and what is done but not on record, cannot be taken
back: it is named. GET looks ahead and changes nothing; POST only from the app's own page."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.agent import IN_THE_PROJECT, TERMINAL
from app.api.deps import get_session, require_own_origin
from app.api.file_changes import held_by_another, revert_one
from app.changes import would_revert
from app.db.models import (
    Command,
    Compare,
    Conversation,
    FileChange,
    Merge,
    Message,
    Run,
    ToolCall,
    Topic,
    project_of,
)
from app.schemas import UndoOut
from app.workspace import for_change

router = APIRouter(prefix="/api", tags=["undo"])

# What a CLI did that KOLONİ noted and holds no change of: nothing on record to take back.
NOTED = ("write_file", "edit_file", "delete_file", "files_changed")
NOT_DISCARDED = "its working copy was not discarded; decide it on its card"
# A change found in the project while a CLI worked in its copy may be the user's own (K-70-kimin).
BY_WHOM = ("who changed it is not known - it changed in the project while the CLI worked in "
           "its copy: undo it on its own row if it is the CLI's")
# How such a change was on record before (`IN_THE_PROJECT`), said as the CLI's.
WAS_UNKNOWN = "changed by the CLI in the project itself, outside its working copy"


def _run(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


def _turns(session: Session, cid: str, run_id: str, later: bool) -> list[tuple[Run, int | None]]:
    """The turn - and, `later`, every later one of its conversation - each with which turn of
    its topic it is, counted as the turn list counts them (those that started)."""
    numbered: list[tuple[Run, int | None]] = []
    counted: dict[str, int] = {}
    for run in session.scalars(
        select(Run).where(Run.conversation_id == cid)
        .order_by(Run.created_at, literal_column("runs.rowid"))
    ):
        number = None
        if run.topic_id and run.started_at:
            number = counted[run.topic_id] = counted.get(run.topic_id, 0) + 1
        numbered.append((run, number))
    at = next((i for i, (run, _n) in enumerate(numbered) if run.id == run_id), None)
    if at is None:
        raise HTTPException(404, "no such turn in this conversation")
    return numbered[at:] if later else [numbered[at]]


def _asked(session: Session, run_id: str) -> str:
    """The turn's own request as the turn list takes it - its message's first line (the page
    cuts it as the list does): the topic's name is its first turn's ("Open one Reviewer…:
    turn 3" for "eight")."""
    content = session.scalar(select(Message.content).where(
        Message.run_id == run_id, Message.role.in_(("user", "trigger"))).order_by(
        Message.created_at, literal_column("messages.rowid")).limit(1)) or ""
    return next((part.strip() for part in content.split("\n") if part.strip()), "")


def _latest(session: Session, cid: str) -> str | None:
    return session.scalar(select(Run.id).where(Run.conversation_id == cid).order_by(
        Run.created_at.desc(), literal_column("runs.rowid").desc()).limit(1))


def _stays(session: Session, ids: list[str]) -> list[str]:
    """What the turns did that this does not take back, besides their commands: what a CLI
    changed with no change on record (past the most one look records, outside the project),
    and the commits KOLONİ made of what was taken."""
    recorded = set(session.scalars(select(FileChange.path).where(FileChange.run_id.in_(ids))))
    said = []
    for note in session.scalars(select(ToolCall).where(
        ToolCall.run_id.in_(ids), ToolCall.origin == "cli", ToolCall.status == "succeeded",
        ToolCall.name.in_(NOTED),
        ~select(FileChange.id).where(FileChange.tool_call_id == ToolCall.id).exists(),
    ).order_by(literal_column("tool_calls.rowid"))):
        try:
            path = json.loads(note.arguments).get("path")
        except (ValueError, AttributeError):
            path = None
        if path in recorded:
            continue  # on record by another change of these turns, which is taken back
        result = note.result or ""
        said.append(result if not path or path in result else f"{path} — {result}")
    for merge in session.scalars(select(Merge).where(Merge.run_id.in_(ids))):
        commit = merge.commit or {}
        if commit.get("state") == "committed":
            sha = str(commit.get("sha") or "")[:7]
            said.append(f"KOLONİ's commit {sha} of what was taken stays in git history")
    return said


async def _undo(
    request: Request, session: Session, turns: list[tuple[Run, int | None]], do: bool,
    through: str | None = None,
) -> dict:
    runs = [run for run, _n in turns]
    if any(run.status not in TERMINAL for run in runs):
        raise HTTPException(409, "a turn of these is still running or waiting to: stop it first")
    # A comparison's sides wait for the user's choice, which takes one in and throws the
    # other away: undoing a side before that would race it (slice 54).
    open_sides = {run.compare_id for run in runs if run.compare_id}
    if open_sides and session.scalar(select(Compare.id).where(
            Compare.id.in_(open_sides), Compare.status == "open").limit(1)):
        raise HTTPException(409, "a comparison of these waits for your choice: decide it first")
    # The turns the user was shown: one that ended since is not taken back unseen.
    if through is not None and runs[-1].id != through:
        raise HTTPException(409, "a turn ended since you looked; look again")
    cid = runs[0].conversation_id
    latest = _latest(session, cid)
    ids = [run.id for run in runs]
    titles = dict(session.execute(
        select(Topic.id, Topic.title).where(Topic.conversation_id == cid)).tuples().all())
    shown = [{"run_id": run.id, "topic": titles.get(run.topic_id or ""), "turn": n,
              "request": _asked(session, run.id)} for run, n in turns]
    project = project_of(session, session.get_one(Conversation, cid))
    # Latest first: as they were applied (a kept copy's may be applied after its turn).
    changes = list(session.scalars(
        select(FileChange).where(FileChange.run_id.in_(ids), FileChange.status == "applied")
        .order_by(func.coalesce(FileChange.decided_at, FileChange.created_at).desc(),
                  literal_column("file_changes.rowid").desc())
    ))
    # Not one whose maker is not known: the user's own work is not taken back unasked.
    unknown = set(session.scalars(select(ToolCall.id).where(
        ToolCall.run_id.in_(ids),
        ToolCall.result.startswith(IN_THE_PROJECT) | ToolCall.result.startswith(WAS_UNKNOWN))))
    skip = [{"path": change.path, "why": BY_WHOM}
            for change in changes if change.tool_call_id in unknown]
    changes = [change for change in changes if change.tool_call_id not in unknown]
    # A finished turn has no change or card still waiting (its end turned them down): what
    # waits of it is a working copy kept over a restart. Discarding it deletes its folder.
    kept = [
        (merge.id, str(merge.kept_in), [
            one["path"] for one in merge.files if one["state"] != "applied"])
        for merge in session.scalars(select(Merge).where(
            Merge.run_id.in_(ids), Merge.status == "interrupted", Merge.kept_in.is_not(None)))
    ]
    commands = list(session.scalars(
        select(Command.command).where(Command.run_id.in_(ids), Command.started_at.is_not(None))
        .order_by(Command.created_at, literal_column("commands.rowid"))
    ))
    stays = _stays(session, ids)
    revert: list[str] = []
    copies = [(folder, paths) for _id, folder, paths in kept]
    if not do and project is not None:  # (a plain chat changed no file: none to look at)
        root = project.root_path
        whys = would_revert(changes, lambda path: for_change(root, path))
        # shortcut: a file another agent holds is skipped here, yet the changes after it on
        # that file are looked at as if it had been reverted; follow the hold if that misleads.
        for change, why in zip(changes, whys, strict=True):
            why = held_by_another(request, root, change) or why
            (skip.append({"path": change.path, "why": why}) if why else revert.append(change.path))
    elif do:
        copies = []
        for merge_id, folder, paths in kept:  # first: nothing of a copy lands after the reverts
            if await request.app.state.runner.decide_kept(merge_id, "reject"):
                copies.append((folder, paths))
            else:  # a decision on it is already under way
                skip += [{"path": path, "why": NOT_DISCARDED} for path in paths]
        for change in changes:
            try:
                await revert_one(request, session, change)
                revert.append(change.path)
            except HTTPException as exc:
                skip.append({"path": change.path, "why": exc.detail})
    note = None
    if do and _latest(session, cid) != latest:
        note = "A turn started while this was done: what it does is not taken back."
    return {
        "turns": shown, "revert": revert, "skip": skip,
        "reject": [path for _folder, paths in copies for path in paths],
        "copies": [{"folder": folder, "files": paths} for folder, paths in copies],
        "commands": commands, "stays": stays, "note": note,
    }


@router.get("/runs/{run_id}/undo", response_model=UndoOut)
async def undo_ahead(run_id: str, request: Request, session: Session = Depends(get_session)):
    turns = _turns(session, _run(session, run_id).conversation_id, run_id, later=False)
    return await _undo(request, session, turns, do=False)


@router.post(
    "/runs/{run_id}/undo", response_model=UndoOut, dependencies=[Depends(require_own_origin)]
)
async def undo(run_id: str, request: Request, session: Session = Depends(get_session)):
    turns = _turns(session, _run(session, run_id).conversation_id, run_id, later=False)
    return await _undo(request, session, turns, do=True)


@router.get("/conversations/{cid}/restore", response_model=UndoOut)
async def restore_ahead(
    cid: str, before: str, request: Request, session: Session = Depends(get_session)
):
    return await _undo(request, session, _turns(session, cid, before, later=True), do=False)


@router.post(
    "/conversations/{cid}/restore", response_model=UndoOut,
    dependencies=[Depends(require_own_origin)],
)
async def restore(
    cid: str, before: str, request: Request, through: str | None = None,
    session: Session = Depends(get_session),
):
    """`through`: the last turn the look ahead listed; the card always sends it. (Left out,
    the turns are not checked against what was shown.)"""
    return await _undo(
        request, session, _turns(session, cid, before, later=True), do=True, through=through
    )
