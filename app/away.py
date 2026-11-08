"""While the user is away (slice 106): the jobs the Lead puts on its "While you're away" card,
which only the user's Start starts; then the night - one job after another, each in a new chat
of its own and its own copy (`backlog.start`), a job that waits for the user's word or fails
twice never holding up the next - until every job is looked at, a limit is reached or the
user says Stop all; and what the morning is told. Nothing of it goes into the project: that
is the user's Take in, on the kept copies."""

import asyncio
import contextlib
import fnmatch
import json
import logging
import os
import posixpath
import re
from datetime import UTC, datetime, timedelta, tzinfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import backlog, web
from app.api.usage import money, month_spend, over_budget, spend
from app.commands import _words
from app.db.models import (
    Agent,
    AwayRun,
    BacklogTask,
    Command,
    Conversation,
    ConversationTeam,
    FileChange,
    Merge,
    Message,
    Project,
    Recipe,
    Run,
    Team,
    ToolCall,
    WebRequest,
    now,
)
from app.handoff import ENDED
from app.roles import LEAD, find_role
from app.serialize import message_out
from app.team import quoted, would_run

log = logging.getLogger(__name__)
# No stop time unless the Lead or the user sets one (the user, 6 Nov): the jobs, each held to
# JOB_MINUTES, run until done, the money the user set or a provider's limit stops them. No
# spend limit either unless one is set (the user, 6 Nov: a plan counts no dollars) - but the
# month's budget, where one is set, still holds.
# The longest one job's turn works before it is cut, as at the night's end, its copy kept.
JOB_MINUTES = 60
MAX_JOBS, MAX_KEPT_OUT = 10, 20
TRIES = 2  # a job that fails is tried once more
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
CARD = (
    "Your card of {jobs} is shown to the user under your answer. Nothing starts before the "
    "user's Start on it: they may change the list, the places kept out and the limits first. "
    "End your turn now with one short line.")
RETRY = "KOLONİ: the last try of this job failed ({why}). Try it once more."
AGAIN = ("KOLONİ: the user asks to try this job again. The work while they were away is over: "
         "this turn works as any turn of this chat - not in a copy kept for them; what it changes "
         "goes into the project as this chat's level says, asked where it asks.")
JOB_TOO_LONG = (f"Stopped after {JOB_MINUTES} minutes, the most one job works: what it did is "
                "kept in its copy.")
CLOSED = "Stopped: KOLONİ was closed while you were away."
KEPT_OUT = ("{path} is kept out: the user asked that nothing touches it while they are away. "
            "Leave it as it is and say so in your report")
def needs_project(said: str) -> str | None:
    """What a job's Lead says the job needs of the project itself (B-122); None: nothing."""
    return backlog.marked(said, backlog.NEEDS_PROJECT)


class Refused(ValueError):
    """What is wrong with the Lead's card, said back to it - or with a request of the page."""


def running(session: Session, project_id: str) -> AwayRun | None:
    return session.scalar(select(AwayRun).where(
        AwayRun.project_id == project_id, AwayRun.status == "running").limit(1))


def until_at(clock: str, at: datetime | None = None, zone: tzinfo | None = None) -> datetime:
    """The next time the local clock (`zone`'s; this machine's without it) says `clock`
    ("HH:MM"), in UTC - worked out on the clock's own time, so that a run over a change of
    summer time ends at the time set all the same."""
    hour, minute = map(int, clock.split(":"))
    local = (at or now()).astimezone(zone).replace(tzinfo=None)
    when = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    when = when if when > local else when + timedelta(days=1)
    return (when.replace(tzinfo=zone) if zone else when.astimezone()).astimezone(UTC)


def most_money(session: Session, project: Project, asked: float | None = None) -> float | None:
    """`asked`, or what the month's budget has left if that is less; None: no limit."""
    if project.monthly_budget is not None:
        spent = month_spend(session, project)["spent"]
        if spent is not None:
            left = max(0.0, round(project.monthly_budget - spent, 2))
            return left if asked is None else min(asked, left)
    return asked


def clean(path: str, root: str | tuple[str, ...] | None = None) -> str:
    """A place kept out, or a path compared with one: relative to the project (`root`, or
    one of several - the project and a job's copy: one of their full paths is made so), with
    forward slashes, `..` and `.` worked out - and, on Windows, a name's dots and spaces at
    its end dropped, as Windows drops them (`secret.` is `secret`); "" for none."""
    path = path.strip().strip("'\"").replace("\\", "/")
    for one in (root,) if isinstance(root, str) else root or ():
        base = one.replace("\\", "/").rstrip("/") + "/"
        if path.casefold().startswith(base.casefold()):
            path = path[len(base):]
            break
    path = posixpath.normpath(path).strip("/") if path else ""
    if os.name == "nt":
        path = "/".join(part.rstrip(". ") or part for part in path.split("/"))
    return "" if path == "." else path


