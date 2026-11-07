"""The team guide: the providers agents may choose for a sub-agent, as the user described
them. What an agent is shown and what is accepted from it are both made from the same
entries, and an entry holds nothing an agent must not see (no address, no key)."""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from math import inf
from typing import Any

from sqlalchemy.orm import Session

from app import catalog
from app.api.usage import over_limit
from app.db.models import Conversation, Provider, Role
from app.limits import plan_used
from app.model_native import CopilotNativeClient
from app.providers import (
    CLI_NAMES,
    HTTP_KINDS,
    IMAGE_CLIS,
    TIERS,
    ClosedToAgents,
    NotListed,
    Providers,
    Source,
    allowed,
    down_now,
    is_on,
    list_providers,
    mode_of,
    resolved,
    works_with_own_tools,
)
from app.roles import LEAD, LEAD_KIND, shown_name

KIND_NAMES = {
    "openai_compat": "OpenAI-compatible server", "anthropic": "Anthropic API", **CLI_NAMES,
}
# How a provider works, in fixed words: these are KOLONİ's, never the user's.
RUNS_API = "API"
RUNS = {
    "step": "one step at a time", "session": "as a session, KOLONİ's tools",
    # How it is started, which is all KOLONİ knows: the user's own settings for that CLI
    # can give leave for more, so "changes nothing" is not said as a fact.
    "reads": "reads with its own tools; started without leave to write or run",
}
RUNS_OWN_ASKS = "with its own tools, asks first"
RUNS_OWN = "with its own tools, needs Full auto"
# The CLIs that ask KOLONİ for leave before a tool of their own acts (Codex over its
# app-server: slice 89a; agy through its hook: 89e). Not Copilot: its sandboxed commands were
# seen to run unasked (R96). Codex looks at files only by running commands: a role short of
# the write and command tools was refused it until B-301, which starts it read-only for such
# a role, with KOLONİ's read tools over the bridge (`reads_only`).
ASKS_FIRST = ("claude_cli", "codex_cli", "agy_cli", "qoder_cli")  # (Qoder: or it is stopped)
# What a CLI that works with its own tools, and does not ask first, does whatever it is
# offered: only a role allowed all of these may work that way.
NATIVE_NEEDS_TOOLS = ("write_file", "edit_file", "run_command")
PICK_NEEDS_FULL_AUTO = (
    "{provider} cannot be chosen now: it works with its own tools and cannot ask before it "
    "writes or runs something, so it only runs at the Full auto permission level, which is "
    "the user's to set. Choose another model, or leave provider out."
)
PICK_NEEDS_THE_TOOLS = (
    "{provider} cannot be chosen for the {role} role: there the CLI uses its own tools, "
    "which write files and run commands, and this role is not allowed to do both. Choose "
    "another model, or leave provider out."
)
# B-385: a sub-agent left with only a model the user closed to agents (`closed_to_agents`) - also
# on a fresh install, whose CLIs start closed: what to do is said with it, to the user too.
CLOSED_TO_AGENTS = ("{role} can't open: {what} open to agents. Tick \"Agents may use\" on the "
                    "Models page.")
PICK_AN_OPEN_ONE = " Or pick a provider open to agents from the team guide."


# Why a role's agent is no recipe's step where it runs (`only_in_project`): said as one is
# opened, and on the Agents page before (B-89, `/roles/models`).
ONLY_IN_THE_PROJECT = ("{provider} works with tools of its own in the project itself: a recipe's "
                       "work stays in its copy until the user takes it in. Open a role that runs "
                       "elsewhere for this step")


@dataclass(frozen=True)
class Entry:
    """One provider an agent may choose, with what the user said about it."""

    provider_id: str
    name: str
    kind: str
    runs: str
    note: str | None
    models: tuple[tuple[str, str | None], ...]  # (name, the user's note on it)
    default: str | None
    # "Only these models" is on and the provider's own default is not one of them: it
    # cannot run without a model being named.
    must_name: bool = False
    # Of `models`, the ones the user gave a tier, in the list's order: (name, tier).
    tiers: tuple[tuple[str, str], ...] = ()
    # Of `tiers`, the place the user gave each in its tier's order (app.api.tiers): (name, place).
    places: tuple[tuple[str, int], ...] = ()
    # Of `models`, those whose note is the catalogue's - none of the user's, or the one a fill
    # copied from the catalogue - with the day it was read: (name, note, day).
    catalogue: tuple[tuple[str, str, str | None], ...] = ()
    # Of `models`, what each is known to take besides text, in words (slice 85b): (name,
    # "sees images and video").
    sees: tuple[tuple[str, str], ...] = ()

    def allows(self, model: str) -> bool:
        """Whether an agent may name this model: one from the list, exactly as written,
        or the provider's default."""
        return model == self.default or any(model == name for name, _note in self.models)

    def selectable(self) -> list[str]:
        names = [name for name, _note in self.models]
        return names if self.default is None or self.default in names else [*names, self.default]


