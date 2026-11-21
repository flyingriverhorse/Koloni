"""☾ Away (slice 106): the To-do tasks the user ticks and their Go away - the only start; then,
once the chat they went away from has finished its turn, one task after another, each in a new
chat of its own and its own copy (`backlog.start`), a task that waits for the user's word or
fails twice never holding up the next - until the user is back (I'm back, a message of theirs),
a limit is reached or they say Stop all; and the one summary they come back to. Nothing of it
goes into the project: that is the user's Take in, on the kept copies."""

import asyncio
import contextlib
import fnmatch
import json
import logging
import os
import posixpath
import re
from datetime import UTC, datetime, timedelta, tzinfo

from sqlalchemy import and_, func, or_, select
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
    Flag,
    Merge,
    Message,
    Project,
    Question,
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
# their ceiling, run until done, the money the user set or a provider's limit stops them. No
# spend limit either unless one is set (the user, 6 Nov: a plan counts no dollars) - but the
# month's budget, where one is set, still holds.
# B-413 (the user, 8 Nov: an honest job may take hours): a turn nobody watches - a night's
# job, a To-do task's, a trigger's - ends where nothing real moved for STUCK_FLAG's minutes
# (`AgentRunner._progress`), and, a last resort, a night's job or a To-do task's after
# CEILING_FLAG's hours, its copy kept, as at the night's end. Settings › The app; a ceiling of
# "" is none. (A trigger's own minutes hold its turns.)
STUCK_FLAG, STUCK_RANGE, STUCK_MINUTES = "stuck_minutes", (5, 1440), 30
CEILING_FLAG, CEILING_RANGE, CEILING_HOURS = "turn_hours", (1, 72), 8
MAX_JOBS, MAX_KEPT_OUT = 10, 20
TRIES = 2  # a job that fails is tried once more
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
OFFERED = (
    "A line under your answer offers the user to go away; nothing starts before their Go "
    "away, which works through the tasks they tick on To-do. End your turn now with one short "
    "line.")
RETRY = "KOLONİ: the last try of this job failed ({why}). Try it once more."
AGAIN = ("KOLONİ: the user asks to try this job again. The work while they were away is over: "
         "this turn works as any turn of this chat - not in a copy kept for them; what it changes "
         "goes into the project as this chat's level says, asked where it asks.")
JOB_TOO_LONG = ("Stopped after {hours} hour{s}, the most one job works: what it did is kept in "
                "its copy.")
CLOSED = "Stopped: KOLONİ was closed while you were away."
# What starts no other work while the user is away (Run the backlog, Try again).
AWAY_NOW = "You're away from this project: press I'm back first"
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


def gone_from(session: Session, cid: str) -> AwayRun | None:
    """The Away that runs for chat `cid`: the user went away from it, or it is a job's of it."""
    return session.scalar(select(AwayRun).where(
        AwayRun.conversation_id == cid, AwayRun.status == "running").limit(1)) or night_of(
        session, cid)


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


def _picked(session: Session, project_id: str, given: object) -> list[BacklogTask]:
    """The To-do tasks the user ticked, in the panel's order: open (proposed, or to do and not
    started), of this project, each once."""
    if not isinstance(given, list) or len(given) > MAX_JOBS:
        raise Refused(f"task_ids is a list of at most {MAX_JOBS} To-do tasks")
    if len(set(given)) != len(given):
        raise Refused("a task is ticked twice")
    tasks = [session.get(BacklogTask, one) if isinstance(one, str) else None for one in given]
    if any(task is None or task.project_id != project_id or task.status not in (
            "proposed", "todo") for task in tasks):
        raise Refused("a task ticked is not an open task of this project's To-do list (gone, "
                      "started or done)")
    return [task for task in tasks if task is not None]


def _keep_order(tasks: list[BacklogTask], order: object) -> list[BacklogTask]:
    """The panel's order (task ids), saved to To-do: each ticked task takes the (priority,
    place) of the task that was at that place among them. The tasks in that order."""
    if not isinstance(order, list) or len(order) > 200:
        return tasks
    ranked = sorted(tasks, key=lambda task: (backlog.PRIORITIES.index(task.priority),
                                             task.position))
    places = [(task.priority, task.position) for task in ranked]
    wanted = sorted(tasks, key=lambda task: order.index(task.id) if task.id in order
                    else len(order))
    for task, (priority, position) in zip(wanted, places, strict=True):
        task.priority, task.position = priority, position
    return wanted