def outside(path: str) -> bool:
    """Whether a place the user names is no place in the project: a full path not in it
    (`/etc`, `C:\\other`), one of the home folder (`~/.ssh`), or one that leads up and out."""
    path = path.strip().strip("'\"")
    return (path.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", path) is not None
            or posixpath.normpath(path.replace("\\", "/")).startswith(".."))


def _jobs(session: Session, project_id: str, given: object) -> list[dict]:
    if not isinstance(given, list) or not 1 <= len(given) <= MAX_JOBS:
        raise Refused(f"jobs is a list of 1 to {MAX_JOBS} jobs, each {{title, line, team, recipe}}")
    teams = {team.name.casefold(): team.name for team in session.scalars(select(Team))}
    recipes = {one.name.casefold(): one.name for one in session.scalars(select(Recipe))}
    jobs = []
    for one in given:
        if not isinstance(one, dict):
            raise Refused("each job is {title, line, team, recipe}")
        title = one.get("title")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            raise Refused("each job has a title of 1 to 200 characters")
        line = one.get("line")
        if line is not None and (not isinstance(line, str) or len(line) > 4000):
            raise Refused("a job's line is a string of at most 4000 characters")
        job = {"title": title.strip(), "line": (line or "").strip() or None,
               "team": None, "recipe": None}
        for key, known in (("team", teams), ("recipe", recipes)):
            name = one.get(key)
            if name is None or name == "":
                continue
            if not isinstance(name, str) or name.strip().casefold() not in known:
                raise Refused(f"no {key} {name!r}: {', '.join(known.values()) or 'there is none'}")
            job[key] = known[name.strip().casefold()]
        # B-409: a job that is a task of the To-do list already is that task, not a copy of it -
        # in the task's own words, which are what its job is given (`backlog.first_message`).
        if (task_id := one.get("task_id")) is not None:
            task = _todo(session, project_id, task_id, job["title"])
            if any(other.get("task_id") == task_id for other in jobs):
                raise Refused(f"{quoted(task.title)} is on the card twice")
            job |= {"title": task.title, "line": task.criteria, "task_id": task_id}
        jobs.append(job)
    return jobs


def _todo(session: Session, project_id: str, task_id: object, title: str) -> BacklogTask:
    """The To-do list's task a job is: one to do, of this project, that the user has OK'd."""
    task = session.get(BacklogTask, task_id) if isinstance(task_id, str) else None
    if task is None or task.project_id != project_id or task.status != "todo":
        raise Refused(f"the job {quoted(title)} names no task to do on this project's To-do "
                      "list (gone, started or done)")
    if backlog.unseen(task):  # (as the To-do list's own runs: `backlog.chain`)
        raise Refused(f"the job {quoted(title)} is a task that waits for the user's OK")
    return task


def _kept_out(given: object, root: str) -> list[str]:
    if given is None:
        return []
    if not isinstance(given, list) or len(given) > MAX_KEPT_OUT or not all(
            isinstance(one, str) and clean(one, root) and len(one) <= 500 for one in given):
        raise Refused(f"kept_out is a list of at most {MAX_KEPT_OUT} paths of the project")
    for one in given:
        if any(mark in one for mark in "*?["):
            raise Refused(f"{one!r} is a pattern: name the file or folder itself (src/payments, "
                          "not src/payments/*)")
        relative = clean(one, root)
        if outside(relative) or ":" in relative or relative == clean(one) and outside(one):
            raise Refused(f"{one!r} is outside the project: name a file or folder in it")
    return list(dict.fromkeys(clean(one, root) for one in given))


def _limits(given: dict) -> tuple[datetime | None, float | None]:
    until = given.get("until")
    if until is not None and (not isinstance(until, str) or not CLOCK.match(until)):
        raise Refused("until is a time of day, HH:MM")
    money = given.get("money")
    if money is not None and (isinstance(money, bool) or not isinstance(money, int | float)
                              or money < 0):
        raise Refused("money is an amount, 0 or more")
    return (until_at(until) if until else None), money


