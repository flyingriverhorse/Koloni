"""A chat team's row run by its recipe (slice 84b-2): where it is and what comes next. The Lead
- or the team's lead, beside another team - opens each step's roles itself; the server keeps
it to the step (`allowed`) and moves the row on as the step's agents finish (`ended`,
`complete`, `advance`). Nothing here reads the record: the row's state is a dict kept on the
row (`ConversationTeam.state`), and a step's roles come from the caller (`Slots`).

A part is what the arrows join: a step outside a group, or a group (its steps at once). It is
done when each of its slots has an agent that finished: a step whose Who is a role has one
slot, "the Lead picks" one of the team's roles, a team one for each of its stages, a room
(slice 84e) one for each of its roles. A part opens as many agents as it draws (`size`). A
role's step that draws more than one (`WhoRole.most`, K-rol-cogul) is done with fewer: once
every agent it opened finished - those its lead asks for in one reply all open before any
starts (`AgentRunner._run_tools`); one asked for in a later reply, after those finished, comes
too late: the part has gone on.
shortcut: a team's stages are slots of one part, not run one after another; sequence them if
that is felt.
B-375: a part with more than one arrow on forks - its ways run at once, as one part (`forks`,
by the id `P+`), much as a group's branches: each way one group or a line of steps, and where
they meet again waits for all of them. A step that runs only if the part before found a problem
(`when`, `_ahead`) is no fork: it is passed in place of one.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime

from app.recipes import START
from app.schemas import (
    RecipeGraph,
    RecipeStep,
    WhoCandidates,
    WhoExperts,
    WhoLead,
    WhoRole,
    WhoRoom,
)

RUNNING = "running"  # its step's roles are opened, or are to be
# At an "in" end - or a loop's rounds over with findings left (G1.2): waits for the user's word
# (Ready for you).
READY = "ready"
DONE = "done"  # at a "report" end: nothing to take in
IN = "in"  # the user took it in
FAILED = "failed"
STOPPED = "stopped"
INTERRUPTED = "interrupted"
# Picked, and not started in a turn another row of its chat started in (B-84): kept only to be
# shown - a run of its own begins over it (`begin`).
WAITING = "waiting"
# Its turn's agents still work on it.
OPEN = (RUNNING, READY)
RESTARTED = "Interrupted by a server restart"
# Why a step that runs only if a problem was found (`when`) is passed: the strip's word - or,
# where the user skipped the check before it (Skip, on its failure card), that none was made.
NO_PROBLEM = "no problem found"
NOT_CHECKED = "nothing was checked"
# Why the team's experts' step is passed, nobody there to fill it (`_ahead`): by which it takes.
NO_EXPERT = {"learned": "no expert has learned yet", "stale": "no expert's guide is to be learned",
             "all": "the team has no expert"}

# The roles that may fill a step's slots, one tuple a slot, from the step (the caller reads them).
Slots = Callable[[RecipeStep], list[tuple[str, ...]]]


def slot_map(graph: RecipeGraph, who: Slots) -> dict[str, list[list]]:
    """Each part's slots, as [the step it is of, its roles], from the roles there are now."""
    parts = {part_of(graph, step.id) for step in graph.steps}
    return {part: [[step.id, list(roles)] for step in steps_of(graph, part) for roles in who(step)]
            for part in parts}


def begin(graph: RecipeGraph, run_id: str, name: str, who: Slots) -> dict:
    """A row's run, at its first part. The recipe and who fills its steps are kept with it as
    it starts: a recipe changed or deleted since, or a role switched off, does not change a
    run under way."""
    slots = slot_map(graph, who)
    passed, at = _ahead(graph, slots, START)
    end = next((e for e in graph.ends if e.id == at), None)
    return {"run_id": run_id, "recipe": name, "graph": graph.model_dump(mode="json", by_alias=True),
            "slots": slots, "at": at, "done": passed, "rounds": {}, "agents": [], "here": [],
            "unmet": {part: _skipped(graph, slots, part, NO_PROBLEM) for part in passed},
            "status": RUNNING if end is None else READY if end.then == "in" else DONE,
            "why": None, "ended_ready": False}


def graph_of(state: dict) -> RecipeGraph:
    return RecipeGraph.model_validate(state["graph"])


def _next(graph: RecipeGraph, at: str) -> str:
    if (fork := _fork(graph, at)) is not None:
        return fork[1]
    return f"{at}+" if at in forks(graph) else next(
        arrow.to for arrow in graph.arrows if arrow.from_ == at)


def ways(graph: RecipeGraph) -> dict[str, list[tuple[list[str], str]]]:
    """B-375: each part with more than one arrow on, and each of its ways: the parts along it
    while each has one arrow in and one on, and the part it stops at - where it meets others
    (more than one arrow in), forks again, or ends."""
    group = {s.id: s.group for s in graph.steps if s.group}
    outs: dict[str, list[str]] = {}
    ins: dict[str, int] = {}
    for a in graph.arrows:
        if not (a.from_ in group and group[a.from_] == group.get(a.to)):  # (not a branch's)
            outs.setdefault(a.from_, []).append(a.to)
            ins[a.to] = ins.get(a.to, 0) + 1
    found: dict[str, list[tuple[list[str], str]]] = {}
    for at, tos in outs.items():
        for one in tos if len(tos) > 1 else ():
            line: list[str] = []
            while ins.get(one) == 1 and len(outs.get(one, ())) == 1 and one not in line:
                line.append(one)
                one = outs[one][0]
            found.setdefault(at, []).append((line, one))
    return found


