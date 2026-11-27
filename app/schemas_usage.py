"""The Usage page's rows beside `app.schemas` (that file is at its size limit): what a set of
agents reported, by model, chat, starter and day."""

from typing import Literal

from pydantic import BaseModel

from app.schemas import CostOut


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
    # What Copilot said it spent in its own units, added up: AI credits in billionths,
    # premium requests. None where it said nothing - not a zero.
    nano_aiu: int | None = None
    premium_requests: float | None = None


class ConversationUsage(UsageRow):
    conversation_id: str
    project_id: str | None  # None: a plain chat's
    title: str
    # Its models' costs added up, as a starter's; None where none of them has one.
    cost: CostOut | None = None


class DayUsage(UsageRow):
    day: str  # YYYY-MM-DD, by this machine's clock
    # Its models' costs added up, as a starter's; None where none of them has one.
    cost: CostOut | None


class StartUsage(UsageRow):
    # "koloni": what KOLONİ asked a model itself with no turn (the day's words, a recipe's
    # draft, a role's guide, a Check that runs a CLI) - in no message.
    started_by: Literal["user", "trigger", "koloni"]
    # Its models' costs added up, as a budget adds them; None where none of them has one.
    cost: CostOut | None


class UsageOut(BaseModel):
    """Each list has what was spent most first."""

    by_model: list[ModelUsage]
    by_conversation: list[ConversationUsage]
    by_start: list[StartUsage]
    # The days anything ran in the period, the first first.
    by_day: list[DayUsage]