def plan(session: Session, conversation: Conversation, run_id: str, args: dict) -> str:
    """plan_away: the Lead's card, in place of one this chat still shows. Nothing starts."""
    if conversation.project_id is None:
        raise Refused("a chat with no folder has nothing to work on while the user is away")
    if running(session, conversation.project_id):
        raise Refused("this project's jobs are being worked on while the user is away already")
    project = session.get_one(Project, conversation.project_id)
    jobs = _jobs(session, project.id, args.get("jobs"))
    kept = _kept_out(args.get("kept_out"), project.root_path)
    until, money = _limits(args)
    for old in session.scalars(select(AwayRun).where(
            AwayRun.conversation_id == conversation.id, AwayRun.status == "planned")):
        old.status = "dismissed"
    session.add(AwayRun(project_id=project.id, conversation_id=conversation.id, run_id=run_id,
                        jobs=jobs, kept_out=kept, until=until,
                        money=most_money(session, project, money)))
    return CARD.format(jobs=f"{len(jobs)} job{'' if len(jobs) == 1 else 's'}")


def change(session: Session, away: AwayRun, fields: dict) -> None:
    """The user's changes to a card not started yet: its jobs, places kept out and limits."""
    if away.status != "planned":
        raise Refused("only a card not started yet is changed")
    if "jobs" in fields:
        away.jobs = _jobs(session, away.project_id, fields["jobs"])
    if "kept_out" in fields:
        away.kept_out = _kept_out(fields["kept_out"],
                                  session.get_one(Project, away.project_id).root_path)
    if "until" in fields or "money" in fields:
        until, money = _limits({"until": away.until and f"{away.until.astimezone():%H:%M}",
                                "money": away.money, **fields})
        away.until = until
        away.money = most_money(session, session.get_one(Project, away.project_id), money)


def start(session: Session, away: AwayRun, runner) -> None:
    """The user's Start: the jobs go on the To-do list in their order, the project is away,
    and the first job starts. The time is the next one its clock says from now."""
    if away.status != "planned":
        raise Refused("this card was started or put away already")
    if backlog.held(session):
        raise Refused("everything is held (Stop everything): Resume first")
    if why := backlog.busy(session, away.project_id, waiting=True):
        raise Refused(f"{why}: the jobs start once nothing else of the To-do list is at work")
    if away.until is not None:
        away.until = until_at(f"{away.until.astimezone():%H:%M}")
    # (A budget set or spent since the card was planned holds the jobs as it stands now.)
    away.money = most_money(session, session.get_one(Project, away.project_id), away.money)
    jobs = []
    for job in away.jobs:
        # (A task still to do - it may have been started or done since the card - in its words
        # as they are now; tried anew in a chat of the night's, as the card has it, also one
        # that had a chat or an earlier night: the To-do list's own start makes a new chat too.)
        # shortcut: a task of an earlier night's leaves that night's report; keep it there by
        # the card's ids if that is missed.
        if job.get("task_id"):
            task = _todo(session, away.project_id, job["task_id"], job["title"])
            task.away_state = task.away_why = task.conversation_id = None
            job = {**job, "title": task.title, "line": task.criteria, "was_todo": True}
        else:
            task = backlog.add(session, away.project_id,
                               {"title": job["title"], "criteria": job.get("line")}, "user")
        task.away_run_id = away.id
        session.flush()
        jobs.append({**job, "task_id": task.id})
    away.jobs, away.status, away.started_at = jobs, "running", now()
    # (A card put before in another chat was for the list as it stood then.)
    for other in session.scalars(select(AwayRun).where(
            AwayRun.project_id == away.project_id, AwayRun.status == "planned")):
        other.status = "dismissed"
    session.commit()
    go_on(session, away.project_id, runner)


def tasks_of(session: Session, away: AwayRun) -> list[BacklogTask]:
    """Its jobs' tasks in the card's order - those still on the list: the night's, and a task of
    the To-do list's it never started, given back to the list at its end (`_close`), while that
    is still not started."""
    was_todo = {job["task_id"]: job.get("was_todo") for job in away.jobs if job.get("task_id")}
    found = {task.id: task for task in session.scalars(
        select(BacklogTask).where(BacklogTask.id.in_(was_todo)))
        if task.away_run_id == away.id or (was_todo[task.id] and task.away_run_id is None
                                           and task.conversation_id is None)}
    return [found[job["task_id"]] for job in away.jobs if job.get("task_id") in found]


def at_work(session: Session, task: BacklogTask) -> bool:
    """A job whose turn runs now - not one that waits for the user's word."""
    return task.away_state is None and task.conversation_id is not None and session.scalar(
        select(Run.id).where(Run.conversation_id == task.conversation_id,
                             Run.status.not_in(backlog.ENDED)).limit(1)) is not None


def spent(session: Session, away: AwayRun) -> dict:
    """What its jobs' chats spent since it started, at the user's prices (`spend`)."""
    chats = [task.conversation_id for task in tasks_of(session, away) if task.conversation_id]
    return spend(session, [Conversation.id.in_(chats),
                           Run.created_at >= (away.started_at or now()).replace(tzinfo=None)])


