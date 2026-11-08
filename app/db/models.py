import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    false,
    select,
    text,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, object_session, relationship

# B-414 (live): a room asked for with 5000 tokens ended with no post - one member's step, with its
# context, came to some 8,500. Its members and the agent that follows it all count (`room_spent`):
# one step each for six members and their follower is some 60,000.
# shortcut: one number whatever the room's size; scale it by its members if a big room is seen
# ending on its tokens before each has posted.
ROOM_MIN_TOKENS = 60_000


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator):
    """SQLite drops tzinfo; every stored time is UTC, so put it back on load."""

    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UtcDateTime}


def in_the_models(name: str | None, type_: str, _parents: dict) -> bool:
    """For Alembic, where it compares a database with these models (`include_name`): the
    full-text index of what was said in earlier turns (`said_in_turns`, migration 0040,
    `app.earlier`) is a virtual table with tables of SQLite's own behind it. No model
    describes them, and no comparison is to take them for something to remove."""
    return type_ != "table" or not (name or "").startswith("said_in_turns")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    root_path: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    # Where run_command executes: on this machine, or in a container with the
    # project folder mounted.
    exec_location: Mapped[str] = mapped_column(String(8), default="host", server_default="host")
    docker_image: Mapped[str | None] = mapped_column(String(200), default=None)
    docker_network: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # The user's standing rules for agents working in this project; only the user writes them.
    rules: Mapped[str | None] = mapped_column(Text, default=None)
    # When the rules last changed; None when they never did, or did before this was kept.
    rules_changed_at: Mapped[datetime | None] = mapped_column(default=None)
    # The user's own SearXNG, asked first by `web_search`; and which is tried first after
    # it, the built-in search ("builtin") or a CLI ("cli").
    search_url: Mapped[str | None] = mapped_column(Text, default=None)
    search_order: Mapped[str] = mapped_column(
        String(8), default="builtin", server_default="builtin"
    )
    # Whether a search may be handed to agy too: it cannot be held to its search tool
    # (`app.model_agy.AgySearch`), so only where the user says so.
    search_agy: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Where `notify` posts. A secret of the user's: no response, event or record shows it.
    notify_url: Mapped[str | None] = mapped_column(Text, default=None)
    # The body it posts there: {"text": …} ("slack"), {"content": …} ("discord"), or
    # the text alone ("text").
    notify_format: Mapped[str] = mapped_column(String(8), default="slack", server_default="slack")
    # Whether `notify` also shows on the user's own desktop.
    notify_desktop: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # The most tokens a turn's agents may report together (sent + written; a question
    # KOLONİ itself asked a model for the turn counts too) before no further model step
    # of it is started. None: no limit.
    turn_token_limit: Mapped[int | None] = mapped_column(Integer, default=None)
    # The most agents at work at the same time in all the project's conversations
    # together; one more is `queued` until there is room. None: no limit.
    max_agents: Mapped[int | None] = mapped_column(Integer, default=None)
    # K-devam-butce: the steps a stopped agent gets on top when it is told to go on with none
    # left - by the user's Continue on its card, or the Lead's call at Full auto.
    continue_steps: Mapped[int] = mapped_column(Integer, default=25, server_default="25")
    # What this calendar month's turns may cost at the user's prices, in their currency
    # (`app.api.usage.month_spend`). None: no budget.
    monthly_budget: Mapped[float | None] = mapped_column(Float, default=None)
    # The month ("2026-10") the user's desktop was told the budget is 80% used: once a month.
    budget_told: Mapped[str | None] = mapped_column(String(7), default=None)
    # The command that checks a sub-agent's work, run in its working copy on what is
    # about to go into the project (`AgentRunner._check`). None: nothing is checked.
    check_command: Mapped[str | None] = mapped_column(String(500), default=None)
    # K-evrim: the command that scores a candidate's work - the last line of its output, a
    # number from 0 to 100 (`evolve.score_of`). None: nothing is measured.
    measure_command: Mapped[str | None] = mapped_column(String(500), default=None)
    # Whether what was taken from a sub-agent is offered to the user for a commit of
    # those files - where the project folder is the top of a git repository.
    git_commit: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # K-dal-takim D2: how a team's finished branch reaches the user's - "merge" (here) or
    # "pull_request" (pushed, a pull request opened; never merged by KOLONİ). None: not chosen
    # yet - the first finished branch of a project with a GitHub remote asks.
    finish_way: Mapped[str | None] = mapped_column(String(20), default=None)
    # Whether a fast model is asked, after each turn that completed, what the turn found:
    # a request KOLONİ makes itself, and at most three notes in the journal
    # (`AgentRunner._note_what_it_found`). Off until the user says so.
    auto_notes: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Whether the Observer role's model is asked, once a sub-agent hands in its report,
    # what of the report its record shows (`AgentRunner._look_over`). Off until the user
    # says so: a request KOLONİ makes and the user pays.
    observe_reports: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Whether the Assistant PO proposes at most three follow-up tasks after a watched turn that
    # did something (`AgentRunner._propose_tasks`), asked of the first model of `suggest_tier`.
    # On by default (the user, 6 Nov).
    suggest_tasks: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    suggest_tier: Mapped[str] = mapped_column(String(10), default="fast", server_default="fast")
    # The titles of the Assistant PO's proposals the user turned down, the latest: not
    # proposed again (`backlog.TURNED_DOWN`).
    po_rejected: Mapped[list | None] = mapped_column(JSON, default=None)
    # How that went after the last such turn: {"run_id", "noted", "skipped", "note"} -
    # `note` is why nothing was noted, in KOLONİ's own words. None: no turn was asked about.
    last_auto: Mapped[dict | None] = mapped_column(JSON, default=None)
    # 22c: the other projects of this KOLONİ whose memory and earlier turns `recall` also
    # looks in, read only (`memory.linked`); ids. Nothing of theirs is given at a start.
    memory_links: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # 22c: the provider whose OpenAI-compatible server embeds the memory for a search by
    # meaning (`app.meaning`), and the model name it is asked for; None: word search alone.
    embedding_provider_id: Mapped[str | None] = mapped_column(String(32), default=None)
    embedding_model: Mapped[str] = mapped_column(
        String(200), default="text-embedding-3-small", server_default="text-embedding-3-small")
    # Folders outside the project a new chat in it starts with, as they really are (slice
    # 41; its chats' own lists since slice 86b).
    also_in: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # Folders outside it a new chat starts with to read in only: a change there is asked
    # about every time, at Full auto too (slice 75).
    read_in: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # The teams a new chat in it starts with (slice 84b): its mode, and its rows as
    # [{"team_id", "recipe_id", "no_recipe"}]; a team or recipe gone since is left out as it
    # is copied.
    # shortcut: kept in the database, not .koloni/settings.json (86c's four keys); move it
    # there when a folder's teams should travel with it in git.
    teams_mode: Mapped[str] = mapped_column(String(8), default="none", server_default="none")
    teams: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # The user's test command for a part of the project, by the part's path in the project map
    # (`app.project_map`): it stands over KOLONİ's guess. Kept here, never in the user's folder.
    test_commands: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    # The local time of day ("HH:MM") the day's summary is sent by the notification path
    # above, and the local day it last went (sent once a day; slice 56). None: never.
    day_note_at: Mapped[str | None] = mapped_column(String(5), default=None)
    day_note_sent: Mapped[date | None] = mapped_column(Date, default=None)
    # Whether the backlog works itself (slice 52): with no task doing, the next todo starts
    # (`app.backlog.chain`). Turned off, with why, when a task's turn fails or is stopped
    # or the month's budget is spent (`backlog_halt`); turning it on clears that.
    backlog_auto: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    backlog_halt: Mapped[str | None] = mapped_column(Text, default=None)
    # B-350: the level and the model the chats its backlog opens start with (`backlog.start`);
    # no provider: the default one, as a new chat's.
    backlog_mode: Mapped[str] = mapped_column(String(12), default="ask", server_default="ask")
    backlog_provider_id: Mapped[str | None] = mapped_column(String(32), default=None)
    backlog_model_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # K-r144: who changes the files in those chats (`Conversation.lead_work`); None: as the
    # project's new chats (`lead_work`).
    backlog_lead_work: Mapped[str | None] = mapped_column(String(9), default=None)
    # Whether its commands see its secret files (.env, keys) as denied or empty: in Copilot's
    # sandbox and in Docker (slices 104, 105). On until the user turns it off.
    hide_secrets: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # The secret variables its commands are given all the same, by name, comma-separated
    # (slice 103: every other one is held back). None: none.
    pass_env: Mapped[str | None] = mapped_column(Text, default=None)
    # 101: whether each turn's commands get a made-up key no agent is told of; sent out, it
    # stops the turn. On until the user turns it off.
    canary: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Its chats' sub-agent settings (tek-ev, the user 6 Nov: Settings › This project), read for
    # every chat of it, old ones too (`settings_of`): named as a chat's own, kept unused.
    # Who changes the files.
    lead_work: Mapped[str] = mapped_column(
        String(9), default="delegates", server_default="delegates")
    # K-cli-vekil: who answers while the user is away, and after how many minutes.
    when_away: Mapped[str] = mapped_column(String(5), default="waits", server_default="waits")
    away_minutes: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    spawn_approval: Mapped[str] = mapped_column(String(8), default="auto", server_default="auto")
    spawn_max_depth: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    spawn_max_agents: Mapped[int] = mapped_column(Integer, default=6, server_default="6")
    spawn_max_parallel: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    # None: no limit (the user, 6 Nov: none by default).
    discussion_budget: Mapped[int | None] = mapped_column(Integer, default=None)
    room_posts: Mapped[int | None] = mapped_column(Integer, default=40, server_default="40")
    room_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    room_minutes: Mapped[int | None] = mapped_column(Integer, default=30, server_default="30")
    # B-414: the least tokens an agent's room is given, whatever it asks (`room_tokens` wins
    # where it is lower); None: none.
    room_min_tokens: Mapped[int | None] = mapped_column(
        Integer, default=ROOM_MIN_TOKENS, server_default=str(ROOM_MIN_TOKENS))
    # 89m: whether a Claude Code agent that changed files finishes only once the tests pass.
    # None: automatic (`app.finish_tests.automatic`).
    finish_tests: Mapped[bool | None] = mapped_column(Boolean, default=None)

    @property
    def has_notify_url(self) -> bool:
        return bool(self.notify_url)

    @property
    def finish_tests_auto(self) -> dict:
        from app.finish_tests import automatic  # (it reads this model's tables)

        return automatic(object_session(self), self)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # The folder its agents work in; None: a plain chat, with no file or command tool
    # (slice 86a). Its root is None then, never "" - that would be the server's own folder.
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    # ask: confirm edits and commands; auto_edit: only commands; full_auto: nothing.
    permission_mode: Mapped[str] = mapped_column(String(12), default="ask", server_default="ask")
    # Sub-agents: when opening one asks first, and how far the tree may grow in a turn.
    # These, `lead_work`, `when_away`, `away_minutes` and `room_*` are read from its project
    # since tek-ev (`settings_of`); a plain chat's are read here.
    spawn_approval: Mapped[str] = mapped_column(String(8), default="auto", server_default="auto")
    spawn_max_depth: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    spawn_max_agents: Mapped[int] = mapped_column(Integer, default=6, server_default="6")
    # How many agents of a turn may be at work at the same time.
    spawn_max_parallel: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    # The most tokens the speakers of one discussion may report - all they sent and all
    # they wrote in it - before it is ended. None: no limit (the user, 6 Nov: by default; a
    # chat that kept 200000 keeps it: 0147).
    discussion_budget: Mapped[int | None] = mapped_column(Integer, default=None)
    # The model this conversation's agents use unless their role says otherwise;
    # None means the first provider and its default model.
    provider_id: Mapped[str | None] = mapped_column(String(32), default=None)
    model_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # The lead's model is chosen each turn by how hard the message is: a fast model is
    # asked first, and the lead runs on the model of the matching tier (`app.team.TIERS`).
    lead_auto: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Each new message of the user's starts a plan turn first (slice 49): the Lead only reads,
    # and what it answers is a plan the user approves, edits or turns down.
    plan_first: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # K-39-betik: a page of this chat shown in the Workspace runs its scripts without asking -
    # the user's "Always run in this chat"; off, each page asks.
    page_scripts: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Who changes the files (slice 48, K-devret): "delegates" - the Lead is not given the tools
    # that write files and hands every change to a sub-agent; "decides" - it makes a small
    # change itself and hands bigger work on; "itself". A new chat starts with its folder's.
    lead_work: Mapped[str] = mapped_column(
        String(9), default="delegates", server_default="delegates")
    # While the user is away (K-vekil-karar): "waits" - every question waits for them - or
    # "lead": the Lead answers what it safely can, once a question has waited `away_minutes`
    # (at once while the folder's night runs).
    when_away: Mapped[str] = mapped_column(String(5), default="waits", server_default="waits")
    away_minutes: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    # The Lead's reasoning level in this conversation ("low" ... "max"); None: its role's.
    lead_effort: Mapped[str | None] = mapped_column(String(8), default=None)
    # What a room opened here may spend unless the user says otherwise as they open it:
    # posts by its members, tokens as their models report them, minutes. None: no limit.
    # (The user, R185: no tokens by default - a room ends on its posts or minutes, or on the
    # turn's and the project's own limits. A chat that kept 400000 keeps it: 0145.)
    room_posts: Mapped[int | None] = mapped_column(Integer, default=40, server_default="40")
    room_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    room_minutes: Mapped[int | None] = mapped_column(Integer, default=30, server_default="30")
    room_min_tokens: Mapped[int | None] = mapped_column(
        Integer, default=ROOM_MIN_TOKENS, server_default=str(ROOM_MIN_TOKENS))
    # Folders outside the project this conversation also works in: its folder's at its
    # start, named in the user's own messages, allowed from a card ("Allow this folder") or
    # added in "This chat's folders" (slice 86b). Its agents use these lists only.
    also_in: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # Folders it may read in only: as above, and allowed on an agent's ask_folder card.
    read_in: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # K-buyuk-proje: the part of its folder's map its agents work in ("core/"); None: all of it.
    part: Mapped[str | None] = mapped_column(String(500), default=None)
    # Who picks the teams whose roles its agents may open (slice 84b): "lead", "manual" (the
    # user) or "none" (any role); the rows picked are `teams`.
    teams_mode: Mapped[str] = mapped_column(String(8), default="none", server_default="none")
    teams: Mapped[list["ConversationTeam"]] = relationship(
        lazy="selectin", order_by="ConversationTeam.position", cascade="all, delete-orphan")
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now)
    # When the user put it away (its list's "Archived" part); None: it is not. Nothing of
    # it goes: a trigger's turn leaves it there, the user's own message brings it back.
    archived_at: Mapped[datetime | None] = mapped_column(default=None)

    # Slice 48's switch, as the API still says it: on is "delegates".
    @property
    def lead_hands_code(self) -> bool:
        return self.lead_work == "delegates"