def go(session: Session, conversation: Conversation, given: dict, runner) -> AwayRun:
    """The user's Go away from chat `conversation` - the only start: the tasks ticked (`given`
    task_ids, in its order; a proposed one is approved and held for Away), the places kept out
    and the limits. The chat's turn finishes first (`go_on`); the cards waiting are decided now
    (`AgentRunner.away_now`)."""
    project_id = conversation.project_id
    if project_id is None:
        raise Refused("a chat with no folder has nothing to work on while you're away")
    if running(session, project_id):
        raise Refused("you're away from this project already")
    if backlog.held(session):
        raise Refused("everything is held (Stop everything): Resume first")
    if why := backlog.busy(session, project_id, waiting=True):
        raise Refused(f"{why}: go away once nothing of the To-do list is at work")
    run_id = session.scalar(select(Run.id).where(Run.conversation_id == conversation.id)
                            .order_by(Run.created_at.desc()).limit(1))
    if run_id is None:
        raise Refused("write to the Orchestrator first: Away finishes this chat's turn")
    project = session.get_one(Project, project_id)
    tasks = _picked(session, project_id, given.get("task_ids") or [])
    kept, (until, money) = _kept_out(given.get("kept_out"), project.root_path), _limits(given)
    tasks = _keep_order(tasks, given.get("order"))
    for planned in session.scalars(select(AwayRun).where(
            AwayRun.project_id == project_id, AwayRun.status == "planned")):
        planned.status = "dismissed"  # (the offer: Go away is the user's answer to it)
    alive = [Conversation.id == conversation.id, Run.ended_at.is_(None)]
    night = AwayRun(project_id=project_id, conversation_id=conversation.id, run_id=run_id,
                    status="running", kept_out=kept, until=until, started_at=now(),
                    money=most_money(session, project, money),
                    spent_before=spend(session, alive)["spent"])
    session.add(night)
    session.flush()
    jobs = []
    for task in tasks:
        was_todo = task.status == "todo"
        task.status = "todo"  # (a proposed one ticked: the user's OK - held by Away)
        task.away_state = task.away_why = task.conversation_id = None
        task.away_run_id = night.id
        jobs.append({"title": task.title, "line": task.criteria, "team": None, "recipe": None,
                     "task_id": task.id, "was_todo": was_todo})
    night.jobs = jobs
    session.commit()
    runner.away_now(conversation.id)
    go_on(session, project_id, runner)
    return night


def back(session: Session, project_id: str) -> Message | None:
    """I'm back, or a message of the user's: the project's Away ends - the job at work finishes,
    its cards then wait for the user - with its summary in the chat, no notification. The
    summary, or None where the project was not away. Committed."""
    night = running(session, project_id)
    if night is None:
        return None
    message, _note = _close(session, night, None, notify=False)
    session.commit()
    return message


def offer(session: Session, conversation: Conversation, run_id: str, args: dict) -> str:
    """offer_away: the Orchestrator's one line offering the user to go away - with the places
    kept out and the limits it heard them name - in place of one this chat still shows. Nothing
    starts: Go away is the user's."""
    if conversation.project_id is None:
        raise Refused("a chat with no folder has nothing to work on while the user is away")
    if running(session, conversation.project_id):
        raise Refused("the user is away from this project already")
    project = session.get_one(Project, conversation.project_id)
    kept = _kept_out(args.get("kept_out"), project.root_path)
    until, money = _limits(args)
    for old in session.scalars(select(AwayRun).where(
            AwayRun.conversation_id == conversation.id, AwayRun.status == "planned")):
        old.status = "dismissed"
    session.add(AwayRun(project_id=project.id, conversation_id=conversation.id, run_id=run_id,
                        jobs=[], kept_out=kept, until=until, money=money))
    return OFFERED


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
    """What it spent since Go away, at the user's prices (`spend`): its jobs' chats, and the
    chat it was gone from - its turns at work then or started since, less what those had spent
    before (`spent_before`)."""
    began = (away.started_at or now()).replace(tzinfo=None)
    chats = [task.conversation_id for task in tasks_of(session, away) if task.conversation_id]
    found = spend(session, [or_(
        and_(Conversation.id.in_(chats), Run.created_at >= began),
        and_(Conversation.id == away.conversation_id,
             or_(Run.ended_at.is_(None), Run.ended_at >= began)))])
    if found["spent"] is not None and away.spent_before:
        found["spent"] = round(max(0.0, found["spent"] - away.spent_before), 6)
    return found


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


