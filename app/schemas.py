import os
import unicodedata
from datetime import datetime
from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app import copies
from app.commands import held_back
from app.raw import MIN_SECRET
from app.skills import GROUPS as SKILL_GROUPS
from app.skills import MAX_ENCODED, MAX_FILES, MAX_ZIP_ENCODED
from app.skills import front as skill_front
from app.skills import needs as skill_needs


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectIn(BaseModel):
    root_path: str
    name: str | None = None


ExecLocation = Literal["host", "docker"]
NotifyFormat = Literal["slack", "discord", "text"]


# An image's name as Docker takes one (registry/name:tag@digest) - never an option of its
# command line (`--privileged`, `-v=C:/:/h`).
DockerImage = Annotated[str, Field(max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")]


class KoloniAsks(TypedDict):
    """What a folder's .koloni/settings.json may say (slice 86c): checked by this very type as
    it is read (`koloni.settings`), so what is shown and what is used cannot differ. A null
    is not one: the record holds none for these."""
    exec_location: NotRequired[ExecLocation]
    docker_image: NotRequired[DockerImage | None]
    docker_network: NotRequired[bool]
    search_order: NotRequired[Literal["builtin", "cli"]]


class KoloniUseIn(BaseModel):
    # What the page showed: used only while the file still says it.
    asks: KoloniAsks


class KoloniOut(BaseModel):
    """The folder's `.koloni/` (slice 86c), kept in git with it."""
    # Whether its settings.json and rules.md are there and read.
    settings_kept: bool
    rules_kept: bool
    # The rules of rules.md, as agents are given them; None: none, or not read.
    rules: str | None
    # Why a file of it is not read, one line each: what is saved in KOLONİ is used instead.
    broken: list[str]
    # What settings.json says that is not what is saved: used only once the user says so.
    asks: KoloniAsks


# Who picks a chat's teams (slice 84b): the Lead, the user ("manual"), or nobody ("none": any
# role, as before).
TeamsMode = Literal["lead", "manual", "none"]
# Who changes the files in a chat (slice 48, K-devret): sub-agents, the Lead for a small change
# and sub-agents for bigger work, or the Lead itself.
LeadWork = Literal["delegates", "decides", "itself"]
# While the user is away (K-vekil-karar): every question waits, or the Lead answers what it
# safely can after a chat's minutes (0: at once; a day at most).
WhenAway = Literal["waits", "lead"]
# How a team's finished branch reaches the user's (K-dal-takim D2): merged here, or pushed as a
# pull request on GitHub - which KOLONİ never merges.
FinishWay = Literal["merge", "pull_request"]
MAX_AWAY_MINUTES = 1440
SpawnApproval = Literal["auto", "always", "never"]
# The most a room's budget can be set to: a number, not a way round having one.
MAX_ROOM_POSTS, MAX_ROOM_TOKENS, MAX_ROOM_MINUTES = 1000, 100_000_000, 24 * 60
MAX_CHAT_TEAMS = 6


class ChatTeamIn(BaseModel):
    team_id: str = Field(max_length=32)
    # Null: the team's default recipe. One of KOLONİ's, not a folder's.
    recipe_id: str | None = Field(default=None, max_length=32)
    # K-tarifsiz: no recipe in this chat, not even the team's default (never with a recipe_id).
    no_recipe: bool = False


class RecipeBranchStep(BaseModel):
    """A step of a group's branch on the strip (K-tarif-kol); stopped: another branch was done
    first."""

    name: str
    state: Literal["done", "now", "next", "stopped"]


class RecipePart(BaseModel):
    """A step of a running recipe as the canvas's step strip shows it: a step, a group of
    steps at once, or its end ("You", "Report")."""

    id: str
    name: str
    # skipped: left when its runner ended the run there (B-83).
    state: Literal["done", "now", "next", "skipped"]
    # How many times its loops came back to it.
    round: int
    # A Room step (slice 84e): its roles meet in one room.
    room: bool = False
    # A review its writer checks, as the user said, or nobody was there to ask ("Who checks?").
    own_check: bool = False
    # B-173: the names of its steps the user's choice on a card left out.
    left_out: list[str] = []
    # A group: its steps run at once.
    group: bool = False
    # Skipped as its condition was not met (`RecipeStep.when`): why, as the strip says it.
    unmet: str | None = None
    # K-rol-cogul: its role steps that draw more than one, role -> at most how many; None: none.
    draws: dict[str, int] | None = None
    # K-evrim: a step of candidates - the best score its measure gave (None: none yet, or none).
    best: float | None = None
    # ... its target, where its rounds ended below it (the best went on); None: not so.
    missed: int | None = None
    # K-evrim-model: this round's candidates measured so far, best first, each with its model -
    # "Coder 2 (gpt-luna): 85 · Coder (sonnet): 61"; None: none yet.
    scores: str | None = None
    # K-tarif-kol: a group's branches, each its steps in order; None: no group.
    branches: list[list[RecipeBranchStep]] | None = None


class RecipePass(BaseModel):
    """One time a run came to a part, and the agents it opened there."""

    part: str
    agents: list[str]


class ChatTeamState(BaseModel):
    run_id: str
    team: str = ""
    recipe: str = ""
    # running: its step's roles are being opened; ready: at an "in" end - or a loop's rounds
    # over with findings left - waiting for the user's Take in; done: at a "report" end; in:
    # taken in; failed / stopped / interrupted (a restart): with `why`; waiting: picked, not
    # started in a turn another team started in. A team with no recipe beside one (B-101):
    # running while its lead works, then done, failed or stopped; its `recipe` is "".
    status: Literal["running", "ready", "done", "in", "failed", "stopped", "interrupted",
                    "waiting"]
    why: str | None = None
    steps: list[RecipePart] = []
    # Every agent of its run: its lead's too, beside another team.
    agents: list[str] = []
    # Stopped as its turn ended at Ready for you - not a team that ended before its end; None: a
    # row of before batch-16, not known.
    ended_ready: bool | None = None
    # Its parts as they ran, in that order (`recipe_run.opened`); empty for a row from before.
    passes: list[RecipePass] = []


class ChatTeamOut(Out):
    team_id: str
    recipe_id: str | None
    # K-tarifsiz (a turn's row kept before it, `Run.teams`, has none: False).
    no_recipe: bool = False
    picked_by: Literal["lead", "user"]
    # The Lead's reason; None for the user's.
    why: str | None
    # Where its recipe's run is (slice 84b-2); None: not run yet.
    state: ChatTeamState | None = None


class FinishTestsAuto(BaseModel):
    """89m: "Finish only when the tests pass" where the user has not said (`finish_tests`)."""
    on: bool
    # The tests' command: the check command, or one the folder's files show; None: none.
    command: str | None
    # Why it is on or off, in words.
    reason: str


class ProjectOut(Out):
    id: str
    name: str
    root_path: str
    created_at: datetime
    exec_location: ExecLocation
    docker_image: str | None
    docker_network: bool
    # The user's own SearXNG, asked first by a web search; None when there is none.
    search_url: str | None
    search_order: Literal["builtin", "cli"]
    # Whether a search may be handed to agy too.
    search_agy: bool
    # Whether a notification address is set. The address itself is never given back.
    has_notify_url: bool
    # The body posted there: {"text": …}, {"content": …}, or the text alone.
    notify_format: NotifyFormat
    # Whether a notification is also shown on the user's desktop.
    notify_desktop: bool
    # The most tokens a turn's agents may report before it is stopped; None: no limit.
    turn_token_limit: int | None
    # The most agents at work at once in all its conversations together; None: no limit.
    max_agents: int | None
    # K-devam-butce: the steps a stopped agent gets on top when told to go on with none left.
    continue_steps: int
    # What this calendar month's turns may cost, in the prices' currency; None: no budget.
    monthly_budget: float | None
    # The command that checks a sub-agent's work before it is taken; None: none.
    check_command: str | None
    # K-evrim: the command whose last line of output scores a candidate (0-100); None: none.
    measure_command: str | None
    # Whether what is taken from a sub-agent is offered for a commit of those files.
    git_commit: bool
    # D2: how a team's finished branch reaches the user's; None: not chosen yet.
    finish_way: FinishWay | None
    # Whether a fast model is asked, after each turn that completed, what the turn found.
    auto_notes: bool
    # 22c: the other projects whose memory and earlier turns `recall` also looks in (ids),
    # read only; the provider whose server embeds for a search by meaning (null: off) and
    # the model name it is asked for.
    memory_links: list[str]
    embedding_provider_id: str | None
    embedding_model: str
    # Whether the Observer role's model looks over each sub-agent's report.
    observe_reports: bool
    # Whether the Assistant PO proposes follow-up tasks after a turn, and on which tier.
    suggest_tasks: bool
    suggest_tier: "Tier"
    # Folders outside the project its agents also work in (absolute paths).
    also_in: list[str]
    # Folders outside it its agents may read in; a change there is asked about every time.
    read_in: list[str]
    # The teams a new chat in it starts with (slice 84b); rows only in Manual.
    teams_mode: TeamsMode
    teams: list[ChatTeamIn]
    # The local time of day ("HH:MM") the day's summary is sent; None: never.
    day_note_at: str | None
    # Whether its commands see its secret files as denied or empty (Copilot, Docker).
    hide_secrets: bool
    # The secret variables its commands are given all the same, comma-separated; None: none.
    pass_env: str | None
    # 101: whether its turns' commands get a planted test key (`Project.canary`).
    canary: bool
    # Its chats' sub-agent settings, every chat's (tek-ev: `models.settings_of`): who changes
    # the files, who answers while the user is away (K-cli-vekil), when opening a sub-agent
    # asks, how far a turn's tree may grow, a discussion's tokens (None: no limit), and what a
    # room may spend unless said otherwise as it is opened (None: no limit).
    lead_work: LeadWork
    when_away: WhenAway
    away_minutes: int
    spawn_approval: SpawnApproval
    spawn_max_depth: int
    spawn_max_agents: int
    spawn_max_parallel: int
    discussion_budget: int | None
    room_posts: int | None
    room_tokens: int | None
    room_minutes: int | None
    # 89m: whether a Claude Code agent that changed files finishes only once the tests pass;
    # None: as `finish_tests_auto` says.
    finish_tests: bool | None
    finish_tests_auto: FinishTestsAuto

    @computed_field
    @property
    def held_env(self) -> list[str]:
        """The secret variables of KOLONİ's environment its commands are not given: the
        names, never a value."""
        return held_back(os.environ, self.pass_env)

    @computed_field
    @property
    def koloni(self) -> KoloniOut:
        """What the folder's `.koloni/` holds, read now."""
        from app import koloni  # here: app.koloni checks its settings with ProjectPatch

        return KoloniOut.model_validate(koloni.state(self))


# A folder's full path, as a list of folders to work in takes it (Windows' longest is 32767).
FolderPath = Annotated[str, Field(max_length=32767)]


class ProjectPatch(BaseModel):
    exec_location: ExecLocation | None = None
    docker_image: str | None = Field(default=None, max_length=200)
    docker_network: bool | None = None
    # Left out: kept as it is. Empty: none.
    search_url: str | None = Field(default=None, max_length=500)
    search_order: Literal["builtin", "cli"] | None = None
    search_agy: bool | None = None
    notify_url: str | None = Field(default=None, max_length=500)
    notify_format: NotifyFormat | None = None
    notify_desktop: bool | None = None
    # Sent as null to take the limit away; left out to keep it.
    # A whole number as such: not `true`, not "50".
    turn_token_limit: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    # The same: null takes it away.
    max_agents: int | None = Field(default=None, gt=0, le=1000, strict=True)
    # Left out: kept as it is. A whole number from 1 to 200.
    continue_steps: int | None = Field(default=None, ge=1, le=200, strict=True)
    # The same: null takes it away. A number as such: not `true`, not "5".
    monthly_budget: float | None = Field(
        default=None, gt=0, le=2**53, allow_inf_nan=False, strict=True)
    # Left out: kept as it is. Empty: none.
    check_command: str | None = Field(default=None, max_length=500)
    measure_command: str | None = Field(default=None, max_length=500)
    git_commit: bool | None = None
    # Left out: kept as it is. "pull_request" is the user's consent to push the project's
    # finished branches: refused where gh cannot open one.
    finish_way: FinishWay | None = None
    auto_notes: bool | None = None
    # 22c. Left out: kept as it is. The whole list of project ids, as it is to be.
    memory_links: list[str] | None = Field(default=None, max_length=50)
    # Sent as null to switch the search by meaning off; left out to keep it.
    embedding_provider_id: str | None = Field(default=None, max_length=32)
    # Left out: kept as it is. Empty: the default model name.
    embedding_model: str | None = Field(default=None, max_length=200)
    observe_reports: bool | None = None
    suggest_tasks: bool | None = None
    suggest_tier: "Tier | None" = None
    # Left out: kept as it is. The whole list, as it is to be.
    also_in: list[FolderPath] | None = Field(default=None, max_length=50)
    read_in: list[FolderPath] | None = Field(default=None, max_length=50)
    # Left out: kept as it is. The rows only with Manual; another mode has none.
    teams_mode: TeamsMode | None = None
    teams: list[ChatTeamIn] | None = Field(default=None, max_length=MAX_CHAT_TEAMS)
    # "HH:MM" by the local clock; null: the day's summary is not sent.
    day_note_at: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    hide_secrets: bool | None = None
    # Left out: kept as it is. Empty: none.
    pass_env: str | None = Field(default=None, max_length=2000)
    canary: bool | None = None
    lead_work: LeadWork | None = None
    when_away: WhenAway | None = None
    away_minutes: int | None = Field(default=None, ge=0, le=MAX_AWAY_MINUTES, strict=True)
    # Left out: kept as it is. As a chat's were (`ConversationPatch`).
    spawn_approval: SpawnApproval | None = None
    spawn_max_depth: int | None = Field(default=None, ge=1, le=4, strict=True)
    spawn_max_agents: int | None = Field(default=None, ge=1, le=20, strict=True)
    spawn_max_parallel: int | None = Field(default=None, ge=1, le=32, strict=True)
    # Sent as null to take the limit away; left out to keep it.
    discussion_budget: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    room_posts: int | None = Field(default=None, ge=1, le=MAX_ROOM_POSTS, strict=True)
    room_tokens: int | None = Field(default=None, ge=1, le=MAX_ROOM_TOKENS, strict=True)
    room_minutes: int | None = Field(default=None, ge=1, le=MAX_ROOM_MINUTES, strict=True)
    # Sent as null: automatic again (`ProjectOut.finish_tests_auto`). Left out: kept.
    finish_tests: bool | None = None


class NeverOut(BaseModel):
    path: str
    why: str


class FoldersOut(BaseModel):
    # The places KOLONİ never opens, by any list or card, with why: and every folder that
    # holds one of them, a drive's root and network paths too.
    never: list[NeverOut]


class FolderBrowseIn(BaseModel):
    # The folder to list, by its full path; left out: the home folder.
    path: FolderPath | None = None


class FolderPlace(BaseModel):
    name: str
    path: str


class FolderEntry(FolderPlace):
    """A folder in the folder listed (never a file)."""

    koloni: bool  # a `.koloni` in it: a KOLONİ project
    git: bool  # a `.git` in it
    hidden: bool  # its name starts with "." or the system hides it
    # Not one to open as a project (`workspace.not_a_project`): shown faded, not chosen.
    blocked: bool


class FolderBrowseOut(BaseModel):
    """One folder for the folder picker (slice 86a), as it really is."""

    path: str
    # From the drive's root to it, each to be opened.
    parts: list[FolderPlace]
    # The home folder, Desktop, Documents, and the drives.
    shortcuts: list[FolderPlace]
    entries: list[FolderEntry]
    # There were more folders in it than are listed.
    more: bool


class StorageOut(BaseModel):
    """What KOLONİ's own data takes on this machine, in MB: the database (its WAL too), its
    backups (each migration's and update's: apart, R125 - they were most of "db"), the working
    copies, the log. None: not counted in time."""
    db_mb: float | None
    backups_mb: float | None
    copies_mb: float | None
    logs_mb: float | None


class HealthOut(BaseModel):
    model_reachable: bool
    model_id: str | None
    tools_supported: bool | None
    model_base_url: str
    # The provider asked: the one given, else the default (the one a conversation uses when
    # nothing else is chosen). None: there is none.
    provider_id: str | None
    provider_name: str | None
    error: str | None
    # The provider is there, but may not run with its default model ("Only these models").
    not_listed: bool
    docker_available: bool
    docker_error: str | None
    # Whether a desktop notification can be shown on this system at all.
    desktop_available: bool
    # A hash of the API this server's code has; a page built from other code has another.
    # None: not known (the typed API is not where it is looked for).
    api_hash: str | None
    # The shell commands on this machine run in (K-pwsh: "PowerShell 7" where it is found).
    shell: str | None
    # Why a PowerShell 7 that is there is not used (the Store's); None otherwise.
    shell_note: str | None


PermissionMode = Literal["ask", "auto_edit", "full_auto"]
# How strong the user says a model is (`app.team.TIERS`).
Tier = Literal["fast", "balanced", "strongest"]
# What a model may take besides text (`app.providers.INPUTS`).
ModelInput = Literal["image", "video", "audio", "pdf"]
# A role's tier rule (slice 81b): always one tier, or the conversation's model (`app.team`).
TierRule = Literal["fast", "balanced", "strongest", "conversation"]
# How hard a model thinks, lowest first (`app.model_client.EFFORTS`, kept the same by a
# test); null: the provider's own. "off": no thinking, where a model is known to turn it off.
Effort = Literal["off", "low", "medium", "high", "xhigh", "max"]



class ConversationOut(Out):
    id: str
    # The folder it works in; None: a plain chat (slice 86a).
    project_id: str | None
    title: str
    permission_mode: PermissionMode
    spawn_approval: SpawnApproval
    spawn_max_depth: int
    spawn_max_agents: int
    spawn_max_parallel: int
    # The most tokens the speakers of one discussion may report; None: no limit.
    discussion_budget: int | None
    provider_id: str | None
    model_id: str | None
    # The lead's model is chosen each turn by how hard a fast model says the message is.
    lead_auto: bool
    # Each new message starts with a plan turn the user approves first (slice 49).
    plan_first: bool
    # K-39-betik: a page shown in the Workspace runs its scripts without asking ("Always run in
    # this chat"); off, each page asks.
    page_scripts: bool
    # Who changes the files; `lead_hands_code` is slice 48's word for "delegates": the Lead is
    # not given write tools.
    lead_work: LeadWork
    lead_hands_code: bool
    # While the user is away: everything waits, or the Lead answers what it safely can.
    when_away: WhenAway
    away_minutes: int
    # The Lead's reasoning level here; None: its role's.
    lead_effort: Effort | None
    # What a room opened here may spend unless the user says otherwise as they open it:
    # posts by its members, tokens as their models report them, minutes. None: no limit.
    room_posts: int | None
    room_tokens: int | None
    room_minutes: int | None
    # Folders outside the project it also works in: its folder's at its start, from the
    # user's messages, cards and "This chat's folders" (slice 86b).
    also_in: list[str]
    # Folders it may read in only: the same, and from an agent's ask_folder card.
    read_in: list[str]
    # K-buyuk-proje: the part of its folder's map its agents work in ("core/"); None: all of it.
    part: str | None
    # Who picks the teams whose roles its agents may open, and the rows picked, in order
    # (slice 84b): none in "No teams".
    teams_mode: TeamsMode
    teams: list[ChatTeamOut]
    created_at: datetime
    updated_at: datetime
    # When the user put it away; None: it is not. It is listed either way.
    archived_at: datetime | None


class ListedBacklogTask(BaseModel):
    """The To-do list's task a chat works on (K-backlog-sohbet)."""

    id: str
    status: Literal["proposed", "todo", "doing", "review", "done", "blocked"]
    # It waits for the user's word: its turn (`backlog.waiting`) or Take in (`backlog.not_in`).
    waiting: bool


class ConversationListed(ConversationOut):
    """A conversation as the project's list shows it."""

    # A working copy of one of its turns was kept on disk and is not decided yet.
    kept: bool
    # It has a turn the user started (not a trigger's).
    wrote: bool
    # The To-do list's task it was started for ("Run the backlog"); None: an ordinary chat.
    backlog_task: ListedBacklogTask | None


class ConversationIn(BaseModel):
    # The folder it is made in; left out or null: none, a plain chat.
    project_id: str | None = Field(default=None, max_length=32)


class ConversationsDeleteIn(BaseModel):
    """Archived conversations to delete (slice 76); the page sends more in parts of 500."""

    ids: list[Annotated[str, Field(max_length=32)]] = Field(min_length=1, max_length=500)


class NotDeleted(BaseModel):
    id: str
    title: str | None
    why: str


class ConversationsDeletedOut(BaseModel):
    """Those deleted, and those that were not, each with why."""

    deleted: list[str]
    refused: list[NotDeleted]


class ProjectDeletePreviewOut(BaseModel):
    """What a delete of the project takes from KOLONİ, counted for its dialog."""

    chats: int
    memory: int
    tasks: int
    triggers: int
    knowledge: int


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    # Left out: kept as it is. Null: no folder - a plain chat (slice 86a).
    project_id: str | None = Field(default=None, max_length=32)
    permission_mode: PermissionMode | None = None
    spawn_approval: SpawnApproval | None = None
    spawn_max_depth: int | None = Field(default=None, ge=1, le=4)
    spawn_max_agents: int | None = Field(default=None, ge=1, le=20)
    spawn_max_parallel: int | None = Field(default=None, ge=1, le=32)
    # Left out: kept as it is. Null: no limit.
    discussion_budget: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    # Sent as null to go back to the default; left out to keep what is chosen.
    provider_id: str | None = None
    model_id: str | None = Field(default=None, max_length=200)
    lead_auto: bool | None = None
    plan_first: bool | None = None
    page_scripts: bool | None = None
    # Slice 48's switch: true is "delegates", false "itself". `lead_work` wins where both are.
    lead_hands_code: bool | None = None
    lead_work: LeadWork | None = None
    when_away: WhenAway | None = None
    away_minutes: int | None = Field(default=None, ge=0, le=MAX_AWAY_MINUTES, strict=True)
    # Sent as null to go back to the Lead role's level; left out to keep it.
    lead_effort: Effort | None = None
    # Left out: kept as it is. Null: no limit.
    room_posts: int | None = Field(default=None, ge=1, le=MAX_ROOM_POSTS)
    room_tokens: int | None = Field(default=None, ge=1, le=MAX_ROOM_TOKENS)
    room_minutes: int | None = Field(default=None, ge=1, le=MAX_ROOM_MINUTES)
    # Left out: kept as it is. The whole list, as it is to be: one added only from the app's
    # own page; one in both lists is one to write in.
    also_in: list[FolderPath] | None = Field(default=None, max_length=500)
    read_in: list[FolderPath] | None = Field(default=None, max_length=500)
    # Left out: kept as it is. A part of the folder's map ("core/"); null or ".": all of it.
    part: str | None = Field(default=None, max_length=500)
    # Left out: kept as it is. True puts it away (nothing of it goes), False brings it back.
    archived: bool | None = None
    # Left out: kept as it is. Leaving Manual takes the rows away; `teams` (the user's rows,
    # the whole list as it is to be) only with Manual.
    teams_mode: TeamsMode | None = None
    teams: list[ChatTeamIn] | None = Field(default=None, max_length=MAX_CHAT_TEAMS)


RunStatus = Literal[
    "queued", "running", "waiting_approval", "completed", "failed", "cancelled", "interrupted"
]


class PlanOut(BaseModel):
    text: str
    status: Literal["proposed", "approved", "rejected"]
    # The model that wrote it, as it said; and whether it was the team's strongest one
    # (otherwise the conversation's own).
    model_id: str | None
    strongest: bool
    # Why the user turned it down, in their words; None where they gave no reason.
    why: str | None = None


class PoDropped(BaseModel):
    title: str
    why: str


class PoOut(BaseModel):
    """The Assistant PO's one request after a turn (`PoMixin`): the model asked, whether it
    was heard out and what it spent (None: not said), how many of its proposals went on the
    To-do list, and why each other was dropped - never its answer nor words the turn did not
    say. `note`: why its answer proposed nothing it could read."""

    provider_name: str | None
    model_id: str | None
    heard: bool
    input_tokens: int | None = None
    output_tokens: int | None = None
    proposed: int = 0
    dropped: list[PoDropped] = []
    # Dropped past those listed (`backlog.PROPOSE_MOST` * 3), counted only.
    dropped_more: int = 0
    note: str | None = None
    # At Full auto: how many of them the Lead added for the user; None where it did not decide.
    lead_added: int | None = None


class RunOut(Out):
    id: str
    conversation_id: str
    status: RunStatus
    error: str | None
    model_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    # A turn nobody is watching: a trigger started it. Its name is the trigger's as it
    # was then; the trigger itself may be gone since.
    unattended: bool
    trigger_id: str | None
    trigger_name: str | None
    # The piece of work this turn goes on with; None for a turn on record without one.
    topic_id: str | None
    # A plan turn: it only reads, and its answer is a plan put before the user (slice 49).
    plan_turn: bool
    # What it planned; None until a plan turn has written one.
    plan: PlanOut | None
    # One side of a comparison (slice 54); None for every other turn.
    compare_id: str | None
    # B-107: the chat's teams as this turn left them; None for a turn without, or from before.
    teams: list[ChatTeamOut] | None = None
    # The Assistant PO's request after the turn; None where it was not asked.
    po: PoOut | None = None


class CompareSideIn(BaseModel):
    provider_id: str
    # None: the provider's default model.
    model_id: str | None = None


class CompareIn(BaseModel):
    content: str
    sides: list[CompareSideIn] = Field(min_length=2, max_length=2)
    # The topic it goes on with, as a message's (`MessageIn`).
    topic_id: str | None = None
    new_topic: bool = False
    # The user's word to start both sides though the project is over this month's budget.
    over_budget: bool = False


class CompareStarted(BaseModel):
    compare_id: str
    run_ids: list[str]


class CompareChoice(BaseModel):
    run_id: str


class PlanApproveIn(BaseModel):
    # The plan as the user edited it; left out or empty: as it was proposed.
    text: str | None = Field(default=None, max_length=20_000)
    # The user's word to start the work though the project is over this month's budget.
    over_budget: bool = False


class PlanRejectIn(BaseModel):
    why: str | None = Field(default=None, max_length=500)


class TopicOut(Out):
    """A piece of work in a conversation: the turns that go on with the same thing."""

    id: str
    conversation_id: str
    title: str
    # The trigger whose turns these are (it may be gone since); None for the user's own.
    trigger_id: str | None
    created_at: datetime


class TopicPatch(BaseModel):
    title: str = Field(max_length=200)


class SpokenIn(BaseModel):
    """What a message asks of the lead's answer when the user listens to it (slice 32a)."""

    model_config = ConfigDict(extra="forbid")
    # A language tag as the browser's voices give it: "en-US", "tr-TR", "en-GB-x-rp".
    # (The page holds the same pattern: voice.ts LANGUAGE_TAG.)
    language: str = Field(pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,4}$")
    # How the user wants it said, in their own words.
    style: str | None = Field(None, max_length=300)


class GeminiVoiceOut(BaseModel):
    """Reading aloud with Gemini (slice 32e): whether a key is saved - never the key."""

    has_key: bool
    model: str
    voice: str
    # How Gemini says what it reads, in the user's words ("" for none). Not the Lead's manner:
    # that one goes to the model that writes.
    style: str
    # Said once, on the answer to a save: "the key is saved, but ...".
    note: str | None = None


class GeminiVoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # None: as it is; "": the saved key (or manner) is removed.
    api_key: str | None = None
    model: str | None = None
    voice: str | None = None
    # (At most 200: what one row of `flags` holds.)
    style: str | None = Field(None, max_length=200)


class GeminiSayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # shortcut: 4000 characters at most (the page sends a sentence at a time); Google's own
    # limit is not on its page - upgrade if a longer one is ever needed.
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None
    style: str | None = Field(None, max_length=300)


class MessageIn(BaseModel):
    content: str
    # Asked for: the lead ends its answer with a line to say aloud, taken off into `spoken`.
    spoken: SpokenIn | None = None
    # Which piece of work the message goes on with: a topic of this conversation by its
    # id, or a new one. With neither, the topic the user was last in.
    topic_id: str | None = None
    new_topic: bool = False
    # The user's word to start it though the project is over this month's budget.
    over_budget: bool = False
    # The files added to it (slice 85b), by id: this conversation's, not sent before.
    attachments: list[str] = Field(default=[], max_length=10)  # attachments.MAX_FILES
    # "Save these to the project too" (slice 23): into docs/attachments/, no card.
    save_to_project: bool = False


class AttachmentOut(Out):
    """A file the user added to a message (slice 85b)."""

    id: str
    conversation_id: str
    # None until its message is sent.
    message_id: str | None
    # A frame the page took of this video attachment.
    frame_of: str | None
    name: str
    # By its bytes, never its name.
    kind: Literal["text", "image", "pdf", "docx", "video", "executable", "file"]
    mime: str
    size: int
    summary: str
    # The agents it was handed to.
    given_to: list[str]
    # A picture's or video's: agent id -> what became of it for that agent's model, in words.
    shown_to: dict[str, str]
    keep_in_project: bool
    created_at: datetime


class AttachmentTextOut(BaseModel):
    # None: no text of it goes to a model (an image, a program, a secret file).
    text: str | None


class MessageOut(Out):
    id: str
    conversation_id: str
    run_id: str
    agent_id: str | None
    # "memory": what KOLONİ told `agent_id` about a fact it had been given from memory.
    # "trigger": what started an unattended turn - a trigger's message, with whatever
    # set it off, as the agent was given it. Not the user's words of that moment.
    # "away": KOLONİ's one line in the chat at the end of a night while the user was away.
    # "git": KOLONİ's line on what a turn did to the project's git (slice 70).
    # "koloni": KOLONİ's own line - under a Lead's answer that named a role it never opened;
    # at Take in, a .venv or the like an agent made in its copy, which stays out (B-383).
    # "landed": KOLONİ's line under a turn's answer on where its work is, from the records (B-205).
    role: Literal["user", "assistant", "agent", "memory", "trigger", "away", "git", "koloni",
                  "landed"]
    from_agent_id: str | None
    delivered_at: datetime | None
    discussion_id: str | None
    # A note from the shared notebook, as it was handed to `agent_id`.
    board_post_id: str | None
    # A post of a room, as it was handed to `agent_id`, a member of it.
    room_post_id: str | None
    content: str
    # What the lead said to be read aloud, taken off the end of its written answer (slice 32a).
    spoken: str | None = None
    status: Literal["streaming", "complete"]
    created_at: datetime


class ToolCallOut(Out):
    id: str
    run_id: str
    agent_id: str
    message_id: str
    seq: int
    # The id the model gave the call (a CLI's: KOLONİ's own, cli_...).
    provider_call_id: str
    name: str
    arguments: str
    status: Literal["pending", "running", "succeeded", "failed", "denied", "interrupted"]
    origin: Literal["koloni", "cli"]
    # The call that started the CLI's own sub-agent this call was made in, if any.
    parent_call_id: str | None
    # Asked to go outside the project: the folder "Allow this folder" would open.
    outside_folder: str | None
    # Asked about for another reason (a secret file in the project): the card's words.
    why_asked: str | None
    result: str | None
    started_at: datetime | None
    ended_at: datetime | None


class ToolCallDecision(BaseModel):
    # For a path outside the project: this call only, or its whole folder from here on.
    # For a skill an agent asks to add: "ask_scripts" adds it without leave for its scripts.
    scope: Literal["once", "folder", "ask_scripts"] = "once"


class SecretIn(BaseModel):
    # An ask_secret card's value (slice 91), or null for no. A shorter one would not be
    # hidden in what a command prints (`raw.spellings`).
    value: str | None = Field(default=None, min_length=MIN_SECRET, max_length=16_384)


class FileChangeOut(BaseModel):
    id: str
    run_id: str
    agent_id: str
    origin: Literal["koloni", "cli"]
    # None: no agent's call made it - a room's copy brought it into the project.
    tool_call_id: str | None
    path: str
    kind: Literal["create", "modify", "delete"]
    # "in_copy": made in the agent's working copy; not in the project (yet).
    # "discarded": it never reached the project and nobody said no - its copy was thrown
    # away without anybody deciding (Stop, or a turn nobody watched), or the user said
    # yes and the turn ended before it was made (Stop, a restart); "rejected" is the
    # user's own no. "approved": the user's yes is there and its agent waits for a
    # place among the agents at work before it is made. "merged": made in the agent's
    # working copy to a file the project changed too - what the project got of it is
    # the one change that joins the two (a record of its own, which can be reverted).
    status: Literal[
        "proposed", "approved", "in_copy", "applied", "rejected", "discarded", "reverted",
        "conflict", "failed", "merged",
    ]
    diff: str
    additions: int
    deletions: int
    created_at: datetime
    decided_at: datetime | None
    # "Save these to the project too" (slice 23): the attached file it saves, by its id.
    attachment_id: str | None = None
    # In the project ("applied", "merged"), not a deletion, and its file is not there now:
    # deleted by hand since (B-55). Said where a conversation is read; False elsewhere.
    gone: bool = False


class FileChangeDiffOut(BaseModel):
    """A change's diff with the whole file around it: read when a fold is opened (slice 42a)."""
    diff: str


class ProjectEntryOut(BaseModel):
    """One file or folder of a project's tree, in the Files window (slice 42c)."""
    name: str
    kind: Literal["dir", "file"]
    size: int | None  # a folder's: None


class SharedFileOut(BaseModel):
    """A file of the teams' shared folder (K-ortak-klasor): its path in it, when last written."""
    path: str
    at: datetime


class SharedPathIn(BaseModel):
    path: str = Field(max_length=200)


class DiagramPictureIn(BaseModel):
    """K-drawio: the user's "Save as PNG / SVG" - the picture the Workspace's viewer drew of the
    diagram at `path`, base64; it is written beside it, by its name."""

    path: str = Field(max_length=200)  # (its picture's is no longer: SharedPathIn answers)
    format: Literal["png", "svg"]
    data: str = Field(max_length=28 * 1024 * 1024)  # (20 MB, as base64: `diagram.MAX_PICTURE`)


class GitSwitchIn(BaseModel):
    """K-dallar: the project's branch to switch to - or, `new`, to make where it stands."""

    name: str = Field(max_length=200)
    new: bool = False


class ProjectFileOut(BaseModel):
    """A file of the project, read only: its text, or why not (larger than 256 KB, or not text)."""
    text: str | None
    size: int
    binary: bool
    too_large: bool


class OthersInstructionsOut(BaseModel):
    """Another project's agent instruction files below the project's root, which CLI agents
    load by themselves (`project_files.others_instructions`)."""
    paths: list[str]
    more: int  # found beyond `paths`
    partial: bool  # a cap stopped the walk before every folder was looked in


class ProjectPartOut(BaseModel):
    """A part of the project in its map (`project_map`): a folder with a marker file."""
    path: str  # "./" for the project's own folder, else "folder/sub/"
    language: str
    files: int  # at most `project_map.MOST_COUNTED`
    more: bool  # it has more files than that
    agents_md: bool
    guess: str | None  # KOLONİ's guess at its test command, run in its folder; None: none
    test: str | None  # the user's where they set one, else the guess
    edited: bool


class ProjectMapOut(BaseModel):
    git: bool
    big: bool  # too big to copy whole (`copies.MAX_FILES`, `copies.MAX_BYTES`)
    partial: bool  # a cap stopped the scan before every folder was looked in
    parts: list[ProjectPartOut]
    not_copied: list[str]  # top folders git ignores, which a copy of a big project leaves out


class PartTestIn(BaseModel):
    path: str
    # Empty: no test. One line, no control characters: it is run as a command (a later slice).
    command: str = Field(max_length=500, pattern=r"^[^\x00-\x1f]*$")


class UndoSkip(BaseModel):
    path: str
    why: str


class UndoTurn(BaseModel):
    run_id: str
    # The topic's name, and which turn of it this is; None where it is in no topic, or
    # never started.
    topic: str | None
    turn: int | None
    # Its own request, as the turn list shows it: the first line of its message, cut.
    request: str


class UndoCopy(BaseModel):
    """A kept working copy discarded: its folder is deleted, and these files were only there."""
    folder: str
    files: list[str]


class UndoOut(BaseModel):
    """A turn undone, or the conversation put back to before one - or, looked ahead, what
    that would do (slice 50): the turns it takes back; the changes reverted (a path for each,
    latest first), those skipped and why; the files of kept working copies turned down, and
    those copies, whose folders are deleted; the commands run and what else is done but not
    on record to take back (`stays`); and, once done, what happened meanwhile (`note`)."""
    turns: list[UndoTurn]
    revert: list[str]
    skip: list[UndoSkip]
    reject: list[str]
    copies: list[UndoCopy]
    commands: list[str]
    stays: list[str]
    note: str | None = None


# "approved": the user said yes, and its agent waits for a place among the agents at work
# before the command runs. "rejected" is the user's own no (or nobody decided before the
# turn ended). "interrupted": cut short - one that ran (a restart, a CLI that never
# reported its end), or, with no `started_at`, one the user said yes to whose turn ended
# before it started.
CommandStatus = Literal[
    "proposed", "approved", "running", "exited", "timed_out", "killed", "rejected",
    "failed_to_start", "interrupted",
    "blocked",  # K-48: a CLI's own, its write refused by its sandbox (`model_native.WRITE_BLOCKED`)
]


class CommandOut(BaseModel):
    id: str
    run_id: str
    agent_id: str
    origin: Literal["koloni", "cli"]
    # None: no agent's call asked for it - the project's check, run on a room's copy.
    tool_call_id: str | None
    command: str
    cwd: str | None
    location: ExecLocation
    image: str | None
    status: CommandStatus
    exit_code: int | None
    output: str
    output_truncated: bool
    timeout_seconds: int
    # The allow-list rule "Always run" would add for this command ("" for one that keeps
    # running, or one asked because web is off: it is asked every time).
    suggested_prefix: str
    # Asked because a web tool is off on the Tools page and it reaches the internet
    # (K-web-komut): KOLONİ's own word, never a CLI's.
    web_off: bool
    # What it does that cannot be taken back - deletes, overwrites a git remote, opens a
    # secret file, sends something off this machine (`harms`) - in one sentence, or "": no
    # rule covers such a command; it is asked at every level, Full auto too (slice 90).
    danger: str
    # A command that keeps running (a dev server), and the address it serves on: loopback
    # only, never KOLONİ's own port nor a model server's (slice 42b).
    keep_running: bool
    preview_url: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None


class FrameOut(BaseModel):
    # Whether a served page may be shown in KOLONİ's frame; None: nothing answered.
    frameable: bool | None


class AllowedCommandOut(Out):
    id: str
    conversation_id: str
    prefix: str
    # `CommandOut.danger` of the rule's own text: a rule stored before slice 90 for one that
    # deletes or names a secret file covers nothing now.
    danger: str
    created_at: datetime


class WebRequestOut(Out):
    """A web search or an HTTP request the user is, or was, asked about."""

    id: str
    run_id: str
    agent_id: str
    tool_call_id: str
    # "page": a site the agent's browser would open (K-tarayici-disari), its address the target;
    # "form", "password", "sign", "field": what it would do on a site's page (A2), said in the
    # target - the site in `host`.
    kind: Literal["search", "http", "page", "form", "password", "sign", "field"]
    # A request's method; None for a search.
    method: str | None
    # The query, or the address.
    target: str
    host: str | None
    # The names of the headers it would send: their values are kept nowhere.
    headers: list[str]
    # How many characters its body has; None without one.
    body_chars: int | None
    # "interrupted": the user said yes, and the turn ended before its answer was there -
    # its agent never got its place, or the request was cut short on its way.
    status: Literal["proposed", "approved", "rejected", "interrupted"]
    created_at: datetime
    decided_at: datetime | None


class AllowedHostIn(BaseModel):
    # A host (`example.com`), or an address for anything but https on its usual port.
    host: str = Field(max_length=500)
    # "page": a site the agent's browser opens, by its bare name (K-tarayici-disari).
    kind: Literal["host", "page"] = "host"
    # A site added marked Ask first (A3); read for "page" alone.
    ask_first: bool = False


class AskFirstIn(BaseModel):
    ask_first: bool


class AllowedWebOut(Out):
    """What a conversation's turns do on the web without asking: search, or GET from a host."""

    id: str
    # The chat a rule is kept on; none for a site kept on its project (`project_id`, A3).
    conversation_id: str | None
    project_id: str | None
    # "page": a site the agent's browser opens - of the whole project (K-tarayici-disari).
    kind: Literal["search", "host", "page"]
    # The host of a "host" or "page" rule; empty for "search".
    host: str
    # A "page" rule's site is asked about all the same, at every level.
    ask_first: bool
    created_at: datetime


# "blocked": it waits for a file another agent holds (`waiting_for` says which).
AgentStatus = Literal[
    "proposed", "queued", "running", "waiting", "blocked", "completed", "failed",
    "cancelled", "rejected", "interrupted",
]


class ChatRulesOut(BaseModel):
    """What runs without asking in one chat of a project (tek-ev: Settings › This project)."""

    conversation_id: str
    title: str
    commands: list[AllowedCommandOut]
    web: list[AllowedWebOut]


class SignOut(BaseModel):
    """A count, not a judgement: the same call failed the same way, or a reading call
    returned the same, `count` times with nothing changed in between (`app.signs`)."""

    kind: Literal["same_failure", "same_result"]
    count: int
    text: str


class WaitingForOut(BaseModel):
    """The agent a blocked agent waits for, and the file that one holds. The holder may
    be an agent of another conversation of the project: it is named here for that."""

    agent_id: str
    agent_name: str
    path: str
    # B-140: the holder's conversation, and whether its turn waits for the user's answer
    # there (that frees the file); None on a record from before this was kept.
    conversation_id: str | None = None
    conversation_title: str | None = None
    asks_you: bool | None = None


class QueuedOnOut(BaseModel):
    """The provider an agent stands in line for (K-paralel-saglayici): its agents at work in
    the whole app, and the most it lets work at once."""

    provider: str
    at_work: int
    most: int


class ClaimOut(BaseModel):
    """A file of the project that an agent of a running turn holds until its work is
    done. The holder may be an agent of another conversation of the project."""

    path: str
    agent_id: str


class CopyOut(BaseModel):
    """Where an agent changes files: in a working copy of its own, in the copy of the
    agent it works for ("parent"), or in the project - because that is too big to copy
    ("too_big"), or because the copy could not be made ("failed")."""

    state: Literal["own", "parent", "too_big", "failed"]
    # K-dallar: the project's branch its own copy was made on; left out where not known, or no git.
    branch: str | None = Field(None, exclude_if=lambda value: value is None)
    # K-dal-takim D2: the git branch of its own it works on (`koloni/<name>`), for the git map.
    on_branch: str | None = Field(None, exclude_if=lambda value: value is None)


class CopyFileOut(BaseModel):
    """One file a working copy holds that the project does not, from what it held when the
    copy took it to what the copy holds now (`changes.in_copy`)."""

    path: str
    kind: Literal["create", "modify", "delete"]
    diff: str
    additions: int
    deletions: int


class WorkingCopyOut(BaseModel):
    """An agent's working copy as its work goes on (slice 70): the agent whose copy it is,
    its folder while that work goes on (None after), and what it changed."""

    agent_id: str
    folder: str | None
    files: list[CopyFileOut]


class CopyCountOut(BaseModel):
    """How much a working copy changed, for a card: files, lines added and removed."""

    files: int
    additions: int
    deletions: int


class GitWorktreeOut(BaseModel):
    path: str
    branch: str | None
    # The project's own folder.
    here: bool


class GitBranchOut(BaseModel):
    """A branch against the project's: its own commits (`ahead`) and the project's it lacks
    (`behind`) - None with no commit to count from, or past the ones counted -, whether it is
    joined (merged into the project's branch), its worktree's folder, and its last commit:
    short id, subject (the repository's words) and time. `ref`: its full name, as it is asked
    for (K-dallar); `remote`: a remote-tracking one, as last fetched."""

    name: str
    ref: str
    remote: bool
    ahead: int | None
    behind: int | None
    joined: bool
    worktree: str | None
    sha: str | None
    subject: str | None
    last_at: str | None


class GitReportOut(BaseModel):
    """What an agent said it did in git (report_git), and whether git shows it now."""

    agent: str
    branch: str | None
    worktree: str | None
    commits: int | None
    merge_into: str | None
    why: str | None
    at: datetime | None
    seen: bool


class GitOut(BaseModel):
    """The project's git, read only (slice 70): its branch ("" where HEAD is on none), how
    many files are changed and not committed, its worktrees and other branches, what
    agents said with report_git, and whether what is taken from a copy is offered for a
    commit (the project's setting)."""

    branch: str
    changed: int
    worktrees: list[GitWorktreeOut]
    branches: list[GitBranchOut]
    # The project's own branch, with its last commit; None on no branch, or with no commit.
    current: GitBranchOut | None
    reports: list[GitReportOut]
    commit: bool
    # K-dallar: why the git map cannot switch the branch now, in words; None: it can.
    switch_blocked: str | None


class GitChangeOut(BaseModel):
    """A file changed in the working tree and not committed, for the Workspace's Changes tab
    (K-degisenler): its path from the project, and git's letter - M, A, D, R (by its new
    path), ? untracked."""

    path: str
    status: Literal["M", "A", "D", "R", "?"]


class FileHistoryOut(BaseModel):
    """One of the last works on a file of the project (K-devir-4): the agent, when, what it
    did and whether that is in the project, in `handoff._STATUS`'s words."""

    at: datetime
    agent_id: str
    agent_role: str
    agent_name: str
    conversation_id: str
    conversation_title: str
    kind: Literal["create", "modify", "delete"]
    status: str


class HandedOut(BaseModel):
    """B-366: one of the agents whose work an agent's briefing carried (`Agent.handed_from`),
    with its name and its chat - one of another chat too, which that chat's page does not hold."""

    agent_id: str
    agent_role: str
    agent_name: str
    conversation_id: str
    conversation_title: str
    at: datetime


class MergeSideOut(BaseModel):
    # When that side last changed the file; None where that is not known (no file).
    changed_at: datetime | None


class MergeSidesOut(BaseModel):
    """When each side last changed a file both changed: the project's file as the disk
    has it; the agent's last change to it as its record has it or, with none on record
    (a command's doing), as the copy's file has it. `newer`: which came last - shown,
    never acted on; None where one of the two is not known."""

    project: MergeSideOut
    agent: MergeSideOut
    newer: Literal["project", "agent"] | None


class MergeFileOut(BaseModel):
    """One file an agent changed in its working copy, against the project."""

    path: str
    kind: Literal["new", "changed", "deleted"]
    # "ready": can be taken; "merged": the project changed it too, on other lines - the
    # two went together, and that is what is taken; "conflict": the project's file
    # changed meanwhile and the two do not go together by themselves - the user says
    # which side is taken (`whole`); "applied": in the project; "refused": not taken,
    # and `note` says why; "left_out": of a copy with nothing to say what it was made
    # from - the file differs from the project's and is not offered at all (nothing
    # says the agent changed it).
    state: Literal["ready", "merged", "applied", "conflict", "refused", "left_out"]
    # From what the project holds to what would be taken: the copy's file; for "merged"
    # the two sides together; for a "conflict" of lines (`whole` false) what goes in
    # whichever side is chosen. None for a file that is not text, or too large to show.
    diff: str | None = None
    additions: int | None = None
    deletions: int | None = None
    note: str | None = None
    # Of a "conflict": True where the choice is between the two files as wholes (`note`
    # says why they were not merged line by line), False where only the same lines
    # clash and the rest of both sides is kept either way. None for any other file, and
    # for one of a copy that is compared with the project alone (`two_way`).
    whole: bool | None = None
    # Of a "conflict" of lines: the lines that clash, as a diff from the project's lines
    # ("-") to the agent's ("+").
    clash: str | None = None
    # Of a "conflict": when each side last changed the file.
    sides: MergeSidesOut | None = None
    # Of a file whose sides clashed: whose the user took. None for any other file.
    chose: Literal["agent", "project"] | None = None
    # Of a kept copy with nothing to say what it was made from: the file differs from the
    # project's as it is now, and which of the two changed is not known. (True or absent.)
    two_way: bool | None = None
    # The digests of the project's file and the copy's that what is shown was made of: an
    # Apply sends them back, and takes nothing where one moved since (`MergeChoices`).
    shown: list[str | None] | None = None


class MergeCheckOut(BaseModel):
    """How the project's check command went, run in the agent's working copy on what was
    about to be taken. "not_run": it has not run (`note` says why, where there is a
    reason); "passed": it ended with exit code 0 - nothing else is; "failed": any other
    end, also one that never started or was cut short (`exit_code` is then None)."""

    command: str
    state: Literal["not_run", "running", "passed", "failed"]
    exit_code: int | None = None
    # The end of what it wrote.
    output: str | None = None
    note: str | None = None
    # The files moved after it ran: the result is of an earlier state.
    stale: bool = False


class MergeCommitOut(BaseModel):
    """The commit of the files that were taken: "offered" to the user, or "committed" by
    their own click (`sha`) - or "not_offered", with why as its `message` (the project is
    a subfolder of a repository). `holds`: of a made commit, what `git show --stat` says it
    holds; None before it is made, and where git did not say. `asks`: what of git's own an
    agent changed in the turn ("hooks", "config") - the commit waits for the user to say
    with them or without (K-yazma-denetimi); None: nothing is asked. `notes`: of a made
    commit, what did not go in as the agent's change alone, a sentence each - a file that
    went in whole, one left out and why, what a commit hook changed, an index git would not
    set (`git.commit`)."""

    state: Literal["offered", "committed", "not_offered", "pull_request"]
    message: str
    sha: str | None = None
    # D2, "pull_request": the pull request's address; what was pushed is `sha`, as `pushed`.
    url: str | None = Field(None, exclude_if=lambda value: value is None)
    pushed: str | None = Field(None, exclude_if=lambda value: value is None)
    # (B-319: not "summary", the working tree's stat an older row has - it counted the
    # user's own edits too.)
    holds: str | None = None
    asks: list[Literal["hooks", "config"]] | None = None
    notes: list[str] | None = None


class MergeBranchOut(BaseModel):
    """K-dal-takim: a line's work on its own git branch, on its way into the project's: the
    branch, the one it merges into (None where git did not say), the files both changed that
    git does not put together, the user's files in the way (uncommitted where the branch
    changes them, or any staged), and why git did not say or merge. Merge waits while any.
    D2: `resolve`, an agent may be asked to put the conflicts together (in the branch's
    worktree); `way`, "pull_request" where the project's finished work goes as one;
    `ask_way`, the card asks which way (the project's first finished branch with a GitHub
    remote) - `pr_off`, why a pull request cannot be chosen now."""

    name: str
    into: str | None = None
    conflicts: list[str] = Field(default_factory=list)
    dirty: list[str] = Field(default_factory=list)
    note: str | None = None
    resolve: bool | None = Field(None, exclude_if=lambda value: not value)
    way: Literal["pull_request"] | None = Field(None, exclude_if=lambda value: value is None)
    ask_way: bool | None = Field(None, exclude_if=lambda value: not value)
    pr_off: str | None = Field(None, exclude_if=lambda value: value is None)


Side = Literal["agent", "project"]


class MergeChoices(BaseModel):
    """For each file whose two sides clash, by its path: whose is taken - the agent's
    ("agent") or the project's ("project"). `shown`: of Apply, each file the card showed,
    by path, as its `shown` - where one is not as the card has it now, nothing is taken.
    None (a Take in that shows no files): as the card was last shown - and choices
    without it are refused (a page from before `shown`). As many as a copy has files."""

    choices: dict[str, Side] = Field(default_factory=dict, max_length=copies.MAX_FILES)
    shown: dict[str, list[str | None]] | None = Field(default=None, max_length=copies.MAX_FILES)
    # D2, of a branch's Merge: keep the branch after it ("Keep this branch after merging") -
    # and, where the card asks which way finished work goes, the user's choice, saved to the
    # project (a pull request is their consent to push its branches).
    keep_branch: bool = False
    way: FinishWay | None = None


class MergeCommitIn(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    # Where it `asks` (MergeCommitOut): with git's hooks, or without them.
    hooks: Literal["with", "without"] | None = None

    @field_validator("message")
    @classmethod
    def _said(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("a commit message has to say something")
        return value.strip()


class MergeOut(Out):
    """An agent's working copy on its way into the project. "pending": the user is
    asked; "rejected": they turned it down; "discarded": nothing was taken and nobody
    was asked (a turn nobody watched, or one that was stopped); "kept": it broke off (its
    turn ended, or a restart) and the copy waits on disk for Take in or Discard - each
    file's `note` says where; "interrupted": it broke off with no folder on record."""

    id: str
    run_id: str
    agent_id: str
    status: Literal["pending", "applied", "rejected", "discarded", "kept", "interrupted"]
    files: list[MergeFileOut]
    # The folder a kept copy is in ("kept"), until it is decided; None otherwise.
    kept_in: str | None = None
    # None: the project has no check command - nothing was checked.
    check: MergeCheckOut | None = None
    # None: no commit of what was taken is offered.
    commit: MergeCommitOut | None = None
    # None: a copy's, taken in file by file.
    branch: MergeBranchOut | None = None
    # The room whose one copy this is; None: an agent's own.
    room_id: str | None = None
    created_at: datetime
    decided_at: datetime | None

    @model_validator(mode="after")
    def _kept(self) -> "MergeOut":
        # B-359: on record a kept copy is "interrupted" with its folder (`kept_on_record`); the
        # page calls it kept, and so does the API.
        if self.status == "interrupted" and self.kept_in:
            self.status = "kept"
        return self


Failure =Literal["rate_limited", "credits_exhausted", "signed_out", "cli_crashed", "empty_output",
                  "other"]


class AskedModel(BaseModel):
    """A model KOLONİ itself asked something: the one a lead's "how hard is this message"
    goes to, or the summariser that made a note of what a turn found."""

    provider_name: str
    model_id: str


class FindingOut(BaseModel):
    """One line of a report's Findings section (slice 84c), for the role that should take it."""

    what: str
    kind: Literal["code", "ui", "security", "docs", "test", "data", "other"]
    # An existing role's name, as the role spells it; None where none was named or known.
    role: str | None
    # B-192: false for a suggestion, which sends no work back (one from before is blocking).
    blocking: bool = True


class AgentSkills(BaseModel):
    given: list[str]
    left_out: dict[str, str]
    # R190: those given whole in its instructions (it could not call use_skill), not to read.
    in_brief: list[str] = []


class AgentOut(Out):
    id: str
    run_id: str
    parent_agent_id: str | None
    tool_call_id: str | None
    provider_name: str | None
    model_id: str | None
    # "settings": the name was read from the CLI's own settings, not reported by it. "auto":
    # Copilot's auto picked it (the agent asked for auto; why is in `effort_note`).
    model_from: str | None
    # How its provider ran when it was opened (a CLI's mode); None for an API, and for
    # an agent from before this was put on record.
    provider_mode: str | None
    # Its CLI keeps what it is sent itself (`Agent.compacts_itself`): no Compact now for it.
    compacts_itself: bool
    # The agent that opened it picked this model from the team guide.
    chosen: bool
    # Why, in that agent's own words (one sentence): to be shown as its words, not as
    # KOLONİ's. None where the model was no pick, and where nobody gave a reason. On a
    # lead (which nobody opened): how hard a fast model said the message is, where the
    # conversation has its lead's model follow that ("hard: ...") - a model's guess.
    chosen_why: str | None
    # The tier the user gave the model it was opened on; None where it has none.
    tier: Tier | None
    # A lead whose model follows the message: who was asked how hard it is. With no
    # `chosen_why` beside it, nothing came of the question and the lead ran where it
    # otherwise would. None: nobody was asked (and for a lead from before this).
    asked_how_hard: AskedModel | None
    role_name: str
    name: str
    tools: list[str]
    # The MCP servers (their names) it may use.
    mcp: list[str]
    task: str | None
    depth: int
    status: AgentStatus
    report: str | None
    error: str | None
    # K-devam-butce: the steps it was given on top of its limits, told to go on with none left.
    steps_given: int
    # Why its model failed, as the provider itself said, and when that limit resets.
    failure: Failure | None
    failure_resets_at: datetime | None
    input_tokens: int | None
    output_tokens: int | None
    # Of all its steps sent: what its provider said was read again from the cache and
    # written to it. None where the provider said nothing of it - not a zero.
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    # What Copilot said it spent in its own units: AI credits in billionths, premium requests.
    nano_aiu: int | None
    premium_requests: float | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    # The ids of the core records of the project's memory it was given when it started.
    # None for an agent from before there was a memory: that is not on record.
    facts_given: list[str] | None
    # The agent of an earlier turn of the same topic it goes on from (for a lead, the
    # lead of the topic's turn before); None for one that starts clean.
    continues_id: str | None
    # Set while its status is "blocked": what it waits for. It asks nothing of the user.
    waiting_for: WaitingForOut | None
    # While it is "queued" because its provider is full: which, and n of n at work there.
    queued_on: QueuedOnOut | None = None
    # Where it changes files, once it has changed one; None: in the project. ("copy" on
    # the wire: the name is taken in a model class.)
    copy_: CopyOut | None = Field(validation_alias="copy", serialization_alias="copy")
    # What was counted of its own tool calls, the last time it reached 3; None: nothing.
    sign: SignOut | None
    # When it last took a model step or a tool of its started or ended; None: neither yet.
    last_event_at: datetime | None
    # What the Observer's model said of its report: an opinion, at most three sentences,
    # signed by `observed_by`. None, with `observation_note` saying why, where it said
    # nothing; all three None where nobody was asked.
    observation: str | None
    observation_note: str | None
    observed_by: AskedModel | None
    # The reasoning level its model steps were sent; None: none was (the model's own).
    effort: Effort | None
    # Why no level went from some step on: its service refused the one it was sent.
    effort_note: str | None = None
    # The last step asked again after a short failure of its provider, and why.
    retry_note: str | None = None
    # The window it was measured against (its role's, else its model's as found); None:
    # unknown. How many messages of what it is sent were summarised (the record is not),
    # the latest summary, and why one could not be made.
    context_window: int | None
    summarised: int
    summary: str | None
    summary_note: str | None
    # What its report's Findings section said; []: none; None: it had no such section.
    findings: list[FindingOut] | None = None
    # Whether a model is still to read what the user writes for it (`Agent.summary_correctable`):
    # the page also leaves it alone where a later agent goes on from it (`continues_id`).
    summary_correctable: bool
    # K-devir: a sub-agent's reads before its first write (None: not counted), and the ids
    # of the ended agents whose work its briefing carried (None: nothing was).
    rediscovery: int | None = None
    handed_from: list[str] | None = None
    # K-skill-uyum: the role's skills it started with, and those left out with why.
    skills: AgentSkills | None = None


class Compaction(BaseModel):
    """The % of its window past which an agent KOLONİ compacts is summarised: one setting
    of the whole app (`agent.COMPACT_AT`)."""

    model_config = ConfigDict(extra="forbid")
    compact_at: int = Field(ge=50, le=95, strict=True)


class StepLimit(BaseModel):
    """B-398: the most steps one agent takes on a job (`limits_mixin.app_steps`): one setting of
    the whole app. A role's own limit, where nearer, still holds."""

    model_config = ConfigDict(extra="forbid")
    max_steps: int = Field(ge=5, le=200, strict=True)


class Unattended(BaseModel):
    """B-413: a turn nobody watches ends where nothing real moved for `stuck_minutes`, and a
    night's job or a To-do task's turn after `turn_hours` (`away.unattended`): settings of the
    whole app. Their ranges are `away.STUCK_RANGE` and `CEILING_RANGE`, written again here and
    in Settings.tsx. Sent one at a time - the one not sent stays as it is; `turn_hours` null is
    no ceiling."""

    model_config = ConfigDict(extra="forbid")
    stuck_minutes: int | None = Field(None, ge=5, le=1440, strict=True)
    turn_hours: int | None = Field(None, ge=1, le=72, strict=True)


class TreeLimits(BaseModel):
    """The most files and MB a repository or a folder on this machine may hold to be learned
    (`knowledge.tree_limits`): one setting of the whole app. Its ranges are `knowledge.FILES_RANGE`
    and `MB_RANGE`, written again here (that module imports this one) and in Settings.tsx; a test
    holds these two equal. Sent one at a time - the one not sent stays as it is."""

    model_config = ConfigDict(extra="forbid")
    max_files: int | None = Field(None, ge=100, le=1_000_000, strict=True)
    max_mb: int | None = Field(None, ge=1, le=10_240, strict=True)


class AnswerLanguage(BaseModel):
    """K-cevap-dili: the language every agent writes in, one setting of the whole app; null is
    Auto (`memory.answer_in`)."""

    model_config = ConfigDict(extra="forbid")
    answer_in: str | None = Field(default=None, max_length=200)

    @field_validator("answer_in")
    @classmethod
    def _a_language(cls, value: str | None) -> str | None:
        from app.memory import language_name  # (not loaded with the schemas: it loads them)

        return language_name(value)


class TellIn(BaseModel):
    """The user's own word to an agent while it works (89d C)."""

    model_config = ConfigDict(extra="forbid")
    words: str = Field(min_length=1, max_length=4000)


class SummaryIn(BaseModel):
    """The user's words for an agent's working state, in the place of its summary."""

    model_config = ConfigDict(extra="forbid")
    # (A summary is at most SUMMARY_MOST tokens: far fewer characters than this.)
    summary: str = Field(min_length=1, max_length=40_000)
    # Its `summarised` when the user began to edit: a summary made since is not written over.
    summarised: int

    @field_validator("summary")
    @classmethod
    def _said(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("a working state has to say something")
        return value.strip()


class RawLine(BaseModel):
    n: int  # counted from 1 for the agent, over all the runs of its CLI
    # stdin: what KOLONİ sent it, where that is what to see (B-343: Codex's turn/start, its level)
    stream: Literal["stdout", "stderr", "stdin"]
    text: str


class RawOut(BaseModel):
    """What an agent's CLI wrote itself, as it is kept in memory (`app.raw`)."""

    # False for an agent whose model is not a CLI: it has no raw stream.
    available: bool
    # The oldest of those asked for, in order: one answer carries only so many.
    lines: list[RawLine]
    # How many of its earlier lines are no longer kept.
    dropped: int
    # Later lines than these are kept: asked for with the number of the last of these.
    more: bool


class BoardAgent(BaseModel):
    """An agent whose work is going on, as the project's board shows it."""

    id: str
    name: str
    # An agent's status - or "waiting_approval": it waits for the user's word.
    status: AgentStatus | Literal["waiting_approval"]
    role: str
    provider_name: str | None
    model_id: str | None
    # The files of the project it holds now, as paths inside it.
    holds: list[str]
    copy_: CopyOut | None = Field(validation_alias="copy", serialization_alias="copy")
    # What its own working copy changed so far (slice 70); None: it has none.
    changed: CopyCountOut | None = None
    waiting_for: WaitingForOut | None
    # As on its record (`AgentOut`); `in_tool`: a tool of its runs now.
    sign: SignOut | None
    last_event_at: datetime | None
    in_tool: bool
    # Of what it asks now, by kind: changes it waits for a yes on, and its questions. What
    # else it may ask (a command, a sub-agent, a folder) is in neither.
    changes_to_approve: int
    questions: int


class BoardOutcome(BaseModel):
    """How a sub-agent of a turn came out (K-board-sonuc): "nothing" - it finished having done
    and said nothing; "timed_out", "silent" (its stall timer cut it) or "error"."""

    id: str
    name: str
    role: str
    provider_name: str | None
    model_id: str | None
    status: AgentStatus
    outcome: Literal["nothing", "timed_out", "silent", "error"]
    # "Re-run the ones that failed" opens it again: it failed, and was not opened again since.
    rerun: bool


class BoardTurn(BaseModel):
    id: str
    status: RunStatus
    started_at: datetime | None
    ended_at: datetime | None
    # Its agents that started, and the model its Lead ran on (None: not known).
    agents: int
    provider_name: str | None
    model_id: str | None
    # In + out of every agent of it that started, as its chat's summary adds them up; None
    # when one of them did not say.
    tokens: int | None
    # It wrote a plan that waits for the user's yes or no (slice 49).
    plan_waits: bool
    # Its sub-agents that ended with a class (`app.api.board.outcome`), oldest first.
    outcomes: list[BoardOutcome] = []


class BoardConversation(BaseModel):
    conversation_id: str
    title: str
    agents: list[BoardAgent]
    # Its agents' changes that wait for the user's decision (a merge card in its chat).
    merges_pending: int
    # Its last turn; None before its first.
    turn: BoardTurn | None
    # The folder it is in (None: a chat with none): every chat's board tags another's (B-72).
    project_id: str | None = None


class BoardWho(BaseModel):
    conversation_id: str
    agent_name: str


class BoardConflict(BaseModel):
    """A file an agent of one conversation holds and agents of another wait for."""

    path: str
    holder: BoardWho
    waiting: list[BoardWho]


class BoardOut(BaseModel):
    """Every conversation of a project and its agents at work, at one look."""

    # The project's limit on agents at work at once (None: none), and how many are.
    limit: int | None
    running: int
    conversations: list[BoardConversation]
    conflicts: list[BoardConflict]
    # What waits for the user on the project's backlog: tasks and changes agents proposed,
    # and tasks whose turn ended and wait for review (slice 52).
    backlog_waiting: int


class ChannelMessageOut(Out):
    id: str
    run_id: str
    from_agent_id: str
    to_agent_id: str
    kind: Literal["task", "report", "message", "reply", "note", "findings"]
    content: str
    created_at: datetime


class LearnWith(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(max_length=32)
    model_id: str = Field(min_length=1, max_length=200)


class Knowledge(BaseModel):
    """K-uzman: what an expert knows - each source an http(s) address, a path in the project
    (a file or a folder) or a topic to research ("research: <topic>"), checked by
    `app.knowledge.checked`; or only "code:", the project's code, scanned (K-bilgi 8)."""

    model_config = ConfigDict(extra="forbid")
    # Its folder's name: `.koloni/knowledge/<topic>/`. One line: it goes into agents' prompts.
    topic: str = Field(min_length=1, max_length=40)
    sources: list[Annotated[str, Field(min_length=1, max_length=2000)]] = Field(
        min_length=1, max_length=10)
    # A learning reads everything under its sources, at most this many pages (or files: a
    # safety cap), and spends at most this much on writing the guide where the model's price is
    # known (K-uzman-derin; migration 0136 raised the old default, 20).
    max_pages: int = Field(500, ge=1, le=1000, strict=True)
    max_usd: float = Field(0.5, gt=0, le=100, allow_inf_nan=False)
    # K-bilgi-repo: a repository's code files new to its guide a learning reads at most, the
    # most central first - the cap that holds where no price is known (a CLI, a plan); 0: no
    # guide to its code, its docs' and the free scan only.
    max_code_files: int = Field(100, ge=0, le=1000, strict=True)
    # A cheaper model it learns with; None: its own.
    learn_with: LearnWith | None = None
    # Pages a search found that the user took off its list: never read again.
    removed: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=200)
    # A guide from a topic to research is learned again once it is a week old, the next time the
    # expert is at work or a recipe's Learn step runs (no job of its own).
    weekly: bool = False
    # It may search the web while answering, where its guide and pages have no answer (each
    # search costs); asked as any search is. None (not said): an expert of a topic to research
    # does (`app.knowledge.checked`).
    search_answering: bool | None = None

    @field_validator("topic")
    @classmethod
    def _one_line(cls, topic: str) -> str:
        # (No control character nor line or paragraph separator - U+2028, U+0085 too; a space is)
        if not topic.isprintable():
            raise ValueError("a topic is one line of printable characters")
        return topic


class PendingRoleOut(BaseModel):
    """A role an agent asked to create and the user has not decided on yet."""

    tool_call_id: str
    run_id: str
    agent_id: str
    name: str
    description: str
    instructions: str
    tools: list[str]
    # K-uzman: what an expert asked for knows, and where it learns it.
    knowledge: Knowledge | None = None


class SkillFound(BaseModel):
    """A skill as it is listed, before or after it is kept."""

    name: str
    description: str
    # The first line of its licence file (or its SKILL.md's `license:`); None: unknown.
    license: str | None
    # Its SKILL.md, whole.
    text: str
    # Its files, "/" between folders, and all their bytes together: secrets are not among them.
    files: list[str]
    size: int
    scripts: list[str]
    # The folder it was taken from, its GitHub address with the commit (`...@<sha>`), or
    # "uploaded (<the chosen folder's name>)".
    source: str


class SeenOut(BaseModel):
    """What code says outright, read as text and never run (slice 92): never that it is safe."""

    read: int  # files read
    # What it may reach ("files", "programs", "network", "server", "system"): the modules.
    reaches: dict[str, list[str]]
    programs: list[str]
    addresses: list[str]
    env: list[str]
    # It reads its environment as a whole: every key in it.
    whole_env: bool
    # Where it hides what it does (eval, new Function, a module named while it runs):
    # what else is said of it cannot be trusted.
    hidden: list[str]
    unread: list[str]


class SkillPreview(SkillFound):
    """What the user is shown before a skill is added."""

    # Each script whole (a long one cut short): saying yes is agreeing to run them.
    script_texts: dict[str, str]
    # What is not copied: secrets, links, dependency folders ("/" at a folder's end).
    skipped: list[str]
    # One sum over what is kept: sent back on adding, it must still be the same.
    sha256: str
    # What its scripts say outright (`app.package_look.scan`).
    seen: SeenOut
    # The rules of `app.injection` its SKILL.md breaks: a warning, never a refusal.
    injection_rules: list[str] = []
    # Slice 92: its frontmatter's `allowed-tools`, as written (KOLONİ gives none of them).
    allowed_tools: list[str] = []
    # Files besides its scripts that run as programs (by their ending, or a #! line).
    programs: list[str] = []
    # Whether every file was read: from GitHub only SKILL.md, licence and scripts are before
    # the yes, so `programs` knows the others by their ending only.
    read_whole: bool = True
    # Its SKILL.md's !`command` lines (Claude Code runs them as the skill loads), at most 20.
    runs_as_it_loads: list[str] = []
    # How many fenced shell blocks its SKILL.md has: commands it tells an agent to run.
    shell_blocks: int = 0


class SkillNeeds(BaseModel):
    # KOLONİ's groups of tools (`app.skills.GROUPS`), MCP servers, and names not known.
    groups: list[str]
    mcp: list[str]
    unknown: list[str]
    # Each group's tools: a role holding one of them has the group.
    tools: dict[str, list[str]]


class SkillOut(SkillFound):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # The stored copy, which no agent writes.
    folder: str
    scripts_run_unasked: bool
    # K-skill-uyum: off on the Tools page, it is given to no role.
    enabled: bool

    @computed_field
    @property
    def needs(self) -> SkillNeeds:
        """What its `allowed-tools` asks of a role (`app.skills.needs`)."""
        found = skill_needs(self.text)
        return SkillNeeds.model_validate(
            {**found, "tools": {group: list(SKILL_GROUPS[group]) for group in found["groups"]}})

    @computed_field
    @property
    def version(self) -> str | None:
        """Its SKILL.md's `version:`, where it says one."""
        return skill_front(self.text)[0].get("version") or None


class SkillFile(BaseModel):
    # Relative, "/" between folders (the chosen folder's name first, or not).
    path: str = Field(max_length=4096)
    data: str = Field(max_length=MAX_ENCODED)  # base64


class SkillUpload(BaseModel):
    """A skill uploaded from the app's page (slice 45b): exactly one of them."""

    # (room beyond a skill's files for the secrets and links it leaves out; the page sends no
    # .git or node_modules)
    files: list[SkillFile] | None = Field(default=None, max_length=5 * MAX_FILES)
    zip: str | None = Field(default=None, max_length=MAX_ZIP_ENCODED)  # a .zip, base64

    @model_validator(mode="after")
    def _one(self):
        if (self.files is None) == (self.zip is None):
            raise ValueError("upload either files or a .zip")
        return self


class SkillIn(BaseModel):
    # Exactly one: a folder of this machine, a public GitHub repository (or a folder in it),
    # or one uploaded from the app's page (never the Lead's: `add_skill` takes the first two).
    folder: str | None = Field(default=None, max_length=4096)
    github: str | None = Field(default=None, max_length=2048)
    upload: SkillUpload | None = None
    # The user's leave for its scripts to run without asking: on, unless taken away.
    scripts_run_unasked: bool = True
    # The preview's sum: when sent, what is added must still be what was shown.
    sha256: str | None = Field(default=None, max_length=64)
    # The user's yes to replacing the skill of its name: the roles that have it keep it.
    replace: bool = False


class SkillPatch(BaseModel):
    scripts_run_unasked: bool | None = None
    enabled: bool | None = None


class PendingSkillOut(SkillPreview):
    """A skill an agent asked to add, and the roles to give it, not decided on yet."""

    tool_call_id: str
    run_id: str
    agent_id: str
    roles: list[str]


class DiscussionMemberOut(Out):
    agent_id: str
    status: Literal["in", "left"]
    opened_here: bool


class DiscussionOut(Out):
    id: str
    run_id: str
    agent_id: str
    tool_call_id: str
    topic: str
    max_rounds: int
    round: int
    status: Literal["running", "ended", "cancelled", "interrupted"]
    outcome: Literal["agreed", "round_limit", "ended_by_user", "too_few", "budget"] | None
    created_at: datetime
    ended_at: datetime | None
    members: list[DiscussionMemberOut]


class DiscussionPostOut(Out):
    id: str
    discussion_id: str
    agent_id: str | None
    round: int
    kind: Literal["said", "left"]
    content: str
    passed: bool
    created_at: datetime


class DiscussionPostIn(BaseModel):
    content: str = Field(max_length=1500)


class RoomMemberIn(BaseModel):
    role: str = Field(max_length=60)
    # The provider (its name) and model the user gives this member; left out: its role's.
    provider: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=200)


class RoomBudgetIn(BaseModel):
    """What one room may spend. Left out: the conversation's own. Null: no limit."""

    posts: int | None = Field(default=None, ge=1, le=MAX_ROOM_POSTS)
    tokens: int | None = Field(default=None, ge=1, le=MAX_ROOM_TOKENS)
    minutes: int | None = Field(default=None, ge=1, le=MAX_ROOM_MINUTES)


class RoomIn(BaseModel):
    goal: str = Field(max_length=4000)
    # (`with` on the wire: the word is taken in Python.)
    members: list[RoomMemberIn] = Field(alias="with", min_length=2, max_length=6)
    budget: RoomBudgetIn | None = None
    # The user's word to open it though the project is over this month's budget.
    over_budget: bool = False


class RoomMoreIn(BaseModel):
    """What is added to a running room's budget; a limit it does not have stays none."""

    posts: int | None = Field(default=None, ge=1, le=MAX_ROOM_POSTS)
    tokens: int | None = Field(default=None, ge=1, le=MAX_ROOM_TOKENS)
    minutes: int | None = Field(default=None, ge=1, le=MAX_ROOM_MINUTES)


class RoomBudgetOut(BaseModel):
    """A room's limits (None: none) - or, as `spent`, how much of each is used."""

    posts: int | None
    tokens: int | None
    minutes: float | None


class RoomMemberOut(BaseModel):
    # None until its agent is opened, right after the room is.
    agent_id: str | None
    role: str
    # "waiting": for a post. "done": its work is over. "left": it failed.
    status: Literal["in", "waiting", "done", "left"]


class RoomOut(BaseModel):
    """Two to six agents working on one goal at the same time, in one working copy."""

    id: str
    run_id: str
    goal: str
    # The agent that opened it; None: the user did.
    agent_id: str | None
    # "sharing": its members share the work out, a step each, before they start.
    status: Literal["sharing", "working", "ended", "cancelled", "interrupted"]
    # "ended_by_opener": the agent that opened it ended it (K-oda-lead).
    outcome: Literal["agreed", "budget", "ended_by_user", "ended_by_opener", "too_few"] | None
    # Which of its reasons: the limit of a room that ended at its budget; "unanswered" for
    # one that ended "too_few" because a question was left with nobody to answer it.
    why: Literal["posts", "tokens", "minutes", "unanswered"] | None
    budget: RoomBudgetOut
    # Posts by its members; tokens as their models reported them (None: none of them
    # reported any); the minutes its clock has counted.
    spent: RoomBudgetOut
    # What it came to, in a line: the sentence its opener ended it with, else its done items'
    # first lines (`app.room.summary`); None: none.
    summary: str | None
    # 29c: the user paused it - its members take no step and post nothing until Resume.
    paused: bool
    # K-oda-izle: whether the turn's Lead follows the room the user opened - or, R178, its agent
    # opener follows the room it opened (`Room.lead_follows`).
    lead_follows: Literal["off", "on", "stopped"]
    members: list[RoomMemberOut]
    created_at: datetime
    ended_at: datetime | None


class RoomItemOut(Out):
    id: str
    room_id: str
    number: int
    title: str
    paths: list[str]
    # Who has it - or had it when it was finished or dropped. None: nobody's.
    holder_agent_id: str | None
    status: Literal["open", "taken", "done", "dropped"]
    result: str | None
    created_at: datetime


class RoomPostOut(Out):
    id: str
    room_id: str
    number: int
    # None: the user's.
    agent_id: str | None
    # "said": the user's. "done" and "left" are KOLONİ's own, for a member whose work is
    # over (with its last words) or that failed.
    # "ended": the opener's sentence of what came of it, as it ended it (K-oda-lead).
    type: Literal["result", "review", "question", "answer", "blocked", "said", "done", "left",
                  "ended"]
    text: str
    to_agent_id: str | None
    reply_to: int | None
    # A question nobody has replied to yet.
    open: bool
    created_at: datetime


class RoomPostIn(BaseModel):
    text: str = Field(max_length=1500)


class RoomOpenedOut(BaseModel):
    run: RunOut
    room: RoomOut


class ViewOut(BaseModel):
    """A file of the conversation to be seen beside the chat (slice 39, `app.views`): one
    an agent wrote, or one it put before the user with `show`."""

    id: str
    path: str
    kind: Literal["html", "svg", "md", "image", "model", "drawio", "pdf", "docx", "xlsx", "pptx"]
    agent_id: str | None
    # The change's own state, or "shown": a file of the project as it now is.
    status: Literal["proposed", "approved", "in_copy", "applied", "shown"]
    # Of what is shown now; None where that is not known (no such file, or too large).
    sha: str | None
    note: str | None
    # Larger than is served (5 MB; a model 50 MB): listed, not shown.
    too_large: bool
    # What the panel's frame loads: the app's own address.
    url: str
    at: datetime


class BoardPostOut(BaseModel):
    """A note on a turn's shared notebook; `agent_id` is None for the user's."""

    id: str
    run_id: str
    agent_id: str | None
    content: str
    seq: int
    created_at: datetime
    # The agents that were handed it, in the order they were.
    read_by: list[str]
    # Its team's notebook (id, and name as it was then); None: the whole turn's.
    team_id: str | None
    team: str | None
    # A team lead's note for every team.
    everyone: bool
    # KOLONİ's continuation note, written as the turn ended (G7).
    koloni: bool


class BoardPostIn(BaseModel):
    content: str = Field(max_length=1500)


class QuestionOut(Out):
    id: str
    run_id: str
    agent_id: str
    tool_call_id: str
    question: str
    options: list[str]
    # KOLONİ's own question, not the agent's: leave for a tool. Its options are the only
    # answers there are.
    leave: bool
    status: Literal["pending", "answered", "cancelled", "interrupted", "superseded"]
    answer: str | None
    created_at: datetime
    answered_at: datetime | None
    # The Lead answered it while the user was away, and why; None: it did not. When the user
    # said OK to that; None: not yet (it is under "Decided for you").
    lead_why: str | None
    seen_at: datetime | None


class AnswerIn(BaseModel):
    answer: str = Field(max_length=4000)


class WarningOut(BaseModel):
    """Text from outside that read like orders to an agent (`app.injection`): the rule and
    where it came from, never the text."""

    id: int
    run_id: str | None
    rule: str
    # How far it is trusted: `app.injection.SEVERITY` (a webhook's is the highest).
    source: Literal["webhook", "web", "mcp", "agent"]
    where: str
    # The agent whose context it went into; None: a webhook's turn, before its Lead.
    agent_id: str | None
    call_id: str | None
    false_alarm: bool
    # How often the user has said this rule was wrong, in any chat.
    false_alarms: int


class SnapshotOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
    runs: list[RunOut]
    topics: list[TopicOut]
    tool_calls: list[ToolCallOut]
    file_changes: list[FileChangeOut]
    commands: list[CommandOut]
    allowed_commands: list[AllowedCommandOut]
    # The searches and requests that were asked about, and what is allowed without asking.
    web_requests: list[WebRequestOut]
    allowed_web: list[AllowedWebOut]
    agents: list[AgentOut]
    channel_messages: list[ChannelMessageOut]
    pending_roles: list[PendingRoleOut]
    pending_skills: list[PendingSkillOut]
    questions: list[QuestionOut]
    discussions: list[DiscussionOut]
    discussion_posts: list[DiscussionPostOut]
    rooms: list[RoomOut]
    room_items: list[RoomItemOut]
    room_posts: list[RoomPostOut]
    board_posts: list[BoardPostOut]
    # The files of the project held right now, by agents of any of its conversations.
    claims: list[ClaimOut]
    # The working copies of this conversation's agents that were, or are to be, taken
    # into the project.
    merges: list[MergeOut]
    # The files added to its messages, and those added to the next one, not sent yet.
    attachments: list[AttachmentOut] = []
    # The "While you're away" cards its Lead put here, with their nights (slice 106).
    away: list["AwayOut"] = []
    # The triggers its agents proposed, decided or not (slice 69).
    trigger_proposals: list["TriggerProposalOut"] = []
    # K-bilgi 6: the "Add to Project notes?" offers under its turns, decided or not.
    notes_offers: list["NotesOfferOut"] = []
    warnings: list[WarningOut] = []
    last_event_id: int


class PostMessageOut(BaseModel):
    message: MessageOut
    run: RunOut


def _words(value: str, most: int, what: str, empty: bool = False) -> str:
    """A kind of work or a team's name: one printable line, tidy spacing, 1 to `most` long
    (`empty`: or none, said elsewhere)."""
    value = " ".join(value.split())
    if not (value or empty) or len(value) > most or not value.isprintable():
        raise ValueError(f"{what} is 1 to {most} printable characters")
    return value


# A role's category, by its key (slice 63b).
Kind = Annotated[str, AfterValidator(lambda value: _words(value, 40, "a kind of work"))]
CategoryName = Annotated[str, AfterValidator(lambda value: _words(value, 40, "a category's name"))]
# A category's colour: a name each theme draws its own way (the Agents page's `--cat-<name>`). The
# four built-in categories, made by migration 0079, are violet, amber, green and blue.
Colour = Literal["violet", "amber", "green", "blue", "rose", "teal", "brown", "olive"]


class CategoryOut(Out):
    key: str
    name: str
    colour: Colour


class CategoryIn(BaseModel):
    name: CategoryName
    colour: Colour


class CategoryPatch(BaseModel):
    # Each left out: kept.
    name: CategoryName | None = None
    colour: Colour | None = None


class CategoryOrder(BaseModel):
    # Every category (keys), each once, in its new order.
    order: list[str] = Field(max_length=200)


# Room left for its lead's name, "<team> lead", which is a role's (60 at most).
TeamName = Annotated[str, AfterValidator(lambda value: _words(value, 55, "a team's name"))]
StageName = Annotated[str, AfterValidator(lambda value: _words(value, 60, "a stage's name"))]


class TeamIn(BaseModel):
    name: TeamName


class TeamPatch(BaseModel):
    # Each left out: kept.
    name: TeamName | None = None
    lead_on: bool | None = None
    lead_may_pick: bool | None = None
    # Null takes it away (left out: kept).
    default_recipe_id: str | None = None


class StageIn(BaseModel):
    name: StageName


class StagePatch(BaseModel):
    name: StageName | None = None
    together: bool | None = None


class StageOrder(BaseModel):
    # Every stage of the team (ids), each once, in its new order.
    order: list[str] = Field(max_length=200)


class Placed(BaseModel):
    stage_id: str


class LearnIn(BaseModel):
    project_id: str


class KnowledgeCopyIn(BaseModel):
    # From the project it was learned in, to another of the user's.
    project_id: str
    to_project_id: str
    # A guide there already is replaced (the page asks first).
    replace: bool = False


class LearnedPage(BaseModel):
    source: str
    read: bool
    why: str | None
    # Found by a search (a topic to research): the user can take it off the list.
    found: bool = False
    # A repository's code file (K-bilgi-repo), not one of its docs.
    code: bool = False


class LearnedCode(BaseModel):
    """K-bilgi-repo: what a repository's code came to - its files scanned (no model) and their
    names, its code files ranked for the guide, those in it, those read and left for the money,
    and what stopped the reading (None: nothing - all of them are in)."""

    scanned: int
    symbols: int
    ranked: int
    in_guide: list[str] = []
    left: list[str] = []
    stopped: str | None = None


class LearnedAdded(BaseModel):
    text: str
    source: str


class LearnedCost(BaseModel):
    amount: float
    currency: str


class Learned(BaseModel):
    learned_at: str
    model: str
    pages: list[LearnedPage]
    # Pages and files left unread for its page limit or its tries.
    unread: int = 0
    # How many of the pages read the guide was written from (the money limit, the size).
    guide_from: int
    # Characters of the pages read that are in none of its sections yet (its money limit): what
    # Learn more writes.
    left: int = 0
    # The money limit paid for one request only (no section and the map): what it is to be
    # raised to at least, in USD, to read further. None: it was not short.
    short: float | None = None
    # None: not known (no price, or a plan or a CLI).
    cost: LearnedCost | None
    # How many of the guide's entries have each label (official, single source, unsure).
    labels: dict[str, int] | None = None
    # What it found while answering and was told to keep, in the guide as a single source.
    added: list[LearnedAdded] = []
    # K-bilgi 8: the names a scan of the project's code found (its files: `guide_from`); None:
    # not a scan.
    symbols: int | None = None
    # K-bilgi 5: how many of its pages or files changed since the learning before (read again,
    # gone); None: not known (its first learning, or one before this was counted).
    changed: int | None = None
    # K-bilgi 7: what its guide was asked as a click's learning ended and could not answer from
    # its pages (`knowledge.measure`); None: not measured.
    unknown: list[str] | None = None
    # K-bilgi-repo: a repository's code (`LearnedCode`); None: not a repository.
    code: LearnedCode | None = None


class NotesAnswerIn(BaseModel):
    """K-bilgi 6: the user's word on a Project notes offer: the lines its card showed, and those of
    them ticked - none is Not now."""

    model_config = ConfigDict(extra="forbid")
    lines: list[Annotated[str, Field(max_length=2000)]] = Field(max_length=50)
    add: list[Annotated[str, Field(max_length=2000)]] = Field(max_length=50)


class NotesOfferOut(BaseModel):
    """K-bilgi 6: what turns found for the project's Project notes, on a card under the turn whose
    chat shows it until the user's word (`NotesAnswerIn`) - which never held it."""

    id: str
    run_id: str | None
    # A line each, as its agents said it (their words, not KOLONİ's).
    lines: list[str]
    status: Literal["waiting", "added", "discarded"]
    answer: str | None


class KnowledgeStateOut(BaseModel):
    """An expert's knowledge in one project, for its Knowledge tab."""

    learning: bool
    # Why it is to be learned again (no guide yet, its sources changed, a file changed); None:
    # as fresh as KOLONİ can tell.
    stale: str | None
    # Why its last learning failed, since KOLONİ started.
    failed: str | None
    # `learned.json`: when, on what, what was read and skipped and why, what it cost.
    learned: Learned | None
    guide: str | None
    folder: str
    # Where the documents are of another major version than the project's manifest asks for
    # ("docs are for v2, the project has v1.4").
    version_warning: str | None = None
    # What the next learning that adds to the guide costs at most, in USD (`knowledge.estimate`);
    # None: not known (a CLI, a plan, a model with no price).
    estimate: float | None = None
    # How many requests that learning makes at most (`knowledge.requests`): said where its cost
    # is not known. None: none learned yet.
    requests: int | None = None
    # B-372: what Try it answers on ("<provider> · <model>"), found without asking a model, and
    # whether that provider is paid per token; or why none can answer. All None: no model
    # answers it (a scan of the code), or not said here.
    answers_on: str | None = None
    per_token: bool | None = None
    answers_refused: str | None = None


KnowsMode = Literal["full", "map"]


class KnowsOut(BaseModel):
    """K-bilgi: a knowledge a role uses: in full (an expert in it) or as a map."""

    knowledge_id: str
    mode: KnowsMode
    topic: str
    # None: every project's.
    project_id: str | None


class KnowsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: KnowsMode


class KnowledgeUser(BaseModel):
    role_id: str
    name: str
    mode: KnowsMode


class KnowledgeOut(BaseModel):
    """K-bilgi: a knowledge on the project's Knowledge page, and how it stands there."""

    id: str
    # None: in every project (an expert's from before the Knowledge page).
    project_id: str | None
    knowledge: Knowledge
    used_by: list[KnowledgeUser]
    state: KnowledgeStateOut


class TryIn(BaseModel):
    project_id: str
    question: str = Field(min_length=1, max_length=2000)


class TryOut(BaseModel):
    answer: str


class PreferredModel(BaseModel):
    """One of a role's preferred models (K-rol-model-sirasi): a provider and a model of it."""

    provider_id: str
    model_id: str = Field(min_length=1, max_length=200)


class RoleOut(Out):
    id: str
    name: str
    description: str
    instructions: str
    tools: list[str]
    builtin: bool
    created_by_agent: bool
    provider_id: str | None
    model_id: str | None
    # K-rol-model-sirasi: the models its agents are tried on first, in this order - one not
    # had now is passed over for the next; after them its own model, then its tier. None: none.
    models: list[PreferredModel] | None
    # Where the role has no model of its own: always the first model of this tier in the
    # team guide that may be picked for the role (the user's rule); "conversation": the
    # conversation's model, as before slice 81b. None: the Lead picks one for each job from
    # `tier_min` to `tier_max` (None: fast, strongest).
    tier: TierRule | None
    tier_min: Tier | None
    tier_max: Tier | None
    # The group the Agents page draws it in.
    kind: str
    # Off: opened only where the user names it in a turn's message.
    enabled: bool
    # The teams (ids) it is in.
    teams: list[str]

    @field_validator("teams", mode="before")
    @classmethod
    def _ids(cls, value: list) -> list:
        return [getattr(team, "id", team) for team in value]
    # The providers (ids) an agent may pick for a sub-agent of this role, out of the
    # team guide. None: every one in the guide; empty: none.
    pick_from: list[str] | None
    # How far one agent of this role may go; None: no limit of the role's.
    max_steps: int | None
    max_tokens: int | None
    # Its agents' reasoning level, and the most one asked for a task may get; None: the
    # model's own, and no most.
    effort: Effort | None
    max_effort: Effort | None
    # How many tokens its agents' model reads at most, as the user set it; None: as found.
    context_window: int | None
    # The MCP servers (their names) whose tools an agent of this role may use.
    mcp: list[str]
    # The skills (their names) its agents are given.
    skills: list[str]
    # 89g: also offered to a Claude Code Lead as one of its own sub-agents.
    inside_cli: bool
    # K-bilgi: the knowledge it uses ("full": an expert in it), with each one's topic and project.
    knows: list[KnowsOut] = Field(validation_alias="knows_shown")
    created_at: datetime
    updated_at: datetime


class StageOut(BaseModel):
    id: str
    name: str
    # Its roles work side by side ("all at once"); else one after another.
    together: bool
    # Its roles (ids), in the Agents page's order.
    roles: list[str]


class TeamOut(BaseModel):
    id: str
    name: str
    # Its roles, by name, in the Agents page's order.
    roles: list[str]
    # Slice 63a: its stages in order, its lead (a role of kind "lead", in no list of roles), the
    # lead on or off, and whether the Lead may pick the team itself. The last two act from 84b.
    stages: list[StageOut]
    lead: RoleOut
    lead_on: bool
    lead_may_pick: bool
    # Slice 84a: the recipe it runs by where a chat picks none (one of KOLONİ's); kept, used
    # from 84b.
    default_recipe_id: str | None


# Slice 84a: a recipe as it is drawn and kept - in KOLONİ's record, in a folder's
# .koloni/recipes/, or as a model's draft: nothing but what a recipe holds. What makes one that
# can run (an end, every step reached, ...) is `app.recipes.problems`.
NodeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]
RecipeName = Annotated[str, AfterValidator(lambda value: _words(value, 60, "a recipe's name"))]
# (Empty, it is said at its part with the rest that keeps it from running - not alone: R57.)
StepName = Annotated[str, AfterValidator(lambda value: _words(value, 60, "a step's name", True))]


class Shut(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WhoRole(Shut):
    role: str = Field(max_length=60)
    # K-rol-cogul: at most this many agents of the role in the step, as many as its lead splits
    # the work into; one (None, or 1) is left out of what is written, so an old recipe's file
    # reads as it did.
    most: Annotated[int | None, Field(None, ge=1, le=5,
                                      exclude_if=lambda value: value in (None, 1))]


class CandidateModel(Shut):
    # A provider of the team guide by its id, and one of its models (None: its default).
    # shortcut: by id - a folder's recipe on another machine names no provider there, and is
    # refused as it runs (`recipes.problems`); match by name if recipes are shared so.
    provider_id: str = Field(max_length=32)
    model_id: str | None = Field(None, max_length=200)


class WhoCandidates(Shut):
    # K-evrim: up to `most` agents of the role each do the whole task their own way, each in a
    # copy of its own; each is scored by the project's measure command, and the best goes on.
    candidates: str = Field(max_length=60)
    most: int = Field(ge=2, le=5)
    # The score that is enough (rounds: slice 3); None: no target.
    target: int | None = Field(None, ge=0, le=100)
    # K-evrim-model: "auto" - the Lead gives each candidate a model, the same or not; "same" -
    # each runs on the role's; a list - the user's, candidate N on its Nth (those past its end
    # on the role's). "auto" is left out of what is written, so an old recipe reads as it did.
    models: Annotated[Literal["auto", "same"] | list[CandidateModel],
                      Field("auto", exclude_if=lambda value: value == "auto")]

    @model_validator(mode="after")
    def _one_each_at_most(self) -> "WhoCandidates":
        if isinstance(self.models, list) and not 1 <= len(self.models) <= self.most:
            raise ValueError(f"pick 1 to {self.most} models, one a candidate")
        return self


class WhoTeam(Shut):
    # Its stages, in its order.
    team: str = Field(max_length=55)


class WhoLead(Shut):
    # The Lead picks who does it.
    lead: Literal[True]


class WhoExperts(Shut):
    # K-uzman: the row's team's experts, an agent each, at once - "stale": only those whose
    # guide is missing or older than their sources (none: the step is passed); "learned"
    # (K-takim-duzen): only those with a guide in the project - none such, the step is passed.
    experts: Literal["all", "stale", "learned"]


class WhoRoom(Shut):
    # Slice 84e: a Room step - its roles meet in one room (2 to 6 of them: `problems` says so).
    room: list[Annotated[str, Field(max_length=60)]] = Field(max_length=10)


# K-tarif-surukle: where the user dragged a part on the board (a group's step: from its group's
# corner); a whole number or not, never a string, NaN or one far off the board.
Coord = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-100_000, le=100_000)]


class RecipePos(Shut):
    x: Coord
    y: Coord


# None (not dragged: the board places it) is left out of what is given back and written, so an
# old recipe's file reads as it did.
Pos = Annotated[RecipePos | None, Field(None, exclude_if=lambda value: value is None)]


class RecipeStep(Shut):
    id: NodeId
    name: StepName
    who: WhoRole | WhoTeam | WhoLead | WhoRoom | WhoExperts | WhoCandidates
    # "done": its agents say they are; "no_findings": a review that leaves no finding.
    done_when: Literal["done", "no_findings"] = "done"
    if_fails: Literal["ask", "stop"] = "ask"
    # The user is asked to approve its work before the recipe goes on.
    ask_me: bool = False
    # The group it runs in, at the same time as the group's other steps.
    group: NodeId | None = None
    # "problem": it runs only if the part before it on the way found a problem - a review there
    # left findings; else it is passed and its agents are never opened. Left out of what is
    # written when not set, so an old recipe's file reads as it did.
    when: Annotated[Literal["problem"] | None, Field(None, exclude_if=lambda value: value is None)]
    pos: Pos


class RecipeGroup(Shut):
    id: NodeId
    name: StepName
    pos: Pos
    # K-tarif-kol: "all" waits for every branch (its steps joined by arrows inside it); "first"
    # goes on once one branch is done, the others stopped. "all" is left out of what is written,
    # so an old recipe's file reads as it did.
    wait: Annotated[Literal["all", "first"], Field("all", exclude_if=lambda value: value == "all")]


class RecipeEnd(Shut):
    id: NodeId
    # "in": the user is asked, then the change is taken into the project; "report": the
    # user is told what was found.
    then: Literal["in", "report"] = "in"
    pos: Pos


class RecipeArrow(Shut):
    # "start" is the user's message.
    from_: NodeId = Field(alias="from")
    to: NodeId


class RecipeLoop(Shut):
    from_: NodeId = Field(alias="from")
    to: NodeId
    # At most this many rounds back; None is refused on save, said at its step.
    rounds: int | None = Field(None, ge=1, le=5)


class RecipeGraph(Shut):
    version: Literal[1] = 1
    steps: list[RecipeStep] = Field(max_length=60)
    groups: list[RecipeGroup] = Field([], max_length=20)
    ends: list[RecipeEnd] = Field([], max_length=10)
    arrows: list[RecipeArrow] = Field([], max_length=200)
    loops: list[RecipeLoop] = Field([], max_length=20)


class RecipeIn(BaseModel):
    name: RecipeName
    graph: RecipeGraph


class RecipeOut(BaseModel):
    # A folder's own: its file's name (no .json), and `project_id` set.
    id: str
    name: str
    ready: bool
    graph: RecipeGraph
    project_id: str | None = None
    file: str | None = None


class RecipeWriter(BaseModel):
    # Why "Or write it" cannot ask the Lead's model now; None: it can.
    why: str | None


class RecipesOut(BaseModel):
    recipes: list[RecipeOut]
    # The folder's recipe files that are not read, each with why.
    broken: list[str]
    writer: RecipeWriter


class RecipeDraftIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class RecipeDraftOut(BaseModel):
    """A model's draft, saved nowhere: the page opens it to be changed and saved."""

    name: str
    graph: RecipeGraph
    provider_name: str
    model_id: str | None


def no_knowledge(data: object) -> object:
    """K-bilgi: a role's knowledge is on the Knowledge page - said, not dropped unseen (a page
    from before would make a plain role)."""
    if isinstance(data, dict) and "knowledge" in data:
        raise ValueError("a role's knowledge is kept on the project's Knowledge page now: add it "
                         "there and give it to the role")
    return data


class RoleIn(BaseModel):
    _no_knowledge = model_validator(mode="before")(no_knowledge)
    name: str
    description: str = ""
    instructions: str = ""
    tools: list[str]
    provider_id: str | None = None
    model_id: str | None = Field(default=None, max_length=200)
    # shortcut: five at most - enough for "first X, then Y"; raise it if a longer list is asked for.
    models: list[PreferredModel] | None = Field(default=None, max_length=5)
    tier: TierRule | None = None
    tier_min: Tier | None = None
    tier_max: Tier | None = None
    # Left out: "build", or the first category where that is gone (`app.roles.landing_kind`).
    kind: Kind | None = None
    enabled: bool = True
    teams: list[str] = Field(default_factory=list, max_length=200)
    pick_from: list[str] | None = Field(default=None, max_length=200)
    max_steps: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    max_tokens: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    effort: Effort | None = None
    max_effort: Effort | None = None
    context_window: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    inside_cli: bool = False


class RolePatch(BaseModel):
    _no_knowledge = model_validator(mode="before")(no_knowledge)
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    tools: list[str] | None = None
    provider_id: str | None = None
    model_id: str | None = Field(default=None, max_length=200)
    # Sent as null or empty: no list. Left out: kept. Five at most (as RoleIn).
    models: list[PreferredModel] | None = Field(default=None, max_length=5)
    # Sent as null: no tier (the Lead picks, within the range). Left out: kept.
    tier: TierRule | None = None
    tier_min: Tier | None = None
    tier_max: Tier | None = None
    kind: Kind | None = None
    enabled: bool | None = None
    # The teams (ids) it is in; left out: kept.
    teams: list[str] | None = Field(default=None, max_length=200)
    # Sent as null: every provider of the team guide may be picked. Left out: kept.
    pick_from: list[str] | None = Field(default=None, max_length=200)
    # Sent as null to take the limit away; left out to keep it. A whole number as such:
    # not `true`, not "50".
    max_steps: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    max_tokens: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    # Sent as null: the model's own, no most. Left out: kept.
    effort: Effort | None = None
    max_effort: Effort | None = None
    # Sent as null: as found. Left out: kept.
    context_window: int | None = Field(default=None, gt=0, le=2**53, strict=True)
    # The names of the MCP servers the role may use; left out: kept.
    mcp: list[str] | None = Field(default=None, max_length=200)
    # The names of the skills its agents are given; left out: kept.
    skills: list[str] | None = Field(default=None, max_length=200)
    # Left out: kept.
    inside_cli: bool | None = None



McpMark = Literal["ask", "free", "off"]


class ExpertIn(BaseModel):
    """K-bilgi: a new expert - its role, and its knowledge in this project."""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    role: RoleIn
    knowledge: Knowledge


class McpToolOut(BaseModel):
    name: str
    # The server's own words, as they were when its tools were last read.
    description: str
    input_schema: dict
    # "ask": the user is asked before each call; "free": it runs without asking, on the
    # user's word; "off": no agent is offered it.
    mark: McpMark
    # Why no agent is offered it (its name, its inputs); None: it can be offered.
    unusable: str | None
    # About how many characters it adds to every model step of an agent that has it;
    # None for one that cannot be offered.
    chars: int | None


class McpServerOut(BaseModel):
    """An MCP server as clients see it: the names of its variables, never their values."""

    id: str
    name: str
    command: list[str]
    env_names: list[str]
    tools: list[McpToolOut]
    read_at: datetime | None
    read_error: str | None
    # False: watched - every call of it is asked about (slice 92).
    trusted: bool
    # False: switched off - given to no agent.
    enabled: bool


class McpServerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    # The program and its arguments: started as they are, no shell reads them.
    command: list[str]
    env: dict[str, str] = Field(default_factory=dict)


class McpServerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] | None = None
    # Each variable named is set to the value given, or taken away (null); one that is
    # not named stays as it is - its value is never sent back to be sent again.
    env: dict[str, str | None] | None = None
    marks: dict[str, McpMark] | None = None
    # The user trusts it: its calls go back to the marks and the level. Never taken back
    # here; another command takes it back (`patch_server`).
    trusted: Literal[True] | None = None
    # On or off for every agent; its marks and trust stay as they are.
    enabled: bool | None = None


class OwnCommandOut(BaseModel):
    """One of the user's own slash commands; `project_id` None: offered in every project."""

    id: str
    name: str
    description: str
    template: str
    role: str | None
    project_id: str | None


class OwnCommandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=40)
    description: str = Field(default="", max_length=200)
    # `{args}` is where what is typed after the name goes.
    template: str = Field(min_length=1, max_length=4000)
    role: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=32)