def _runs(provider: Provider) -> str:
    # As when its client is built: a mode this kind cannot run in is its default one.
    mode = mode_of(provider)
    if mode is None:
        return RUNS_API
    if mode == "native":
        return RUNS_OWN_ASKS if provider.kind in ASKS_FIRST else RUNS_OWN
    return RUNS[mode]


def guide(providers: Iterable[Provider], copy: dict | None = None) -> list[Entry]:
    """The providers the user lets agents choose, in the user's order. `copy`: the
    models.dev copy the catalogue's notes are read from (the shipped one if none)."""
    entries = []
    for provider in providers:
        # Only the models agents may use (slice 81a) and the user left on; a list of none of
        # them leaves it out, as one switched off is.
        mine = [m for m in provider.models or []
                if m.get("agents", True) and m.get("enabled", True)]
        if not provider.for_agents or provider.enabled is False or (provider.models and not mine):
            continue
        models = tuple((m["name"], m.get("note")) for m in mine)
        known = {row["name"]: row for row in catalog.models_for(
            catalog.catalogue_of(provider.kind, provider.base_url, copy), copy, provider.name)}
        # The user's own note wins. None, or one of the catalogue's tier notes word for word (a
        # fill copied it): the catalogue's note for the tier the row has now, with its day.
        noted = []
        for m in mine:
            note, entry = m.get("note"), known.get(m["name"], {})
            if note not in (None, *catalog.NOTES.values()) or not (note or entry):
                continue  # the user's own, or a model the catalogue has nothing on
            said = catalog.NOTES.get(m.get("tier") or entry.get("tier") or "", note)
            if said:
                day = (entry.get("source") or {}).get("read_on")
                noted.append((m["name"], said, (day or "")[:10] or None))
        # What is shown is what would run: a default the provider may not run with is
        # not offered as one.
        # (Nor is one the user said agents may not use.)
        off = [m["name"] for m in provider.models or [] if m not in mine]
        held = (bool(provider.only_listed) and provider.default_model not in [
            name for name, _note in models
        ]) or provider.default_model in off or (
            # (The Anthropic API has no default of its own: `allowed`.)
            provider.kind == "anthropic" and not provider.default_model)
        entries.append(Entry(
            provider_id=provider.id,
            # A name from before names were checked is shown, and chosen, without what
            # does not print.
            name=shown_name(provider.name),
            kind=KIND_NAMES.get(provider.kind, provider.kind),
            runs=_runs(provider),
            note=provider.note,
            models=models,
            default=None if held else provider.default_model,
            must_name=held,
            tiers=tuple((m["name"], m["tier"]) for m in mine if m.get("tier")),
            places=tuple((m["name"], m["order"]) for m in mine if m.get("tier") and "order" in m),
            catalogue=tuple(noted),
            # (A CLI's model is said to see only what its CLI is given: images, `IMAGE_CLIS`.)
            sees=tuple((m["name"], words) for m in mine if (
                words := catalog.inputs_words({
                    kind: said for kind, said in catalog.inputs(provider, m["name"], copy).items()
                    if provider.kind in HTTP_KINDS
                    or provider.kind in IMAGE_CLIS and kind == "image"}))),
        ))
    return entries


# How hard a message is said to be, in the order of `TIERS`: for a lead whose model follows
# the message, the tier it runs at.
DIFFICULTY = ("easy", "normal", "hard")


def tier_of(provider: Provider, model: str | None) -> str | None:
    """The tier the user gave this model of this provider; None where they gave none."""
    return next((m.get("tier") for m in provider.models or [] if m["name"] == model), None)