def forks(graph: RecipeGraph) -> dict[str, tuple[list[list[str]], str]]:
    """The forks that run (`ways`; `problems` refuses the others): {the part they fork from:
    (its ways, each one group or a line of steps in none, and the one part they all meet at -
    which no other arrow comes to)}.
    shortcut: worked out again at each call (a drawing is at most 60 steps, 200 arrows); keep
    it on the state if runs are seen to slow."""
    groups, plain = {g.id for g in graph.groups}, {s.id for s in graph.steps if not s.group}
    found = {}
    for at, lines in ways(graph).items():
        join = lines[0][1]
        if all(stop == join and line and (
                line[0] in groups and len(line) == 1 or set(line) <= plain) for line, stop in lines
               ) and sum(a.to == join for a in graph.arrows) == len(lines):
            found[at] = ([line for line, _stop in lines], join)
    return found


def _fork(graph: RecipeGraph, part: str) -> tuple[list[list[str]], str] | None:
    """The fork a part is (`P+`), else None."""
    return forks(graph).get(part[:-1]) if part.endswith("+") else None


def is_group(graph: RecipeGraph, part: str) -> bool:
    """Whether a part runs steps at once: a group, or a fork's ways."""
    return any(g.id == part for g in graph.groups) or _fork(graph, part) is not None


def races(graph: RecipeGraph, part: str) -> list[str]:
    """The "first" groups a part runs: itself, or a way of its fork."""
    return [g.id for g in graph.groups if g.wait == "first" and part_of(graph, g.id) == part]


def unfilled(graph: RecipeGraph, part: str) -> str:
    """Why a part with no slot at all is passed: its experts' none to fill it."""
    who = steps_of(graph, part)[0].who
    return NO_EXPERT[who.experts] if isinstance(who, WhoExperts) else "nobody here can do it"


def _skipped(graph: RecipeGraph, slots: dict[str, list[list]], part: str, why: str) -> str:
    """Why a part `_ahead` passed is: nobody to fill it, else `why` - it runs only on a problem."""
    return unfilled(graph, part) if slots.get(part) == [] else why


def _if_found(graph: RecipeGraph, part: str) -> bool:
    """Whether a part runs only if the part before it found a problem (`RecipeStep.when`; such a
    step is in no group: `conditions`).
    shortcut: a problem is what the review's report says - its findings, `Already failing
    before:` lines, no Findings section, or "none" with nothing checked (`AgentRunner._found`) -
    not a command's exit code (which command is "the tests" is not known; a grep with no match
    exits 1), nor a `Checked:` line that says a test failed under `Findings: none`; read the
    step's commands too if a Tester is seen to pass failing tests so."""
    return any(s.when == "problem" for s in steps_of(graph, part))


def fixed_next(state: dict) -> bool:
    """Whether its part goes on to one that runs only if a problem was found: its review is
    told every failing test is a finding (`AgentRunner._found`)."""
    graph = graph_of(state)
    to = _next(graph, state["at"]) if _fork(graph, state["at"]) else next(
        (a.to for a in graph.arrows if a.from_ == state["at"]), None)
    return to is not None and _if_found(graph, to)


def _ahead(graph: RecipeGraph, slots: dict[str, list[list]], at: str,
           found: bool = False) -> tuple[list[str], str]:
    """The parts after `at` passed - for having no slot at all (K-uzman's experts' step, where
    the team has none or none is to learn), or as one that runs only if the part before it found
    a problem where it found none (`found`: `at` did; a part passed found none) - and the part it
    goes on to. Either is drawn skipped, with why (`_skipped`)."""
    passed, to = [], _next(graph, at)
    while to not in passed and (slots.get(to) == [] or _if_found(graph, to) and not found):
        passed.append(to)
        found = False
        to = _next(graph, to)
    return passed, to


def part_of(graph: RecipeGraph, at: str) -> str:
    """The part a step (or a group) is drawn on the way as: its group, or itself - or the fork
    it is on a way of."""
    step = next((s for s in graph.steps if s.id == at), None)
    part = step.group if step is not None and step.group else at
    return next((f"{fork}+" for fork, (lines, _join) in forks(graph).items()
                 if any(part in line for line in lines)), part)


def steps_of(graph: RecipeGraph, part: str) -> list[RecipeStep]:
    if (fork := _fork(graph, part)) is not None:
        return [s for line in fork[0] for one in line for s in steps_of(graph, one)]
    return [s for s in graph.steps if s.id == part or (s.group == part and s.group)]


def _inner(graph: RecipeGraph) -> dict[str, str]:
    """K-tarif-kol: a group's arrows between its own steps, each step to the next of its branch -
    and a fork's between the steps of a way (B-375)."""
    group = {s.id: s.group for s in graph.steps if s.group}
    return {a.from_: a.to for a in graph.arrows
            if a.from_ in group and group[a.from_] == group.get(a.to)} | {
        one: after for lines, _join in forks(graph).values() for line in lines
        for one, after in zip(line, line[1:], strict=False)}


def branches(graph: RecipeGraph, part: str) -> list[list[str]]:
    """A group's branches, each its steps in order: one starts at a step no arrow inside the
    group comes to (a group with none: each step a branch of its own) - a fork's, its groups'
    and its lines of steps. [] for no group."""
    after = _inner(graph)
    lines = [[s.id] for s in steps_of(graph, part) if s.id != part and s.id not in after.values()]
    for line in lines:
        while line[-1] in after and after[line[-1]] not in line:
            line.append(after[line[-1]])
    return lines


def _filled(state: dict, step_id: str) -> bool:
    """Each of a step's slots in its part - but those the user left out - has an agent that
    finished, and none of its agents still works."""
    out = state.get("left_out", {}).get(state["at"], ())
    here = [e for e in at_work(state) if e["step"] == step_id]
    return all(e["ok"] is not None for e in here) and all(
        any(e["slot"] == i and e["ok"] for e in here)
        for i, (step, _roles) in enumerate(state["slots"].get(state["at"], []))
        if step == step_id and i not in out)