def over(session: Session, away: AwayRun, at: datetime | None = None) -> str | None:
    """Why the night stops now (`at`): its time has come, or its money is spent."""
    if away.until is not None and (at or now()) >= away.until:
        return f"Stopped at {away.until.astimezone():%H:%M}, the time you set."
    if away.money is not None:
        found = spent(session, away)
        if found["spent"] is not None and found["spent"] >= away.money:
            return (f"Stopped at {money(found['spent'])} of {money(away.money)} "
                    f"{found['currency']}, the spend limit.")
    return None


def job_over(session: Session, cid: str, at: datetime | None = None) -> str | None:
    """Why a job's turn at work is cut: it has worked JOB_MINUTES."""
    began = session.scalar(select(Run.started_at).where(
        Run.conversation_id == cid, Run.status.not_in(backlog.ENDED)).limit(1))
    return JOB_TOO_LONG if began and (at or now()) - began >= timedelta(
        minutes=JOB_MINUTES) else None


def go_on(session: Session, project_id: str, runner, at: datetime | None = None) -> bool:  # noqa: C901
    """Where the project is away and no job of it is at work: the next job starts - a new
    one, or one that failed once, again in its chat - or the night ends: every job looked
    at, a limit reached, the month's budget or a provider's limit spent. Whether anything
    changed. Never raises: where starting fails, the night stops with why."""
    try:
        away = running(session, project_id)
        if away is None:
            return False
        if why := over(session, away, at):
            stop(session, away, why, runner)
            return True
        if backlog.held(session):  # (Stop everything: its time and money still end it)
            return False
        tasks = tasks_of(session, away)
        working = [task for task in tasks if at_work(session, task)]
        for task in working:  # (a long command takes no step: the clock looks too)
            if task.conversation_id and (why := job_over(session, task.conversation_id, at)):
                for run_id in session.scalars(select(Run.id).where(
                        Run.conversation_id == task.conversation_id,
                        Run.status.not_in(backlog.ENDED))):
                    runner.cut(run_id, why)
        if working:
            return False
        task = next((t for t in tasks if t.away_state is None and t.status == "todo"), None)
        if task is None:
            end(session, away, None, runner)
            return True
        chat = session.get(Conversation, task.conversation_id or away.conversation_id)
        if why := over_budget(session, session.get_one(Project, project_id), chat):
            stop(session, away, f"Stopped: the project is {why}.", runner)
            return True
        if task.conversation_id is None:
            _start(session, away, task, runner)
        else:
            error = session.scalar(select(Run.error).where(
                Run.conversation_id == task.conversation_id).order_by(Run.created_at.desc()))
            task.status = "doing"
            backlog.say(session, session.get_one(Conversation, task.conversation_id),
                        RETRY.format(why=ENDED.get(error, error) or "no reason given"),
                        runner.bus, runner.start)
        return True
    except Exception:
        log.exception("project %s: the next job of the night did not start", project_id)
        with contextlib.suppress(Exception):
            session.rollback()
            if (away := running(session, project_id)) is not None:
                end(session, away, "Stopped: the next job did not start.", runner)
        return True


def _start(session: Session, away: AwayRun, task: BacklogTask, runner) -> None:
    """A job in a new chat: as the chat the card was in - its level, its model (the chat's
    rules hold tonight too; what nobody watching may do unasked is held to,
    `AgentRunner._night_asks`) - with the team and recipe the card gave it. Who changes the
    files and the rest of its sub-agent settings are the project's, as any chat's
    (`settings_of`, `lead_work_of`)."""
    job = next(job for job in away.jobs if job.get("task_id") == task.id)
    evening = session.get_one(Conversation, away.conversation_id)
    team = session.scalar(select(Team).where(Team.name == job["team"])) if job.get("team") else None
    recipe = session.scalar(select(Recipe).where(Recipe.name == job["recipe"])) if job.get(
        "recipe") else None

    def shape(chat: Conversation) -> None:
        chat.permission_mode = evening.permission_mode
        chat.provider_id, chat.model_id = evening.provider_id, evening.model_id
        if team is not None:
            chat.teams_mode = "manual"
            chat.teams = [ConversationTeam(team_id=team.id, recipe_id=recipe and recipe.id,
                                           picked_by="user", position=0)]

    backlog.start(session, task, runner.bus, runner.start, shape, night=True)


def job_of(session: Session, cid: str) -> BacklogTask | None:
    return session.scalar(select(BacklogTask).where(
        BacklogTask.conversation_id == cid, BacklogTask.away_run_id.is_not(None)).limit(1))