def project_of(session, conversation: Conversation) -> Project | None:
    """The folder a conversation works in; None for a plain chat."""
    return session.get(Project, conversation.project_id) if conversation.project_id else None


# What of a chat is read from its folder (`settings_of`); and `lead_work` (`lead_work_of`).
SPAWN = ("spawn_approval", "spawn_max_depth", "spawn_max_agents", "spawn_max_parallel")
FOLLOWED = (*SPAWN, "discussion_budget", "when_away", "away_minutes", "room_posts", "room_tokens",
            "room_minutes", "room_min_tokens")


def settings_of(session, conversation: Conversation) -> Project | Conversation:
    """Where a chat's sub-agent settings are read - `spawn_*`, `discussion_budget`,
    `when_away`, `away_minutes`, `room_*` (tek-ev, the user 6 Nov): its project's, for every
    chat of it, old ones too. Who changes the files is `lead_work_of`.
    shortcut: a plain chat reads its own row - the defaults, as nothing in the app changes them
    since the chat's Sub-agents panel went; give plain chats settings of their own if missed."""
    return project_of(session, conversation) or conversation


def lead_work_of(session, conversation: Conversation) -> str:
    """Who changes the files in a chat: its project's (`settings_of`) - in a chat its To-do
    list opened, a night's job too, the To-do page's choice where there is one (K-r144)."""
    project = project_of(session, conversation)
    if project is None:
        return conversation.lead_work
    todo = project.backlog_lead_work and session.scalar(select(BacklogTask.id).where(
        BacklogTask.conversation_id == conversation.id).limit(1))
    return project.backlog_lead_work if todo else project.lead_work


def new_chat(session, project: Project | None) -> Conversation:
    """A new chat, added: it starts with its folder's other folders (slice 86b) and teams
    (84b) - less a team gone since; a recipe gone since is the team's default. From here they
    are its own."""
    conversation = Conversation(project_id=project.id if project else None,
                                also_in=list(project.also_in) if project else [],
                                read_in=list(project.read_in) if project else [])
    if project is not None and project.teams_mode != "none":
        conversation.teams_mode = project.teams_mode
        rows = [row for row in project.teams if session.get(Team, row["team_id"]) is not None]
        conversation.teams = [ConversationTeam(
            team_id=row["team_id"], picked_by="user", position=at,
            recipe_id=row.get("recipe_id") if session.get(Recipe, row.get("recipe_id") or "")
            else None, no_recipe=bool(row.get("no_recipe")),
        ) for at, row in enumerate(rows)]
    session.add(conversation)
    return conversation


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    error: Mapped[str | None] = mapped_column(Text, default=None)
    model_id: Mapped[str | None] = mapped_column(String(200), default=None)
    input_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    output_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    # A turn nobody is watching: started by a trigger, not by a message the user wrote
    # just then. The trigger's id, and its name as it was when the turn started.
    unattended: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    trigger_id: Mapped[str | None] = mapped_column(String(32), default=None)
    trigger_name: Mapped[str | None] = mapped_column(String(80), default=None)
    # The piece of work this turn goes on with (app.topics). None only for a turn that
    # was put on record without one.
    topic_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    # What the user's message asked of the lead's answer to be said aloud:
    # {"language": ..., "style"?: ...}. None: nothing is said aloud (slice 32a).
    spoken: Mapped[dict | None] = mapped_column(JSON, default=None)
    # Its message is the user's own, sent from the app's own page (slice 81b): a role it
    # names is opened though it is off or out of the team. Not a trigger's, a plan's, a
    # task's, nor one an agent posted with a command.
    by_user: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # A plan turn (slice 49): set from the conversation's plan_first as the message came in.
    plan_turn: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # What it planned: {text, status: proposed|approved|rejected, model_id, strongest, why}.
    # None until a plan turn has written one.
    plan: Mapped[dict | None] = mapped_column(JSON, default=None)
    # One side of a comparison (slice 54): the same message, on a model of the user's choosing,
    # in a working copy of its own. None for every other turn.
    compare_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    # B-107: each chat team's row as this turn left it (`ChatTeamOut`), so a later change of
    # the chat's teams, or the row run again, does not redraw the turn. None: no team ran.
    teams: Mapped[list | None] = mapped_column(JSON, default=None)
    # The Assistant PO's request after the turn (`PoMixin`), as it went (`PoOut`), for the
    # canvas; None where it was not asked.
    po: Mapped[dict | None] = mapped_column(JSON, default=None)