def _done(state: dict, graph: RecipeGraph, step_id: str, seen: frozenset[str] = frozenset()
          ) -> bool:
    """A step of its part is done: filled, its candidates picked (K-evrim), and so is the step
    before it in its branch. (Arrows that go round, which `problems` refuses, are done never.)"""
    before = next((a for a, b in _inner(graph).items() if b == step_id), None)
    who = next(s.who for s in graph.steps if s.id == step_id)
    return step_id not in seen and (
        before is None or _done(state, graph, before, seen | {step_id})) and _filled(
        state, step_id) and (not isinstance(who, WhoCandidates) or bool(state.get("picked")))


def _open(state: dict, graph: RecipeGraph) -> set[int]:
    """Its part's slots whose step may start now: the first of its branch, or after one done -
    not one of a branch another was done before ("first": `lost`).
    (KOLONİ's own Lead hears back once all of a reply's agents ended: a branch's next step is
    opened by KOLONİ as the one before ends - `follows` - so a branch never waits for the step
    beside it. A CLI's Lead hears each as it ends, and opens it itself.)"""
    before, gone = {b: a for a, b in _inner(graph).items()}, lost(state)
    return {i for i, (step, _roles) in enumerate(state["slots"].get(state["at"], []))
            if step not in gone and (step not in before or _done(state, graph, before[step]))}


def follows(state: dict, step_id: str) -> list[tuple[str, str, int]]:
    """K-tarif-kol: the step after `step_id` in its branch, once it may start: each of its places
    still empty that one role fills - not one the user's choice left out - as (that role, its
    step's name, how many to open: a step of candidates all of them at once, else one). KOLONİ
    opens them (`AgentRunner._spawn_on`). [] where none such.
    shortcut: a place a choice of roles fills ("the Lead picks", a team's stage of two) is left
    to the Lead's next reply; open its first role if that is felt."""
    if state["status"] != RUNNING:
        return []
    graph = graph_of(state)
    to = _inner(graph).get(step_id)
    if to is None or part_of(graph, to) != state["at"] or to in lost(state):
        return []
    at, now, step = state["at"], _open(state, graph), next(s for s in graph.steps if s.id == to)
    off, out = _kept_off(state, graph, at), state.get("left_out", {}).get(at, ())
    held = {e["slot"] for e in at_work(state) if e["ok"] is not False}
    return [(roles[0], step.name, _draws(graph, to, roles) if isinstance(
                step.who, WhoCandidates) else 1)
            for i, (one, roles) in enumerate(state["slots"].get(at, []))
            if one == to and i in now and i not in held and i not in out and len(roles) == 1
            and _fits(off, [one, roles], roles[0])]


def still_follows(state: dict, step_id: str, role: str) -> bool:
    """Whether the step after `step_id` in its branch, which KOLONİ is opening (`follows`), still
    has a place `role` may fill now: the run at work at its part, the step open (not lost), the
    place free - room left for more of a step of candidates - and not one the user left out."""
    graph = graph_of(state)
    to = _inner(graph).get(step_id)
    if state["status"] != RUNNING or to is None or part_of(graph, to) != state["at"]:
        return False
    held, out = state["slots"][state["at"]], state.get("left_out", {}).get(state["at"], ())
    return any(held[i][0] == to and i not in out for i in _free(state, role)[1])


def lead_picks(state: dict) -> list[str]:
    """B-375 (R179): its part's steps "the Lead picks" that may start now and have nobody yet -
    KOLONİ opens none of them (`follows`, `beside`), so its runner is told to open them at once,
    beside the rest; by their step's name, with its group's ("All at once: Plan")."""
    graph, at = graph_of(state), state["at"]
    if state["status"] != RUNNING or not is_group(graph, at):
        return []
    now, out = _open(state, graph), state.get("left_out", {}).get(at, ())
    held = {e["slot"] for e in at_work(state) if e["ok"] is not False}
    groups = {g.id: f"{g.name}: " for g in graph.groups}
    names = {s.id: groups.get(s.group or "", "") + s.name
             for s in graph.steps if isinstance(s.who, WhoLead)}
    return [names[one] for i, (one, _roles) in enumerate(state["slots"].get(at, []))
            if one in names and i in now and i not in held and i not in out]


def _won(state: dict, graph: RecipeGraph, race: str) -> list[str] | None:
    """A "first" group's (`races`) branch done first (one with a slot the user did not leave
    out), kept on the state the first time it is seen - a stopped branch that ends well after
    does not take its place; None: none yet."""
    # (Not one whose work went again since: Ask for changes empties the part's agents.)
    if (kept := state.get("won", {}).get(race)) and _done(state, graph, kept[-1]):
        return kept
    out, held = state.get("left_out", {}).get(state["at"], ()), state["slots"].get(state["at"], [])
    line = next((line for line in branches(graph, race) if _done(state, graph, line[-1])
                 and any(step in line and i not in out for i, (step, _r) in enumerate(held))),
                None)
    if line is not None:
        state.setdefault("won", {})[race] = line
    return line


def gives_up(state: dict, step_id: str) -> bool:
    """A "first" group's step failed while another of its branches may still be done first: its
    branch is only out of the race, nobody asked. Once none is left, its If it fails holds."""
    graph = graph_of(state)
    race = next((one for one in races(graph, state["at"])
                 if any(s.id == step_id for s in steps_of(graph, one))), None)
    if race is None:
        return False
    here, held = at_work(state), state["slots"].get(state["at"], [])
    left = state.get("left_out", {}).get(state["at"], ())

    def out(line: list[str]) -> bool:  # (a step of it failed, its place filled by none)
        return any(e["ok"] is False and e["step"] in line and not any(
            o["ok"] and o["slot"] == e["slot"] for o in here) for e in here)

    lines = branches(graph, race)
    return any(step_id in line and out(line) for line in lines) and any(
        step_id not in line and not out(line) and any(
            step in line and i not in left for i, (step, _r) in enumerate(held))
        for line in lines)