def night_of(session: Session, cid: str) -> AwayRun | None:
    """The night a chat's job is of, while it runs."""
    task = job_of(session, cid)
    night = session.get(AwayRun, task.away_run_id) if task and task.away_run_id else None
    return night if night is not None and night.status == "running" else None


def night_job(session: Session, cid: str) -> BacklogTask | None:
    """A chat's job, while its night runs."""
    return job_of(session, cid) if night_of(session, cid) else None


def turn_ended(session: Session, run: Run, status: str) -> bool:
    """A turn of a job's chat ended (`run.status` set): done, to be tried once more where it
    failed while the night goes on, or could not be done, with why. Whether a job moved;
    not committed."""
    if run.compare_id or (task := job_of(session, run.conversation_id)) is None:
        return False
    # (Gone with the chat its card was in: as a night that is over.)
    away = session.get(AwayRun, task.away_run_id) if task.away_run_id else None
    if status == "completed":
        # B-122: one its Lead says needs the project itself (what its copy leaves out) waits.
        needs = needs_project(backlog.last_word(session, run))
        task.away_state, task.away_why = ("waits", f"{backlog.NEEDS_PROJECT} {needs}") if (
            needs) else ("done", None)
    elif status == "failed" and away is not None and away.status == "running" and (
            session.scalar(
            select(func.count()).select_from(Run).where(
                Run.conversation_id == run.conversation_id, Run.status == "failed")) or 0) < TRIES:
        task.away_state = None  # (`go_on` tries it again)
    elif task.away_state != "stopped":  # (cut by the night's stop: `stop`)
        task.away_state = "failed"
        task.away_why = ENDED.get(run.error, run.error) or backlog.HOW.get(
            status, "was stopped").capitalize()
    return True


def after_the_night(session: Session, run: Run) -> Message | None:
    """A job of a night that is over moved on (Allow and go on, say): the night ends when its
    last job did, and the morning's line says it now - live, both stayed as the night left them
    ("0 done, 2 wait"). The line changed, or None. Not committed."""
    task = job_of(session, run.conversation_id)
    away = session.get(AwayRun, task.away_run_id) if task and task.away_run_id else None
    # (Only the night's own turn, gone on after it: a later message in the job's chat is not its.)
    if away is None or away.status != "ended" or away.ended_at is None or (
            run.created_at.replace(tzinfo=None) > away.ended_at.replace(tzinfo=None)):
        return None
    away.ended_at = now()
    # Its own line: written at its end, before a later night of the chat started (one runs at a
    # time) - not the newest, which may be that later night's.
    later = session.scalar(select(AwayRun.started_at).where(
        AwayRun.conversation_id == away.conversation_id, AwayRun.id != away.id,
        AwayRun.started_at > away.started_at).order_by(AwayRun.started_at).limit(1))
    said = session.scalar(select(Message).where(
        Message.conversation_id == away.conversation_id, Message.role == "away",
        Message.created_at >= away.started_at,
        *([Message.created_at < later] if later is not None else [])).order_by(
        Message.created_at.desc()).limit(1))
    if said is not None:
        said.content = line(counts(session, away))
    return said


def waits(session: Session, run_id: str, waiting: bool) -> str | None:
    """A job's turn waits for the user's word - the job waits, and the next one may go on -
    or goes on after it. The project's id where a job moved; committed."""
    run = session.get(Run, run_id)
    task = job_of(session, run.conversation_id) if run is not None else None
    if task is None or (task.away_state == "waits") == waiting:
        return None
    if waiting:
        found = asks(session, run_id)
        task.away_state = "waits"
        task.away_why = found[0]["text"] if found else "An agent asks for your word in its chat."
    elif task.away_state == "waits":
        task.away_state, task.away_why = None, None
    else:
        return None
    session.commit()
    return task.project_id