class OwnCommandPatch(BaseModel):
    """What is sent changes; `role` / `project_id` sent as null: no role / every project."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=200)
    template: str | None = Field(default=None, min_length=1, max_length=4000)
    role: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=32)


class McpReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Ask osv.dev first whether the package npx or uvx is given is known malware: its name
    # is sent. One it lists is not started.
    osv: bool = False
    # Its files in a folder agents write in, {full path: sha256}, as the reading before
    # told them: the user said to start it anyway (97).
    in_project: dict[str, str | None] | None = None


class BuiltinToolOut(BaseModel):
    """One of KOLONİ's own tools the Tools page switches (slice 61)."""

    name: str
    on: bool


class BuiltinToolIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool


class MalwareOut(BaseModel):
    """What osv.dev was asked of a package: its known-malware records (MAL-…), or why it
    could not be asked."""

    package: str
    records: list[str]
    error: str | None


class McpReadOut(BaseModel):
    """A server after its tools were read, and what that reading found against the one
    before: the names of the tools that are new, changed and gone."""

    server: McpServerOut
    new: list[str]
    changed: list[str]
    gone: list[str]
    # None: osv.dev was not asked.
    malware: MalwareOut | None = None
    # Set: it was not started - it runs these files from a folder agents write in, {full
    # path: sha256, None where it is too big to hash: asked every time}, and the user is to
    # say whether to start it anyway (97).
    in_project: dict[str, str | None] | None = None


class PackageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(max_length=21)
    # The version the user was shown: the one downloaded to be looked into.
    version: str | None = Field(default=None, max_length=64)


class PackageOut(BaseModel):
    """An MCP server's package as npm or PyPI lists it, before anything of it is downloaded."""

    registry: Literal["npm", "pypi"]
    name: str
    version: str
    # npm lists its size unpacked (`unpacked`), PyPI its file's; None: not listed.
    size: int | None
    unpacked: bool
    license: str | None


class PackageSeenOut(SeenOut):
    registry: Literal["npm", "pypi"]
    name: str
    version: str
    license: str | None
    size: int  # downloaded
    on_install: list[str]
    dependencies: list[str]


class LastRun(BaseModel):
    """Where a role's latest agent ran, and at which tier (None: its model had none)."""

    provider_name: str | None
    model_id: str | None
    tier: Tier | None


class RolesActivityOut(BaseModel):
    """For the Agents page: what is on record of each role's agents."""

    # By role name: its latest agent that was opened (not one proposed or turned down).
    last: dict[str, LastRun]
    # By role name: how many of its agents are at work now.
    running: dict[str, int]


class RoleJobOut(BaseModel):
    id: str
    conversation_id: str
    conversation_title: str
    status: AgentStatus
    provider_name: str | None
    model_id: str | None
    tier: Tier | None
    chosen_why: str | None
    task: str | None
    created_at: datetime