# A role's tier rule that is no tier: it runs on the conversation's model, as before 81b.
CONVERSATION = "conversation"


def nth_choice(n: int) -> str:
    """A place in the role's list of models, as the record says it: "2nd choice". (The list
    holds five at most: no 11th.)"""
    return f"{n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'} choice"


def place_of(role: Role | None, found: tuple["Entry", str | None]) -> int:
    """Where this model stands in the role's list, counted as the user wrote it (1 first) -
    an entry passed over for a reason still counts. (The model is on the list: the callers
    found it there.)"""
    return next(i for i, one in enumerate((role.models if role else None) or [], 1)
                if (one["provider_id"], one["model_id"]) == (found[0].provider_id, found[1]))


def tier_range(role: Role) -> list[str]:
    """The tiers the Lead may give a job of this role, lowest first: the user's "Always X",
    none where its rule is the conversation's model, or from `tier_min` to `tier_max`."""
    if role.tier == CONVERSATION:
        return []
    if role.tier:
        return [role.tier]
    return list(TIERS[TIERS.index(role.tier_min or TIERS[0]):
                      TIERS.index(role.tier_max or TIERS[-1]) + 1])


def tier_for(role: Role | None, asked: str | None = None) -> str | None:
    """The tier an agent of this role runs at where it has no model of its own: `asked`, the
    tier its opener gave the job, if the role's rule allows it; with none, balanced or the
    nearest end of the range. ValueError says what is allowed. None for the Lead without a
    tier: it runs on the conversation's model, which the chat's picker decides."""
    if role is None or (role.builtin and role.name == LEAD and not role.tier):
        return None
    if role.tier == CONVERSATION:
        if asked is not None:
            raise ValueError(f"the {role.name} role runs on the conversation's model: that is "
                             "the user's rule. Leave tier out.")
        return None
    allowed = tier_range(role)
    if asked is None:
        middle = TIERS.index("balanced")
        return min(allowed, key=lambda tier: abs(TIERS.index(tier) - middle))
    if asked in allowed:
        return asked
    if role.tier:
        raise ValueError(f"the {role.name} role always runs on the {role.tier} tier: that is "
                         "the user's rule. Leave tier out.")
    raise ValueError(f"the {role.name} role may be given {allowed[0]} to {allowed[-1]}: "
                     f"choose one of {', '.join(allowed)}, or leave tier out.")


def outside_rule(role: Role, provider: Provider, model: str | None) -> str | None:
    """Why a model named for an agent of this role - a provider and model picked, or the one
    an earlier agent ran on - is not one its tier rule allows, in `tier_for`'s words; None
    where it is, where the rule is the whole range, or the role has a model of its own. A
    team's lead on the conversation's model (0083) is held to none, as the Lead: that is
    where it runs by default, not all it may be given."""
    if role.provider_id or len(tier_range(role)) == len(TIERS) or (
            role.kind == LEAD_KIND and role.tier == CONVERSATION):
        return None
    try:
        tier_for(role, tier_of(provider, model) or "untiered")
    except ValueError as exc:
        return str(exc)
    return None


