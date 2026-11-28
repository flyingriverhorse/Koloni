"""A project's board: every conversation's agents at work, at one look - who runs, who
waits and for what, which files each holds, and where two conversations want one file.
Read from the agents' records and from who holds what now; it changes nothing."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, func, literal_column, or_, select, true
from sqlalchemy.orm import Session

from app import backlog, decisions
from app.agent import AGENT_TERMINAL, _line_on_record
from app.api.deps import get_session
from app.changes import in_copy
from app.db.models import (
    Agent,
    BacklogTask,
    Conversation,
    FileChange,
    Merge,
    Project,
    Question,
    Run,
    ToolCall,
)
from app.schemas import BoardOut

router = APIRouter(prefix="/api", tags=["board"])

# Each copy's counts by its agent, with how many changes its line has in it and the last of
# them: the board is read every few seconds, and a copy is diffed again only once it changed.
_COUNTED: dict[str, tuple[tuple, dict]] = {}
MOST_COUNTED = 200


def _counted(session: Session, agent: Agent) -> dict:
    """What the agent's own working copy changed so far (slice 70): files, lines added and
    removed. It diffs whole files: never on the event loop (`_copies_counted`)."""
    line = _line_on_record(session, agent.id)
    stamp = tuple(
        session.execute(
            select(func.count(FileChange.id), func.max(literal_column("file_changes.rowid"))).where(
                FileChange.agent_id.in_(line), FileChange.status == "in_copy"
            )
        ).one()
    )
    if (known := _COUNTED.get(agent.id)) and known[0] == stamp:
        return known[1]
    files = in_copy(session, line)
    counts = {
        "files": len(files),
        "additions": sum(one["additions"] for one in files),
        "deletions": sum(one["deletions"] for one in files),
    }
    if len(_COUNTED) >= MOST_COUNTED:
        _COUNTED.clear()
    _COUNTED[agent.id] = (stamp, counts)
    return counts


def _copies_counted(session: Session, project: Project | None) -> dict[str, dict]:
    """`_counted` of every agent at work in its own copy, of the project or of all: for a
    thread of its own."""
    mine = Conversation.project_id == project.id if project else true()
    return {
        agent.id: _counted(session, agent)
        for agent in session.scalars(
            select(Agent)
            .join(Run, Run.id == Agent.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(mine, Agent.status.not_in(AGENT_TERMINAL))
        )
        if (agent.copy or {}).get("state") == "own"
    }


@router.get("/board", response_model=BoardOut)
async def board_everywhere(request: Request, session: Session = Depends(get_session)):
    """Every chat's board, of every folder and of none: what waits for the user anywhere."""
    changed = await asyncio.to_thread(_copies_counted, session, None)
    return board_of(session, None, request.app.state.runner, changed)