class RoleJobsOut(BaseModel):
    """A role's latest agents with their conversations, and what is known of its last 30
    days: agents opened, how many failed, and the tokens they reported (`unreported`: how
    many said none - those are not counted as zero)."""

    jobs: list[RoleJobOut]
    days30: dict[str, int]


class HistoryCount(BaseModel):
    """How a role's agents, or a team's or a recipe's runs, ended: done, failed or stopped,
    or still in progress."""

    name: str
    done: int = 0
    failed: int = 0
    running: int = 0


class HistoryJob(BaseModel):
    id: str
    role_name: str
    conversation_id: str
    conversation_title: str
    status: AgentStatus
    provider_name: str | None
    model_id: str | None
    created_at: datetime
    # The teams and recipes whose run it was one of (`Run.teams`, `state.agents`), by name.
    teams: list[str]
    recipes: list[str]


class RolesHistoryOut(BaseModel):
    """The Agents page's History: the sub-agents opened in the last `days`, by role; the turns'
    teams and recipes run, as each turn kept them (`Run.teams`); the latest jobs. A turn's own
    Lead (depth 0) is no role's job: only how many turns it led."""

    days: int
    lead_turns: int
    roles: list[HistoryCount]
    teams: list[HistoryCount]
    recipes: list[HistoryCount]
    jobs: list[HistoryJob]
    # The newest this many jobs are listed; the counts are of all of them.
    jobs_limit: int