def asks(session: Session, run_id: str) -> list[dict]:
    """What a turn waits for that a yes or a no answers - a command, a change, a request or
    an agent to open - with its endpoint's kind; else the newest call still open (a question,
    a folder, a secret), answered in its chat."""
    names = {one.id: one.name
             for one in session.scalars(select(Agent).where(Agent.run_id == run_id))}
    found = [
        *({"kind": "commands", "id": one.id, "text": f"{names.get(one.agent_id) or 'An agent'} "
           f"asks to run {quoted(one.command)}"} for one in session.scalars(select(Command).where(
               Command.run_id == run_id, Command.status == "proposed"))),
        *({"kind": "file-changes", "id": one.id, "text": f"{names.get(one.agent_id) or 'An agent'}"
           f" asks to change {one.path}"} for one in session.scalars(select(FileChange).where(
               FileChange.run_id == run_id, FileChange.status == "proposed"))),
        *({"kind": "web-requests", "id": one.id, "text": f"{names.get(one.agent_id) or 'An agent'}"
           f" asks to reach {one.target}"} for one in session.scalars(select(WebRequest).where(
               WebRequest.run_id == run_id, WebRequest.status == "proposed"))),
        *({"kind": "agents", "id": one.id, "text": f"{one.role_name} waits to be opened"}
          for one in session.scalars(select(Agent).where(
              Agent.run_id == run_id, Agent.status == "proposed"))),
    ]
    if found:
        return found
    call = session.scalar(select(ToolCall).where(
        ToolCall.run_id == run_id, ToolCall.status.in_(("pending", "running")),
        ToolCall.name.in_(("ask_user", "ask_folder", "ask_secret", "spawn_agent", "create_role",
                           "add_skill"))).order_by(ToolCall.seq.desc()).limit(1))
    if call is None:
        return []
    return [{"kind": None, "id": call.id,
             "text": f"{names.get(call.agent_id) or 'An agent'} asks you something ({call.name})"}]


def kept_out(away: AwayRun | None, path: str | None = None, command: str | None = None,
             root: str | tuple[str, ...] | None = None, cwd: str | None = None) -> str | None:
    """The place kept out that a path of the project is in (relative, or a full one under
    `root`), or that a word of a command names as a path - as written, and from the folder it
    runs in (`cwd`, relative): `del secret\\pay.py`, `--out=db/x`, `echo x>db\\y`, `rm s*`,
    not `npm run dbg-tool` for "db". None for one that is not."""
    if away is None or not away.kept_out:
        return None
    if path is None:
        words = [piece for word in _words(command or "")
                 for piece in re.split(r"[=,;:<>|&()]+(?![/\\])", word) if piece]
        here = clean(cwd or "", root)
        return next(filter(None, (kept_out(away, one, root=root) for word in words for one in (
            word, *([posixpath.join(here, word.replace("\\", "/"))] if here else [])))), None)
    named = clean(path, root).casefold()
    if re.search(r"[*?\[]", named):  # (a pattern: each of its parts may match a kept place's)
        parts = named.split("/")
        return next((one for one in away.kept_out if all(
            fnmatch.fnmatchcase(kept, part) for kept, part in zip(
                one.casefold().split("/"), parts, strict=False))), None)
    return next((one for one in away.kept_out
                 if named == one.casefold() or named.startswith(one.casefold() + "/")), None)


def tried(session: Session, away: AwayRun, task_id: str | None, what: str) -> None:
    """Something of a job tried a place kept out, and was refused: on record for the morning."""
    away.tried = [*away.tried, {"task_id": task_id, "what": what[:300]}]
    session.commit()


def stop(session: Session, away: AwayRun, why: str, runner, ends: bool = True) -> None:
    """Stop all, or a limit reached: the night ends, and a job at work is cut - its copy kept
    (`AgentRunner.cut`) and stopped, not failed (B-148). One that waits for the user's word
    waits on. Not `ends`: Stop everything (`app.api.hold`) - the night stays, and its next
    job waits for Resume (`go_on`); a job that waits for the user's word is stopped too, as
    every turn is then."""
    cut = []
    for task in tasks_of(session, away):
        if at_work(session, task) or (not ends and task.away_state == "waits"):
            open_runs = list(session.scalars(select(Run.id).where(
                Run.conversation_id == task.conversation_id, Run.status.not_in(backlog.ENDED))))
            if open_runs:  # (one that waits as done - it needs the project - has none)
                task.away_state, task.away_why = "stopped", why
                cut.extend(open_runs)
    if ends:
        end(session, away, why, runner)
    else:
        session.commit()
    for run_id in cut:
        runner.cut(run_id, why)


def counts(session: Session, away: AwayRun) -> dict[str, int]:
    tasks = tasks_of(session, away)
    return {state: sum(1 for task in tasks if task.away_state == state)
            for state in ("done", "waits", "failed", "stopped")} | {
        "not_started": sum(1 for task in tasks if task.conversation_id is None)}


def line(found: dict[str, int]) -> str:
    """The morning's one line in the chat the card was in."""
    said = [f"{found['done']} done"]
    said += [f"{found['waits']} wait{'s' if found['waits'] == 1 else ''}"] if found["waits"] else []
    said += [f"{found['failed']} could not be done"] if found["failed"] else []
    said += [f"{found['stopped']} stopped"] if found["stopped"] else []
    said += [f"{found['not_started']} not started"] if found["not_started"] else []
    return f"While you were away: {', '.join(said)} - on the canvas"


