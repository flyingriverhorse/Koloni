"""☾ Away's request and response shapes beside `app.schemas` (that file is at its size limit; it
imports these back for `AwayOut`)."""

from typing import Literal

from pydantic import BaseModel, Field


class AwayGoIn(BaseModel):
    """The user's Go away (☾ Away): the To-do tasks ticked, the panel's order of the list, the
    places kept out and the limits - none unless named."""

    task_ids: list[str] = Field(default=[], max_length=10)
    order: list[str] = Field(default=[], max_length=200)
    until: str | None = None  # HH:MM; null: no time limit
    money: float | None = Field(default=None, ge=0)  # null: no money limit
    kept_out: list[str] = Field(default=[], max_length=20)


class AwayAsk(BaseModel):
    """What a waiting job's turn asks: `kind` the endpoint that answers it with yes or no
    (/api/{kind}/{id}/approve), or None - answered in its chat."""

    kind: Literal["commands", "file-changes", "web-requests", "agents"] | None
    id: str
    text: str


class AwayTried(BaseModel):
    task_id: str | None
    what: str


class AwayBranchOut(BaseModel):
    """0.1.9: a job's branch as its turn left it (`away_branch.row`) - its name, its commit and
    the branch it was made from, its commits and files since, KOLONİ's checks' verdict, origin's
    address (never its password) and what moved outside it meanwhile (H2); `why`: what git said
    where it could not look at the branch."""

    name: str | None
    from_head: str | None = None
    tip: str | None
    into: str | None
    why: str | None = None
    commits: int | None
    files: int | None
    checks: Literal["green", "red", "not complete"] | None
    origin: str | None
    moved: list[str] = []


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
    # The Scout's view (slice 52b), as on its task.
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
    # 0.1.9: how it works on the project - in a copy, on a branch, pushed in the morning too -
    # and why in a copy where git is there; its branch once its turn ended.
    mode: Literal["copy", "branch", "push"] | None = None
    mode_why: str | None = None
    branch: AwayBranchOut | None = None