class RunOn(BaseModel):
    """A provider a role's agents could be given as their own model (the chat's team picker):
    the model they would run with there, and whether such an agent could be a recipe's step
    and a room's member (B-89)."""

    provider_id: str
    model_id: str | None
    step: bool
    room: bool


class RoleModelOut(BaseModel):
    """What an agent of a role would run on now, and what may be picked for it."""

    role: str
    provider_name: str
    # None where it is not known before it runs: the provider's own default.
    model_id: str | None
    # Where that comes from: the role's own model, the first model of the role's tier,
    # the one chosen in the conversation, or the app's default provider.
    source: Literal["role", "tier", "conversation", "default"]
    # The tier it would run at with none given for the job (its "Always", else balanced or
    # the range's nearest end). Where `source` is neither "role" nor "tier", no model of it
    # could be had (none has that tier, or none that may be picked for the role now) and
    # the next rule decided. None: no tier was looked for (the Lead, a model of its own).
    tier: Tier | None
    # Why it is not the tier's first model, or (B-314) why no model of the tier was had and it
    # runs where it does, as the agent's card says it (`Would.moved`). None: nothing moved it.
    moved: str | None = None
    # The providers an agent may pick for a sub-agent of this role now, by name: the
    # team guide, less what the role does not let be picked.
    pick_from: list[str]
    # Why no agent of the role would run on that now: "Only these models" on its provider
    # leaves the model out (as an agent that asks for one is told), or the provider is a
    # CLI that cannot be opened here now (as `cannot_pick` says it). None: it would.
    cannot_run: str | None
    # Why an agent of the role, where it runs, could not be a recipe's step (a CLI working in
    # the project itself), and could not be a member of a room (a CLI with its own tools), as
    # the agent that opens one is told (B-89). None: it could.
    cannot_step: str | None = None
    cannot_room: str | None = None
    # Where its agents could run instead, as their own model; [] where none could.
    run_on: list[RunOn] = []
    # Of the team guide (the role's own list is judged too, so not `pick_from` alone), the
    # providers a pick could not open in this conversation now (a CLI with its own tools,
    # at this permission level or for this role's tools): the
    # provider's name -> why, as the agent that picks it is told. In a turn nobody is
    # watching nothing is picked at all, which no row says.
    cannot_pick: dict[str, str]
    # Asked for (`?levels=1`): the reasoning levels that model takes; [] where it takes none
    # or its provider does not say them without a cost - no level is sent to it. None: not
    # asked for, or the asking failed.
    efforts: list[Effort] | None = None
    # Asked for too: the model's name sets its level, so it takes none (B-404: `level_in_name`).
    level_named: bool = False
    # Asked for too: how many tokens that model reads at most, as its provider says it
    # (Anthropic's Models API, llama-server's `/props`); None: unknown, or not asked for.
    context_window: int | None = None
    # On the Lead's row, where the conversation has its lead's model follow the message:
    # who would be asked how hard a message is now. None there: nobody would be.
    asks_how_hard: AskedModel | None