def _close(session: Session, away: AwayRun, why: str | None) -> tuple[Message, tuple | None]:
    """The night on record as over, with why, and its one line at the bottom of the chat the
    card was in; and the notification for it, where the project has an address. Not
    committed."""
    away.status, away.ended_at, away.why = "ended", now(), why
    # (A task of the To-do list's it never started is the list's again: the night held it.)
    made = {job["task_id"] for job in away.jobs if not job.get("was_todo")}  # (by the night)
    for task in tasks_of(session, away):
        if task.id not in made and task.conversation_id is None:
            task.away_run_id = None
    said = line(counts(session, away))
    last = session.scalar(select(Run.id).where(Run.conversation_id == away.conversation_id)
                          .order_by(Run.created_at.desc()).limit(1)) or away.run_id
    message = Message(conversation_id=away.conversation_id, run_id=last, role="away",
                      content=said)
    session.add(message)
    project = session.get_one(Project, away.project_id)
    note = (project.name, project.notify_url, project.notify_format, project.notify_desktop,
            f"{why or 'Every job was looked at.'} {said}.")
    return message, note if project.notify_url or project.notify_desktop else None


def end(session: Session, away: AwayRun, why: str | None, runner) -> None:
    """The night is over: on record with why (None: every job was looked at), its one line
    in the chat the card was in, and one notification where the project has an address."""
    message, note = _close(session, away, why)
    session.commit()
    runner.bus.emit(away.conversation_id, None, "message.created", message_out(message))
    if note:
        send(note)


def send(note: tuple) -> None:
    """The night's one notification, on its way (on the app's loop)."""
    sending = asyncio.get_running_loop().create_task(_notify(*note))
    _sending.add(sending)
    sending.add_done_callback(_sending.discard)


_sending: set[asyncio.Task] = set()


async def _notify(name: str, url: str | None, form: str, on_desktop: bool, text: str) -> None:
    ways = ([("desktop", web.show(f"KOLONİ — {name}", text))] if on_desktop else []) + (
        [("address", web.notify(url, text, form))] if url else [])
    for way, sending in ways:
        try:
            await sending
        except Exception as exc:  # (never the address in the log: it may hold a key)
            log.warning("a notification of %s was not sent to the %s: %s", name, way,
                        exc if isinstance(exc, web.WebError) else type(exc).__name__)


def settle(session: Session, notes: list | None = None) -> None:
    """When the app comes up: a night a previous process left running is over - its jobs at
    work or waiting were cut with it - with its line in the chat as any end; its notification
    goes in `notes`, sent once the app's loop runs. Nothing is started again. Not committed."""
    for away in session.scalars(select(AwayRun).where(AwayRun.status == "running")).all():
        for task in tasks_of(session, away):
            if task.conversation_id is not None and task.away_state in (None, "waits"):
                task.away_state, task.away_why = "failed", CLOSED
        _message, note = _close(session, away, CLOSED)
        if note and notes is not None:
            notes.append(note)


def kept_copies(session: Session, cid: str) -> list[Merge]:
    """A job's work, kept for the user's Take in."""
    return list(session.scalars(select(Merge).join(Run, Run.id == Merge.run_id).where(
        Run.conversation_id == cid, Merge.status == "interrupted", Merge.kept_in.is_not(None))
        .order_by(Merge.created_at)))


def taken_in(session: Session, away: AwayRun, cid: str) -> list[str]:
    """A job's files the user took into the project from its kept copy (B-123): of its turns
    of the night - not of later work in its chat."""
    night = [Run.created_at >= (away.started_at or now()).replace(tzinfo=None)] + (
        [Run.created_at <= away.ended_at.replace(tzinfo=None)] if away.ended_at else [])
    return sorted({str(one["path"]) for merge in session.scalars(
        select(Merge).join(Run, Run.id == Merge.run_id).where(
            Run.conversation_id == cid, Merge.status == "applied", *night))
        for one in merge.files if one["state"] == "applied"})


def doing_now(session: Session, cid: str) -> str | None:
    """What a job's agents do right now, as the canvas says it (slice 84d): the newest tool
    of its chat that runs - "Coder · editing a.py"; None while none does."""
    call = session.scalar(select(ToolCall).join(Run, Run.id == ToolCall.run_id).where(
        Run.conversation_id == cid, ToolCall.status == "running").order_by(
        ToolCall.started_at.desc()).limit(1))
    if call is None:
        return None
    try:
        args = json.loads(call.arguments)
    except ValueError:
        args = {}
    args = args if isinstance(args, dict) else {}
    said = (f"editing {args.get('path')}" if call.name in ("write_file", "edit_file")
            else str(args.get("command")) if call.name == "run_command" else call.name)
    who = session.get(Agent, call.agent_id)
    return f"{who.name or who.role_name} · {said}" if who is not None else said