@dataclass(frozen=True)
class Would:
    """What an agent of a role would run on now, where that comes from ("role", "tier",
    "conversation" or "default"), and the entries an agent may pick for it instead."""

    provider: Provider
    model_id: str | None
    source: Source
    pick_from: list[Entry]
    # Why no agent of the role is opened on that now: its provider may not run that
    # model ("Only these models"). None when it may.
    refused: NotListed | None = None
    # Of the team guide (not `pick_from` alone: the role's list is judged too), the providers
    # a pick could not open at the conversation's permission level, by name: why, as the
    # agent that picks one is told.
    cannot_pick: dict[str, str] = field(default_factory=dict)
    # Why an agent of the role would not work on that now though it is opened there: the
    # provider is itself one a pick could not open, in the same words. For the table
    # only - `spawn_agent` opens such an agent, and it fails at its start.
    cannot_open: str | None = None
    # The tier whose first model was looked for (`tier_for`); None: none was.
    tier: str | None = None
    # Slice 81c. Of the team guide, by name: the providers past their limit of spend
    # (`over_limit`'s why), and the subscriptions past their step-down share (`plan_used`'s).
    past_limit: dict[str, str] = field(default_factory=dict)
    plan_used: dict[str, str] = field(default_factory=dict)
    # Of the team guide, by name: the providers that looked down when last read (`looked_down`).
    down: dict[str, str] = field(default_factory=dict)
    # The tiers a pick may step down to: the role's rule (`tier_range`).
    steps: tuple[str, ...] = ()
    # Why the tier's model is not its first one (`pick`); None: it is, or there was none.
    moved: str | None = None
    # Whether `moved` names those `cannot_pick` passed over: not for the Lead, whose row
    # shows a reason as the guess of how hard the message is.
    # shortcut: its other reasons (a limit, a provider down) are shown so too; give the
    # Lead's row a label of its own for them if that misleads.
    says_blocked: bool = True
    # K-rol-model-sirasi: the role's own list of models (`Role.models`) in the user's order,
    # less those whose provider is not in the team guide now. Tried before the tier, each
    # as `_with_room` tries the tier's; `_moved_on` moves along it and then the tier's.
    preferred: tuple[tuple[Entry, str], ...] = ()

    def tried(self, tier: str, blocked_too: bool = False) -> list[tuple[Entry, str]]:
        """The models the user gave this tier among what may be picked for the role now, in
        the tier's order the user set (app.api.tiers); those never ordered after them,
        providers in the user's order, then the models of one in its list's order.
        `blocked_too`: and those `cannot_pick` holds back."""
        found = [
            (entry, name) for entry in self.pick_from
            if blocked_too or entry.name not in self.cannot_pick
            for name, its in entry.tiers if its == tier
        ]
        # (`sorted` keeps equal places as they were: the order before the user set one.)
        return sorted(found, key=lambda one: dict(one[0].places).get(one[1], inf))

    def _with_room(
        self, tried: list[tuple[Entry, str]]
    ) -> tuple[tuple[Entry, str] | None, list[str]]:
        passed, down, first_down = [], [], None
        for entry, name in tried:
            if entry.name in self.cannot_pick:
                # Said too (B-76: Codex passed over for a role with no commands, unsaid):
                # its first sentence, "Codex cannot be chosen for the Reviewer role".
                why = self.cannot_pick[entry.name].split(":")[0]
                if self.says_blocked and why not in passed:
                    passed.append(why)
            elif entry.name in self.past_limit:
                if self.past_limit[entry.name] not in passed:  # (once for a provider's models)
                    passed.append(self.past_limit[entry.name])
            elif entry.name in self.down:
                first_down = first_down or (entry, name)
                if self.down[entry.name] not in down:
                    down.append(self.down[entry.name])
            else:
                return (entry, name), passed + down
        # Every one past its limit: none of the tier is had. Of those that looked down the
        # first is still tried: what was read of them may be old.
        return first_down, passed

    def pick(self, tier: str) -> tuple[tuple[Entry, str] | None, str | None]:
        """The tier's first model in the user's order whose provider is not past its limit,
        and why it is not the first: a subscription past its step-down share gives the
        model one tier lower instead, where the role's rule allows that tier and one of it
        is had. The rule is the user's and wins: "Always X" allows that tier alone, and a
        role with a model of its own is never given a tier at all."""
        found, passed = self._with_room(self.tried(tier, blocked_too=True))
        if not found:
            # B-314: none of the tier had - why, where one was passed over, for `would_run` to
            # say where it runs instead. (None where no model has the tier at all.)
            return None, "; ".join(passed) or None
        said = [f"{'; '.join(passed)}: the next {tier} model"] if passed else []
        at = TIERS.index(tier)
        lower = TIERS[at - 1] if at > 0 and TIERS[at - 1] in self.steps else None
        if lower and found[0].name in self.plan_used:
            # K-claude-hesap: lower on the same plan, or on another kind - never another account
            # of the same CLI to get past this one's share (`limits.another_account`).
            # shortcut: one of that CLI on the user's own model server is passed over too.
            below, passed = self._with_room([
                one for one in self.tried(lower, blocked_too=True)
                if not another_account_of(one[0], found[0])])
            if below:
                said = [f"{self.plan_used[found[0].name]}: {lower} instead of {tier}"]
                said += [f"{'; '.join(passed)}: the next {lower} model"] if passed else []
                found = below
        return found, "; ".join(said) or None

    def first(self, tier: str) -> tuple[Entry, str] | None:
        return self.pick(tier)[0]