class ProviderModel(BaseModel):
    """A model the user counts as selectable on a provider, with a short note on it."""

    name: str
    note: str | None = None
    # How strong the user says it is. None: it is in no automatic choice - no role's
    # tier, no easier or harder job, no lead's automatic model.
    tier: Tier | None = None
    # Whether agents may pick it (slice 81a). The user still can, for a conversation or a role.
    agents: bool = Field(default=True, strict=True)
    # False: switched off - nobody uses it, the user neither (`providers.allowed`); its row
    # stays. None (as every row from before says): on.
    enabled: bool | None = Field(default=None, strict=True)
    # B-396: why KOLONİ switched it off (`AgentRunner._refused`); kept while it stays off, never
    # taken from a request (`api.providers`).
    off_why: str | None = None
    # What the user marked it to take besides text (slice 85b). None: not marked.
    inputs: list[ModelInput] | None = None
    # K-copilot-baglam: Copilot's context window tier (`--context`), only on the user's GitHub
    # account (`providers.check_guide`). None or "default": none is passed.
    context: Literal["default", "long_context"] | None = None


class TierModel(BaseModel):
    """A model of a tier, by its provider."""

    provider_id: str
    model: str


class TierModelOut(TierModel):
    provider_name: str
    # False: agents may not use it - it keeps its place and is passed over.
    agents: bool


class TiersIn(BaseModel):
    """Each tier's models in the order they are tried (slice 81a)."""

    strongest: list[TierModel] = Field(max_length=1000)
    balanced: list[TierModel] = Field(max_length=1000)
    fast: list[TierModel] = Field(max_length=1000)


class TiersOut(BaseModel):
    strongest: list[TierModelOut]
    balanced: list[TierModelOut]
    fast: list[TierModelOut]


class ProviderOut(Out):
    """A provider as clients see it: whether a key is set, never the key."""

    id: str
    name: str
    kind: Literal[
        "openai_compat", "anthropic", "claude_cli", "qoder_cli", "codex_cli", "copilot_cli",
        "agy_cli",
    ]
    base_url: str | None
    default_model: str | None
    executable: str | None
    mode: Literal["session", "step", "native", "reads"] | None
    options: dict | None
    # The team guide: agents may choose it, what it is good for, its selectable models.
    for_agents: bool
    note: str | None
    models: list[ProviderModel]
    # Never run with a model outside the list, nor with none.
    only_listed: bool
    # False: switched off - nobody uses it; its key and settings stay. (Always said; optional,
    # as `key_warning`, only so that what reads a provider from before needs no change.)
    enabled: bool | None = None
    # The most agents at work on it at once, in the whole app, as the user set it; None: by
    # its kind - `most_at_once`, what holds now (K-paralel-saglayici).
    max_running: int | None
    most_at_once: int | None = None
    # Its limits (slice 81c): a key that is a plan counts no money; a subscription's picks go
    # a tier lower from `step_down_at` percent of its plan; the most it may spend.
    plan: bool
    step_down_at: int | None
    day_limit: float | None
    month_limit: float | None
    has_key: bool
    # Why its key will not be taken (kept all the same), said of the key and never with it.
    key_warning: str | None = None
    # K-cli-surface: the CLI version it last ran natively on, where KOLONİ did not measure it.
    version_note: str | None = None
    # K-native-not: by each way it runs with its own tools, which of KOLONİ's rules nobody
    # watches there (`providers.NOT_WATCHED`) - for an agent, by the mode it ran in; and the
    # same where the agent's project runs its commands in Docker (`providers.ON_HOST`).
    not_watched: dict[str, list[str]] | None = None
    not_watched_in_docker: dict[str, list[str]] | None = None
    position: int
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _without_the_key(cls, value):
        if isinstance(value, dict):
            return value
        from app import cli_surface  # (they import the clients: not at the top)
        from app.providers import mode_of, most_at_once, not_watched

        fields = {name: getattr(value, name) for name in cls.model_fields if name not in (
            "has_key", "key_warning", "most_at_once", "version_note", "not_watched",
            "not_watched_in_docker")}
        return {**fields, "models": value.models or [], "has_key": bool(value.api_key),
                "key_warning": _key_warning(value.kind, value.api_key),
                "most_at_once": most_at_once(value),
                "not_watched": not_watched(value.kind, docker=False),
                "not_watched_in_docker": not_watched(value.kind, docker=True),
                "version_note": cli_surface.note(value.kind, value.executable)
                if mode_of(value) in ("native", "reads") else None}  # (reads: agy's, B-310)


def _key_warning(kind: str, key: str | None) -> str | None:
    """Why an Anthropic provider's key will not be taken by the API: only its prefix is read,
    and only a subscription token's is known to be refused - the user's working key had a
    prefix other than sk-ant-api, so no other is warned of."""
    if kind == "anthropic" and key and key.startswith("sk-ant-oat"):
        return ("this looks like a Claude subscription token - the API does not accept it; "
                "add Claude Code instead")
    return None


class ProviderIn(BaseModel):
    name: str
    kind: str
    base_url: str | None = None
    api_key: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=200)
    executable: str | None = Field(default=None, max_length=500)
    mode: str | None = None
    options: dict | None = None
    for_agents: bool = False
    note: str | None = None
    models: list[ProviderModel] | None = None
    only_listed: bool = False
    max_running: int | None = Field(default=None, gt=0, le=1000, strict=True)


class ProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=200)
    executable: str | None = Field(default=None, max_length=500)
    mode: str | None = None
    options: dict | None = None
    # Left out to keep what is set; a null note or list clears it.
    for_agents: bool | None = None
    note: str | None = None
    models: list[ProviderModel] | None = None
    only_listed: bool | None = None
    enabled: bool | None = Field(default=None, strict=True)
    # Sent as null to take the limit away; left out to keep it.
    max_running: int | None = Field(default=None, gt=0, le=1000, strict=True)
    # The same, each of them (slice 81c); `plan` left out or null is kept.
    plan: bool | None = None
    step_down_at: int | None = Field(default=None, ge=50, le=100, strict=True)
    day_limit: float | None = Field(
        default=None, gt=0, le=2**53, allow_inf_nan=False, strict=True)
    month_limit: float | None = Field(
        default=None, gt=0, le=2**53, allow_inf_nan=False, strict=True)