class Compare(Base):
    """One message sent to two models side by side (slice 54), each a turn of its own in a
    working copy of its own: nothing of either reaches the project before the user picks one.
    "open" until then; "chosen" (its turn is the conversation's from then on) or "discarded"."""

    __tablename__ = "compares"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="open")
    chosen_run_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # [{"run_id", "provider_id", "model_id"}], in the order the user gave them.
    sides: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Topic(Base):
    """A piece of work in a conversation: the turns that go on with the same thing. A
    trigger's turns are a topic of their own, which no message of the user's joins."""

    __tablename__ = "topics"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    # The first line of the message that started it, until the user names it.
    title: Mapped[str] = mapped_column(String(200))
    # The trigger whose turns these are; None for the user's own. Not a foreign key: the
    # topic stays when its trigger is deleted.
    trigger_id: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    # The agent that wrote it; None for the user's own messages.
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id"), default=None, index=True)
    # "user", "assistant", "agent": a message another agent sent to `agent_id`,
    # "memory": KOLONİ telling `agent_id` that a fact it was given no longer stands, or
    # "trigger": what started an unattended turn - the trigger's message, not the user's
    # words of that moment. Or "away": KOLONİ's one line at the end of a night while the
    # user was away (slice 106), which no agent is given. KOLONİ's lines in the chat:
    # "git", "koloni", "landed" (where a turn's work is, B-205).
    role: Mapped[str] = mapped_column(String(12))
    from_agent_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # For a message from another agent: when its receiver was given it. A note left for
    # an agent at work has none until that agent's next step.
    delivered_at: Mapped[datetime | None] = mapped_column(default=None)
    # Set on what an agent wrote while speaking in a discussion: it is in the shared
    # place, not part of the agent's own conversation.
    discussion_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # Set on a note from the shared notebook as it was handed to `agent_id`: that this
    # row exists is the record that the agent was given the note.
    board_post_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # Set on a post of a room as it was handed to `agent_id`, a member of that room: the
    # content is what the member was told of it.
    room_post_id: Mapped[str | None] = mapped_column(String(32), default=None)
    content: Mapped[str] = mapped_column(Text, default="")
    # The line the lead wrote to be said aloud, off the end of `content` (slice 32a).
    spoken: Mapped[str | None] = mapped_column(Text, default=None)
    # An answer that thought, as its API gave it, to be sent back so (`StepResult.blocks`):
    # never shown, never edited. None for every other message.
    blocks: Mapped[dict | None] = mapped_column(JSON, default=None)
    status: Mapped[str] = mapped_column(String(12), default="complete")
    created_at: Mapped[datetime] = mapped_column(default=now)


class Attachment(Base):
    """A file the user added to a message (slice 85b): kept as
    `runtime/attachments/<conversation>/<id>` (its text beside it, `<id>.txt`), never under
    the name it came with. Gone with its conversation."""

    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    # None until the message it was added to is sent.
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id"), default=None, index=True)
    # A frame the page took of a video (`app.attachments.MAX_FRAMES` of each), and which.
    frame_of: Mapped[str | None] = mapped_column(ForeignKey("attachments.id"), default=None)
    name: Mapped[str] = mapped_column(String(200))
    # By its bytes, never its name (`app.attachments.KINDS`).
    kind: Mapped[str] = mapped_column(String(12))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    # A few words of what it holds: "132 lines", "12 pages, no text on page 3".
    summary: Mapped[str] = mapped_column(Text, default="")
    # The agents it was handed to (spawn_agent, message_agent), by id.
    given_to: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # A picture's or video's: agent id -> what became of it for that agent's model, in words
    # for its card ("shown to sonnet on Claude Code", "not shown to ...: why"; slice 85c).
    shown_to: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    # The user's "Save these to the project too" (slice 23): the Lead saves it into
    # docs/attachments/, without a card (but for a name later turns obey).
    keep_in_project: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(default=now)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    seq: Mapped[int] = mapped_column(Integer)
    # The model's own id for this call; echoed back as tool_call_id on the next step.
    provider_call_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(64))
    # Raw JSON text as the model sent it, so invalid JSON can still be recorded.
    arguments: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    result: Mapped[str | None] = mapped_column(Text, default=None)
    # Who did it: "koloni" ran it for an agent, or "cli" - a CLI agent in native mode
    # did it with a tool of its own and KOLONİ wrote it down afterwards.
    origin: Mapped[str] = mapped_column(String(8), default="koloni", server_default="koloni")
    # Made inside a CLI's own sub-agent: the call that started that sub-agent. Such a
    # sub-agent is not an agent of KOLONİ's, only a tool call with others hanging off it.
    parent_call_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # Asked to go outside the project: the folder "Allow this folder" opens, as it
    # really is. None where it asked nothing, or the folder is not there yet.
    outside_folder: Mapped[str | None] = mapped_column(Text, default=None)
    # Asked about for another reason, in words for the card: a secret file in the project.
    why_asked: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)


class FileChange(Base):
    __tablename__ = "file_changes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    # None: no call of an agent's made it - what a room's copy brought into the project
    # beside its members' own changes (a command's doing, a file both sides changed).
    tool_call_id: Mapped[str | None] = mapped_column(ForeignKey("tool_calls.id"))
    path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(8))
    before_content: Mapped[str | None] = mapped_column(Text, default=None)
    after_content: Mapped[str] = mapped_column(Text)
    before_sha: Mapped[str | None] = mapped_column(String(64), default=None)
    after_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="proposed")
    created_at: Mapped[datetime] = mapped_column(default=now)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    # Who did it: "koloni" ran it for an agent, or "cli" - a CLI agent in native mode
    # did it with a tool of its own and KOLONİ wrote it down afterwards.
    origin: Mapped[str] = mapped_column(String(8), default="koloni", server_default="koloni")
    # A file the user attached, saved into the project as it is (slice 85b): where KOLONİ
    # keeps its bytes. Its shas are of those bytes; `after_content` is its text, or a line
    # that says what it is.
    after_from: Mapped[str | None] = mapped_column(Text, default=None)


class Command(Base):
    __tablename__ = "commands"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    # None: no call of an agent's asked for it - the project's check, run on a room's copy.
    tool_call_id: Mapped[str | None] = mapped_column(ForeignKey("tool_calls.id"))
    command: Mapped[str] = mapped_column(Text)
    # Project-relative, posix separators. Empty for a command a CLI ran with a tool of
    # its own: where its shell stood is not known.
    cwd: Mapped[str | None] = mapped_column(Text, default=None)
    # Fixed when the command is recorded; a later settings change does not move it.
    location: Mapped[str] = mapped_column(String(8))
    image: Mapped[str | None] = mapped_column(String(200), default=None)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    exit_code: Mapped[int | None] = mapped_column(Integer, default=None)
    output: Mapped[str] = mapped_column(Text, default="")
    output_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    # Who did it: "koloni" ran it for an agent, or "cli" - a CLI agent in native mode
    # did it with a tool of its own and KOLONİ wrote it down afterwards.
    origin: Mapped[str] = mapped_column(String(8), default="koloni", server_default="koloni")
    # A server (`npm run dev`): no timeout, the tool answers while it runs on (slice 42b).
    keep_running: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Asked because a web tool was off and it reaches the internet (K-web-komut): no rule
    # covers it then, and its card offers none. Set by KOLONİ, never from a CLI's own words.
    web_off: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # The first address on this machine it printed, KOLONİ's and model servers' ports aside.
    preview_url: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)


class AllowedCommand(Base):
    __tablename__ = "allowed_commands"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "project_id", "prefix", name="uq_allowed_commands_prefix"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    # The folder it was made in: a rule holds for its chat there only (slice 86a). Not a
    # key, as on a memory record.
    project_id: Mapped[str] = mapped_column(String(32))
    prefix: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)


class WebRequest(Base):
    """A web search or an HTTP request the user was asked about before it went out."""

    __tablename__ = "web_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    tool_call_id: Mapped[str] = mapped_column(ForeignKey("tool_calls.id"))
    kind: Mapped[str] = mapped_column(String(8))  # "search" | "http"
    method: Mapped[str | None] = mapped_column(String(8), default=None)
    # The query, or the address.
    target: Mapped[str] = mapped_column(Text)
    host: Mapped[str | None] = mapped_column(String(253), default=None)
    # The names of the headers it would send (never their values), and its body's size.
    headers: Mapped[list] = mapped_column(JSON, default=list)
    body_chars: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[str] = mapped_column(String(12), default="proposed")
    created_at: Mapped[datetime] = mapped_column(default=now)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)