def another_account_of(one: Entry, of: Entry) -> bool:
    """K-claude-hesap: whether `one` is another provider of `of`'s CLI - another account of
    it - never stepped to past `of`'s plan share (an API kind's are other services)."""
    return one.provider_id != of.provider_id and one.kind == of.kind and of.kind.endswith("_cli")


def not_listed(provider: Provider, model: str | None) -> NotListed | None:
    """Why this provider may not run with this model (`allowed`), or None."""
    try:
        allowed(provider, model)
    except NotListed as exc:
        return exc
    return None


def cannot_pick(
    unasked: bool, provider: str, mode: str, tools: Iterable[str], role: str,
    looks_by_running: bool = False,
) -> str | None:
    """Why a provider cannot be picked for a sub-agent of a role, at a permission level
    and with the tools that agent would have - or None. `unasked`: it is a CLI at work
    with its own tools that neither asks KOLONİ first nor only reads; `looks_by_running`:
    one that asks, but looks at files only by running commands, and is not started
    read-only for these tools (`reads_only`). Nothing stands in the way of any other."""
    if unasked and mode != "full_auto":
        return PICK_NEEDS_FULL_AUTO.format(provider=provider)
    if (unasked or looks_by_running) and not all(tool in tools for tool in NATIVE_NEEDS_TOOLS):
        return PICK_NEEDS_THE_TOOLS.format(role=role, provider=provider)
    return None


def reads_only(model: object, tools: Iterable[str]) -> bool:
    """B-301: whether an agent with these tools works read-only on this model's side: a CLI at
    work with tools of its own that can be started so (`starts_read_only`: Codex, Copilot, agy
    reading - not Claude Code, whose own writes are asked as they come), for a role not allowed
    all of NATIVE_NEEDS_TOOLS. Its own writes are refused then, and it writes only with KOLONİ's
    write tools over the bridge, where KOLONİ decides. A role that runs commands is had so only
    where they run in a read-only sandbox (`read_only_commands`: Codex's); elsewhere they could
    write."""
    has = set(tools)
    # (Nor a role that writes on one no bridge reaches - an agy older than B-310's: its document
    # would never be written, and it would say it was done.)
    return bool(getattr(model, "native", False) and getattr(model, "starts_read_only", False)
                ) and not set(NATIVE_NEEDS_TOOLS) <= has and (
        "run_command" not in has or bool(getattr(model, "read_only_commands", False))) and (
        bool(getattr(model, "collaborates", True)) or not {"write_file", "edit_file"} & has)


def only_in_project(model: object, tools: Iterable[str] | None = None) -> bool:
    """Whether an agent on this model works in the project whatever it is opened as: a
    CLI with tools of its own (KOLONİ does not make its changes) that is not one of
    those started in a working copy (`own_copy`: Claude Code, Codex and native agy). Such
    an agent is no recipe's step (`ONLY_IN_THE_PROJECT`). With the agent's `tools`: not one
    that works read-only (`reads_only`, B-301) - it changes nothing itself, and is started in
    its line's copy, where KOLONİ's write tools write for it."""
    return bool(getattr(model, "native", False)) and not getattr(model, "own_copy", False) and (
        tools is None or not reads_only(model, tools))