class ProviderModelsOut(BaseModel):
    """Model names to offer for a provider, and why there are none when there are none."""

    models: list[str]
    note: str | None


class CatalogueFillIn(BaseModel):
    """A provider not added yet, as the form has it so far."""

    kind: str
    base_url: str | None = None
    models: list[ProviderModel] = []


class CatalogueFillOut(BaseModel):
    """A team guide proposed from the catalogue, not saved; how many did not fit."""

    models: list[ProviderModel]
    left_out: int


class FillAllProvider(BaseModel):
    """One provider's team guide as proposed from the catalogue (never its key or address)."""

    id: str
    name: str
    kind: str
    # Whether the catalogue knows its models; one it does not is ticked once given a tier.
    catalogued: bool
    for_agents: bool
    models: list[ProviderModel]


class FillAllOut(BaseModel):
    providers: list[FillAllProvider]
    # The catalogue's note for each tier: a row given another tier in the preview gets that one.
    notes: dict[str, str]


class FillAllSave(BaseModel):
    """A provider's guide as the user left it in the preview."""

    id: str
    for_agents: bool
    models: list[ProviderModel] = Field(max_length=30)  # MAX_MODELS (app.providers)


class FillAllIn(BaseModel):
    providers: list[FillAllSave] = Field(max_length=200)

    @field_validator("providers")
    @classmethod
    def _once_each(cls, providers: list[FillAllSave]) -> list[FillAllSave]:
        if len({p.id for p in providers}) != len(providers):
            raise ValueError("a provider is in the list twice")
        return providers


class SuggestIn(BaseModel):
    """A provider not added yet: its kind and the address typed so far."""

    kind: str
    base_url: str | None = Field(default=None, max_length=2000)


class KnownAddress(BaseModel):
    """A service's address an OpenAI-compatible provider may be given, by the service's name."""

    name: str
    api: str


class SuggestOut(BaseModel):
    """What the catalogue offers a provider not added yet: model names, and for a service
    spoken to with a key, its name, address and the name its docs give the key."""

    models: list[str]
    service: str | None
    api: str | None
    env: list[str]
    # For an OpenAI-compatible one: the addresses known (catalog.suggest); none for others.
    addresses: list[KnownAddress]


class ModelPriceOut(BaseModel):
    """For a million tokens sent, written, read again from the cache and written to it."""

    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None
    currency: str


class ModelFactsOut(BaseModel):
    """What is known of a model, each fact null where it is not (never a guess)."""

    efforts: list[Effort] | None
    context_window: int | None
    max_output: int | None
    price: ModelPriceOut | None
    tier: Tier | None
    # models.dev says it is being retired; null where the model is not in the catalogue.
    deprecated: bool | None
    # Where each known fact came from: "you", "catalog", "models.dev", "server", "anthropic",
    # "docs" (OpenAI's, for levels: `catalog._OPENAI_LEVELS`);
    # "models.dev (deepseek)": models.dev's word of another service, which has the model.
    sources: dict[str, str]
    # When the copy of models.dev was read.
    catalogue_date: str | None
    # A lookup that was needed (the server on this machine, Anthropic) did not answer.
    failed: bool = False
    # What it takes besides text, each kind someone said (slice 85b); a kind left out is
    # not known.
    inputs: list["ModelInputOut"] = []


class ModelInputOut(BaseModel):
    kind: ModelInput
    takes: bool
    # "models.dev", "you" (its row or catalog.local.json), or "tried": KOLONİ sent it one.
    source: Literal["models.dev", "you", "tried"]


class CatalogueUpdateOut(BaseModel):
    """The catalogue the app reads (or what the user's "Update catalogue" kept): how many
    services and models, and when it was read."""

    providers: int
    models: int
    updated_at: str | None
    # Why the user's own catalog.local.json is not read (`catalog.local`); None: it is, or
    # there is none.
    local: str | None
    # "Keep the catalogue fresh": downloaded again at the start once a week old (on until
    # the user turns it off).
    keep_fresh: bool


class CatalogueFreshIn(BaseModel):
    keep_fresh: bool


class RunCommand(BaseModel):
    """A command for the user to run in their own terminal, and where it is documented."""

    command: str
    # The same for cmd.exe, where it differs (a sign-in folder's login).
    cmd: str | None = None
    docs: str


class ModelState(BaseModel):
    name: str
    state: Literal["usable", "unusable", "unknown"]
    why: str | None
    # models.dev says it is being retired: it still runs, and is no longer offered.
    retired: bool = False


class AvailabilityOut(BaseModel):
    """Whether each model can be used now. None: not known (or, for `installed`, not a CLI)."""

    installed: bool | None
    install: RunCommand | None = None
    signed_in: bool | None = None
    sign_in: RunCommand | None = None
    # The plan a signed-in Claude Code names ("max", "pro"); None where it is not said.
    plan: str | None = None
    # K-claude-hesap: for a provider with a sign-in folder of its own, how to log in there.
    login: RunCommand | None = None
    models: list[ModelState]


class ProviderTestOut(BaseModel):
    ok: bool
    model_id: str | None
    tools_supported: bool | None
    error: str | None
    # What the model answered, when the test really ran it (CLI providers, on request).
    reply: str | None = None
    # "settings": the model's name was read from the CLI's own settings.
    model_from: str | None = None


class MemorySource(BaseModel):
    """The file lines a record rests on, as they were noted."""

    path: str
    start: int | None
    end: int | None


class MemoryFoundAt(BaseModel):
    """Where the block a record was noted on stands now, when it is no longer where it
    was noted - and the lines there. Nobody has looked at them yet."""

    start: int
    end: int
    excerpt: str | None


class MemoryLastChange(BaseModel):
    """The last change an agent made to a record's source file, as far as on record."""

    agent_id: str
    agent_name: str
    at: datetime


class MemoryOut(BaseModel):
    """One record of a project's memory, with how its source stands now."""

    id: str
    project_id: str
    # "preference": a line the summariser suggests for the user's preferences (22b), waiting.
    tier: Literal["note", "fact", "preference"]
    text: str
    about: str | None
    # Whether an agent can be given this unasked: a fact in the core on a subject work can
    # name (and then only while its source stands). False: only found by looking it up -
    # a note, a record not in effect, or a subject that is empty or too general.
    given_unasked: bool
    # Whose words these are. "auto": KOLONİ's summariser, a fast model that was given
    # what was said in a turn and looked at nothing itself - `noted_by` says which model
    # (as it was asked for); null for every other record.
    origin: Literal["user", "agent", "auto"]
    noted_by: AskedModel | None = None
    agent_id: str | None
    agent_name: str | None
    run_id: str | None
    conversation_id: str | None
    observed_at: datetime
    source: MemorySource | None
    # "unchanged": the lines read as they did when it was noted (not: the note is right).
    # "changed": they do not, or cannot be read. "moved": they do not, but the same block
    # stands once somewhere else in the file (`found_at`) - which may be a copy; it is
    # given to nobody until the user confirms it. "none": no file behind it.
    # "elsewhere": a linked project's record (22c) - its file is not here, nobody looked.
    source_state: Literal["unchanged", "changed", "moved", "none", "elsewhere"]
    # 22c: the name of the linked project a found record is from; null for this project's.
    from_project: str | None = None
    # 22c: found by the search by meaning, not by its words.
    by_meaning: bool = False
    found_at: MemoryFoundAt | None
    # The noted lines as they are on disk now, cut to a size; null when there is no file
    # or nothing can be read there.
    excerpt: str | None
    # When the file was last changed on disk, and whether that was while a turn of this
    # project was running; null when it cannot be told.
    source_modified: datetime | None
    modified_in_turn: bool | None
    checked_how: str | None
    status: Literal["active", "proposed", "superseded", "rejected"]
    # The record this one took the place of - or, while it waits, asks to.
    supersedes_id: str | None
    wants_core: bool
    # ("auto": a note made by itself that a newer one of its kind took the place of.)
    decided_by: Literal["user", "agent", "auto"] | None
    decided_at: datetime | None
    # What that decision was ("feedback": the user's words at a card asking for changes,
    # K-devir-2); null for one from before this was kept.
    decided_how: Literal["written", "feedback", "approved", "corrected", "confirmed", "restored",
                         "rejected", "removed", "replaced", "added"] | None
    # Written in a turn nobody was watching (a trigger started it).
    unattended: bool
    created_at: datetime
    last_change: MemoryLastChange | None


class MemoryDecision(BaseModel):
    """Something decided in the user's name: on a record, or on the rules."""

    kind: Literal["written", "feedback", "approved", "corrected", "confirmed", "restored",
                  "rejected", "removed", "added", "rules"]
    at: datetime
    # The record it was decided on, with its words as they are now; null for the rules.
    memory_id: str | None
    text: str | None
    about: str | None


class LastAuto(BaseModel):
    """How it went when a fast model was to note what a turn found (`auto_notes`)."""

    run_id: str
    noted: int
    # Notes it gave that were not kept: their subject was taken by somebody's own note,
    # the same words were on record, or they were not what a note may be.
    skipped: int
    # Why nothing was noted, in KOLONİ's own fixed words; null when something was.
    note: str | None


class ProjectMemoryOut(BaseModel):
    core: list[MemoryOut]
    # Notes that wait for the user: put forward for the core, or written on a subject
    # the core has a fact on.
    proposals: list[MemoryOut]
    journal: list[MemoryOut]
    # What is no longer in effect, newest first.
    past: list[MemoryOut]
    # 22b: lines the summariser suggests for the user's preferences, waiting for the user.
    suggestions: list[MemoryOut] = []
    # The user's own preferences, one text for every project; null when none are saved.
    preferences: str | None = None
    rules: str | None
    # Whether they are the folder's .koloni/rules.md (slice 86c), kept in git with it.
    rules_kept: bool = False
    # Why the folder's .koloni/rules.md is not read, as the page says it; null: it is, or is
    # not there.
    rules_not_read: str | None = None
    # When the rules last changed; null when they never did, or did before this was kept.
    rules_changed_at: datetime | None = None
    # The last decision on each record and the last change to the rules, newest first, at
    # most ten. Decisions from before their kind was kept are not listed.
    decisions: list[MemoryDecision] = []
    core_chars: int
    core_limit: int
    # How noting by itself went after the last turn it was tried for; null: for none yet.
    last_auto: LastAuto | None = None


class SaidOut(Out):
    """Something said in an earlier turn of the project, as a search found it - or a
    backlog task as the user closed it (`run_id` is then "task:" and the task's id)."""

    # "You" for the user; otherwise the name of the agent that said it.
    who: str
    conversation_id: str | None  # None: a backlog task of no conversation
    conversation_title: str
    run_id: str
    at: datetime | None  # None: a task closed before there was an index
    # What was said, as it was said: all of it, or about 600 characters around the match.
    excerpt: str
    kind: Literal["turn", "task"]  # a turn's words, or a backlog task as it was closed
    trigger: bool  # said in a turn nobody watched: a trigger's
    # 22c: the name of the linked project it was said in; null for this project's own.
    project: str | None = None
    by_meaning: bool = False


class MemorySearchOut(BaseModel):
    """What an agent's `recall` would find: the records of the memory that are in effect
    and speak to the words, and what was said in earlier turns."""

    memory: list[MemoryOut]
    turns: list[SaidOut]
    # 22c: why the search by meaning did not run, when a provider is chosen for it and it
    # did not ("search by meaning is off: …"); null otherwise.
    meaning_off: str | None = None


class MemoryIn(BaseModel):
    text: str
    about: str | None = None
    # Optional: the project file and lines the fact rests on. KOLONİ takes the digest of
    # those lines; end_line left out means the one line.
    file: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class MemoryApproveIn(BaseModel):
    # Left out to approve the note as it is.
    text: str | None = None


class MemoryPatch(BaseModel):
    text: str | None = None
    # Left out to keep the subject; null or "" for none.
    about: str | None = None


class RulesIn(BaseModel):
    rules: str


class RulesOut(BaseModel):
    rules: str | None


class PreferencesIn(BaseModel):
    text: str


class PreferencesOut(BaseModel):
    """The user's own preferences (22b): one text for every project; null when none."""

    text: str | None


class TriggerPermissions(BaseModel):
    """What a trigger's turns may do without asking. Nothing, to begin with: such a turn
    reads, and writes notes. The conversation's own level and allow list do not count."""

    write: bool = False
    # The ids of rules on the allow list of the trigger's own conversation. With nobody
    # watching, a ticked rule lets exactly one command run: the one that is its text.
    commands: list[str] = Field(default_factory=list, max_length=20)
    # How many sub-agents a turn may open, all told.
    agents: int = Field(default=0, ge=0, le=4)
    # Whether a turn may search the web.
    web: bool = False
    # The hosts a turn may make HTTP requests to: bare names, matched exactly.
    hosts: list[str] = Field(default_factory=list, max_length=20)
    # Whether a turn may send the user a notification.
    notify: bool = False


class TriggerLeave(TypedDict):
    """A trigger's permissions as they are kept and shown. What it may do on the web is
    there only where it is allowed: left out, its turns may not."""

    write: bool
    commands: list[str]
    agents: int
    web: NotRequired[bool]
    hosts: NotRequired[list[str]]
    notify: NotRequired[bool]


class TriggerBudget(BaseModel):
    """A turn's model steps (all its agents together) and its length in minutes; and how
    many turns the trigger may start in a day. There is no "unlimited"."""

    steps: int = Field(default=15, ge=1, le=200)
    minutes: int = Field(default=10, ge=1, le=240)
    per_day: int = Field(default=24, ge=1, le=500)


TriggerKind = Literal["schedule", "files", "webhook"]


class TriggerIn(BaseModel):
    name: str
    kind: TriggerKind
    conversation_id: str
    message: str
    # schedule: {"every_minutes": N} or {"at": "HH:MM", "days": "daily" | "weekdays" | a list
    # of "mon".."sun", in week order}; files: {"glob": "src/**/*.py"}; webhook: {}.
    config: dict = Field(default_factory=dict)
    permissions: TriggerPermissions = Field(default_factory=TriggerPermissions)
    budget: TriggerBudget = Field(default_factory=TriggerBudget)
    catch_up: bool = True
    enabled: bool = True
    # {"runs": N} or {"until": "YYYY-MM-DD"}; None: no end (`app.triggers.check_ends`).
    ends: dict | None = None
    # A schedule runs even when nothing changed since its last completed run.
    run_unchanged: bool = False
    # Made from an agent's proposal, in the form (slice 69): that card is done with.
    proposal_id: str | None = None


class TriggerPatch(BaseModel):
    """Left out: kept as it is. A trigger's kind does not change. `ends` sent as null: no
    end."""

    name: str | None = None
    conversation_id: str | None = None
    message: str | None = None
    config: dict | None = None
    permissions: TriggerPermissions | None = None
    budget: TriggerBudget | None = None
    catch_up: bool | None = None
    enabled: bool | None = None
    ends: dict | None = None
    run_unchanged: bool | None = None


class TriggerEnds(TypedDict, total=False):
    """When a trigger ends by itself: after so many runs, or after a day (the last it runs on)."""

    runs: int
    until: str


class TriggerRunOut(Out):
    """One time a trigger came due."""

    id: str
    # The turn it started; None when it started none.
    run_id: str | None
    at: datetime
    # None while its turn is still running. "stopped": the user stopped the turn.
    outcome: Literal[
        "completed", "failed", "budget", "stopped", "skipped_busy", "skipped_budget",
        "skipped_month", "skipped_limit", "skipped_same",
    ] | None
    late: bool
    note: str | None


class TriggerChangeOut(BaseModel):
    """One thing that was done to a trigger: made, changed, switched or deleted."""

    id: str
    project_id: str
    trigger_id: str
    # The trigger's name at that moment.
    name: str
    at: datetime
    what: Literal[
        "created", "renamed", "message changed", "settings changed", "permissions changed",
        "budget changed", "switched on", "switched off", "new key", "deleted",
    ]
    # How it stood afterwards, in words: what it may do now, why it was switched off.
    detail: str | None


class TriggerOut(BaseModel):
    id: str
    project_id: str
    conversation_id: str
    name: str
    kind: TriggerKind
    config: dict
    message: str
    # Its `commands` are the ticked rules still on its conversation's allow list.
    permissions: TriggerLeave
    # The texts of those rules, in the same order: the command lines it may run.
    command_lines: list[str]
    budget: TriggerBudget
    catch_up: bool
    enabled: bool
    # Its end, None for none; and the turns it started since that was set.
    ends: TriggerEnds | None
    ran: int
    run_unchanged: bool
    failures: int
    # Why KOLONİ switched it off ("ended: 10 runs done" too); None while it is on, or when
    # the user switched it off.
    off_because: str | None
    last_run_at: datetime | None
    last_result: str | None
    # A schedule's next time; None for the other kinds, and before the first look.
    next_at: datetime | None
    # 93-B2: its last runs in a row that found nothing, where that has spaced its times out;
    # None while it keeps its own times.
    slowed: int | None
    # Its last runs in a row that found nothing, whether or not that has slowed it yet (R125).
    idle: int
    last_words: str | None
    created_at: datetime
    # When it was last made, changed or switched.
    updated_at: datetime
    # The last fifty things done to it, newest first.
    changes: list[TriggerChangeOut]
    # The last twenty times it came due, newest first.
    runs: list[TriggerRunOut]


class TriggerCreatedOut(TriggerOut):
    # A webhook's key, shown this once and kept nowhere; None for the other kinds.
    key: str | None


class TriggerStartedOut(BaseModel):
    run_id: str


class TriggerProposalOut(BaseModel):
    """A trigger an agent proposed (slice 69), on its card until the user's word. Approved,
    it reads only, opens no sub-agent and has the usual budget."""

    id: str
    conversation_id: str
    # The turn that proposed it: its card is under that turn.
    run_id: str
    name: str
    kind: Literal["schedule", "files"]
    config: dict
    message: str
    ends: TriggerEnds
    status: Literal["proposed", "approved", "rejected"]
    # Approved: the trigger it became.
    trigger_id: str | None
    created_at: datetime


class TriggersPaused(BaseModel):
    paused: bool


class HoldStopped(BaseModel):
    run_id: str
    conversation_id: str
    title: str
    # B-175: what tells two chats of one title apart - their project, or when the turn was sent.
    project: str | None
    created_at: datetime


class HoldOut(BaseModel):
    """Stop everything (`app.api.hold`): whether it holds, since when, how many turns of every
    chat have not ended, and what a hold holds (triggers on, backlogs that work themselves,
    the projects' nights while the user is away) - and, while it holds, the turns it stopped."""
    held: bool
    since: datetime | None
    running: int
    triggers: int
    backlogs: list[str]
    nights: list[str]
    stopped: list[HoldStopped]
    # Of the turns it stopped, those that have not ended yet.
    stopping: int
    # R147: that the turns it stopped stay stopped after Resume, in a sentence - while it holds,
    # and in Resume's answer; None where it stopped none.
    stays_stopped: str | None = None


class PriceOut(Out):
    """What the user says a model costs: for a million tokens sent, and a million written."""

    model_id: str
    input: float
    output: float
    # As the user wrote it ("USD", "TL"): amounts in different ones are never added.
    currency: str
    # For a million tokens read again from the provider's cache, and a million written
    # to it. Left out where the user wrote none: those tokens then have no price.
    cache_read: float | None = None
    cache_write: float | None = None