def checks(session: Session, cid: str) -> list[str]:
    """What a job's reviews last said, role by role, as far as its agents reported (as Ready
    for you says it): "Reviewer: no findings", "Tester: 2 findings left", "Reviewer: 1
    suggestion" (B-192: one that sends no work back)."""
    said = {agent.role_name: agent.findings or [] for agent in session.scalars(
        select(Agent).join(Run, Run.id == Agent.run_id).where(
            Run.conversation_id == cid, Agent.findings.is_not(None)).order_by(Agent.created_at))}

    def counted(n: int, word: str) -> str:
        return f"{n} {word}{'s' if n > 1 else ''}"

    lines = []
    for role, found in said.items():
        left = sum(1 for f in found if f.get("blocking", True))
        parts = ([f"{counted(left, 'finding')} left"] if left else []) + (
            [counted(len(found) - left, "suggestion")] if len(found) > left else [])
        lines.append(f"{role}: {', '.join(parts) or 'no findings'}")
    return lines


def report(session: Session, away: AwayRun) -> dict:
    """The card, and once started its night as the To-do page, the top bar and the morning's
    node show it (`AwayOut`)."""
    tasks = {task.id: task for task in tasks_of(session, away)}
    jobs, by_file, slipped = [], {}, []
    root = session.get_one(Project, away.project_id).root_path
    for job in away.jobs:
        one = {key: job.get(key) for key in ("title", "line", "team", "recipe", "task_id")}
        task = tasks.get(job.get("task_id") or "")
        if task is not None:
            cid = task.conversation_id
            kept = kept_copies(session, cid) if cid else []
            files = sorted({str(f["path"]) for merge in kept for f in merge.files})
            state = task.away_state or ("working" if at_work(session, task) else "next")
            run_id = session.scalar(select(Run.id).where(Run.conversation_id == cid).order_by(
                Run.created_at.desc()).limit(1)) if cid else None
            one |= {"conversation_id": cid, "state": state, "why": task.away_why,
                    "assessment": task.assessment, "kept": [merge.id for merge in kept],
                    "files": files, "taken": taken_in(session, away, cid) if cid else [],
                    # What its copy changed where the user said not to, refused or not (a
                    # command that wrote there without naming it): for them to see first.
                    "kept_out": [path for path in files if kept_out(away, path, root=root)],
                    "asks": asks(session, run_id) if state == "waits" and run_id else [],
                    "now": doing_now(session, cid) if state == "working" and cid else None,
                    "checks": checks(session, cid) if cid else [],
                    "spent": spend(session, [Conversation.id == cid])["spent"] if cid else None}
            slipped += [{"task_id": task.id, "what": f"{task.title}: changed {path} in its copy"}
                        for path in one["kept_out"]]
            if state == "done":
                for path in files:
                    by_file.setdefault(path, []).append(task.title)
        jobs.append(one)
    for one in jobs:
        if one.get("state") == "done":
            one["shared"] = [path for path in one["files"] if len(by_file.get(path, ())) > 1]
    found = spent(session, away)  # (not started: nothing, in the prices' currency)
    proposed = list(session.scalars(select(BacklogTask).where(
        BacklogTask.project_id == away.project_id, BacklogTask.status == "proposed",
        BacklogTask.created_at >= away.started_at.replace(tzinfo=None),
        *([BacklogTask.created_at <= away.ended_at.replace(tzinfo=None)] if away.ended_at
          else []))).all()) if away.started_at else []
    return {
        "id": away.id, "project_id": away.project_id, "conversation_id": away.conversation_id,
        "run_id": away.run_id, "status": away.status, "jobs": jobs, "kept_out": away.kept_out,
        "until": away.until, "money": away.money, "started_at": away.started_at,
        "ended_at": away.ended_at, "why": away.why, "seen_at": away.seen_at,
        "tried": away.tried, "slipped": slipped,
        "spent": found["spent"] if away.started_at else None,
        "currency": found["currency"] or "USD", "at_least": bool(found["at_least"]),
        "counts": counts(session, away), "proposed": proposed, "job_minutes": JOB_MINUTES,
        "on_plan": on_plan(session, away),
    }


def on_plan(session: Session, away: AwayRun) -> str | None:
    """The provider the jobs' Lead runs on where it is a plan, whose use counts no money: the
    money limit holds nothing back there (`app.api.usage._coster`). None otherwise."""
    evening = session.get(Conversation, away.conversation_id)
    provider = would_run(session, find_role(session, LEAD), evening).provider
    return provider.name if provider is not None and provider.plan else None