def would_run(  # noqa: C901
    session: Session, role: Role | None, conversation: Conversation | None,
    unattended: bool = False, tools: Iterable[str] | None = None, tier: str | None = None,
    step: Providers | None = None,
) -> Would:
    """The one place that says where a role's agent runs and what may be picked for it:
    a turn's lead, `spawn_agent` and a discussion's new member act on it, and the table
    of who uses what shows it. In this order: the role's list of models (K-rol-model-sirasi,
    `Role.models`) in the user's order, each passed over as a tier's model is - past its
    limit, down, not to be picked, gone from the guide - and only where its opener gave the
    job no tier; the role's own model; the first model of the tier `tier_for` gives
    (`tier`: the one its opener gave the job, already allowed - it wins over the list, as an
    opener's chosen model does) among what may be picked for the role; the conversation's
    model; the default provider. A model from a tier is not an agent's pick of a model, and
    a tier no model could be had from decides nothing. What may be
    picked is the team guide as it is now, less what the role does not let be picked -
    the guide is the most there ever is. It also says what stands in the way now: of the
    role's own model (`refused`, `cannot_open`), and of a pick (`cannot_pick`).

    What its caller knows of the agent goes into that: `unattended`, a turn nobody
    watches, and `tools`, what the agent will really have (never more than its opener may hand on).
    Left out: a turn the user watches and the role's own tools, which is what the table
    shows. A tier's model that could not run under them is passed over, and so (B-301) is a
    provider not the role's own that could not: the next one in the user's order is taken.
    `step`: the clients, where the agent is a recipe's step - a provider it would work in the
    project itself on (`only_in_project`) is passed over too, as `_propose` refuses it."""
    provider, model_id, source = resolved(session, role, conversation)
    providers = list_providers(session)
    whole = entries = guide(providers)
    if role is not None and role.pick_from is not None:
        entries = [entry for entry in entries if entry.provider_id in role.pick_from]
    # By how the provider is set up (a new conversation starts at Ask); `spawn_agent`
    # asks the client itself, which is built from the same settings.
    mode = conversation.permission_mode if conversation else "ask"

    has = (role.tools if tools is None else list(tools)) if role else []

    def in_step(one: Provider) -> str | None:
        if role is None or step is None or not only_in_project(
                step.client(one, one.default_model), has):
            return None
        return ONLY_IN_THE_PROJECT.format(provider=shown_name(one.name))

    def in_the_way(one: Provider) -> str | None:
        if role is None:
            return None
        # (No `looks_by_running`: Codex, the one that looks so, is started read-only for any
        # role short of NATIVE_NEEDS_TOOLS - B-301.)
        # shortcut: judged by the kind's table, not the client (`AgentRunner._needs_its_tools`);
        # `spawn_agent` judges the client again. Judge it here too if the two are seen to part.
        # B-314: but Copilot, the one kind that works so, is started with its view tool only for
        # a role short of the write and command tools (`reads_only`, B-301): no tools of its own
        # act unasked then. Its tier passed it over for such a role, onto the conversation's model.
        unasked = _runs(one) == RUNS_OWN and not reads_only(
            CopilotNativeClient if one.kind == "copilot_cli" else None, has)
        return in_step(one) or cannot_pick(unasked, shown_name(one.name), mode, has, role.name)

    by_id = {one.id: one for one in providers}
    # (Over the whole guide, not `entries`: the role's list is the user's rule, held to no
    # `pick_from`, and what stands in its way is read here too.)
    blocked = {
        entry.name: why for entry in whole if (why := in_the_way(by_id[entry.provider_id]))
    }
    would = Would(provider, model_id, source, entries, None, blocked)
    # With nobody watching no CLI at work with tools of its own runs at all
    # (`AgentRunner._cannot_be_held`): a tier does not land on one.
    held = {one.id for one in providers if unattended and works_with_own_tools(one)}
    # What stands in a tier's way (81c).
    past = {e.name: why for e in whole if (why := over_limit(session, by_id[e.provider_id]))}
    used = {e.name: why for e in whole if (why := plan_used(session, by_id[e.provider_id]))}
    looked = down_now(session)
    down = {e.name: f"{e.name} was {why} when last looked at"
            for e in whole if (why := looked.get(e.provider_id))}
    by_entry = {e.provider_id: e for e in whole}
    preferred, dropped = [], []  # (the role's list as it may be tried now, and why the rest not)
    for one in (role.models if role else None) or []:
        entry = by_entry.get(one["provider_id"])
        if entry is None:
            dropped.append("a model of the role's list is not in the team guide")
        elif one["provider_id"] in held:
            dropped.append(f"{entry.name} works with tools of its own, which nobody watches")
        elif (refused := not_listed(by_id[entry.provider_id], one["model_id"])) is not None:
            dropped.append(refused.to_agent.split(":")[0])
        elif closed_to_agents(by_id[entry.provider_id], one["model_id"]):  # (B-385)
            dropped.append(f"{entry.name}'s {one['model_id']} is closed to agents")
        else:
            preferred.append((entry, one["model_id"]))
    would = replace(would, past_limit=past, plan_used=used, down=down,
                    steps=tuple(tier_range(role)) if role else (),
                    says_blocked=role is None or role.name != LEAD, preferred=tuple(preferred))
    among = replace(would, pick_from=[e for e in entries if e.provider_id not in held])
    # The role's list first, where the opener gave no tier (the Lead's tier wins, as today).
    first, passed = among._with_room(preferred) if preferred and tier is None else (None, [])
    if tier is None:
        passed = [*dict.fromkeys(dropped), *passed]
    if first:
        nth = place_of(role, first)  # (role is not None: `preferred` came from its list)
        why = f"the role's {nth_choice(nth)}" if nth > 1 or passed else None
        return replace(
            would, provider=session.get_one(Provider, first[0].provider_id), model_id=first[1],
            source="role", moved=f"{'; '.join(passed)}: {why}" if passed else why)
    wanted = tier_for(role, tier) if source != "role" else None
    found, moved = among.pick(wanted) if wanted else (None, None)
    if not found and moved:
        moved += (": the conversation's model" if source == "conversation"
                  else ": the default provider")
    if passed:  # (none of the role's list had: why, then where it runs instead)
        moved = f"{'; '.join(passed)}: none of the role's models" + (f"; {moved}" if moved else "")
    would = replace(would, tier=wanted, moved=moved)
    if found:
        entry, model_id = found
        would = replace(
            would, provider=session.get_one(Provider, entry.provider_id), model_id=model_id,
            source="tier",
        )
    cannot = in_the_way(would.provider)
    if in_step(would.provider) and would.source != "role":
        # B-301: the conversation's or the first provider cannot be the recipe's step - the
        # next that can, in the user's order (of the role's own list), held to what a tier's
        # model is (a limit, a plan's share, the role's tier rule; one that looked down last),
        # and why said (`moved`). The role's own model is the user's rule: kept, and refused.
        fit = [e for e in among.pick_from if e.name not in blocked and e.name not in past
               and e.name not in used and not e.must_name
               and not (role and outside_rule(role, by_id[e.provider_id], e.default))]
        if would.provider.name in used and would.provider.id in by_entry:
            # (Past its plan's share: never another account of its CLI, as `pick`.)
            fit = [e for e in fit if not another_account_of(e, by_entry[would.provider.id])]
        then = next((e for e in fit if e.name not in down), fit[0] if fit else None)
        if then is not None and cannot:
            would = replace(would, provider=session.get_one(Provider, then.provider_id),
                            model_id=then.default, source="default",
                            moved=f"{cannot.split(':')[0]}: the next provider")
            cannot = None
    refused = not_listed(would.provider, would.model_id)
    if refused is None and role is not None and role.name != LEAD and would.source in (
            "conversation", "default") and closed_to_agents(would.provider, would.model_id):
        # B-385 (live): with no tier's model had, a sub-agent - a team's coordinator too, whose
        # rule is the conversation's model - fell back to the Lead's Copilot model, every one of
        # which the user had closed to agents. Never: it is not opened, and says why.
        # shortcut: no move onto another provider open to agents here (it may be paid per
        # token, which `_paid_for` does not ask about); add one, asked, if a refusal is felt.
        shown = shown_name(would.provider.name)
        said = CLOSED_TO_AGENTS.format(role=shown_name(role.name), what=(
            f"no model of {shown} is" if would.provider.id not in by_entry
            else f"{shown}'s {would.model_id} is not"))
        # (An agent that picks may still pick one that is open: it is told so, the user not.)
        refused = ClosedToAgents(said, said + (PICK_AN_OPEN_ONE if among.pick_from else ""))
    return replace(would, refused=refused, cannot_open=cannot)


