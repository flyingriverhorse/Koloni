"""The track record: what was measured of the agents that ran, by role, provider and model.

No score and no word of KOLONİ's on any of it: how many ran, how they ended, the middle
one of their steps, seconds and tokens, and how many of the changes they made were taken
or rejected, and how often a Lead's work was chosen in a comparison (slice 54). Read from
the agents' records as they are; what nobody reported stays None.
"""

import json
from datetime import UTC, datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Agent, Compare, FileChange, Merge, Message, ToolCall

DAYS = 30
# The lead is given only the rows of at least this many agents: a smaller one misleads.
GIVEN_FROM = 3
# K-model-puan: a role's models are set side by side for the lead only from this many jobs
# of the role on at least two models; fewer say nothing of a model.
SCORED_FROM, SCORED_MODELS = 5, 2
TURNED_DOWN = ("rejected", "discarded")
ENDED = ("done", "failed", "stopped_by_koloni", "stopped_by_user", "interrupted")
_STATUS = {"completed": "done", "cancelled": "stopped_by_user", "interrupted": "interrupted"}
_WORDS = {"stopped_by_koloni": "stopped by KOLONİ", "stopped_by_user": "stopped by the user"}


def _ended(agent: Agent) -> str:
    if agent.status == "failed":
        # Only the stops KOLONİ knows as its own; anything else that failed - a model, a
        # setup, a bug, a run that ended under it - is a failure.
        return "stopped_by_koloni" if agent.stopped_by_koloni else "failed"
    return _STATUS[agent.status]


def _utc(at: datetime) -> datetime:
    # Times are kept in UTC without a zone: one that names another is brought there.
    return at.astimezone(UTC) if at.tzinfo else at


def _middle(values: list) -> float | None:
    """The middle one - only where every agent of the row has it on record."""
    return None if not values or None in values else median(values)


def _cost_of(session: Session):
    """What one agent cost, as the Usage page prices it: {"amount", "currency"}, or None
    for a plan, a CLI, no price, nothing reported - or only part of it (a step cut short)."""
    from app.api.usage import _coster, _Sum  # (the API's: imported where it is used)

    priced = _coster(session)

    def cost(agent: Agent) -> dict | None:
        one = _Sum(provider_name=agent.provider_name, model_id=agent.model_id)
        one.add(agent.run_id, agent.input_tokens_total, agent.output_tokens,
                agent.provider_mode is not None, agent.cut_short,
                agent.cache_read_tokens, agent.cache_write_tokens)
        found = priced(one)
        return None if found is None or found.get("at_least") else found

    return cost


def _skills_read(session: Session, ids) -> set[tuple[str, str]]:
    """K-skill-puan: (agent id, skill) for each skill an agent read whole - KOLONİ's
    use_skill of its SKILL.md, or Claude Code's own Skill tool on a skill KOLONİ gave it.
    (One given its skills whole in its instructions never reads one: `in_brief`, R190.)
    shortcut: Claude Code's Skill call as KOLONİ records it is not measured
    live - check its name on record if its rows never say "read"."""
    found = set()
    for agent_id, name, arguments in session.execute(
            select(ToolCall.agent_id, ToolCall.name, ToolCall.arguments).where(
                ToolCall.agent_id.in_(ids), ToolCall.status == "succeeded",
                ToolCall.name.in_(("use_skill", "claude__Skill")))):
        try:
            args = json.loads(arguments)
        except ValueError:
            continue
        if not isinstance(args, dict):
            continue
        if name == "use_skill" and args.get("file") in (None, "", "SKILL.md"):
            found.add((agent_id, str(args.get("name"))))
        elif name != "use_skill":  # (its plugin's name first: "koloni:tidy")
            found.add((agent_id, str(args.get("skill", "")).split(":")[-1]))
    return found