class AllowedWeb(Base):
    """What a conversation's turns do on the web without asking: search ("search", no
    host), or GET from one host ("host"). Kept apart from the allowed commands, so that
    no host can ever be read as a command. K-tarayici-disari: "page" - a site the agent's
    browser opens (a bare host name); kept on the project (`project_id`, no chat: A3), it
    holds in all its chats (`commands.web_rules_here`) - on the chat in a chat of no
    project - and `ask_first` has it asked every time all the same."""

    __tablename__ = "allowed_web"
    __table_args__ = (
        UniqueConstraint("conversation_id", "kind", "host", name="uq_allowed_web"),
        UniqueConstraint("project_id", "kind", "host", name="uq_allowed_web_project"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id"), index=True, default=None)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), index=True, default=None)
    kind: Mapped[str] = mapped_column(String(8))
    host: Mapped[str] = mapped_column(String(253), default="")
    ask_first: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(default=now)


class Agent(Base):
    """One agent at work inside a run: the lead, or a sub-agent it (or a child) opened."""

    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    parent_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), default=None)
    # The spawn_agent call that opened this agent; None for the lead.
    tool_call_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # Where this agent's model steps went, copied when it started; None if not on record.
    provider_name: Mapped[str | None] = mapped_column(String(60), default=None)
    model_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # Where the model's name comes from when the CLI did not say it and KOLONİ did not
    # set it: "settings" is the CLI's own settings file. "auto": Copilot's auto picked it, the
    # agent was asked for auto (and goes on on auto). None otherwise.
    model_from: Mapped[str | None] = mapped_column(String(16), default=None)
    # How its provider ran when the agent was opened, copied then (a CLI's mode: "reads"
    # is a CLI that only reads with its own tools). None for an API, or if not on record.
    provider_mode: Mapped[str | None] = mapped_column(String(8), default=None)
    # The agent that opened it picked this model from the team guide, not its role.
    chosen: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Why it picked that model, or the tier it gave (slice 81b), in the opener's own words:
    # one sentence. None when nothing was picked (or the agent goes on where it ran before).
    chosen_why: Mapped[str | None] = mapped_column(String(300), default=None)
    # The tier the user gave the model it was opened on ("fast" | "balanced" | "strongest");
    # None where that model has none, and for an agent from before this was kept.
    tier: Mapped[str | None] = mapped_column(String(10), default=None)
    # A lead whose model follows the message: the model that was asked how hard it is
    # ({"provider_name", "model_id"}: the model as it was asked for - its `OwnRequest`
    # has the name the model itself reported, where it did). None: nobody was asked.
    asked_how_hard: Mapped[dict | None] = mapped_column(JSON, default=None)
    # Copied from the role when the agent starts; editing the role later changes nothing here.
    role_name: Mapped[str] = mapped_column(String(60))
    # What other agents call it: its role, numbered when the role is opened again in a turn.
    name: Mapped[str] = mapped_column(String(80), default="")
    tools: Mapped[list] = mapped_column(JSON)
    # The MCP servers (their names) it may use, copied from the role in the same way.
    mcp: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    task: Mapped[str | None] = mapped_column(Text, default=None)  # None for the lead
    depth: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="running")
    report: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    # K-devam-butce: the steps it was given on top of its limits, told to go on with none
    # left (the user's Continue, the Lead's call), added up.
    steps_given: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Why its model failed, from what the provider itself said (`app.limits.FAILURES`),
    # and when the limit it ran into resets, where that was said. None for an agent that
    # did not fail there - stopped by KOLONİ's own rules, say - and from before this.
    failure: Mapped[str | None] = mapped_column(String(20), default=None)
    failure_resets_at: Mapped[datetime | None] = mapped_column(default=None)
    # What its last step sent (the size of its context), and all it wrote.
    input_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    output_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    # All it sent: what every step of it reported, added up (a step sends the whole
    # conversation again). None when nothing was reported - and for an agent from before
    # this was kept, whose total is not made up from the size of its last step.
    input_tokens_total: Mapped[int | None] = mapped_column(Integer, default=None)
    # Of all it sent: what its provider said was read again from the cache and written
    # to it, added up over its steps. None where the provider said nothing of it.
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    # What Copilot says it spent in its own units, added up over its runs: AI credits in
    # billionths, and premium requests (its older unit). None where it said nothing.
    nano_aiu: Mapped[int | None] = mapped_column(Integer, default=None)
    premium_requests: Mapped[float | None] = mapped_column(Float, default=None)
    # A model step or a CLI run of it ended (Stop, a limit, a failure) before saying what
    # it spent: the numbers above are then only part of what it used.
    cut_short: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(default=now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    # The number of the last note on the turn's notebook this agent has been handed.
    board_seen: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # The core records of the project's memory this agent was given when it started
    # (their ids). None for an agent from before there was a memory: not on record.
    facts_given: Mapped[list | None] = mapped_column(JSON, default=list)
    # The agent of an earlier turn of the same topic that this one goes on from: it has
    # that agent's name and starts with what that agent did and said. For a lead, the
    # lead of the topic's turn before. None for an agent that starts clean.
    continues_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # While its status is "blocked": the agent it waits for and the file that one holds
    # ({"agent_id", "agent_name", "path"}). None at every other time. Who holds what is
    # kept in memory (`app.claims`); this is only what the waiting agent shows.
    waiting_for: Mapped[dict | None] = mapped_column(JSON, default=None)
    # While its status is "queued" because its provider is full ({"provider", "at_work",
    # "most"}); None at every other time (K-paralel-saglayici).
    queued_on: Mapped[dict | None] = mapped_column(JSON, default=None)
    # Where it changes files, once it has changed one (`app.copies`): {"state": "own"} in
    # a working copy of its own, "parent" in the copy of the agent it works for; in the
    # project because that is too big to copy ("too_big") or could not be copied
    # ("failed"). None: in the project, like the lead.
    copy: Mapped[dict | None] = mapped_column(JSON, default=None)
    # The last of what was counted of its own tool calls (`app.signs`): {"kind", "count",
    # "text"}. Kept once counted; None: nothing was.
    sign: Mapped[dict | None] = mapped_column(JSON, default=None)
    # When it last took a model step or a tool of its started or ended. None: neither yet.
    last_event_at: Mapped[datetime | None] = mapped_column(default=None)
    # It was stopped by a limit, a rule or a count of KOLONİ's own (a step or token limit,
    # a turn's budget, a trigger's permissions, the same failure 5 times unwatched): not
    # a failure, in the track record (`app.record`). False for every agent before this.
    stopped_by_koloni: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false())
    # What the Observer's model said of its report (at most three sentences): an opinion,
    # signed by `observed_by` ({"provider_name", "model_id"}, as on `asked_how_hard`).
    # None with `observation_note` saying why there is none; both None: nobody was asked.
    observation: Mapped[str | None] = mapped_column(Text, default=None)
    observation_note: Mapped[str | None] = mapped_column(Text, default=None)
    observed_by: Mapped[dict | None] = mapped_column(JSON, default=None)
    # The reasoning level its model steps were sent; None: none was (the model's own).
    effort: Mapped[str | None] = mapped_column(String(8), default=None)
    # Its level as its opener picked it, and why (`agent.EFFORT_PICKED`); or why no level went
    # from some step on: its service refused one (`agent.EFFORT_REFUSED`).
    effort_note: Mapped[str | None] = mapped_column(Text, default=None)
    # The last step asked again after a short failure of its provider (`agent.RETRIED`).
    retry_note: Mapped[str | None] = mapped_column(Text, default=None)
    # The window its model steps were measured against: its role's, else its model's as
    # found; None: unknown, and nothing of its history is summarised.
    context_window: Mapped[int | None] = mapped_column(Integer, default=None)
    # How many messages of what it is sent were summarised so far, the latest summary,
    # and why one could not be made (the older tool outputs were left out instead).
    # What is on record is never changed by this.
    summarised: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    summary_note: Mapped[str | None] = mapped_column(Text, default=None)
    # How many of its answers the summary stands for (`agent._Summary.anchor`): the lead
    # of a later turn goes on from it, as the user may have corrected it.
    summary_anchor: Mapped[int | None] = mapped_column(Integer, default=None)
    # What its report's Findings section said (`app.findings`): [{"what", "kind", "role"}].
    # [] where it said none; None where it had no such section (or no report).
    findings: Mapped[list | None] = mapped_column(JSON, default=None)
    # K-devir-0: for a sub-agent, how many reading or searching calls it made before its
    # first write (all of them, where it wrote nothing): KOLONİ's read_file / list_dir /
    # search / recall and a CLI's own reads as KOLONİ recorded them. None: not counted -
    # a lead, or a CLI whose reads are not seen (`app.handoff.rediscovery`).
    rediscovery: Mapped[int | None] = mapped_column(Integer, default=None)
    # K-devir-1: the ended agents of the project whose work its briefing carried ("Earlier
    # on this", `app.handoff.earlier_on`): their ids. None: nothing was carried.
    handed_from: Mapped[list | None] = mapped_column(JSON, default=None)
    # K-skill-uyum: the skills its role had for it when it started - {"given": [names],
    # "left_out": {name: why}} (`app.skills.split`). None: its role had none, or from before.
    skills: Mapped[dict | None] = mapped_column(JSON, default=None)
    # 27 / 93-C3: the CLI session its last native turn left ({"id", "under"}: what it was
    # started under, `ClaudeNativeClient._under`; Claude Code's or Qoder's), for its next turn -
    # or a later turn's lead going on from it - to resume with only what is new. None: none.
    cli_session: Mapped[dict | None] = mapped_column(JSON, default=None)

    @property
    def compacts_itself(self) -> bool:
        """Whether KOLONİ leaves what its CLI is sent uncompacted: a sub-agent (its work is one
        run of its CLI), or a lead whose next turn goes on in its session, which compacts that
        itself. Any other native or session CLI lead starts anew each turn, sent the whole
        history: KOLONİ compacts that (`AgentRunner._idle_after`, Compact now).
        shortcut: one run step by step too, as before - though each step is a CLI started anew,
        its history only trimmed; compact it as an API model's once step mode is worth it."""
        return self.provider_mode == "step" or self.cli_session is not None or bool(
            self.provider_mode and self.depth)

    @property
    def summary_correctable(self) -> bool:
        """Whether a model is still to read what the user writes for its working state: it
        has a summary with its anchor, and is a lead (a later turn's lead goes on from it)
        or still at work. Whether a later agent goes on from it already is not said here."""
        return bool(self.summary) and self.summary_anchor is not None and (
            self.depth == 0
            or self.status not in ("completed", "failed", "cancelled", "rejected", "interrupted"))


class OwnRequest(Base):
    """A request KOLONİ itself made of a model, outside any agent's steps: the question a
    lead whose model follows the message is opened with (`AgentRunner._by_how_hard`), and
    what a fast model is asked after a turn about what the turn found
    (`AgentRunner._note_what_it_found`; made for the turn's lead). On
    record apart from the agent it was made for, under the provider and model that were
    asked: what it spent is counted and priced there (`app.api.usage`), wherever the
    agent then ran. Its conversation is its run's, as an agent's is. One made with no turn
    (the day's words, a recipe's draft, a role's guide: `app.providers.ask_own`) has no run
    and no agent: Usage's "KOLONİ itself" (K-56)."""

    __tablename__ = "own_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), index=True, default=None)
    # Whom it was made for.
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), default=None)
    # The project one with no turn was made for, where it was for one (a recipe's draft is
    # no project's); None for one with a turn: its run's conversation says it.
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), default=None)
    # Where it went, as on an agent: the provider's name, how that ran (a CLI's mode;
    # None for an API), and the model - the one that answered where it said so.
    provider_name: Mapped[str] = mapped_column(String(60))
    provider_mode: Mapped[str | None] = mapped_column(String(8), default=None)
    model_id: Mapped[str] = mapped_column(String(200))
    # What it sent and what was written back, as reported; None where nothing was.
    input_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    output_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    # Of what it sent: read again from the provider's cache, and written to it.
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    # It was sent and ended (Stop, a failure) before saying what it spent.
    cut_short: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(default=now)