def lost(state: dict) -> set[str]:
    """The steps of its part another branch of a "first" group was done before: their agents are
    stopped, and what they report counts for nothing."""
    graph = graph_of(state)
    return {s.id for race in races(graph, state["at"]) if (won := _won(state, graph, race))
            for s in steps_of(graph, race) if s.id not in won}


def outrun(state: dict) -> list[str]:
    """The agents still at work on those steps (`lost`): KOLONİ stops them."""
    gone = lost(state)
    return [e["agent"] for e in at_work(state) if e["ok"] is None and e["step"] in gone]


def branch_strip(state: dict, graph: RecipeGraph, part: str, shown: str) -> list[list[dict]] | None:
    """A group's branches as the canvas's strip shows them, at work - or done with some stopped
    (`shown`: the part's own state there): each step done, now (it may start, or works), next
    or stopped. None: no group, or none of that."""
    if shown not in ("now", "done") or not is_group(graph, part):
        return None
    names, stopped = {s.id: s.name for s in graph.steps}, state.get("outrun", {}).get(part, ())
    if shown == "done":
        if not stopped:
            return None  # ("Checks ✓" says it all)
        return [[{"name": names[s], "state": "stopped" if s in stopped else "done"} for s in line]
                for line in branches(graph, part)]
    gone, held = lost(state), state["slots"].get(part, [])
    now = {held[i][0] for i in _open(state, graph)}
    return [[{"name": names[s], "state": "done" if _done(state, graph, s) else "stopped"
              if s in gone else "now" if s in now else "next"} for s in line]
            for line in branches(graph, part)]


def name_of(graph: RecipeGraph, part: str) -> str:
    end = next((e for e in graph.ends if e.id == part), None)
    if end is not None:
        return "You" if end.then == "in" else "Report"
    if (fork := _fork(graph, part)) is not None:
        return " + ".join(" → ".join(name_of(graph, one) for one in line) for line in fork[0])
    group = next((g for g in graph.groups if g.id == part), None)
    return group.name if group is not None else steps_of(graph, part)[0].name


def roles_at(state: dict, part: str) -> list[str]:
    """A part's roles, by name, once each."""
    return sorted({role for _step, roles in state["slots"].get(part, []) for role in roles})


def _reviews(graph: RecipeGraph, part: str) -> set[str]:
    return {s.id for s in steps_of(graph, part) if s.done_when == "no_findings"}


def _before(graph: RecipeGraph, part: str) -> list[str]:
    """The parts on the way (`strip`) strictly before this one."""
    way = strip(graph)
    return way[:way.index(part)] if part in way else []


def _kept_off(state: dict, graph: RecipeGraph, part: str) -> tuple[set[str], set[str]]:
    """G1.2, who wrote the work does not pass its check: a part's review steps - not a room's,
    which passes as a whole, its other members checking, nor one the user let its writer
    check (`checks`) - and the roles (casefolded) that did a part before it on the way."""
    wrote, own = state.get("wrote", {}), state.get("own", ())
    return ({s.id for s in steps_of(graph, part) if s.done_when == "no_findings"
             and not isinstance(s.who, WhoRoom) and s.id not in own},
            {role for one in _before(graph, part) for role in wrote.get(one, ())})


def _fits(off: tuple[set[str], set[str]], slot: list, role: str) -> bool:
    """Whether `role` may fill a slot: one of its roles, and - a review's - not one that did
    the work before it (`_kept_off`)."""
    (step, roles), (reviews, wrote) = slot, off
    return role.casefold() in {r.casefold() for r in roles} and not (
        step in reviews and role.casefold() in wrote)


def ahead(state: dict) -> dict:
    """Where its part, done, takes it (`advance`), its own state left as it is."""
    state = json.loads(json.dumps(state))
    advance(state)
    return state


def writers(state: dict) -> set[str]:
    """The roles (casefolded) that did the work before its part."""
    return _kept_off(state, graph_of(state), state["at"])[1]


def unchecked(state: dict) -> list[tuple[int, str, list[str]]]:
    """Its part's review slots only roles that did the work could fill (`_fits`): who checks
    is the user's ("Who checks?", `checks`). Each its index, its step and those roles."""
    at = state["at"]
    if state["status"] != RUNNING:
        return []
    off = _kept_off(state, graph_of(state), at)
    return [(i, step, roles) for i, (step, roles) in enumerate(state["slots"].get(at, []))
            if step in off[0] and roles and not any(_fits(off, [step, roles], r) for r in roles)]


def checks(state: dict, part: str, slot: int, role: str | None) -> None:
    """The user's word on who checks a slot `unchecked` found: `role` in place of its roles;
    None, the role that did the work - its step on record (`own`), the node says so."""
    if role is not None:
        state["slots"][part][slot][1] = [role]
    else:
        state["own"] = sorted({*state.get("own", ()), state["slots"][part][slot][0]})