def closed_to_agents(provider: Provider, model: str | None) -> bool:
    """B-385: whether the user closed this provider, or this model of it, to agents: it is not
    in the team guide (`guide`), or its model's row says agents may not use it. One switched off
    (`is_on`) is closed to them too."""
    rows = provider.models or []
    return not provider.for_agents or not is_on(provider, model) or (bool(rows) and not any(
        m.get("agents", True) and m.get("enabled", True) for m in rows)) or any(
        m["name"] == model and not m.get("agents", True) for m in rows)


def asked_how_hard(
    session: Session, would: Would, clients: Providers, tier: str = TIERS[0]
) -> tuple[Entry, str] | None:
    """Whom a lead whose model follows the message asks how hard it is: the first fast
    model that may be picked for the Lead (`would`) now and that can answer with every
    tool off. None: nobody is asked. What `AgentRunner._by_how_hard` acts on, and what
    the table of who uses what says. `tier`: another tier's first, for another request
    of KOLONİ's own (a recipe drawn: balanced)."""
    # shortcut: a fast model past its provider's limit of spend (81c) is still asked this one
    # short question; pass it over as `Would.pick` does if such a question is ever counted.
    for fast in would.tried(tier):  # in the tier's order, as the user set it
        client: Any = clients.client(session.get_one(Provider, fast[0].provider_id), fast[1])
        # As `ask_once` asks: a CLI at work with its own tools speaks with them off. One
        # that still has them then (agy reads where it likes however it is started) is
        # passed over: the user's message is not handed to it.
        if getattr(client, "native", False):
            client = client.talker()
        if not getattr(client, "native", False):
            return fast
    return None


