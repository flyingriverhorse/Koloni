"""What an agent's opener is told of the changes of its working copy that did not reach the project
(`AgentRunner._merge`, `_take_in`): moved out of `app.agent` whole, as it was."""

from app.agent.ctx import Ctx
from app.agent.words import MAX_PATHS_TOLD

NOT_APPLIED = (
    "These changes of {name}'s were not applied to the project: {files}. Do not go on "
    "as if they were there"
)
MEANWHILE = "changed in the project meanwhile"
PROJECTS_LINES = (
    "In {files} the user kept the project's own lines where {name} had changed the same "
    "ones: {name}'s version of those lines is not there."
)
# Of a file taken together with the project's own changes (B-59: the user's line was taken
# for the agent's). Each file with the lines of it that are the project's, where it added any.
THEIRS_KEPT = (
    "In {files} the project's own changes made meanwhile were kept beside {name}'s: they "
    "are not {name}'s doing."
)


def not_applied(ctx: Ctx, files: dict, why: str | None) -> str:
    """What an agent's opener is told of the changes that did not reach the project
    ("" when all did). `why`: one reason for all of them, else each has its own.
    And of a file that did, with the project's own lines where the two clashed: the
    agent's version of those lines is not there, by the user's word."""
    left = [one for one in files.values() if one["state"] != "applied"]
    lines = [
        path
        for path, one in files.items()
        if one["state"] == "applied" and one.get("chose") == "project"
    ]
    theirs = [
        f"{path} ({one['theirs']})" if one["theirs"] else path
        for path, one in files.items()
        if one["state"] == "applied" and "theirs" in one
    ]
    kept_lines = " ".join(
        filter(
            None,
            [
                PROJECTS_LINES.format(name=ctx.name, files=", ".join(lines[:MAX_PATHS_TOLD]))
                if lines
                else "",
                THEIRS_KEPT.format(name=ctx.name, files=", ".join(theirs[:MAX_PATHS_TOLD]))
                if theirs
                else "",
            ],
        )
    )
    if not left:
        return kept_lines
    # Each reason once, with the files it goes for.
    by_reason: dict[str, list[str]] = {}
    for one in left[:MAX_PATHS_TOLD]:
        reason = "" if why else one.get("note") or MEANWHILE
        by_reason.setdefault(reason, []).append(one["path"])
    told = [
        ", ".join(paths) + (f" ({reason})" if reason else "") for reason, paths in by_reason.items()
    ]
    if len(left) > MAX_PATHS_TOLD:
        told.append(f"and {len(left) - MAX_PATHS_TOLD} more")
    said = NOT_APPLIED.format(name=ctx.name, files="; ".join(told))
    return " ".join(filter(None, [f"{said}: {why}." if why else f"{said}.", kept_lines]))