def own_checks(graph: RecipeGraph) -> list[tuple[str, str]]:
    """The review steps of one role that a step of that role before them on the way did the
    work for, each (its id, what is said): drawn so, the writer would pass its own check. (A
    room's, or a step the Lead or a team fills, is known only as it runs: `_fits`.)"""
    found = []
    for part in strip(graph):
        before = [step for one in _before(graph, part) for step in steps_of(graph, one)]
        # K-tarif-kol: and the steps before it in its branch.
        # shortcut: at work (`_kept_off`) only the parts before are kept off its check - a step
        # the Lead or a team fills there is not; count a branch's writers there if that is met.
        earlier = {line[i]: line[:i] for line in branches(graph, part) for i in range(len(line))}
        for step in steps_of(graph, part):
            writers = {role.casefold(): one.name for one in before + [
                s for s in graph.steps if s.id in earlier.get(step.id, ())]
                if one.done_when != "no_findings" and (role := role_of(one))}
            if step.done_when == "no_findings" and isinstance(step.who, WhoRole) and (
                    step.who.role.casefold() in writers):
                found.append((step.id, f"{step.name}: {step.who.role} would check its own work "
                                       f"({writers[step.who.role.casefold()]})"))
    return found


def conditions(graph: RecipeGraph) -> list[tuple[str, str]]:
    """The steps that run only if the part before found a problem (`when`) that could never
    tell: in a group (a part runs or not as a whole), after a part that is no review (only a
    review's findings are read), or after a review whose own loop takes its findings back
    first; each (its id, what is said)."""
    found = []
    for step in graph.steps:
        if step.when != "problem":
            continue
        before = _before(graph, step.id)[-1:]
        if part_of(graph, step.id) != step.id:  # (in a group, or on a fork's way)
            found.append((step.id, f"{step.name}: a step that runs only if a problem was found "
                                   "is on its own, not at once with other steps"))
        elif not before or not _reviews(graph, before[0]):
            found.append((step.id, f"{step.name} runs only if the step before found a problem, "
                                   "but that is no review (Done when: no finding is left)"))
        elif any(part_of(graph, loop.from_) == before[0] for loop in graph.loops):
            found.append((step.id, f"{step.name} runs only if the step before found a problem, "
                                   f"but {name_of(graph, before[0])} loops back with what it "
                                   "finds; keep the loop or the condition"))
    return found


def open_to(state: dict) -> list[str]:
    """Its part's roles, by name, that its agents may be opened in now (`_fits`)."""
    off = _kept_off(state, graph_of(state), state["at"])
    held, now = state["slots"].get(state["at"], []), _open(state, graph_of(state))
    return [role for role in roles_at(state, state["at"]) if any(
        _fits(off, slot, role) for i, slot in enumerate(held) if i in now)]


def allowed(state: dict) -> set[str]:
    """The roles (casefolded) its agents may be opened in now: its part's, while it runs."""
    if state["status"] != RUNNING:
        return set()
    return {role.casefold() for role in open_to(state)}


def _free(state: dict, role: str) -> tuple[list[int], list[int]]:
    """The slots of its part `role` fits, and those of them with room: as many agents as the
    slot draws (`size`) - one that failed is no longer one of them."""
    graph, at = graph_of(state), state["at"]
    held, off, now = state["slots"][at], _kept_off(state, graph, at), _open(state, graph)
    mine = [i for i, slot in enumerate(held) if i in now and _fits(off, slot, role)]
    return mine, [i for i in mine if sum(e["slot"] == i and e["ok"] is not False
                                         for e in at_work(state)) < _draws(graph, *held[i])]


def _draws(graph: RecipeGraph, step_id: str, roles: list[str]) -> int:
    """How many agents a slot draws: "the Lead picks" one; a role's step its `most`
    (K-rol-cogul: none if the role is off), and so a step of candidates (K-evrim); else one of
    each of its roles."""
    who = next(s.who for s in graph.steps if s.id == step_id)
    return 1 if isinstance(who, WhoLead) else len(roles) * (
        (who.most or 1) if isinstance(who, WhoRole | WhoCandidates) else 1)


def role_of(step: RecipeStep) -> str | None:
    """The one role a step names: a role's step's, or its candidates' (K-evrim)."""
    who = step.who
    return who.role if isinstance(who, WhoRole) else who.candidates if isinstance(
        who, WhoCandidates) else None


def pick_due(state: dict) -> RecipeStep | None:
    """K-evrim: its part's step of candidates (one a part: `problems`) whose agents all ended
    and that is not picked yet - in a branch, before the step after it opens; None: none such."""
    step = next((s for s in steps_of(graph_of(state), state["at"])
                 if isinstance(s.who, WhoCandidates)), None)
    return step if step is not None and not state.get("picked") and step.id not in lost(
        state) and _filled(state, step.id) else None


def has_room(state: dict, role: str) -> bool:
    """Whether an agent of `role` fills a place of its part still empty (one more Reviewer is
    not the group's missing Tester)."""
    return bool(_free(state, role)[1])


def beside(state: dict, role: str) -> list[tuple[str, str]]:
    """In an "all at once" group, the places an agent of `role` leaves empty that one role
    fills, each (that role, its step's name): opened with it, at the same time. [] where
    it is no group, or `role` has no place in it."""
    graph, at = graph_of(state), state["at"]
    if state["status"] != RUNNING or not is_group(graph, at):
        return []
    _mine, free = _free(state, role)
    if not free:
        return []
    off, names = _kept_off(state, graph, at), {s.id: s.name for s in graph.steps}
    held = {e["slot"] for e in at_work(state) if e["ok"] is not False}
    now = _open(state, graph)
    return [(roles[0], names[step]) for i, (step, roles) in enumerate(state["slots"][at])
            if i != free[0] and i not in held and i in now and len(roles) == 1
            and _fits(off, [step, roles], roles[0])]


def fills_review(state: dict, role: str) -> bool:
    """Whether an agent of `role` opened now takes a review's place (`opened`)."""
    if state["status"] != RUNNING:
        return False
    mine, free = _free(state, role)
    return bool(mine) and state["slots"][state["at"]][(free or mine)[0]][0] in _reviews(
        graph_of(state), state["at"])