def unattended(session: Session) -> tuple[int, int | None]:
    """B-413: the minutes with nothing moving that end a turn nobody watches, and the hours a
    night's job or a To-do task's turn works at most (None: no ceiling) - as Settings › The app
    has them; a row out of its range is held to it, one that is no whole number is the default."""
    def read(name: str, low_high: tuple[int, int], default: int | None) -> int | None:
        row = session.get(Flag, name)
        if row is None:
            return default
        if row.value == "":
            return None
        try:
            return min(low_high[1], max(low_high[0], int(row.value)))
        except ValueError:
            return default
    return (read(STUCK_FLAG, STUCK_RANGE, STUCK_MINUTES) or STUCK_MINUTES,
            read(CEILING_FLAG, CEILING_RANGE, CEILING_HOURS))


def too_long(hours: int) -> str:
    return JOB_TOO_LONG.format(hours=hours, s="" if hours == 1 else "s")


def job_over(session: Session, cid: str, at: datetime | None = None) -> str | None:
    """Why a job's turn at work is cut: it has worked its ceiling's hours (`unattended`)."""
    hours = unattended(session)[1]
    began = session.scalar(select(Run.started_at).where(
        Run.conversation_id == cid, Run.status.not_in(backlog.ENDED)).limit(1))
    return too_long(hours) if hours and began and (at or now()) - began >= timedelta(
        hours=hours) else None


def _cut_over(session: Session, working: list[BacklogTask], runner, at: datetime | None) -> None:
    """The turns of the jobs at work that have worked their ceiling's hours are cut (`job_over`)."""
    for task in working:  # (a long command takes no step: the clock looks too)
        if task.conversation_id and (why := job_over(session, task.conversation_id, at)):
            for run_id in session.scalars(select(Run.id).where(
                    Run.conversation_id == task.conversation_id,
                    Run.status.not_in(backlog.ENDED))):
                runner.cut(run_id, why)


def go_on(session: Session, project_id: str, runner, at: datetime | None = None) -> bool:
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
        _cut_over(session, working, runner, at)
        if working or _chat_at_work(session, away):
            return False
        task = next((t for t in tasks if t.away_state is None and t.status == "todo"), None)
        if task is None:
            _looked_at(session, away)
            return False
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


def _chat_at_work(session: Session, away: AwayRun) -> bool:
    """The chat the user went away from still at its turn: To-do waits for it - not for one
    that waits for the user's word."""
    return session.scalar(select(Run.id).where(
        Run.conversation_id == away.conversation_id,
        Run.status.in_(("running", "queued"))).limit(1)) is not None


def _looked_at(session: Session, away: AwayRun) -> None:
    """Every task was looked at: Away goes on until the user is back - the project's address
    is told so, once."""
    if away.id in _told_looked_at or not away.jobs:  # (none ticked: nothing to tell)
        return
    _told_looked_at.add(away.id)
    project = session.get_one(Project, away.project_id)
    if project.notify_url or project.notify_desktop:
        send((project.name, project.notify_url, project.notify_format, project.notify_desktop,
              f"Every To-do task was looked at. {line(session, away)}."))


# The Aways whose "looked at" was told (`_looked_at`): this process's, as its loop's tasks.
_told_looked_at: set[str] = set()


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
        elif evening.teams_mode == "manual":  # (the teams the user picked there)
            chat.teams_mode = "manual"
            chat.teams = [ConversationTeam(team_id=one.team_id, recipe_id=one.recipe_id,
                                           picked_by=one.picked_by, position=one.position)
                          for one in evening.teams]

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
        said.content = line(session, away)
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


def stop(session: Session, away: AwayRun, why: str, runner, ends: bool = True,
         waiting: bool = False) -> None:
    """Stop all (`waiting`), or a limit reached: the night ends, and a job at work is cut - its
    copy kept (`AgentRunner.cut`) and stopped, not failed (B-148). One that waits for the user's
    word waits on at a limit; Stop all stops it too. Not `ends`: Stop everything
    (`app.api.hold`) - the night stays, and its next job waits for Resume (`go_on`); a job that
    waits for the user's word is stopped too, as every turn is then."""
    # (The chat gone from at its turn too: Stop all stops everything of Away.)
    cut = list(session.scalars(select(Run.id).where(
        Run.conversation_id == away.conversation_id, Run.status.not_in(backlog.ENDED))))
    for task in tasks_of(session, away):
        if at_work(session, task) or (waiting or not ends) and task.away_state == "waits":
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