class Merge(Base):
    """An agent's working copy on its way into the project: the files it changed, each
    with how it ended. One an agent has while the user is asked ("pending"); afterwards
    "applied", "rejected" (the user turned it down), "discarded" (nothing was taken and
    nobody was asked: a turn nobody watched, or one that was stopped) or "interrupted"
    (it broke off, and the copy is kept on disk: `app.agent.kept_on_record`)."""

    __tablename__ = "merges"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    # [{"path", "kind", "state", "diff", "additions", "deletions", "note"}]
    files: Mapped[list] = mapped_column(JSON)
    # Where the copy is on disk, for one that was kept ("interrupted"); None otherwise.
    kept_in: Mapped[str | None] = mapped_column(String, default=None)
    # How the project's check command went on what was about to be taken: {"command",
    # "state": "not_run" | "running" | "passed" | "failed", "exit_code", "output", and
    # "stale" once the files moved after it ran}. None: the project had no check command.
    check: Mapped[dict | None] = mapped_column("check_state", JSON, default=None)
    # The commit of what was taken: {"state": "offered" | "committed" | "not_offered" (with
    # why as its message), "message", "sha", "holds": `git show --stat` of a made commit}.
    # None: none is offered.
    commit: Mapped[dict | None] = mapped_column("commit_state", JSON, default=None)
    # K-dal-takim: of a line's work on a git branch of its own - {"name", "into", "conflicts",
    # "dirty", "note"} (`AgentRunner._merge_branch`). None: a copy's, taken in file by file.
    branch: Mapped[dict | None] = mapped_column("branch_state", JSON, default=None)
    # The room whose copy this is; None: an agent's own. (No foreign key: they go together.)
    room_id: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)


class ChannelMessage(Base):
    """What one agent handed to another: a task going down, or a report coming back."""

    __tablename__ = "channel_messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    from_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    to_agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    kind: Mapped[str] = mapped_column(String(8))  # task, report, message, reply, note, findings
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Discussion(Base):
    """Several agents talking about one topic in a shared place, opened by one of them."""

    __tablename__ = "discussions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))  # the one that opened it
    tool_call_id: Mapped[str] = mapped_column(String(32))
    topic: Mapped[str] = mapped_column(Text)
    max_rounds: Mapped[int] = mapped_column(Integer)
    round: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="running")
    # agreed | round_limit | ended_by_user | too_few | budget; None while it runs or when
    # cut off
    outcome: Mapped[str | None] = mapped_column(String(16), default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)


class DiscussionMember(Base):
    __tablename__ = "discussion_members"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    discussion_id: Mapped[str] = mapped_column(ForeignKey("discussions.id"))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    position: Mapped[int] = mapped_column(Integer)  # the order they speak in
    status: Mapped[str] = mapped_column(String(8), default="in")  # "in" | "left"
    opened_here: Mapped[bool] = mapped_column(Boolean, default=False)


class DiscussionPost(Base):
    """One thing said in a discussion; `agent_id` is None for what the user said."""

    __tablename__ = "discussion_posts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    discussion_id: Mapped[str] = mapped_column(ForeignKey("discussions.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(32), default=None)
    round: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8), default="said")  # "said" | "left"
    content: Mapped[str] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Room(Base):
    """Two to six agents working on one goal at the same time, in one working copy. The
    user opens it, and it is the whole of its turn until it is over: then the turn's lead,
    who took no part, is given `told` and answers the user. Or an agent opens it, waits
    for it, and is given its record as its call's answer."""

    __tablename__ = "rooms"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    goal: Mapped[str] = mapped_column(Text)
    # The agent that opened it with `open_room`, and is given its record as that call's
    # answer; None: the user opened it.
    agent_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # "sharing": its members share the work out, a step each | "working" | "ended" |
    # "cancelled" (Stop, or its turn failed under it) | "interrupted" (a restart)
    status: Mapped[str] = mapped_column(String(12), default="sharing")
    # 29c: the user paused it while it runs - its members take no step and post nothing, and
    # its clock stands, until Resume.
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # K-oda-izle: of a room the user opened: "on" while they let the turn's Lead follow it, as an
    # opener does; "stopped" once the Lead follows it no further, whatever they say; else "off".
    # (R178: and of one an agent opened, "on" while that opener follows it.)
    lead_follows: Mapped[str] = mapped_column(String(8), default="off", server_default="off")
    # agreed | budget | ended_by_user | ended_by_opener | too_few; None while it runs or when
    # cut off
    outcome: Mapped[str | None] = mapped_column(String(16), default=None)
    # Which of its reasons: for "budget" the limit reached (posts | tokens | minutes); for
    # "too_few" "unanswered" where every member's work was over with a question still open.
    why: Mapped[str | None] = mapped_column(String(12), default=None)
    # What it may spend: posts by its members, tokens as their models report them,
    # minutes. None: no limit.
    max_posts: Mapped[int | None] = mapped_column(Integer, default=None)
    max_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    max_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    # B-390: the tokens held against its budget - all its members' steps sent and wrote while
    # it ran, and its opener's while it followed it (K-oda-lead: the column's name is from
    # then). None: none reported.
    tokens: Mapped[int | None] = mapped_column("opener_tokens", Integer, default=None)
    # Its minutes: the seconds counted so far, and since when they are being counted
    # now (None: its clock stands - it is over, or only kept waiting for places).
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    clock_since: Mapped[datetime | None] = mapped_column(default=None)
    # What the lead was given when it was over: its record, as KOLONİ wrote it then.
    told: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)


class RoomMember(Base):
    __tablename__ = "room_members"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # the order the user named them in
    role: Mapped[str] = mapped_column(String(60))
    # The provider and model the user named for it here; None: its role's own.
    provider_id: Mapped[str | None] = mapped_column(String(32), default=None)
    model_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # The agent it is in the turn; None until that is opened (and for one that never was).
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), default=None)
    # "in" | "waiting" (for a post) | "done" (its work is over) | "left" (it failed)
    status: Mapped[str] = mapped_column(String(8), default="in")
    # The number of the last post of the room it has been given.
    seen: Mapped[int] = mapped_column(Integer, default=0)