def opened(state: dict, agent_id: str, role: str) -> dict:
    """An agent of `role` was opened for its part: it takes the first slot it fits with room
    (`_free`), else the first it fits. Returns its entry in the part."""
    held = state["slots"][state["at"]]
    mine, free = _free(state, role)
    at = (free or mine)[0]
    state["agents"].append(agent_id)
    state["here"].append(entry := {"agent": agent_id, "slot": at, "step": held[at][0],
                                   "role": role, "ok": None, "found": False})
    # The canvas draws its work line by these: each time the run came to a part, who it opened -
    # a round of a loop to itself (K-evrim's candidates) a pass of its own, to fold (B-391).
    # shortcut: a part run again right after itself (Ask for changes) adds to its last pass - but
    # after a loop went round (`back_to` resets `rounds`) it opens a new one, drawn as a round.
    passes, round_ = state.setdefault("passes", []), state["rounds"].get(state["at"], 0)
    if not passes or passes[-1]["part"] != state["at"] or passes[-1].get("round", 0) != round_:
        passes.append({"part": state["at"], "agents": [], "round": round_})
    passes[-1]["agents"].append(agent_id)
    return entry


def at_work(state: dict) -> list[dict]:
    """Its part's entries, less an agent the user declined (kept, marked `gone`: a card put in
    its call is still heard)."""
    return [e for e in state["here"] if not e.get("gone")]


def entry_of(state: dict, agent_id: str) -> dict | None:
    return next((e for e in state["here"] if e["agent"] == agent_id), None)


def complete(state: dict) -> bool:
    """Every slot of its part - but those the user left out (`narrow`) - has an agent that
    finished, and none of its agents still works."""
    graph, held, here = graph_of(state), state["slots"][state["at"]], at_work(state)
    out = state.get("left_out", {}).get(state["at"], ())
    # K-tarif-kol: a "first" group, by its branch done first - once the others stopped; and not
    # while its candidates wait for their pick.
    raced = {s.id for race in races(graph, state["at"]) if _won(state, graph, race) is not None
             for s in steps_of(graph, race)}
    return all(e["ok"] is not None for e in here) and pick_due(state) is None and all(
        held[i][0] in raced or any(e["slot"] == i and e["ok"] for e in here)
        for i in range(len(held)) if i not in out)


def in_group(state: dict) -> bool:
    """Whether its part now is an "all at once" group: one the user's choice may narrow."""
    return is_group(graph_of(state), state["at"])


def narrow(state: dict, chosen: frozenset[str]) -> None:
    """B-173: the user chose some of an "all at once" part's roles (`chosen`, casefolded, as
    their answer on a card named them): its other places are left out - the part is done
    without them, which is said (`left_out_of`). Nothing chosen of its roles, or no group:
    as drawn."""
    at = state["at"]
    if not chosen or not in_group(state):
        return
    held = state["slots"][at]
    out = [i for i, (_step, roles) in enumerate(held)
           if not any(r.casefold() in chosen for r in roles)]
    if len(out) < len(held):
        state.setdefault("left_out", {})[at] = out


def left_out_of(state: dict, part: str) -> list[str]:
    """The names of a part's steps the user's choice left out (`narrow`)."""
    names = {s.id: s.name for s in graph_of(state).steps}
    held = state["slots"].get(part, [])
    return [names[held[i][0]] for i in state.get("left_out", {}).get(part, ()) if i < len(held)]


def _reached(state: dict) -> None:
    """B-173: its part is come to - again too: from now on the user's choices are for it, and
    none made for it before stands."""
    state["reached"] = datetime.now(UTC).isoformat()
    state.get("left_out", {}).pop(state["at"], None)
    state.get("unmet", {}).pop(state["at"], None)  # (passed before, it runs now)
    for race in races(graph_of(state), state["at"]):  # (K-tarif-kol: a "first" group races anew)
        state.get("won", {}).pop(race, None)