# The most a million tokens can be said to cost: far above any price, far below a
# number that no longer adds up.
MAX_PRICE = 1_000_000


class PriceIn(PriceOut):
    """A price as it is taken in. The rules are here and not on what is given back: a
    price already kept is listed whatever it is, so that it can be taken away."""

    model_id: str = Field(min_length=1, max_length=200)
    # Numbers only: not `true`, not "3".
    input: float = Field(ge=0, le=MAX_PRICE, allow_inf_nan=False, strict=True)
    output: float = Field(ge=0, le=MAX_PRICE, allow_inf_nan=False, strict=True)
    currency: str = Field(min_length=1, max_length=8)
    cache_read: float | None = Field(
        default=None, ge=0, le=MAX_PRICE, allow_inf_nan=False, strict=True)
    cache_write: float | None = Field(
        default=None, ge=0, le=MAX_PRICE, allow_inf_nan=False, strict=True)

    @field_validator("model_id", mode="before")
    @classmethod
    def _a_name(cls, value: object) -> object:
        """Without the spaces around it; nothing that is not shown (a line break, a
        control character, a mark that turns the text's direction)."""
        if not isinstance(value, str):
            return value
        if not value.strip().isprintable():
            raise ValueError("a model's name has only characters that can be seen")
        return value.strip()

    @field_validator("currency")
    @classmethod
    def _a_currency(cls, value: str) -> str:
        # Letters, digits and currency signs, from end to end: no space, nothing unseen.
        if not all(sign.isalnum() or unicodedata.category(sign) == "Sc" for sign in value):
            raise ValueError("a currency is letters, digits and currency signs")
        return value


class CostOut(BaseModel):
    amount: float
    currency: str
    # True where an agent of the row is unknown, or tokens of it are not priced
    # (`cache_unpriced`): the amount is the least it cost. Left out where everything of
    # the row is known and priced.
    at_least: bool | None = None
    # True where tokens of the row were read from a cache or written to one and the user
    # wrote no price for that: they are not in the amount at all. Left out otherwise.
    cache_unpriced: bool | None = None
    # "models.dev": the user wrote no price for the model, and the catalogue's was used;
    # and when that copy of the catalogue was read.
    price_from: str | None = None
    price_read_on: str | None = None


class CataloguePriceOut(BaseModel):
    """models.dev's price of a model, used where the user wrote none: for a million tokens
    sent, written, read from the cache and written to it, in USD; and its copy's date."""

    model_id: str
    provider_name: str
    input: float
    output: float
    cache_read: float | None = None
    cache_write: float | None = None
    currency: str
    read_on: str | None


class CompareSideOut(BaseModel):
    run_id: str
    provider_id: str
    model_id: str | None
    status: RunStatus
    # The lead's last answer; "" until it has one.
    answer: str
    # Why its turn failed, as the turn's own record says; None for one that did not.
    error: str | None
    # What it changed in its copy: the files its kept copy holds, or its records' paths.
    changed_files: list[str]
    # Its copy is kept still, its card waiting: before the choice, or where not all of the
    # chosen side's could be taken.
    kept: bool
    # What its agents reported, added up as Usage adds them; None while nothing is known.
    input_tokens: int | None
    output_tokens: int | None
    # From the prices the user wrote, a sum for each currency; None without one for each
    # model it ran on.
    cost: list[CostOut] | None
    # From its start to its end; None until it has ended.
    seconds: float | None


class CompareOut(BaseModel):
    id: str
    conversation_id: str
    # running | ready (both ended, nothing chosen) | chosen | discarded
    status: Literal["running", "ready", "chosen", "discarded"]
    chosen_run_id: str | None
    sides: list[CompareSideOut]


class UsageRow(BaseModel):
    """What a set of agents reported. A sum is over what is known and None when nothing
    is; `unknown_agents` are the agents whose numbers are not both on record. A request
    KOLONİ made of a model itself (a lead's "how hard is this message") is counted as one
    more agent, under the model that was asked."""

    runs: int
    agents: int
    input_tokens: int | None
    output_tokens: int | None
    # Of `input_tokens`: what the providers said was read again from their cache and
    # written to it. None where none of them said - not a zero.
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    unknown_agents: int


class ModelUsage(UsageRow):
    provider_name: str | None
    # The provider of that name now; None for one deleted since.
    provider_id: str | None = None
    model_id: str | None
    # From the price the user wrote for this model; None without one, with nothing
    # known, and for a CLI (a plan has no price for a token).
    cost: CostOut | None


class ConversationUsage(UsageRow):
    conversation_id: str
    project_id: str | None  # None: a plain chat's
    title: str


class StartUsage(UsageRow):
    # "koloni": what KOLONİ asked a model itself with no turn (the day's words, a recipe's
    # draft, a role's guide, a Check that runs a CLI) - in no message.
    started_by: Literal["user", "trigger", "koloni"]
    # Its models' costs added up, as a budget adds them; None where none of them has one.
    cost: CostOut | None


class BudgetOut(BaseModel):
    """This calendar month's spend of a project at the user's prices, against its budget."""

    budget: float | None
    # The prices' currency; None with none, or with several (nothing is then added up).
    currency: str | None
    # None with a budget: this month's costs are in several currencies - nothing is added
    # up, and the budget holds nothing back.
    spent: float | None
    # Some of `spent` is only the least it cost (an agent unknown, cache tokens unpriced).
    at_least: bool
    # spent / budget; None without a budget.
    share: float | None
    warn: bool  # at 80%
    over: bool  # at 100%
    # Turns on a model with no price (or a CLI, or nothing reported): not in `spent`.
    unpriced_runs: int


class UsageOut(BaseModel):
    """Each list has what was spent most first."""

    by_model: list[ModelUsage]
    by_conversation: list[ConversationUsage]
    by_start: list[StartUsage]


class DayFile(BaseModel):
    path: str
    # The last change of the day to it: what "View" opens.
    change_id: str


class DayFailed(BaseModel):
    run_id: str
    error: str | None


class DayConversation(BaseModel):
    conversation_id: str
    title: str
    turns: int
    changed_files: int
    failed: int
    files: list[DayFile]
    failed_runs: list[DayFailed]


class DayOut(BaseModel):
    """A project's day, counted from the record (slice 56): no model is asked."""

    turns: int
    # The names of the agents that worked, each once.
    agents: list[str]
    # The files changes of the day reached in the project, each once.
    changed_files: list[str]
    # What waits for the user now, in every conversation, as the board counts it.
    waiting: int
    failed: int
    # None where no agent reported any; `tokens_at_least` where one reported nothing or part.
    input_tokens: int | None
    output_tokens: int | None
    tokens_at_least: bool
    # From the user's prices; None unless every model that ran has one, in one currency.
    cost: CostOut | None
    # Those with a turn of the day: the latest first.
    conversations: list[DayConversation]


class DayWordsIn(BaseModel):
    since: datetime
    # Whose model is asked.
    conversation_id: str
    # The user's word to ask it though the project is over this month's budget.
    over_budget: bool = False


class DayWordsOut(BaseModel):
    """The day in words: a model's text, not KOLONİ's count."""

    text: str
    provider_name: str
    model_id: str | None


class RecordEnded(BaseModel):
    """How the agents of a row ended. `stopped_by_koloni`: a limit, a rule or a count of
    KOLONİ's own stopped it; every other failure - a model's, a setup's - is `failed`."""

    done: int
    failed: int
    stopped_by_koloni: int
    stopped_by_user: int
    interrupted: int


class RecordChanges(BaseModel):
    taken: int
    rejected: int


class RecordCompared(BaseModel):
    chosen: int
    not_chosen: int


class RecordRediscovery(BaseModel):
    """K-devir-0: the reads its sub-agents made before their first write, on average, over
    the `agents` of the row that have it on record."""

    mean: float
    agents: int


class RecordRow(BaseModel):
    """What was measured of the agents of one role on one provider and model (`app.record`):
    counts, and the middle one of their steps, seconds and tokens - None unless every agent
    of the row has it on record. No score."""

    role_name: str
    provider_name: str | None
    model_id: str | None
    agents: int
    ended: RecordEnded
    steps: float | None
    seconds: float | None
    input_tokens: float | None
    output_tokens: float | None
    changes: RecordChanges
    # Its Leads that were a side of a comparison the user decided (slice 54): chosen, or not.
    compared: RecordCompared
    # None where no agent of the row has its reads before the first write on record.
    rediscovery: RecordRediscovery | None
    # K-model-puan: jobs done with nothing of them turned down; jobs whose changes the user
    # (or an unwatched turn) turned down as a whole; the middle one of what they cost, as
    # the Usage page prices it - None unless every agent of the row has a whole cost.
    taken_in: int
    turned_down: int
    cost: CostOut | None


class SkillRecordRow(RecordRow):
    """K-skill-puan: a row of the agents given one skill (`app.record.rows` by_skill), and
    how many of them read it whole, and (R190) how many were given it whole in their brief;
    the rest only had it."""

    skill: str
    used: int
    in_brief: int


class RecordOut(BaseModel):
    rows: list[RecordRow]
    skills: list[SkillRecordRow]


class LimitWindow(BaseModel):
    # What the CLI calls the window, where it names it; how long it is, where that is known.
    name: str | None
    minutes: int | None
    # None for a window that has reset since it was read (`stale`): never shown as a zero.
    used_percent: float | None
    resets_at: datetime | None
    stale: bool
    # When this window was read, where that is before the reading's own `read_at`: a newer
    # reading did not name it (B-74). None: as the reading.
    read_at: datetime | None = None
    # An API's window (slice 73): how many it allows, and how many are left of them, as its
    # answer's headers said. None: not said (every CLI's).
    limit: int | None = None
    remaining: int | None = None


class LimitCredits(BaseModel):
    balance: str | None
    has_credits: bool | None
    unlimited: bool | None


class LimitsOut(BaseModel):
    """What is left of the plan of the account a CLI is signed in to - or why that is
    not known (`unknown`), and then nothing else."""

    unknown: str | None = None
    read_at: datetime | None = None
    # Why it could not be read afresh just now: the rest is the last good reading.
    failed: str | None = None
    # Where Claude Code said it: "its last run" (a run of its own here), "a short run to
    # read it" (Read now) or "your Claude Code session" (the user's own, its status line).
    source: str | None = None
    plan: str | None = None
    windows: list[LimitWindow] = []
    credits: LimitCredits | None = None
    # A plan key's quota was used up (its 429), seen at `read_at`: what is left is not said.
    used_up: bool | None = None


class ClaudeSessionSetupOut(BaseModel):
    """The status line command the user adds to their Claude Code settings, and the
    script of KOLONİ's it runs."""

    command: str
    script: str


Priority = Literal["high", "normal", "low"]


class BacklogTaskOut(Out):
    """A task of a project's backlog (`app.backlog`)."""

    id: str
    title: str
    detail: str | None
    criteria: str | None
    priority: Priority
    status: Literal["proposed", "todo", "doing", "review", "done", "blocked"]
    position: int
    # The conversation "Work the backlog" started it in.
    conversation_id: str | None
    created_by: Literal["user", "agent"]
    # A change an agent proposed and the user has not decided on: the fields it would set.
    pending: dict | None
    # An agent's view of how the work compares with the criteria: an opinion, not a status.
    assessment: str | None
    # Waiting for review, with work of its chat not in the project yet (`backlog.not_in`):
    # read by the backlog's list only, false elsewhere.
    not_in: bool = False
    # K-symphony: the tasks it waits for (until each is done), whether Run the backlog took it,
    # and why it is stuck (status blocked) - `BacklogTask.flow`.
    after: list[str] = []
    queued: bool = False
    stuck: str | None = None
    # Doing, its turn waiting for the user's word now (`backlog.waiting`): the list's only.
    waiting: bool = False
    # Proposed by the Assistant PO at a turn's end (`BacklogTask.po`); None: not its.
    po: "BacklogPoOut | None" = None


class BacklogPoOut(BaseModel):
    chat: str
    # The words of the turn's record the proposal came from.
    why: str
    # At Full auto, the Lead's word on it and why; `seen`: the user's OK of that word.
    lead: Literal["add", "no"] | None = None
    lead_why: str | None = None
    seen: bool = False
    # The injection rules its words break (`app.injection`): the Lead adds none of those.
    injection: list[str] = []


class BacklogTaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=4000)
    criteria: str | None = Field(default=None, max_length=4000)
    priority: Priority = "normal"


class BacklogTaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=4000)
    criteria: str | None = Field(default=None, max_length=4000)
    priority: Priority | None = None
    # Not "proposed": only an agent proposes.
    status: Literal["todo", "doing", "review", "done", "blocked"] | None = None
    # Its place: before the task that has this place now (after them all if none has).
    position: int | None = Field(default=None, ge=0)
    # The tasks of its project it waits for (K-symphony): [] waits for none.
    after: list[str] | None = Field(default=None, max_length=50)


class BacklogDecideIn(BaseModel):
    decision: Literal["approve", "reject"]


class BacklogNextOut(BaseModel):
    """The first task Run the backlog started, and its conversation; None when none started
    at once (as many are at work as may be: the rest start as they end)."""

    task_id: str | None
    conversation_id: str | None


class BacklogAutoIn(BaseModel):
    on: bool


class BacklogChoiceIn(BaseModel):
    """The level and the model the chats the backlog opens start with (B-350), whole: no
    provider is the default one, no model its default model."""

    permission_mode: PermissionMode
    provider_id: str | None = Field(default=None, max_length=32)
    model_id: str | None = Field(default=None, max_length=200)
    # K-r144: who changes the files there; None: as the project's new chats.
    lead_work: LeadWork | None = None


class BacklogDrafter(BaseModel):
    why: str | None
    provider_id: str | None = None
    model_id: str | None = None


class BacklogAutoOut(BaseModel):
    """Whether the backlog works itself, and why its run is paused or last stopped (or None);
    and the level and the model the chats it opens start with (`BacklogChoiceIn`)."""

    on: bool
    halt: str | None
    permission_mode: PermissionMode
    provider_id: str | None
    model_id: str | None
    lead_work: LeadWork
    # Why no backlog task can run on the provider its chats would use, or None: one with tools
    # of its own (Run the backlog and by itself are refused while it holds).
    cannot_run: str | None
    # Who "Write it with the Product owner" asks (`api.backlog._drafter`): its provider and
    # model (None: its default), or why nobody is asked now.
    drafter: BacklogDrafter | None = None


class BacklogDraftIn(BaseModel):
    # (The page's title and detail, a line apart.)
    text: str = Field(min_length=1, max_length=4201)


class BacklogDraftOut(BaseModel):
    """A model's tasks from the user's note, saved nowhere: each is added by the user's word."""

    tasks: list[BacklogTaskIn]
    by: str


class AwayJobIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    line: str | None = Field(default=None, max_length=4000)
    team: str | None = None
    recipe: str | None = None
    task_id: str | None = None  # the To-do list's task the job is (B-409); None: a new one


class AwayIn(BaseModel):
    """The user's changes to a "While you're away" card before its Start (slice 106)."""

    jobs: list[AwayJobIn] | None = Field(default=None, min_length=1, max_length=10)
    kept_out: list[str] | None = Field(default=None, max_length=20)
    until: str | None = None  # HH:MM; null: no time limit
    money: float | None = Field(default=None, ge=0)  # null: no money limit


class AwayAsk(BaseModel):
    """What a waiting job's turn asks: `kind` the endpoint that answers it with yes or no
    (/api/{kind}/{id}/approve), or None - answered in its chat."""

    kind: Literal["commands", "file-changes", "web-requests", "agents"] | None
    id: str
    text: str


class AwayTried(BaseModel):
    task_id: str | None
    what: str


class AwayJobOut(BaseModel):
    """A job of the card, and once started how it stands: next (not started), working,
    waits, done, failed or stopped (cut by the night's time, money or Stop all: B-148); `why`
    says why it waits, failed or stopped."""

    title: str
    line: str | None
    team: str | None
    recipe: str | None
    task_id: str | None = None
    conversation_id: str | None = None
    state: Literal["planned", "next", "working", "waits", "done", "failed", "stopped"] = "planned"
    why: str | None = None
    # The Assistant product owner's view (slice 52b), as on its task.
    assessment: str | None = None
    # Its work kept for the user's Take in: the kept copies, and the files in them.
    kept: list[str] = []
    files: list[str] = []
    # The files of its work the user took into the project (B-123).
    taken: list[str] = []
    # The files another done job of the night changed too: joined line by line at Take in.
    shared: list[str] = []
    # The files its copy changed in a place the user kept out: theirs to look at first.
    kept_out: list[str] = []
    asks: list[AwayAsk] = []
    # What its reviews last said, as far as its agents reported: "Reviewer: no findings".
    checks: list[str] = []
    # What it does right now, while it works (slice 84d's words): "Coder · editing a.py".
    now: str | None = None
    spent: float | None = None


class AwayOut(BaseModel):
    """A "While you're away" card and its night (`app.away`)."""

    id: str
    project_id: str
    conversation_id: str
    run_id: str
    status: Literal["planned", "running", "ended", "dismissed"]
    jobs: list[AwayJobOut]
    kept_out: list[str]
    until: datetime | None
    money: float | None
    started_at: datetime | None
    ended_at: datetime | None
    why: str | None
    # When its report was first on screen; None: not yet (the morning's canvas goes to it).
    seen_at: datetime | None
    # What tried a place kept out, refused at night; and what a job's copy changed there all
    # the same (a command that wrote there without naming it), found in the morning.
    tried: list[AwayTried]
    slipped: list[AwayTried] = []
    # What its jobs spent since it started, at the user's prices; None: not known.
    spent: float | None
    # The prices' currency (USD where none is set): the money limit's too.
    currency: str
    # The longest one job works before it is cut.
    job_minutes: int | None  # (B-413: None, no ceiling)
    # The provider the jobs' Lead runs on where it is a plan: no money is counted there.
    on_plan: str | None = None
    at_least: bool
    counts: dict[str, int]
    # What agents proposed for the To-do list while it ran: not started, the user's to keep.
    proposed: list[BacklogTaskOut]


SnapshotOut.model_rebuild()  # (its cards are defined above)


class LocalServerIn(BaseModel):
    """The model server on this machine, as the Models page sets it (slice 64): the program
    and its arguments, one by one - never a line for a shell."""

    executable: str = Field(min_length=1, max_length=4096)
    args: list[Annotated[str, Field(max_length=4096)]] = Field(max_length=500)


class LocalServerGpu(BaseModel):
    """The graphics card, as nvidia-smi says it: MiB and %, None where it does not say."""

    memory_used: int | None
    memory_total: int | None
    load: int | None
    share: int | None  # the server's own memory


class LocalServerOut(LocalServerIn):
    """It, how it is now, and what it printed (masked). `models`: the `.gguf` files in the
    program's `models` folder. `model`, `n_ctx` and `gpu` only while it runs, None where
    unknown."""

    models: list[str]
    state: Literal["stopped", "running", "exited"]
    exit_code: int | None
    model: str | None
    n_ctx: int | None
    gpu: LocalServerGpu | None
    output: str


class RestoreOut(BaseModel):
    """A restore staged for the next start (`app.backup`): when its export was made, whether
    it holds the secrets, and what needs its key again where it does not."""
    made_at: str | None
    secrets: bool
    need_keys: list[str]


class StagedOut(BaseModel):
    """The restore that waits for the next start (None: none does), and where the newest
    one a start could not apply is kept (None: none is)."""
    staged: RestoreOut | None
    failed: str | None