class RoomItem(Base):
    """One piece of a room's work: it has one holder, and a file is changed only under an
    item of one's own whose paths cover it."""

    __tablename__ = "room_items"
    __table_args__ = (UniqueConstraint("room_id", "number", name="uq_room_items_number"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3... in the order they were added
    title: Mapped[str] = mapped_column(String(200))
    # Files and folders of the project it covers, as paths inside it; none: no file.
    paths: Mapped[list] = mapped_column(JSON, default=list)
    # Who has it - or had it when it was finished or dropped. None: nobody's.
    holder_agent_id: Mapped[str | None] = mapped_column(String(32), default=None)
    status: Mapped[str] = mapped_column(String(8), default="open")  # open|taken|done|dropped
    # What came of it, in its holder's words; for a dropped one, why.
    result: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class RoomPost(Base):
    """Something said in a room; `agent_id` is None for what the user said."""

    __tablename__ = "room_posts"
    __table_args__ = (UniqueConstraint("room_id", "number", name="uq_room_posts_number"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3... in the order they were said
    agent_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # A member's: result | review | question | answer | blocked. The user's: said.
    # KOLONİ's own, for a member: done (its work is over; its last words) | left (it failed).
    # Its opener's: ended (what came of it, as it ended it).
    type: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    to_agent_id: Mapped[str | None] = mapped_column(String(32), default=None)
    reply_to: Mapped[int | None] = mapped_column(Integer, default=None)  # a post's number
    # A question nobody has replied to yet.
    open: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=now)


class BoardPost(Base):
    """One note on a turn's shared notebook; `agent_id` is None for the user's."""

    __tablename__ = "board_posts"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_board_posts_seq"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    agent_id: Mapped[str | None] = mapped_column(String(32), default=None)
    content: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer)  # 1, 2, 3... in the order they were written
    created_at: Mapped[datetime] = mapped_column(default=now)
    # K-not-oda: the team whose notebook it is on, its name as it was then; None: the whole
    # turn's (no teams, the Lead's, the user's, KOLONİ's).
    team_id: Mapped[str | None] = mapped_column(String(32), default=None)
    team: Mapped[str | None] = mapped_column(String(60), default=None)
    # A team lead's note for every team's agents.
    everyone: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # KOLONİ's own: the continuation note it writes as a turn ends (G7); `agent_id` is None.
    koloni: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class ShownFile(Base):
    """A file of the project an agent put before the user with `show` (`app.views`)."""

    __tablename__ = "shown_files"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    path: Mapped[str] = mapped_column(Text)  # project-relative, posix separators
    note: Mapped[str | None] = mapped_column(Text, default=None)
    # The agent whose working copy it was shown from (`AgentRunner.copy_workspace`): it is
    # served from there while that copy is, and from the project after. None: the project.
    copy_owner: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Memory(Base):
    """Something kept for later turns of a project: a note in the journal (searched, never
    handed out unasked) or a fact in the core (given to every agent that starts work).

    The model says only the text, the subject and the file lines it rests on; every other
    field here is written by KOLONİ. Nothing is deleted: a record is superseded or
    rejected, and who decided that and when stays on it.
    """

    __tablename__ = "memories"
    __table_args__ = (
        # One record in effect on a subject, in each tier.
        Index(
            "uq_memories_active_subject", "project_id", "tier", "about_key", unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    # "note" | "fact" | "preference": a line the summariser suggests for the user's
    # preferences (22b), waiting ("proposed") until the user adds it or says not now.
    tier: Mapped[str] = mapped_column(String(12))
    text: Mapped[str] = mapped_column(Text)
    # The subject, as written, and as it is compared (case and spacing evened out).
    about: Mapped[str | None] = mapped_column(String(80), default=None)
    about_key: Mapped[str | None] = mapped_column(String(80), default=None)
    # Whose words: "user" | "agent" | "auto" - KOLONİ's summariser, a fast model that was
    # given what was said in a turn and looked at nothing itself (`noted_by`).
    origin: Mapped[str] = mapped_column(String(8))
    # For an "auto" note: the model that made it, as it was asked for
    # ({"provider_name", "model_id"}). None for every other record.
    noted_by: Mapped[dict | None] = mapped_column(JSON, default=None)
    agent_id: Mapped[str | None] = mapped_column(String(32), default=None)
    run_id: Mapped[str | None] = mapped_column(String(32), default=None)
    conversation_id: Mapped[str | None] = mapped_column(String(32), default=None)
    observed_at: Mapped[datetime] = mapped_column(default=now)
    # "file": lines of a project file, with their digest as KOLONİ read them then;
    # "user": the user wrote it; None: an agent's note that rests on nothing.
    source_kind: Mapped[str | None] = mapped_column(String(8), default=None)
    source_path: Mapped[str | None] = mapped_column(Text, default=None)
    source_start: Mapped[int | None] = mapped_column(Integer, default=None)
    source_end: Mapped[int | None] = mapped_column(Integer, default=None)
    source_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    # What KOLONİ knows about how the source was looked at; see app.memory.
    checked_how: Mapped[str | None] = mapped_column(String(80), default=None)
    # "active" | "proposed" (waits for the user, in effect nowhere) | "superseded" | "rejected"
    status: Mapped[str] = mapped_column(String(12), default="active")
    # The record this one took the place of - or, while "proposed", asks to.
    supersedes_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # A note its agent put forward for the core; the user has not decided yet.
    wants_core: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # "user" | "agent" | "auto" (a newer note made by itself took an older one's place)
    decided_by: Mapped[str | None] = mapped_column(String(8), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    # What that last decision was: "written" | "feedback" (the user's words at a card asking
    # for changes, K-devir-2) | "approved" | "corrected" | "confirmed" | "restored" |
    # "rejected" | "removed", or "replaced" for a record another one took the place of.
    # None for a decision from before this was kept: it is not guessed.
    decided_how: Mapped[str | None] = mapped_column(String(12), default=None)
    # Written in a turn nobody was watching.
    unattended: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(default=now)


class UserPreferences(Base):
    """The user's own preferences (22b): one text, written by the user, given to every agent
    in every project before the project's rules. One row, id 1; made when first saved."""

    __tablename__ = "user_preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str | None] = mapped_column(Text, default=None)
    changed_at: Mapped[datetime | None] = mapped_column(default=None)


class Question(Base):
    """Something an agent asked the user in the middle of its work - or that KOLONİ asked
    them for it: leave for a tool it cannot show as a change or a command (`leave`)."""

    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"))
    tool_call_id: Mapped[str] = mapped_column(ForeignKey("tool_calls.id"))
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSON)  # choices offered; empty for a free answer
    # KOLONİ's own question, not the agent's: may this tool run? Its options are all there
    # is to say - any answer but the yes among them is a no.
    leave: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # "pending" | "answered" | "cancelled" | "interrupted" | "superseded" (G5.4: answered, but
    # the work it asked about changed since: asked again)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    answer: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    answered_at: Mapped[datetime | None] = mapped_column(default=None)
    # The Lead answered it for the user, who was away, and said why (K-vekil-karar); None: it
    # did not. `seen_at`: when the user looked at that and said OK.
    lead_why: Mapped[str | None] = mapped_column(Text, default=None)
    seen_at: Mapped[datetime | None] = mapped_column(default=None)


class Provider(Base):
    """Somewhere model steps can be sent: an HTTP endpoint or a CLI on this machine."""

    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # see app.providers.KINDS
    base_url: Mapped[str | None] = mapped_column(Text, default=None)
    # Kept in plain text in the local database; never sent back to any client.
    api_key: Mapped[str | None] = mapped_column(Text, default=None)
    default_model: Mapped[str | None] = mapped_column(String(200), default=None)
    executable: Mapped[str | None] = mapped_column(Text, default=None)  # CLI kinds: a path
    # CLI kinds: "session" (one run per agent, tools over MCP) or "step" (one run per
    # model step). None for HTTP kinds.
    mode: Mapped[str | None] = mapped_column(String(8), default=None)
    # What only this kind of provider has; see app.providers.check_options.
    options: Mapped[dict | None] = mapped_column(JSON, default=None)
    # The team guide. Agents may choose this provider for a sub-agent; what it is good
    # for, in the user's words; and the models the user counts as selectable on it,
    # each {"name": ..., "note": ...}.
    for_agents: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    note: Mapped[str | None] = mapped_column(String(300), default=None)
    models: Mapped[list | None] = mapped_column(JSON, default=None)
    # What KOLONİ learned sending a model an attachment (slice 85b): {model: {"image": true,
    # "video": false}} - taken, or refused. Not in `models`: the page saves those rows whole.
    tried_inputs: Mapped[dict | None] = mapped_column(JSON, default=None)
    # Never run with a model outside `models`, nor with none at all.
    only_listed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Switched off: nobody uses it (`app.providers.allowed`); its key and settings stay. A
    # model of it is switched off by its row's "enabled".
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # The most agents at work on it at the same time, in the whole app. None: no limit.
    max_running: Mapped[int | None] = mapped_column(Integer, default=None)
    # Slice 81c. A key that is a plan (credits): its runs count no money.
    plan: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # A subscription's plan share (50-100) from which its picks go one tier lower.
    step_down_at: Mapped[int | None] = mapped_column(Integer, default=None)
    # The most it may spend in a day, a month, in the user's price currency; past it a new
    # turn whose Lead runs on it waits for the user's word. None: no limit.
    day_limit: Mapped[float | None] = mapped_column(Float, default=None)
    month_limit: Mapped[float | None] = mapped_column(Float, default=None)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now)


class Category(Base):
    """A label the Agents page finds roles by (slice 63b): a role's `kind` is its key. It
    changes no team's stages; it goes only while no role is in it."""

    __tablename__ = "categories"
    key: Mapped[str] = mapped_column(String(40), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(40))
    # One of `app.schemas.Colour`: each theme draws it its own way.
    colour: Mapped[str] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer, default=0)


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    # One line shown to a model choosing a sub-agent.
    description: Mapped[str] = mapped_column(Text, default="")
    # Added to the system prompt of an agent with this role.
    instructions: Mapped[str] = mapped_column(Text, default="")
    tools: Mapped[list] = mapped_column(JSON)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    # The model agents in this role use; None means the conversation's.
    provider_id: Mapped[str | None] = mapped_column(String(32), default=None)
    model_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # K-rol-model-sirasi: the models its agents are tried on first, in the user's order
    # ({"provider_id", "model_id"}); one not had now (past its limit, down, not to be picked)
    # is passed over for the next, and after them come the role's own model, then its tier
    # (`app.team.would_run`). None or empty: none.
    models: Mapped[list | None] = mapped_column(JSON, default=None)
    # Where the role has no model of its own: always the first model the user gave this tier
    # ("fast" | "balanced" | "strongest") among what may be picked for the role - the user's
    # rule, the Lead cannot change it; "conversation": the conversation's model, as before
    # slice 81b. None: the Lead picks one for each job, from `tier_min` to `tier_max`
    # (None: fast, strongest), balanced where it says none.
    tier: Mapped[str | None] = mapped_column(String(16), default=None)
    tier_min: Mapped[str | None] = mapped_column(String(10), default=None)
    tier_max: Mapped[str | None] = mapped_column(String(10), default=None)
    # Its category's key (`Category`, slice 63b): "plan", "build", "data", "ml", "ops", "check",
    # "write" (built-in roles) or one of the user's own; a team's lead's is "lead", in no category.
    kind: Mapped[str] = mapped_column(String(40), default="build", server_default="build")
    # Off: no agent opens it unless the user names it in the turn's message (slice 62).
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    teams: Mapped[list["Team"]] = relationship(
        secondary="role_teams", lazy="selectin", order_by="[Team.created_at, Team.id]")
    # The providers (their ids) an agent may pick for a sub-agent of this role, out of
    # the team guide. None: every one in the guide; empty: none - the role runs on its
    # own model.
    pick_from: Mapped[list | None] = mapped_column(JSON, default=None)
    # How far one agent of this role may go: model steps, and tokens as its model reports
    # them (all it sent and all it wrote). None: no limit of the role's.
    max_steps: Mapped[int | None] = mapped_column(Integer, default=None)
    max_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    # Its agents' reasoning level ("low" ... "max"), and the most the Lead may ask for one
    # of them; None: the model's own, and no most.
    effort: Mapped[str | None] = mapped_column(String(8), default=None)
    max_effort: Mapped[str | None] = mapped_column(String(8), default=None)
    # How many tokens its agents' model reads at most, as the user set it; None: as found.
    context_window: Mapped[int | None] = mapped_column(Integer, default=None)
    # The MCP servers (their names) whose tools an agent of this role may use.
    mcp: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # The skills (their names) its agents are given (`app.skills`).
    skills: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # K-bilgi: the knowledge it uses, [{"knowledge_id", "mode"}] - "full": it is an expert in it
    # (its whole guide at each step); "map": where its guide is. Replaced whole, not changed in
    # place (a JSON field changed in place is not seen).
    knows: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    # 89g: also offered to a Claude Code Lead as one of its own sub-agents (`--agents`): cheaper,
    # but no agent of KOLONİ's - it stops only with its Lead. Off unless the user turns it on.
    inside_cli: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now)

    @property
    def knows_shown(self) -> list[dict]:
        """Its `knows`, each with its knowledge's topic and project (None: every project)."""
        session = object_session(self)
        if session is None:
            return []
        rows = {row.id: row for row in session.scalars(select(ProjectKnowledge).where(
            ProjectKnowledge.id.in_([one["knowledge_id"] for one in self.knows or []])))}
        return [{**one, "topic": rows[one["knowledge_id"]].topic,
                 "project_id": rows[one["knowledge_id"]].project_id}
                for one in self.knows or [] if one["knowledge_id"] in rows]


class ProjectKnowledge(Base):
    """K-bilgi: what the agents of a project can look things up in - a topic, its sources and how
    it is learned (`app.knowledge`); roles use it by `Role.knows`. Its guide is in the project's
    `.koloni/knowledge/<topic>/`. No project: in every project - an expert's knowledge from before
    K-bilgi (roles have no project), or one an agent made in a chat with no folder."""

    __tablename__ = "knowledge"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), index=True, default=None)
    # Its folder's name; never changed (a new topic is a new folder: a new knowledge).
    topic: Mapped[str] = mapped_column(String(40))
    sources: Mapped[list] = mapped_column(JSON)
    max_pages: Mapped[int] = mapped_column(Integer)
    max_usd: Mapped[float] = mapped_column(Float)
    # K-bilgi-repo: a repository's code files new to its guide a learning reads at most.
    max_code_files: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    learn_with: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), default=None)
    removed: Mapped[list] = mapped_column(JSON, default=list)
    weekly: Mapped[bool] = mapped_column(Boolean, default=False)
    # Agents using it may search the web while answering, where its guide has no answer.
    search_web: Mapped[bool | None] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=now)