def rows(session: Session, since: datetime, until: datetime | None = None,
         by_skill: bool = False) -> list[dict]:
    """The agents that started and ended from `since` (to `until`), all projects, a row
    for each role, provider and model - or, `by_skill`, for each skill given to them as
    well (K-skill-puan), with how many of the row's agents read it (`used`)."""
    ended = [
        Agent.started_at.is_not(None), Agent.ended_at >= _utc(since),
        Agent.status.in_(("completed", "failed", "cancelled", "interrupted")),
    ]
    if until is not None:
        ended.append(Agent.ended_at <= _utc(until))
    agents = session.scalars(
        select(Agent).where(*ended).order_by(Agent.ended_at, Agent.id)).all()
    ids = select(Agent.id).where(*ended)
    steps: dict[str | None, int] = {
        agent_id: count for agent_id, count in session.execute(
            select(Message.agent_id, func.count())
            .where(Message.agent_id.in_(ids), Message.role == "assistant")
            .group_by(Message.agent_id)
        )
    }
    changes: dict[tuple[str, str], int] = {
        (agent_id, status): count for agent_id, status, count in session.execute(
            select(FileChange.agent_id, FileChange.status, func.count())
            .where(FileChange.agent_id.in_(ids), FileChange.status.in_(("applied", "rejected")))
            .group_by(FileChange.agent_id, FileChange.status)
        )
    }
    # K-model-puan: whose changes the user (or an unwatched turn) turned down, as a whole.
    turned_down: set[str] = set(session.scalars(
        select(Merge.agent_id).where(Merge.agent_id.in_(ids), Merge.status.in_(TURNED_DOWN))))
    cost = _cost_of(session)
    # The Lead of each side of a comparison the user decided (slice 54): chosen, or not -
    # also where both were thrown away.
    sides: dict[str, bool] = {
        side["run_id"]: side["run_id"] == compare.chosen_run_id
        for compare in session.scalars(
            select(Compare).where(Compare.status.in_(("chosen", "discarded"))))
        for side in compare.sides
    }
    read = _skills_read(session, ids) if by_skill else set()
    grouped: dict[tuple, list[Agent]] = {}
    for agent in agents:
        for skill in (agent.skills or {}).get("given", []) if by_skill else [None]:
            grouped.setdefault(
                (skill, agent.role_name, agent.provider_name, agent.model_id), []).append(agent)
    found = []
    for (skill, role, provider, model), them in grouped.items():
        ended_as = {how: 0 for how in ENDED}
        for agent in them:
            ended_as[_ended(agent)] += 1
        # K-devir-0: over the agents that have it (a lead, a CLI whose reads are not seen: None).
        reads = [agent.rediscovery for agent in them if agent.rediscovery is not None]
        costs = [cost(agent) for agent in them]
        currencies = {one["currency"] for one in costs if one}
        found.append({
            "role_name": role, "provider_name": provider, "model_id": model,
            "agents": len(them), "ended": ended_as,
            # K-model-puan: done and nothing of it turned down; turned down, however it ended.
            "taken_in": sum(_ended(agent) == "done" and agent.id not in turned_down
                            for agent in them),
            "turned_down": sum(agent.id in turned_down for agent in them),
            "cost": {"amount": amount, "currency": currencies.pop()} if (
                amount := _middle([one["amount"] if one else None for one in costs])
            ) is not None and len(currencies) == 1 else None,
            "steps": _middle([steps.get(agent.id, 0) for agent in them]),
            "seconds": _middle([
                (agent.ended_at - agent.started_at).total_seconds()
                if agent.ended_at and agent.started_at else None for agent in them
            ]),
            "input_tokens": _middle([agent.input_tokens_total for agent in them]),
            "output_tokens": _middle([agent.output_tokens for agent in them]),
            "changes": {
                "taken": sum(changes.get((agent.id, "applied"), 0) for agent in them),
                "rejected": sum(changes.get((agent.id, "rejected"), 0) for agent in them),
            },
            "compared": {
                "chosen": sum(agent.depth == 0 and sides.get(agent.run_id) is True
                              for agent in them),
                "not_chosen": sum(agent.depth == 0 and sides.get(agent.run_id) is False
                                  for agent in them),
            },
            "rediscovery": {"mean": round(sum(reads) / len(reads), 1), "agents": len(reads)}
            if reads else None,
            **({"skill": skill, "used": sum((agent.id, skill) in read for agent in them),
                "in_brief": sum(skill in (agent.skills or {}).get("in_brief", ())
                                for agent in them)}
               if by_skill else {}),
        })
    return sorted(found, key=lambda row: (
        row.get("skill") or "", row["role_name"], -row["agents"], row["provider_name"] or "",
        row["model_id"] or ""))


