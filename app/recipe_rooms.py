"""0.1.10, rooms are gone: a recipe's Room step drawn before, read as an "All at once" group
(`without_rooms`, `RecipeGraph`'s first look at what it is given). A leaf: it imports nothing of
KOLONİ's own."""

from collections.abc import Iterator

# 0.1.9's Room step held at most this many roles (`WhoRoom`), and a recipe this many steps
# (`RecipeGraph`): a drawing with more is not read.
MOST_ROOM_ROLES, MOST_STEPS = 10, 60


def without_rooms(graph: object) -> object:
    """0.1.10, rooms are gone: a Room step ({"room": [roles]}, slice 84e) of a recipe drawn
    before - saved, a folder's file, a run's state - read as an "All at once" group in its place
    (its id, name and spot, so its arrows and loops still meet it) with a step of each role, named
    "<its name> · <role>", each keeping the step's other choices. One role, or none, is a plain
    step of it (none: "" - no role here, which the board says). A drawing of any other shape - a
    room of more than 10 roles or more than 60 steps, as 0.1.9 refused them, steps, groups or ends
    no list - is left as it is, for the schema to say why.
    shortcut: a room that ran only if a problem was found (`when`) becomes a group that always runs
    - a group runs on no condition; draw a review before it and the condition by hand if one is
    seen to cost too much."""
    if not isinstance(graph, dict):
        return graph
    steps_in, groups_in, ends_in = (graph.get(key) for key in ("steps", "groups", "ends"))
    if (
        not isinstance(steps_in, list)
        or len(steps_in) > MOST_STEPS
        or not all(isinstance(one, list | None) for one in (groups_in, ends_in))
    ):
        return graph
    rooms = [one for one in steps_in if isinstance(one, dict) and _room_of(one) is not None]
    if not rooms or not all(
        isinstance(one.get("id"), str)
        and isinstance(room := _room_of(one), list)
        and len(room) <= MOST_ROOM_ROLES
        for one in rooms
    ):
        return graph
    nodes = [*steps_in, *(groups_in or []), *(ends_in or [])]
    taken = {one["id"] for one in nodes if isinstance(one, dict) and isinstance(one.get("id"), str)}
    names = {
        one["name"].casefold()
        for one in steps_in
        if isinstance(one, dict) and isinstance(one.get("name"), str)
    }
    # The roles that do the recipe's work at a step of their own (no review).
    writers = {
        str(who.get("role") or who.get("candidates")).casefold()
        for one in steps_in
        if isinstance(one, dict)
        and isinstance(who := one.get("who"), dict)
        and (who.get("role") or who.get("candidates"))
        and one.get("done_when") != "no_findings"
    }
    steps, groups = [], list(groups_in or [])
    for step in steps_in:
        room = _room_of(step) if isinstance(step, dict) else None
        if not isinstance(room, list):  # (no Room step: every one is a list by now)
            steps.append(step)
            continue
        roles = list(dict.fromkeys(one for one in room if isinstance(one, str)))
        rest = {key: value for key, value in step.items() if key not in ("id", "name", "who")}
        name = step["name"] if isinstance(step.get("name"), str) else ""
        fresh = _fresh(step["id"], taken)
        if len(roles) < 2 or rest.get("group") is not None:
            # (A room in a group was never ready: its roles go into that group.)
            steps += [
                {
                    **rest,
                    "id": step["id"] if at == 0 else next(fresh),
                    "name": name if at == 0 else _named(name, one, names),
                    "who": {"role": one},
                }
                for at, one in enumerate(roles or [""])
            ]
            continue
        group = {"id": step["id"], "name": name}
        if rest.get("pos") is not None:
            group["pos"] = rest["pos"]
        groups.append(group)
        # A room ran as a whole, and so did its condition and its review: a step in a group runs
        # on no condition of its own, and a role that does the work elsewhere would check its own
        # there - it works in the group, the others review (all of them review where that would
        # leave none: the recipe then says who would check its own work).
        rest = {**rest, "group": step["id"]}
        rest.pop("pos", None)
        rest.pop("when", None)
        works = (
            {one.casefold() for one in roles} & writers
            if rest.get("done_when") == "no_findings"
            and any(one.casefold() not in writers for one in roles)
            else set()
        )
        steps += [
            {
                **rest,
                "id": next(fresh),
                "name": _named(name, one, names),
                "who": {"role": one},
                **({"done_when": "done"} if one.casefold() in works else {}),
            }
            for one in roles
        ]
    return {**graph, "steps": steps, "groups": groups}


def _room_of(step: dict) -> object:
    """`without_rooms`: a step's room (its `who`'s "room"); None: no Room step."""
    who = step.get("who")
    return who.get("room") if isinstance(who, dict) else None


def _fresh(base: str, taken: set) -> Iterator[str]:
    """`without_rooms`: ids no node of the recipe has, from its Room step's (`NodeId`), one
    after another."""
    n = 1
    while True:
        while (made := f"{base[:36]}-{n}") in taken:
            n += 1
        taken.add(made)
        yield made


def _named(name: str, role: str, names: set) -> str:
    """`without_rooms`: "<the room's name> · <role>", within a step name's 60 characters, and no
    other step's (as a recipe is saved, two of one name are refused)."""
    made = (f"{name} · {role}" if name else role)[:54]  # (room for " 99999")
    n = 1
    while (shown := made if n == 1 else f"{made} {n}").casefold() in names:
        n += 1
    names.add(shown.casefold())
    return shown