class NotesOffer(Base):
    """K-bilgi 6: what turns found for a project's Project notes (`app.project_notes`), waiting for
    the user's word on a card under the last watched turn that added to it - never holding a turn.
    One waits at a time in a project: a turn nobody watches adds its items to it."""

    __tablename__ = "notes_offers"
    __table_args__ = (
        # One waits in a project at a time.
        Index("uq_notes_offers_waiting", "project_id", unique=True,
              sqlite_where=text("status = 'waiting'")),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    # The chat and turn whose card shows it; None: only turns nobody watched added to it yet, or
    # its chat was deleted (by id alone, no foreign key: the project's offer outlives the chat).
    conversation_id: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    run_id: Mapped[str | None] = mapped_column(String(32), default=None)
    # [{"line", "text", "source"}]: `line` on the card, `text` the note's page.
    items: Mapped[list] = mapped_column(JSON)
    # "waiting" | "added" | "discarded"; the user's word on it, as said.
    status: Mapped[str] = mapped_column(String(10), default="waiting")
    answer: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)


class Team(Base):
    """A group of roles a conversation can work with (slice 62): a role may be in many."""

    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    # Slice 63a. Its lead: a role of kind "lead" (`app.roles.LEAD_KIND`), made and deleted with
    # it, in no list of roles; it is to run the team beside another one (84b), and runs nothing
    # yet. Off: the Lead always runs the team itself.
    lead_role_id: Mapped[str | None] = mapped_column(String(32), default=None)
    lead_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Whether the Lead may pick this team itself, where it decides a chat's teams (84b).
    lead_may_pick: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Slice 84a: the recipe it runs by where a chat picks none (84b); one of KOLONİ's, not a
    # folder's.
    default_recipe_id: Mapped[str | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), default=None)
    stages: Mapped[list["TeamStage"]] = relationship(
        lazy="selectin", order_by="TeamStage.position", cascade="all, delete-orphan")


class Recipe(Base):
    """The steps of a piece of work (slice 84a): who does each, what runs at once, where it
    loops back and how it ends, as `app.recipes` checks them. A ready one is copied, never
    changed. A folder's own are files of its `.koloni/recipes/`, not rows."""

    __tablename__ = "recipes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    ready: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    graph: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now)


class ConversationTeam(Base):
    """A team a chat works with, and its recipe (slice 84b): the user's in Manual, the Lead's
    where it decides. Its agents open only these teams' roles (`app.roles.closed`)."""

    __tablename__ = "conversation_teams"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    # None: the team's default recipe.
    # shortcut: one of KOLONİ's only - a folder's own (.koloni/recipes) are files, not rows; let
    # a row name one when 84b-2 runs recipes and a folder's are wanted in a chat.
    recipe_id: Mapped[str | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), default=None)
    # K-tarifsiz: the user's "No recipe" in this chat - not even the team's default; its lead
    # splits the work itself. Never with a `recipe_id`.
    # shortcut: the user's in Manual only - the Lead's pick_teams cannot say it; add it there
    # if Lead decides should run a team with no recipe though it has a default.
    no_recipe: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    picked_by: Mapped[str] = mapped_column(String(8))
    # The Lead's reason for its pick; None for the user's.
    why: Mapped[str | None] = mapped_column(Text, default=None)
    position: Mapped[int] = mapped_column(Integer)
    # Where its recipe's run is (slice 84b-2, `app.recipe_run`): its turn, its step, rounds
    # back, the step's agents and how it stands. None: not run yet.
    state: Mapped[dict | None] = mapped_column(JSON, default=None)


class TeamStage(Base):
    """One of a team's stages, in its order (slice 63a): a role of the team sits in one."""

    __tablename__ = "team_stages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    # Its roles work side by side ("all at once"); else one after another.
    together: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class RoleTeam(Base):
    __tablename__ = "role_teams"
    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    # Its stage in that team; None only until `app.roles.place_in_stages` gives it one.
    stage_id: Mapped[str | None] = mapped_column(
        ForeignKey("team_stages.id", ondelete="SET NULL"), default=None)


class Skill(Base):
    """A skill in the shape Claude Code reads (a SKILL.md and files beside it), copied
    into KOLONİ's own store (`app.skills`): what its source becomes later is not it."""

    __tablename__ = "skills"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # From its SKILL.md; a role names its skills by this.
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # The folder it was taken from, as it was named.
    source: Mapped[str] = mapped_column(Text)
    # The first line of its licence file; None: it has none.
    license: Mapped[str | None] = mapped_column(Text, default=None)
    # Its SKILL.md, whole: what `use_skill` gives.
    text: Mapped[str] = mapped_column(Text)
    # The stored copy, and its files (paths in it, "/" between folders) and their bytes.
    folder: Mapped[str] = mapped_column(Text)
    files: Mapped[list] = mapped_column(JSON)
    size: Mapped[int] = mapped_column(Integer)
    # Its scripts, and each one's sha256 as it was copied: a script that is no longer
    # that is asked about, whatever leave the skill has.
    scripts: Mapped[list] = mapped_column(JSON)
    hashes: Mapped[dict] = mapped_column(JSON)
    # The user's leave for its scripts to run without asking.
    scripts_run_unasked: Mapped[bool] = mapped_column(Boolean, default=True)
    # K-skill-uyum: off on the Tools page, it is given to no role's agent.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(default=now)


class McpServer(Base):
    """A program on this machine that speaks MCP over stdio, added by the user: its tools
    are offered to the agents of the roles that name it (`app.mcp_client`)."""

    __tablename__ = "mcp_servers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # Part of every name its tools are offered under: short, and never changed.
    name: Mapped[str] = mapped_column(String(16), unique=True)
    # The program and its arguments, as they are started: no shell reads them.
    command: Mapped[list] = mapped_column(JSON)
    # Its own variables. Their values are kept in plain text in the local database, like
    # a provider's key, and are never sent back to any client: only their names are.
    env: Mapped[dict] = mapped_column(JSON, default=dict)
    # Its tools as they were last read, each {"name", "description", "input_schema",
    # "unusable", "mark"}: what agents are offered until the user reads them again.
    tools: Mapped[list] = mapped_column(JSON, default=list)
    # When its tools were last asked for, and why that failed; None when it did not, and
    # before the first time. (After a reading that failed the tools are the ones before.)
    read_at: Mapped[datetime | None] = mapped_column(default=None)
    read_error: Mapped[str | None] = mapped_column(Text, default=None)
    # Its program and scripts that lie in a folder agents write in, {full path: sha256}, as
    # they were when the user said to start it anyway (97): changed, it is asked about again.
    trusted_files: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    # Slice 92: until the user trusts it every call of it is asked about, at every level and
    # whatever its tools' marks. One added before is trusted (migration 0113).
    trusted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=true())
    # Switched off on the Tools page: given to no agent; its marks and trust stay (0145).
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(default=now)

    @property
    def env_names(self) -> list[str]:
        return sorted(self.env or {})


