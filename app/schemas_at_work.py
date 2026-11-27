"""What the user says to a turn and its agents while they work: a message (`MessageIn`, with
what is asked of its spoken answer) and a word to one agent (`TellIn`) - moved here from
`app.schemas` to make room there."""

from pydantic import BaseModel, ConfigDict, Field


class SpokenIn(BaseModel):
    """What a message asks of the lead's answer when the user listens to it (slice 32a)."""

    model_config = ConfigDict(extra="forbid")
    # A language tag as the browser's voices give it: "en-US", "tr-TR", "en-GB-x-rp".
    # (The page holds the same pattern: voice.ts LANGUAGE_TAG.)
    language: str = Field(pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,4}$")
    # How the user wants it said, in their own words.
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


class TellIn(BaseModel):
    """The user's own word to an agent while it works (89d C)."""

    model_config = ConfigDict(extra="forbid")
    words: str = Field(min_length=1, max_length=4000)
