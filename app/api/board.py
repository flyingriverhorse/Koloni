"""A project's board: every conversation's agents at work, at one look - who runs, who
waits and for what, which files each holds, and where two conversations want one file.
Read from the agents' records and from who holds what now; it changes nothing."""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, literal_column, or_, select, true, union
from sqlalchemy.orm import Session

from app import backlog
from app.agent import AGENT_TERMINAL, _line_on_record
from app.api.deps import get_session
from app.changes import in_copy
from app.db.models import (
    Agent,
    BacklogTask,
    Command,
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

# How a sub-agent's model was cut, in the words KOLONİ's clients end it with (`model_client`,
# `model_anthropic`, `model_cli`, `model_session`, `model_native`): its stall timer - nothing
# came for a while after it began - or its time limit.
# shortcut: matched on those English phrases; add one when a client says its timer otherwise.
SILENT = re.compile(r"\b(?:sent nothing|did not answer) for \d", re.IGNORECASE)
TIMED_OUT = re.compile(r"\bdid not (?:start answering|answer) within \d", re.IGNORECASE)
# A report that is an error: one that starts with one ("Error: ...", "API Error (529)", a
# bare "Error"), not one that has the word, nor "Error handling added" or "Error-free now".
STARTS_WITH_ERROR = re.compile(r"^\W*(?:api\s+)?error\W*(?:[:(\d]|$)", re.IGNORECASE)
# shortcut: a report of fewer words says nothing of substance; read what it says if a short
# one that did its work is seen tagged.
SUBSTANCE_WORDS = 12


def outcome(status: str, error: str | None, report: str | None, called: bool,
            stopped_by_koloni: bool = False) -> str | None:
    """K-board-sonuc: how a sub-agent that ended came out, where that is worth a tag:
    "silent" (cut by its stall timer), "timed_out", "error" (it failed another way, or its
    report starts with an error), "nothing" (it finished having called no tool at all - not
    even to read - changed no file, run no command: `called`; and said nothing of substance).
    None for one that did its work, one KOLONİ's own limit stopped, and one stopped or declined
    by the user.
    shortcut: what a CLI does with its own tools is not all on record (its edits are, its
    reads are not): such an agent is "nothing" only when its report is short too."""
    if status == "failed" and not stopped_by_koloni:
        said = error or ""
        return "silent" if SILENT.search(said) else "timed_out" if TIMED_OUT.search(
            said) else "error"
    if status != "completed":
        return None
    if STARTS_WITH_ERROR.match(report or ""):
        return "error"
    return "nothing" if not called and len((report or "").split()) < SUBSTANCE_WORDS else None


def outcomes(session: Session, runs: list[str]) -> dict[str, list[tuple]]:
    """Of these turns, their sub-agents that ended with a class (`outcome`), by turn, oldest
    first: (the agent's row, its class, whether "Re-run the ones that failed" opens it again).
    Only one that failed is opened again - not one that finished, whatever its report says -
    and not one the Lead already opened again in that turn (a later one of its role and task
    that finished). One closed with its turn (the Lead's failure, given to those still at
    work) has no class: its turn's failure is its card's. Two queries, however many turns."""
    # (Read every few seconds: of its report only the start, which is all `outcome` reads.)
    ended = session.execute(
        select(Agent.id, Agent.run_id, Agent.name, Agent.role_name, Agent.task,
               Agent.provider_name, Agent.model_id, Agent.status, Agent.error,
               Agent.stopped_by_koloni, Agent.ended_at, Run.error.label("run_error"),
               Run.ended_at.label("run_ended_at"),
               func.substr(Agent.report, 1, 400).label("report"))
        .join(Run, Run.id == Agent.run_id)
        .where(Agent.run_id.in_(runs), Agent.depth > 0,
               Agent.status.in_(("completed", "failed")))
        .order_by(Agent.created_at, literal_column("agents.rowid"))
    ).all()
    ids = [agent.id for agent in ended]
    # A call of any tool, a change, a command. (By the turns too: their ids are indexed.)
    called = set(session.scalars(union(
        select(FileChange.agent_id).where(FileChange.run_id.in_(runs),
                                          FileChange.agent_id.in_(ids)),
        select(Command.agent_id).where(Command.run_id.in_(runs), Command.agent_id.in_(ids)),
        select(ToolCall.agent_id).where(ToolCall.run_id.in_(runs), ToolCall.agent_id.in_(ids)),
    )))
    found: dict[str, list[tuple]] = {}
    for at, agent in enumerate(ended):
        if (agent.error and agent.error == agent.run_error and agent.ended_at
                and agent.run_ended_at and agent.ended_at >= agent.run_ended_at):
            continue  # (`AgentRunner._close_agents`: ended with its turn, as its turn did)
        came = outcome(agent.status, agent.error, agent.report, agent.id in called,
                       agent.stopped_by_koloni)
        if came is None:
            continue
        retried = any(
            later.status == "completed" and later.run_id == agent.run_id
            and later.role_name == agent.role_name and later.task == agent.task
            for later in ended[at + 1:])
        found.setdefault(agent.run_id, []).append(
            (agent, came, agent.status == "failed" and not retried))
    return found


# Each copy's counts by its agent, with how many changes its line has in it and the last of
# them: the board is read every few seconds, and a copy is diffed again only once it changed.
_COUNTED: dict[str, tuple[tuple, dict]] = {}
MOST_COUNTED = 200


def _counted(session: Session, agent: Agent) -> dict:
    """What the agent's own working copy changed so far (slice 70): files, lines added and
    removed. It diffs whole files: never on the event loop (`_copies_counted`)."""
    line = _line_on_record(session, agent.id)
    stamp = tuple(session.execute(
        select(func.count(FileChange.id), func.max(literal_column("file_changes.rowid")))
        .where(FileChange.agent_id.in_(line), FileChange.status == "in_copy")).one())
    if (known := _COUNTED.get(agent.id)) and known[0] == stamp:
        return known[1]
    files = in_copy(session, line)
    counts = {"files": len(files), "additions": sum(one["additions"] for one in files),
              "deletions": sum(one["deletions"] for one in files)}
    if len(_COUNTED) >= MOST_COUNTED:
        _COUNTED.clear()
    _COUNTED[agent.id] = (stamp, counts)
    return counts


def _copies_counted(session: Session, project: Project | None) -> dict[str, dict]:
    """`_counted` of every agent at work in its own copy, of the project or of all: for a
    thread of its own."""
    mine = Conversation.project_id == project.id if project else true()
    return {
        agent.id: _counted(session, agent) for agent in session.scalars(
            select(Agent).join(Run, Run.id == Agent.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(mine, Agent.status.not_in(AGENT_TERMINAL)))
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
    return board_of(session, project, request.app.state.runner, changed)


def waiting_in(conversation: dict) -> int:
    """What of a board's conversation waits for the user: the twin of the page's
    `waitCount` (frontend/src/board/waiting.ts), for what is said without the page."""
    # Each change and question of an agent that asks; one for what has no kind here.
    asking = sum(
        max(agent.get("changes_to_approve", 0) + agent.get("questions", 0), 1)
        for agent in conversation["agents"] if agent["status"] == "waiting_approval")
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
        select(Conversation)
        .where(mine)
        .order_by(Conversation.updated_at.desc())
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
        holder: cid for holder, cid in session.execute(
            select(Agent.id, Run.conversation_id)
            .join(Run, Run.id == Agent.run_id)
            .where(Agent.id.in_(
                [agent.waiting_for["agent_id"] for agent, _cid in at_work if agent.waiting_for]
            ))
        )
    }
    # What the agents that ask now put before the user, by kind: a change to approve, a
    # question. (Asked only of them: a record left by a turn that ended asks nothing.)
    asking = [agent.id for agent, _cid in at_work if runner.asking(agent.id)]
    changes, questions = ({
        agent_id: n for agent_id, n in session.execute(
            select(table.agent_id, func.count(table.id))
            .where(table.agent_id.in_(asking), table.status == status)
            .group_by(table.agent_id))
    } for table, status in ((FileChange, "proposed"), (Question, "pending")))
    # The agents a tool runs for now: their quiet is measured against a longer time.
    in_tool = set(session.scalars(
        select(ToolCall.agent_id).where(
            ToolCall.status == "running",
            ToolCall.agent_id.in_([agent.id for agent, _cid in at_work]))
    ))
    # Changes put before the user: the agent that made them may have ended its own work.
    pending: dict[str, int] = dict(session.execute(
        select(Run.conversation_id, func.count(Merge.id))
        .join(Run, Run.id == Merge.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(mine, Merge.status == "pending")
        .group_by(Run.conversation_id)
    ).tuples().all())
    # Each conversation's last turn: the one put on record last. A message taken back
    # before its turn started was never a turn (as `topics.latest_of_user` says).
    last = (
        select(func.max(literal_column("runs.rowid")))
        .select_from(Run)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(mine)
        .where(or_(Run.status != "cancelled", Run.started_at.is_not(None)))
        .group_by(Run.conversation_id)
    )
    runs = session.execute(
        select(Run.conversation_id, Run.id, Run.status, Run.started_at, Run.ended_at,
               Run.input_tokens, Run.output_tokens, Run.plan)
        .where(literal_column("runs.rowid").in_(last))
    ).all()
    ran = [run.id for run in runs]
    # Its agents that started, and their tokens as the chat's turn summary adds them up
    # (`turnTokens`): known only where every one of them said its own.
    started = {
        rid: (n, sent, made) if n_sent == n and n_made == n else (n, None, None)
        for rid, n, sent, made, n_sent, n_made in session.execute(
            select(Agent.run_id, func.count(Agent.id), func.sum(Agent.input_tokens),
                   func.sum(Agent.output_tokens), func.count(Agent.input_tokens),
                   func.count(Agent.output_tokens))
            .where(Agent.run_id.in_(ran), Agent.started_at.is_not(None))
            .group_by(Agent.run_id)
        )
    }
    # The model its Lead ran on: a turn keeps the model's name, only an agent its provider.
    lead = {
        rid: (provider, model) for rid, provider, model in session.execute(
            select(Agent.run_id, Agent.provider_name, Agent.model_id)
            .where(Agent.run_id.in_(ran), Agent.depth == 0)
        )
    }
    came = outcomes(session, ran)
    turns = {}
    for run in runs:
        # No agent started: what the turn itself kept.
        n, sent, made = started.get(run.id, (0, run.input_tokens, run.output_tokens))
        provider, model = lead.get(run.id, (None, None))
        turns[run.conversation_id] = {
            "id": run.id, "status": run.status,
            "started_at": run.started_at, "ended_at": run.ended_at,
            "agents": n, "provider_name": provider, "model_id": model,
            "tokens": None if sent is None or made is None else sent + made,
            "plan_waits": run.status == "completed"
            and (run.plan or {}).get("status") == "proposed",
            "outcomes": [{
                "id": agent.id, "name": agent.name, "role": agent.role_name,
                "provider_name": agent.provider_name, "model_id": agent.model_id,
                "status": agent.status, "outcome": how, "rerun": again,
            } for agent, how, again in came.get(run.id, [])],
        }
    agents: dict[str, list[dict]] = {}
    conflicts: dict[tuple[str, str], dict] = {}
    for agent, cid in at_work:
        agents.setdefault(cid, []).append({
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
        })
        wanted = agent.waiting_for
        if not wanted or home.get(wanted["agent_id"], cid) == cid:
            continue
        # A file held in one conversation and waited for in another: one entry for the
        # file and its holder, with everyone of other conversations who waits for it.
        conflict = conflicts.setdefault((wanted["path"], wanted["agent_id"]), {
            "path": wanted["path"],
            "holder": {
                "conversation_id": home[wanted["agent_id"]],
                "agent_name": wanted["agent_name"],
            },
            "waiting": [],
        })
        conflict["waiting"].append({"conversation_id": cid, "agent_name": agent.name})
    return {
        # (Every chat's: no one limit; at work, in every project.)
        "limit": project.max_agents if project else None,
        "running": runner.at_work(project.root_path) if project else sum(
            runner.at_work(root) for root in session.scalars(select(Project.root_path))),
        "conversations": [
            {
                "conversation_id": talk.id,
                "title": talk.title,
                "agents": agents.get(talk.id, []),
                "merges_pending": pending.get(talk.id, 0),
                "turn": turns.get(talk.id),
                "project_id": talk.project_id,
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
            for task in session.scalars(
                select(BacklogTask).where(theirs))
        ),
    }