@router.get("/projects/{project_id}/board", response_model=BoardOut)
async def board(project_id: str, request: Request, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    changed = await asyncio.to_thread(_copies_counted, session, project)
    # K1: what was decided for the user and waits for their OK - one count, the project's.
    decided = await asyncio.to_thread(decisions.unseen_count, session, project.id)
    return {**board_of(session, project, request.app.state.runner, changed), "decided": decided}


def unseen(talk: Conversation, turn: dict | None) -> bool:
    """herdr's "done, not seen" (28 Nov 2026): its last turn ended - done, failed or stopped - after
    its page last had it on screen (`Conversation.seen_at`, set by `/looking`)."""
    ended = turn and turn["status"] in ("completed", "failed", "cancelled", "interrupted")
    end = turn["ended_at"] if turn else None
    return bool(ended and end and (talk.seen_at is None or end > talk.seen_at))


def waiting_in(conversation: dict) -> int:
    """What of a board's conversation waits for the user: the twin of the page's
    `waitCount` (frontend/src/board/waiting.ts), for what is said without the page."""
    # Each change and question of an agent that asks; one for what has no kind here.
    asking = sum(
        max(agent.get("changes_to_approve", 0) + agent.get("questions", 0), 1)
        for agent in conversation["agents"]
        if agent["status"] == "waiting_approval"
    )
    proposed = any(agent["status"] == "proposed" for agent in conversation["agents"])
    plan = bool((conversation.get("turn") or {}).get("plan_waits"))
    return conversation["merges_pending"] + max(asking, int(proposed)) + plan


def board_of(
    session: Session, project: Project | None, runner, changed: dict | None = None
) -> dict:
    """One project's board; None: every chat's, of every folder and of none (slice 86a)
    - the same few queries either way, however many projects there are."""
    mine = Conversation.project_id == project.id if project else true()
    theirs = BacklogTask.project_id == project.id if project else true()
    talks = session.scalars(
        select(Conversation).where(mine).order_by(Conversation.updated_at.desc())
    ).all()
    # Only the agents whose work is going on; none of what they said or did is read.
    at_work = session.execute(
        select(Agent, Run.conversation_id)
        .join(Run, Run.id == Agent.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(mine, Agent.status.not_in(AGENT_TERMINAL))
        .order_by(Agent.created_at, literal_column("agents.rowid"))
    ).all()
    # The conversation of each agent that is waited for: one whose own work is over
    # still holds what it changed in a working copy that is not taken in yet.
    home: dict[str, str] = {
        holder: cid
        for holder, cid in session.execute(
            select(Agent.id, Run.conversation_id)
            .join(Run, Run.id == Agent.run_id)
            .where(
                Agent.id.in_(
                    [agent.waiting_for["agent_id"] for agent, _cid in at_work if agent.waiting_for]
                )
            )
        )
    }
    # What the agents that ask now put before the user, by kind: a change to approve, a
    # question - and of those, its own, not KOLONİ's card about it (`Question.leave`). (Asked
    # only of them: a record left by a turn that ended asks nothing.)
    asking = [agent.id for agent, _cid in at_work if runner.asking(agent.id)]
    changes, questions, own = (
        {
            agent_id: n
            for agent_id, n in session.execute(
                select(table.agent_id, func.count(table.id))
                .where(table.agent_id.in_(asking), table.status == status, *also)
                .group_by(table.agent_id)
            )
        }
        for table, status, also in (
            (FileChange, "proposed", ()),
            (Question, "pending", ()),
            (Question, "pending", (Question.leave.is_(False),)),
        )
    )
    # The agents a tool runs for now: their quiet is measured against a longer time.
    in_tool = set(
        session.scalars(
            select(ToolCall.agent_id).where(
                ToolCall.status == "running",
                ToolCall.agent_id.in_([agent.id for agent, _cid in at_work]),
            )
        )
    )
    # Changes put before the user: the agent that made them may have ended its own work. And a
    # copy kept for Take in that holds a file, as its chat's Ready for you counts it (`keptToTake`).
    pending: dict[str, int] = dict(
        session.execute(
            select(Run.conversation_id, func.count(Merge.id))
            .join(Run, Run.id == Merge.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(
                mine,
                or_(
                    Merge.status == "pending",
                    and_(
                        Merge.status == "interrupted",
                        Merge.kept_in.is_not(None),
                        func.json_array_length(Merge.files) > 0,
                    ),
                ),
            )
            .group_by(Run.conversation_id)
        )
        .tuples()
        .all()
    )
    # Each conversation's last turn: the one sent last (a message sent again after a restart
    # is the newest), else put on record last. A message taken back before its turn started
    # was never a turn (as `topics.latest_of_user` says).
    ranked = (
        select(
            Run.id,
            func.row_number()
            .over(
                partition_by=Run.conversation_id,
                order_by=(Run.created_at.desc(), literal_column("runs.rowid").desc()),
            )
            .label("at"),
        )
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(mine)
        .where(or_(Run.status != "cancelled", Run.started_at.is_not(None)))
        .subquery()
    )
    runs = session.execute(
        select(
            Run.conversation_id,
            Run.id,
            Run.status,
            Run.started_at,
            Run.ended_at,
            Run.input_tokens,
            Run.output_tokens,
            Run.plan,
        ).where(Run.id.in_(select(ranked.c.id).where(ranked.c.at == 1)))
    ).all()
    ran = [run.id for run in runs]
    # Its agents that started, and their tokens as the chat's turn summary adds them up
    # (`turnTokens`): known only where every one of them said its own.
    started = {
        rid: (n, sent, made) if n_sent == n and n_made == n else (n, None, None)
        for rid, n, sent, made, n_sent, n_made in session.execute(
            select(
                Agent.run_id,
                func.count(Agent.id),
                func.sum(Agent.input_tokens),
                func.sum(Agent.output_tokens),
                func.count(Agent.input_tokens),
                func.count(Agent.output_tokens),
            )
            .where(Agent.run_id.in_(ran), Agent.started_at.is_not(None))
            .group_by(Agent.run_id)
        )
    }
    # The model its Lead ran on: a turn keeps the model's name, only an agent its provider.
    lead = {
        rid: (provider, model)
        for rid, provider, model in session.execute(
            select(Agent.run_id, Agent.provider_name, Agent.model_id).where(
                Agent.run_id.in_(ran), Agent.depth == 0
            )
        )
    }
    turns = {}
    for run in runs:
        # No agent started: what the turn itself kept.
        n, sent, made = started.get(run.id, (0, run.input_tokens, run.output_tokens))
        provider, model = lead.get(run.id, (None, None))
        turns[run.conversation_id] = {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "agents": n,
            "provider_name": provider,
            "model_id": model,
            "tokens": None if sent is None or made is None else sent + made,
            "plan_waits": run.status == "completed"
            and (run.plan or {}).get("status") == "proposed",
        }
    agents: dict[str, list[dict]] = {}
    conflicts: dict[tuple[str, str], dict] = {}
    for agent, cid in at_work:
        agents.setdefault(cid, []).append(
            {
                "id": agent.id,
                "name": agent.name,
                "status": "waiting_approval" if runner.asking(agent.id) else agent.status,
                "role": agent.role_name,
                "provider_name": agent.provider_name,
                "model_id": agent.model_id,
                "holds": runner.claims.held_by(agent.id),
                "copy": agent.copy,
                "changed": (changed or {}).get(agent.id),
                "waiting_for": agent.waiting_for,
                "sign": agent.sign,
                "last_event_at": agent.last_event_at,
                "in_tool": agent.id in in_tool,
                "changes_to_approve": changes.get(agent.id, 0),
                "questions": questions.get(agent.id, 0),
                "own_questions": own.get(agent.id, 0),
            }
        )
        wanted = agent.waiting_for
        if not wanted or home.get(wanted["agent_id"], cid) == cid:
            continue
        # A file held in one conversation and waited for in another: one entry for the
        # file and its holder, with everyone of other conversations who waits for it.
        conflict = conflicts.setdefault(
            (wanted["path"], wanted["agent_id"]),
            {
                "path": wanted["path"],
                "holder": {
                    "conversation_id": home[wanted["agent_id"]],
                    "agent_name": wanted["agent_name"],
                },
                "waiting": [],
            },
        )
        conflict["waiting"].append({"conversation_id": cid, "agent_name": agent.name})
    return {
        # (Every chat's: no one limit; at work, in every project.)
        "limit": project.max_agents if project else None,
        "running": runner.at_work(project.root_path)
        if project
        else sum(runner.at_work(root) for root in session.scalars(select(Project.root_path))),
        "conversations": [
            {
                "conversation_id": talk.id,
                "title": talk.title,
                "agents": agents.get(talk.id, []),
                "merges_pending": pending.get(talk.id, 0),
                "turn": turns.get(talk.id),
                "project_id": talk.project_id,
                "unseen": unseen(talk, turns.get(talk.id)),
            }
            for talk in talks
        ],
        "conflicts": list(conflicts.values()),
        # (A task with a change waiting that is also in review counts twice: two things.)
        # (Counted here, not in SQL: a JSON column keeps None as JSON null.)
        "backlog_waiting": sum(
            (task.status == "review" or task.status == "proposed" and not backlog.declined(task))
            + (task.pending is not None)
            + (task.status == "todo" and backlog.unseen(task))  # ("Added for you": its OK)
            for task in session.scalars(select(BacklogTask).where(theirs))
        ),
    }