def advance(state: dict) -> str:
    """Its part is done: back along its loop where a review in it left findings and rounds
    are left, else on to the next part - or to its end. Findings left with no round to go
    back (or no loop) stop it before a next step: the user's (G1.2). Returns what its runner
    is told.
    shortcut: rounds are counted for the run - a loop round an outer one does not give a
    loop its rounds again (Ask for changes does: `back_to`)."""
    graph, at = graph_of(state), state["at"]
    # K-tarif-kol: what a "first" group's stopped branches did or found counts for nothing.
    gone = lost(state)
    reviews = _reviews(graph, at) - gone
    # (B-387: a review that failed found nothing - its slot filled by another, it sends none back.)
    found = any(e["found"] and e["ok"] is not False for e in state["here"] if e["step"] in reviews)
    # (`ended`: a report with findings to hand on; Skip on a failed check's card: none was made.)
    handed = any(e.get("findings") for e in state["here"] if e["step"] in reviews)
    unchecked = any(e.get("unchecked") for e in state["here"] if e["step"] in reviews)
    if gone or at in state.get("outrun", {}):  # (the strip says them stopped)
        state.setdefault("outrun", {})[at] = sorted(s for s in gone if not _done(state, graph, s))
    loop = next((one for one in graph.loops if part_of(graph, one.from_) == at), None)
    # K-evrim: a step of candidates goes round again from its pick (its loop to itself) while
    # the picked one's score is below the step's target - every round its loop has, with none.
    who = next((s.who for s in steps_of(graph, at) if isinstance(s.who, WhoCandidates)), None)
    won = (state.get("scores", {}).get(state.pop("picked", None) or "") or {}).get("score")
    again = who is not None and loop is not None and part_of(graph, loop.to) == at and (
        who.target is None or won is None or won < who.target)
    wrote = state.setdefault("wrote", {})
    # (An expert changes nothing: having learned keeps it from no check of the work.)
    experts = {s.id for s in graph.steps if isinstance(s.who, WhoExperts)}
    wrote[at] = sorted(set(wrote.get(at, ())) | {
        e["role"].casefold() for e in at_work(state) if e["ok"] and e.get("role")
        and e["step"] not in reviews and e["step"] not in experts})
    # B-190: a step's agent changed a file (`AgentRunner._after_step`): the end is Take in.
    state["changed"] = state.get("changed", False) or any(e.get("changed") for e in at_work(state))
    state["here"] = []
    # A step that ran as the part before found a problem fixed it: its loop goes back to check.
    # (One that is a review and found nothing goes on.)
    fixed = not found and _if_found(graph, at) and not reviews
    if (found or fixed or again) and loop is not None and state["rounds"].get(at, 0) < (
            loop.rounds or 0):
        back = part_of(graph, loop.to)
        state["rounds"][at] = state["rounds"].get(at, 0) + 1
        if found:
            state["sent_back"] = at  # (the loop that did: `found_left`)
        if back in state["done"]:
            state["done"] = state["done"][:state["done"].index(back)]
        state["at"] = back
        _reached(state)
        if fixed:
            return (f"Fixed: back to {name_of(graph, back)}, round {state['rounds'][at]} of "
                    f"{loop.rounds}, to check it again - open {' or '.join(open_to(state))}.")
        if again and who is not None:
            below = ("no target" if who.target is None else "no score" if won is None
                     else f"{won:g} below {who.target}")
            return (f"Round {state['rounds'][at] + 1} of {(loop.rounds or 0) + 1} ({below}): open "
                    f"{who.candidates} ×{who.most} again - they start from the picked one's "
                    "copy and read KOLONİ's round note.")
        # (B-117: a role the step does not name, one a finding names, is refused there.)
        return (f"Findings are left: back to {name_of(graph, back)}, round "
                f"{state['rounds'][at]} of {loop.rounds}. Hand them to "
                f"{' or '.join(open_to(state))} with findings_from - the step's roles take "
                "them, whatever role a finding names.")
    passed, to = _ahead(graph, state["slots"], at, found)
    end = next((e for e in graph.ends if e.id == to), None)
    # Findings left, and the next part is one that runs on them: it does - but not once its own
    # loop's rounds are spent, so that what it fixed last is checked (G1.2's end, below).
    spent = next((one for one in graph.loops if part_of(graph, one.from_) == to
                  and state["rounds"].get(to, 0) >= (one.rounds or 0)), None) if _if_found(
        graph, to) else None
    fixes = found and _if_found(graph, to) and spent is None
    if found and end is None and not fixes:
        # G1.2: no round left (or no loop) with findings left - the work does not go on.
        stop, by = (spent, to) if spent else (loop, at)
        state["status"] = READY
        state["why"] = (f"findings are left after {stop.rounds} round"
                        f"{'' if stop.rounds == 1 else 's'} of {name_of(graph, by)}" if stop
                        else f"findings are left after {name_of(graph, at)}")
        return (f"The recipe stops here: {state['why']}. The user is asked what to do with "
                "the work (Ready for you).")
    state["done"] += [at, *passed]
    why = NOT_CHECKED if unchecked else NO_PROBLEM
    # B-177: one that ran in a round of this pass (its loop came back from it) is done, not
    # skipped - the Debugger that fixed the tests is not "no problem found" once they pass.
    skipped = {part: _skipped(graph, state["slots"], part, why) for part in passed
               if not state["rounds"].get(part)}
    state["unmet"] = {**state.get("unmet", {}), **skipped}
    state["at"] = to
    out = left_out_of(state, at)
    _reached(state)
    left = (" Findings are left: the user sees them." if found and not fixes else "") + (
        # (K-evrim: its rounds over, the target not reached - the picked one's work goes on.)
        f" Target {who.target} not reached ({won:g}): the picked one's work goes on."
        if who is not None and who.target is not None and won is not None and won < who.target
        else "") + (
        f" Left out by the user's choice: {', '.join(out)}." if out else "") + "".join(
        f" Skipped, {why}: {', '.join(name_of(graph, p) for p in skipped if skipped[p] == why)}."
        for why in dict.fromkeys(skipped.values()))
    if fixes:
        hand = (f"Hand its findings to {' or '.join(open_to(state))} with findings_from."
                if handed else f"Its report has no findings to hand on: give "
                f"{' or '.join(open_to(state))} what it said in its task.")
        return (f"Next: {name_of(graph, to)}, as {name_of(graph, at)} found a problem. "
                f"{hand}{left}")
    if end is None:
        # (B-191: by its roles - the Lead guessed the Coder, then asked the user.)
        # (An "all at once" group opens each of its roles. shortcut: one of its steps that
        # takes a choice of roles is said with "and" too.)
        roles = (" and " if is_group(graph, state["at"]) else " or ").join(
            open_to(state))
        return f"Next: {name_of(graph, state['at'])}" + (
            f" - open {roles}" if roles else "") + f".{left}"
    # B-178: at a "report" end too, where a step that runs on a problem (Quality check's
    # Debugger) did work: its fix is the user's to take in, not a copy kept at the turn's end.
    # B-190: and where any step's agent changed a file (a Spec writer's docs/spec.md).
    # shortcut: a fix that changed no file is asked about all the same.
    ready = end.then == "in" or state["changed"] or any(
        roles and _if_found(graph, part) for part, roles in wrote.items())
    state["status"] = READY if ready else DONE
    return ("The recipe is at its end: the user is asked to take the work in." if ready
            else "The recipe is at its end: tell the user what was found.") + left