def decided(session: Session, away: AwayRun) -> list[str]:
    """What the Orchestrator decided for the user while they were away, in its chats - the
    cards it answered, and the commands their own words let run (K-yargıç) - oldest first."""
    chats = [away.conversation_id, *(task.conversation_id for task in tasks_of(session, away)
                                     if task.conversation_id)]
    began = (away.started_at or now()).replace(tzinfo=None)
    window = [Run.conversation_id.in_(chats), *(
        [] if away.ended_at is None else [Run.created_at <= away.ended_at.replace(tzinfo=None)])]
    answered = session.execute(select(Question.question, Question.answer, Question.created_at)
                               .join(Run, Run.id == Question.run_id).where(
        *window, Question.lead_why.is_not(None), Question.created_at >= began)).all()
    ran = session.execute(select(Command.command, Command.judged, Command.created_at)
                          .join(Run, Run.id == Command.run_id).where(
        *window, Command.judged.is_not(None), Command.created_at >= began)).all()
    said = [(at, f"{quoted(asked[:120])}: {answer}") for asked, answer, at in answered] + [
        (at, f"ran {quoted(command[:120])} (your words)") for command, judged, at in ran
        if (judged or {}).get("verdict") == "run"]
    return [text for _at, text in sorted(said, key=lambda one: one[0])]


def line(session: Session, away: AwayRun) -> str:
    """The one summary in the chat the user went away from: "While you were away (23:10 -
    07:42): 2 of 2 To-do done · 3 decided for you · 1 waits · 0.84 USD"."""
    found, ended = counts(session, away), away.ended_at or now()
    began = away.started_at or ended
    said = [f"{found['done']} of {len(away.jobs)} To-do done"] + [
        f"{n} {words}" for n, words in (
            (len(decided(session, away)), "decided for you"), (found["waits"], "waits"),
            (found["failed"], "could not be done"), (found["stopped"], "stopped"),
            (found["not_started"], "not started")) if n]
    cost = spent(session, away)
    if cost["spent"]:
        said.append(f"{money(cost['spent'])} {cost['currency'] or 'USD'}")
    return (f"While you were away ({began.astimezone():%H:%M} – {ended.astimezone():%H:%M}): "
            + " · ".join(said))


def _close(session: Session, away: AwayRun, why: str | None,
           notify: bool = True) -> tuple[Message, tuple | None]:
    """Away on record as over, with why, and its one summary at the bottom of the chat it was
    gone from; and the notification for it, where the project has an address (not for the
    user's own coming back: `notify` False). Not committed."""
    away.status, away.ended_at, away.why = "ended", now(), why
    # (A task of the To-do list's it never started is the list's again: the night held it.)
    made = {job["task_id"] for job in away.jobs if not job.get("was_todo")}  # (by the night)
    for task in tasks_of(session, away):
        if task.id not in made and task.conversation_id is None:
            task.away_run_id = None
    said = line(session, away)
    last = session.scalar(select(Run.id).where(Run.conversation_id == away.conversation_id)
                          .order_by(Run.created_at.desc()).limit(1)) or away.run_id
    message = Message(conversation_id=away.conversation_id, run_id=last, role="away",
                      content=said)
    session.add(message)
    project = session.get_one(Project, away.project_id)
    note = (project.name, project.notify_url, project.notify_format, project.notify_desktop,
            f"{why or 'You are back.'} {said}.")
    return message, note if notify and (project.notify_url or project.notify_desktop) else None


def end(session: Session, away: AwayRun, why: str | None, runner) -> None:
    """Away is over (why: a limit, Stop all, a failure to start): on record with why, its one
    summary in the chat it was gone from, and one notification where the project has an
    address."""
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
        "counts": counts(session, away), "proposed": proposed,
        "decided": decided(session, away), "job_minutes": (
            None if (hours := unattended(session)[1]) is None else hours * 60),
        "on_plan": on_plan(session, away),
    }


def on_plan(session: Session, away: AwayRun) -> str | None:
    """The provider the jobs' Lead runs on where it is a plan, whose use counts no money: the
    money limit holds nothing back there (`app.api.usage._coster`). None otherwise."""
    evening = session.get(Conversation, away.conversation_id)
    provider = would_run(session, find_role(session, LEAD), evening).provider
    return provider.name if provider is not None and provider.plan else None