class OwnCommand(Base):
    """A slash command the user saved (slice 53): `/name args` puts its template in the
    message box, `{args}` replaced; with a role, as that role's task."""

    __tablename__ = "own_commands"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # None: offered in every project.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), index=True, default=None)
    name: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str] = mapped_column(Text)
    # By name, as the box's chip names it; a role deleted since leaves the text alone.
    role: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Trigger(Base):
    """Something that starts a turn by itself in one conversation: the clock, a change to
    the project's files, or a request from outside. Such a turn is unattended, and what
    it may do without asking is written here - not taken from the conversation."""

    __tablename__ = "triggers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(8))  # "schedule" | "files" | "webhook"
    config: Mapped[dict] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(Text)
    # {"write": bool, "commands": [ids of rules on its conversation's allow list],
    #  "agents": 0-4}. Which of those rules count is read off that list each time
    # (`app.commands.ticked`): a rule taken off it is gone from here too.
    permissions: Mapped[dict] = mapped_column(JSON)
    # {"steps": a turn's model steps, "minutes": its length, "per_day": turns in a day}
    budget: Mapped[dict] = mapped_column(JSON)
    # Run once when KOLONİ starts if a due time passed while it was off.
    catch_up: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Turns that failed one after another; at three the trigger is switched off, and
    # `off_because` says why. Both are cleared when the user switches it on again.
    failures: Mapped[int] = mapped_column(Integer, default=0)
    off_because: Mapped[str | None] = mapped_column(Text, default=None)
    last_run_at: Mapped[datetime | None] = mapped_column(default=None)
    last_result: Mapped[str | None] = mapped_column(String(16), default=None)
    # A schedule: the moment its times are counted from, and the next one. None until
    # the scheduler has looked at it once.
    anchor_at: Mapped[datetime | None] = mapped_column(default=None)
    next_at: Mapped[datetime | None] = mapped_column(default=None)
    # A webhook: the SHA-256 of its key. The key itself is shown once and kept nowhere.
    key_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    # How its agent ended its last unattended turn, in the agent's words (cut to a size).
    last_words: Mapped[str | None] = mapped_column(Text, default=None)
    # When it ends by itself (K-tetik-bitis): {"until": "YYYY-MM-DD"}, the last local day it
    # runs on, or {"runs": N}; None: it runs until it is switched off. `ran`: the turns it
    # started since its end was set (or it was switched on again).
    ends: Mapped[dict | None] = mapped_column(JSON, default=None)
    ran: Mapped[int] = mapped_column(Integer, default=0)
    # A schedule whose project's repository stands as it did when its last completed turn
    # started is skipped (K-tetik-degismedi): that key (`app.triggers.job_key`), unless
    # `run_unchanged` says to run even so.
    last_key: Mapped[str | None] = mapped_column(String(64), default=None)
    run_unchanged: Mapped[bool] = mapped_column(Boolean, default=False)
    # Its last runs in a row that found nothing (93-B2, `app.triggers.slowed`): from three on,
    # its times are spaced out. Back to 0 when one finds something or the user touches it.
    idle: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(default=now)
    # When it was last made, changed or switched (the newest of its `TriggerChange`s).
    updated_at: Mapped[datetime] = mapped_column(default=now)


class TriggerProposal(Base):
    """A trigger an agent proposed (slice 69, `propose_trigger`): on a card in its chat until
    the user approves it, makes it their own in the form, or rejects it. Only the user's word
    on the app's own page makes the trigger - with the safest leave, whatever was proposed."""

    __tablename__ = "trigger_proposals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(8))  # "schedule" | "files": never a webhook
    config: Mapped[dict] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(Text)
    ends: Mapped[dict] = mapped_column(JSON)
    # "proposed" | "approved" | "rejected"; approved: the trigger it became.
    status: Mapped[str] = mapped_column(String(10), default="proposed")
    trigger_id: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)


class TriggerChange(Base):
    """One thing that was done to a trigger: made, changed, switched, deleted. A trigger
    is a standing leave to act with nobody watching, so this stays - also after the
    trigger itself is gone, which is why it names the trigger without belonging to it."""

    __tablename__ = "trigger_changes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    trigger_id: Mapped[str] = mapped_column(String(32), index=True)
    # The trigger's name at that moment.
    name: Mapped[str] = mapped_column(String(80))
    at: Mapped[datetime] = mapped_column(default=now)
    # "created" | "renamed" | "message changed" | "settings changed" |
    # "permissions changed" | "budget changed" | "switched on" | "switched off" | "deleted"
    what: Mapped[str] = mapped_column(String(24))
    # How it stands after the change, in words (what it may do now; why it was
    # switched off); None where `what` says it all.
    detail: Mapped[str | None] = mapped_column(Text, default=None)


class TriggerRun(Base):
    """One time a trigger came due: the turn it started, or why it started none."""

    __tablename__ = "trigger_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    trigger_id: Mapped[str] = mapped_column(ForeignKey("triggers.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), default=None)
    at: Mapped[datetime] = mapped_column(default=now)
    # "completed" | "failed" | "budget" | "stopped" | "skipped_busy" | "skipped_budget" |
    # "skipped_month" (the project was over this month's budget), "skipped_limit" (its
    # Lead's provider was over its limit of spend, 81c), "skipped_same" (nothing changed
    # since its last completed turn, K-tetik-degismedi); None while it runs.
    outcome: Mapped[str | None] = mapped_column(String(16), default=None)
    # Started after its time: KOLONİ was off, or asleep, when it came due.
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text, default=None)


class Price(Base):
    """What the user says a model costs, for a million tokens sent and a million written.
    KOLONİ knows no price of its own: money is shown only from these."""

    __tablename__ = "prices"
    model_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    input: Mapped[float] = mapped_column(Float)
    output: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8))
    # For a million tokens read again from the provider's cache, and a million written
    # to it. None: the user wrote no such price, and those tokens are not priced.
    cache_read: Mapped[float | None] = mapped_column(Float, default=None)
    cache_write: Mapped[float | None] = mapped_column(Float, default=None)


class LimitReading(Base):
    """What an account last said of its plan (`app.limits`): Claude Code's from its runs,
    Codex's from "Check now". Kept so that a restart does not forget it."""

    __tablename__ = "limit_readings"
    # `app.limits.account`, as JSON: the CLI's kind and its command, or a provider's id.
    account: Mapped[str] = mapped_column(Text, primary_key=True)
    # The reading as it is shown, its times as ISO text; `read_at` apart.
    reading: Mapped[dict] = mapped_column(JSON)
    read_at: Mapped[datetime] = mapped_column()


class Flag(Base):
    """A switch of the whole app that outlives a restart ("triggers_paused"), or one of its
    settings (Gemini's voice: its key, which no answer carries, model and voice; app.api.voice)."""

    __tablename__ = "flags"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), default=None)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=now)


class BacklogTask(Base):
    """One task of a project's backlog (slice 52). What an agent adds is "proposed", and
    what it would change waits in `pending`: both wait for the user's word. Its
    `assessment` is an agent's opinion, written at once; "done" is only ever the user's."""

    __tablename__ = "backlog_tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    criteria: Mapped[str | None] = mapped_column(Text, default=None)
    priority: Mapped[str] = mapped_column(String(8), default="normal")  # high | normal | low
    # proposed | todo | doing | review | done | blocked
    status: Mapped[str] = mapped_column(String(10), default="todo")
    # The user's order within the project, 0 first; listed after priority.
    position: Mapped[int] = mapped_column(Integer)
    # The conversation "Work the backlog" started it in; not a key, as on a memory record.
    conversation_id: Mapped[str | None] = mapped_column(String(32), default=None)
    created_by: Mapped[str] = mapped_column(String(8))  # user | agent
    pending: Mapped[dict | None] = mapped_column(JSON, default=None)
    assessment: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    # A job of a night's run while the user was away (slice 106), and how it came out there:
    # waits (for the user's word), failed (`away_why` says why) or done; None while it is to
    # do or at work.
    away_run_id: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    away_state: Mapped[str | None] = mapped_column(String(8), default=None)
    away_why: Mapped[str | None] = mapped_column(Text, default=None)
    # K-symphony, how it stands in a run of the backlog (`app.backlog.chain`): {"after": the
    # ids of the tasks it waits for (the user's), "queued": Run the backlog took it, "fix": why
    # its fix round is due, "fixed": it had it, "stuck": why it is blocked}. Replaced whole
    # (`backlog.set_flow`): a JSON field changed in place is not seen.
    flow: Mapped[dict | None] = mapped_column(JSON, default=None)
    # Proposed by the Assistant PO at a turn's end (`AgentRunner._propose_tasks`): {"chat": the
    # conversation, "why": the words of the turn's record it came from, "lead": "add" | "no" -
    # the Lead's word at Full auto - or None, "lead_why", "seen": the user's OK of that word}.
    # None: not the Assistant PO's. Replaced whole, as `flow` is.
    po: Mapped[dict | None] = mapped_column(JSON, default=None)

    @property
    def after(self) -> list[str]:
        return (self.flow or {}).get("after") or []

    @property
    def queued(self) -> bool:
        return bool((self.flow or {}).get("queued"))

    @property
    def stuck(self) -> str | None:
        return (self.flow or {}).get("stuck")


class AwayRun(Base):
    """While the user is away (slice 106): the jobs the Lead put on its card, the places kept
    out and the limits - "planned" until the user's Start, "running" through the night, then
    "ended" (`why`: what stopped it, None when every job was looked at) - or "dismissed"."""

    __tablename__ = "away_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    # The chat it was planned in, and the turn whose Lead put it on the card.
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(10), default="planned")
    # In order: [{"title", "line", "team", "recipe"}], and "task_id" once started.
    jobs: Mapped[list] = mapped_column(JSON, default=list)
    kept_out: Mapped[list] = mapped_column(JSON, default=list)
    # Stop at this time, or once this much is spent on its jobs; None: no such limit.
    until: Mapped[datetime | None] = mapped_column(default=None)
    money: Mapped[float | None] = mapped_column(Float, default=None)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    why: Mapped[str | None] = mapped_column(Text, default=None)
    # When its report was first on the user's screen: KOLONİ opened after the night goes to
    # it until then (the morning), and not again.
    seen_at: Mapped[datetime | None] = mapped_column(default=None)
    # What tried a place kept out, refused: [{"task_id", "what"}].
    tried: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Embedding(Base):
    """A vector of a memory record's words, or of what was said in an earlier turn (22c,
    `app.meaning`): what a search by meaning compares the question's vector with. `kind`
    "memory" with the record's id, or "turn" with the `said_in_turns` row's rowid; `model`
    is the name the vector was asked under, and in the key: vectors of different models do
    not compare, and two projects that embed with different models each keep their own."""

    __tablename__ = "embeddings"
    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(200), primary_key=True)
    vector: Mapped[list] = mapped_column(JSON)