def back_to(state: dict) -> str:
    """Where Ask for changes sends a run back to: the step its last loop goes back to, else
    its first; its name. Its loops have their rounds again: the user's word is a new start -
    and K-evrim's kept best too (B-370): work changed as asked is not measured against work
    the user asked changes to. How many times it was sent back is kept (`asked`): its runner's
    steps grow with it."""
    graph = graph_of(state)
    back = part_of(graph, graph.loops[-1].to) if graph.loops else _ahead(
        graph, state["slots"], START)[1]
    if back in state["done"]:
        state["done"] = state["done"][:state["done"].index(back)]
    state.update(status=RUNNING, at=back, here=[], skipped=[], why=None, rounds={},
                 kept_best={}, asked=state.get("asked", 0) + 1)
    _reached(state)
    return name_of(graph, back)


def carried(old: dict | None, recipe: tuple[str, RecipeGraph] | None) -> dict:
    """What a row's run of `recipe` (its name and drawing) begun anew keeps of its earlier
    state `old`: the user's words at a card (Ask for changes) for a part a turn ended before it
    ran again with them - {"carried": [the part, the words, its name]} - for that part when the
    new run is there (`words`); none where the drawing has no such part by that name now (the
    recipe changed since: an id may be another part's)."""
    if not recipe or not old or old.get("recipe") != recipe[0] or old.get("status") not in (
            STOPPED, WAITING):
        return {}  # (taken in, or another recipe: they were for that work)
    kept = [old["at"], old["words"], name_of(graph_of(old), old["at"])] if old.get(
        "words") else old.get("carried")
    graph = recipe[1]
    there = kept and kept[0] in {part_of(graph, step.id) for step in graph.steps} and (
        name_of(graph, kept[0]) == kept[2])
    return {"carried": kept} if there else {}


def words(state: dict) -> str | None:
    """The user's words for its part now: given in this run, or carried to it (`carried`)."""
    kept = state.get("carried")
    return state.get("words") or (kept[1] if kept and kept[0] == state["at"] else None)


def found_left(state: dict) -> str | None:
    """B-116: its runner ended with the run sent back along a loop for findings and nothing of
    the round done yet - G1.2's end, not a rule broken (`skip`): what is said of it. None: not
    so."""
    graph, at, found = graph_of(state), state["at"], state.get("sent_back")
    if not found or not state["rounds"].get(found) or any(e["ok"] for e in state["here"]) or (
            not any(part_of(graph, one.from_) == found and part_of(graph, one.to) == at
                    for one in graph.loops)):
        return None
    rounds = state["rounds"][found]
    return (f"findings are left after {rounds} round{'' if rounds == 1 else 's'} of "
            f"{name_of(graph, found)}")


def skip(state: dict) -> str:
    """Its runner ended with the run at work, told what was left (B-83, G1.3): the parts left,
    from where it is to its end, are skipped - kept on the state for the step strip. What is
    said of them: a rule broken."""
    graph = graph_of(state)
    way, ends = strip(graph), {end.id for end in graph.ends}
    left = way[way.index(state["at"]):] if state["at"] in way else []
    state["skipped"] = [part for part in left if part not in ends and part not in state["done"]]
    names = [name_of(graph, part) for part in state["skipped"]]
    return f"rule broken: {' and '.join(names)} {'was' if len(names) == 1 else 'were'} not done"


def strip(graph: RecipeGraph) -> list[str]:
    """Its parts in order along the first arrows, to its end: the steps the canvas shows."""
    way, at = [], _next(graph, START)
    while at not in way:
        way.append(at)
        if any(e.id == at for e in graph.ends):
            break
        at = _next(graph, at)
    return way


def size(graph: RecipeGraph, slots: dict[str, list[list]], part: str) -> int:
    """How many agents a part draws (slice 84e), and so opens at most: a role's step its
    `most` (one unless drawn more, K-rol-cogul), a team's a role of each stage, a room a
    member each; "the Lead picks" one."""
    return sum(_draws(graph, step, roles) for step, roles in slots.get(part, []))


def cap(graph: RecipeGraph, slots: dict[str, list[list]]) -> int:
    """The most agents a run's steps open, all told, as it is drawn: each part's (`size`), and
    again for each part a loop goes back over, once a round (its end draws none).
    shortcut: told, not counted against - the helpers a step's agents open themselves are
    bounded only by the chat's limit per agent and its depth limit; count them into a run's
    total if a recipe is seen to open too many."""
    way = strip(graph)
    sizes = [size(graph, slots, part) for part in way]
    total = sum(sizes)
    for loop in graph.loops:
        at, back = part_of(graph, loop.from_), part_of(graph, loop.to)
        if at in way and back in way:
            total += (loop.rounds or 0) * sum(sizes[way.index(back):way.index(at) + 1])
    return total


def room_at(graph: RecipeGraph, part: str) -> RecipeStep | None:
    """The part's Room step (slice 84e: a room meets on its own, in no group); None: not one."""
    return next((s for s in steps_of(graph, part) if isinstance(s.who, WhoRoom)), None)


def round_at(state: dict, graph: RecipeGraph, part: str) -> int:
    """How many times its loops came back over this part: one a loop goes back to, one it
    goes back from (the review that sent the work back checks it again, R116), or one between."""
    way = strip(graph)
    if part not in way:
        return 0
    return sum(state["rounds"].get(at, 0) for one in graph.loops
               if (at := part_of(graph, one.from_)) in way and (back := part_of(graph, one.to))
               in way and way.index(back) <= way.index(part) <= way.index(at))