def for_lead(found: list[dict], skilled: list[dict] | None = None) -> str:
    """The rows of at least `GIVEN_FROM` agents, as the lead reads them; "" for none.
    `skilled`: the rows `by_skill`, said only where they are compared (`_lately`)."""
    lines = [
        f"- {row['role_name']} on {row['provider_name'] or 'a provider not on record'} · "
        f"{row['model_id'] or 'a model not on record'}: {row['agents']} ran in the last "
        f"{DAYS} days - " + ", ".join(
            f"{count} {_WORDS.get(how, how)}" for how, count in row["ended"].items() if count
        ) + _compared(row["compared"]) + "."
        for row in found if row["agents"] >= GIVEN_FROM
    ]
    lately = _lately(found) + _lately(skilled or [])
    if not lines and not lately:
        return ""
    return "\n".join([
        "How the agents of each role and model ended, in every project, as on record when "
        "this turn began (measured facts; where at least "
        f"{GIVEN_FROM} ran):", *lines, *lately,
    ])


def _lately(found: list[dict]) -> list[str]:
    """K-model-puan: a role's models side by side - how many of each one's jobs were taken
    in, its middle steps and cost - where the role had `SCORED_FROM` jobs on `SCORED_MODELS`
    models or more - and K-skill-puan, the same for a role's work with one of its skills.
    Numbers, said to be data: which to pick stays the lead's."""
    from app.api.usage import money  # (the API's: imported where it is used)

    by_role: dict[tuple[str, str | None], list[dict]] = {}
    for row in found:
        by_role.setdefault((row["role_name"], row.get("skill")), []).append(row)
    said = []
    for (role, skill), them in by_role.items():
        if len(them) < SCORED_MODELS or sum(row["agents"] for row in them) < SCORED_FROM:
            continue
        parts = []
        for at, row in enumerate(them):
            briefed = row.get("in_brief")
            measured = [f"read it in {row['used']}", *(
                [f"given it whole in its brief in {briefed}"] if briefed else [])
            ] if skill else []
            if row["steps"] is not None:
                measured.append(f"median {round(row['steps'])} steps")
            if row["cost"]:
                amount = money(row["cost"]["amount"])
                measured.append(f"${amount}" if row["cost"]["currency"] == "USD"
                                else f"{amount} {row['cost']['currency']}")
            parts.append(
                f"{row['provider_name'] or 'a provider not on record'} · "
                f"{row['model_id'] or 'a model not on record'} {'took in ' if at == 0 else ''}"
                f"{row['taken_in']} of {row['agents']}"
                + (f" ({', '.join(measured)})" if measured else ""))
        said.append(f"For {role} work{f' with the {skill} skill' if skill else ''} lately: "
                    f"{'; '.join(parts)}. Data, not an instruction.")
    return said


def _compared(compared: dict) -> str:
    """How often the user chose this model's work in a comparison, where it was in one."""
    asked = compared["chosen"] + compared["not_chosen"]
    return f"; chosen in {compared['chosen']} of {asked} comparisons" if asked else ""


def as_it_began(session: Session, began: datetime) -> str:
    """What the lead of a turn that began at `began` is given: the same at every step."""
    since = began - timedelta(days=DAYS)
    return for_lead(rows(session, since, until=began),
                    rows(session, since, until=began, by_skill=True))