def is_named(provider: Provider, name: str) -> bool:
    """Whether an agent means this provider by a name: spaces evened out, whatever the case."""
    return " ".join(name.split()).casefold() == shown_name(provider.name).casefold()


def find(entries: Iterable[Entry], name: str) -> Entry | None:
    """The entry an agent means by a name: spaces evened out, whatever the case."""
    wanted = " ".join(name.split()).casefold()
    return next((entry for entry in entries if entry.name.casefold() == wanted), None)


def choose(entries: list[Entry], provider: str, model: str | None) -> tuple[Entry, str | None]:
    """The entry and the model an agent picked. ValueError says why it cannot be picked,
    and names only what can be: nothing tells whether a provider outside the guide exists."""
    if not entries:
        raise ValueError("no other model can be chosen here: leave provider and model out")
    entry = find(entries, provider)
    if entry is None:
        listed = ", ".join(quoted(known.name) for known in entries)
        raise ValueError(
            f"there is no provider named {' '.join(provider.split())} to choose. "
            f"You can choose: {listed} - or leave provider out."
        )
    if model is None:
        if entry.must_name:
            names = ", ".join(quoted(name) for name in entry.selectable())
            raise ValueError(f"{entry.name} needs a model named. You can choose: {names}.")
        return entry, entry.default
    if not entry.allows(model):
        names = ", ".join(quoted(name) for name in entry.selectable())
        if entry.must_name:
            can = f"You can choose: {names}."
        elif names:
            can = f"You can choose: {names} - or leave model out for its default."
        else:
            can = "It lists no models: leave model out for its default."
        raise ValueError(f"{entry.name} has no model named {model}. {can}")
    return entry, model


def quoted(text: str) -> str:
    """The user's words as data: in quotes, so they cannot pass for KOLONİ's own."""
    return json.dumps(text, ensure_ascii=False)


def describe(entries: Iterable[Entry]) -> str:
    """The guide as an agent reads it, one line for each provider."""
    entries = list(entries)
    marked = ", unless marked as the catalogue's" if any(e.catalogue for e in entries) else ""
    lines = [
        "Other models you may give the sub-agent, by provider (optional: when a note fits "
        f"the job, or when the user asks for it by name; the notes are the user's{marked}):"
    ]
    for entry in entries:
        from_catalogue = {name: (note, day) for name, note, day in entry.catalogue}
        sees = dict(entry.sees)
        line = f"- {quoted(entry.name)} ({entry.kind}, {entry.runs})."
        if entry.note:
            line += f" The user's note: {quoted(entry.note)}"
        if entry.models:
            tiers = dict(entry.tiers)
            listed = []
            for name, note in entry.models:
                # The tier the user gave it, in KOLONİ's fixed words; then their note, or
                # the catalogue's, said to be that.
                said, day = from_catalogue.get(name, (None, None))
                more = "; ".join(filter(None, [
                    f"{tiers[name]} tier" if name in tiers else None,
                    sees.get(name),
                    f"the catalogue's note{f' ({day})' if day else ''}: {quoted(said)}" if said
                    else quoted(note) if note else None,
                ]))
                listed.append(quoted(name) + (f" ({more})" if more else ""))
            line += f" Models: {', '.join(listed)}."
        if entry.must_name:
            line += " It has no default: name one of its models."
        elif entry.default:
            line += f" Default model: {quoted(entry.default)}."
        else:
            line += " Default model: its own choice."
        lines.append(line)
    return "\n".join(lines)
