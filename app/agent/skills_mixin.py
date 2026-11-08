"""Skills (`app.skills`): which an agent is given and told of, use_skill / run_skill_script /
add_skill, and the user's waiting word on a skill, an outside folder or a new role
(`asks_skill`, `asks_outside`, `decide_role`) - `SkillsMixin`.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from app import catalog, models_dev, skills
from app.agent.ctx import Ctx, _NobodyToAsk
from app.commands import web_off_reason
from app.db.models import Agent, McpServer, Provider, Skill, now
from app.roles import find_role, is_team_lead, tools_off
from app.tools import ToolError
from app.workspace import MAX_READ_BYTES

if TYPE_CHECKING:
    from app.agent import AgentRunner

SKILL_REJECTED = (
    "rejected: the user declined to add the skill {name}. This is their decision, not a "
    "tool error: do not propose it again. Go on without it, or ask what they would like."
)

# Told to an agent whose role has skills, with each one's name and line.
SKILLS_PROMPT = (
    "Your skills - ready instructions for kinds of work. Before you do work one of them is "
    "for, read the whole of it with use_skill and follow it:"
)

# For a CLI working with its own tools, which cannot ask for one: the skills themselves.
SKILLS_GIVEN = "Your skills - ready instructions for kinds of work; follow the one a job is for:"

SKILLS_BUDGET = 40_000
CUT_SHORT = "\n[cut short here: the skills are too long]"


def _in_full(known: list[Skill]) -> list[tuple[Skill, str]]:
    """The skills `SKILLS_GIVEN` holds, each with its body, as far as the budget goes: the one
    that reaches it cut short (`CUT_SHORT`), those after it not named either."""
    held, left = [], SKILLS_BUDGET
    for skill in known:
        body = skills.front(skill.text)[1]
        if len(body) > left:
            body = body[:left] + CUT_SHORT
        held.append((skill, body))
        left -= len(body)
        if left <= 0:
            break
    return held


class SkillsMixin:
    # --- skills (`app.skills`) -----------------------------------------------

    def _skills(self: "AgentRunner", ctx: Ctx) -> list[Skill]:
        """The skills of the agent's role it is given, read off the record each time: one the
        user unticks, or switches off, is gone at once; one it cannot run here never comes
        (K-skill-uyum, `skills.split`). Every way to a skill comes through here."""
        with self._factory() as session:
            return self._skill_split(session, ctx.role, ctx.tools, ctx.mcp, ctx.provider_id,
                                     ctx.model_name)[0]

    def _skill_split(self: "AgentRunner", session: Session, role_name: str, tools, mcp,
                     provider_id: str | None, model: str | None
                     ) -> tuple[list[Skill], dict[str, str]]:
        """A role's skills as `skills.split` has them for an agent with these tools (less
        those off on the Tools page) and MCP servers, on this provider's model."""
        role = find_role(session, role_name)
        kept = list(session.scalars(
            select(Skill).where(Skill.name.in_(role.skills if role else []))
            .order_by(Skill.created_at, literal_column("skills.rowid"))).all())
        if not kept:
            return [], {}
        provider = session.get(Provider, provider_id) if provider_id else None
        mute = provider is not None and catalog.no_tool_calls(
            provider, catalog.model_key(provider, model),
            models_dev.load(self.settings.runtime_root))
        # (A server switched off on the Tools page is not had, as a tool switched off is not.)
        return skills.split(kept, set(tools) - tools_off(session), set(mcp) - self._servers_off(),
                            mute)

    def _servers_off(self: "AgentRunner") -> set[str]:
        """The names of the MCP servers switched off on the Tools page: given to no agent."""
        with self._factory() as session:
            return set(session.scalars(select(McpServer.name).where(McpServer.enabled.is_(False))))

    def _skills_told(self: "AgentRunner", ctx: Ctx, can_ask: bool) -> str:
        """What an agent with skills is told of them: each one's name and line, where it can
        read the whole with use_skill - else the skills themselves, as far as the budget
        goes."""
        known = self._skills(ctx)
        if not known:
            return ""
        if can_ask:
            return "\n\n" + SKILLS_PROMPT + "".join(
                f"\n- {skill.name}: {skill.description}" for skill in known)
        return "\n\n" + SKILLS_GIVEN + "".join(
            f"\n\n## {skill.name}\n{skill.description}\n\n{body}"
            for skill, body in _in_full(known))

    def _given_in_brief(self: "AgentRunner", ctx: Ctx) -> None:
        """R190: the skills its instructions hold whole (`_skills_told` for an agent that cannot
        call use_skill) on its record, so that they are not said to be given and never read.
        shortcut: native Claude Code's, given in its instructions where no plugin holds them
        (`run_native`), are not marked; mark them there if their rows mislead."""
        named = [skill.name for skill, body in _in_full(self._skills(ctx))
                 if not body.endswith(CUT_SHORT)]
        with self._factory() as session:
            held = session.get_one(Agent, ctx.agent_id).skills
        if named and held is not None and held.get("in_brief") != named:
            self._set_agent(ctx.cid, ctx.agent_id, skills={**held, "in_brief": named})

    def _skill_of(self: "AgentRunner", ctx: Ctx, name: object) -> Skill:
        found = next((skill for skill in self._skills(ctx) if skill.name == name), None)
        if found is None:
            raise ToolError(f"{name!r} is not one of your skills")
        return found

    def _use_skill(self: "AgentRunner", ctx: Ctx, args: dict) -> str:
        """The whole of one of the agent's skills, or another of its files."""
        skill, file = self._skill_of(ctx, args.get("name")), args.get("file") or "SKILL.md"
        if file == "SKILL.md":
            others = [rel for rel in skill.files if rel != "SKILL.md"]
            listed = f"\n\n[Its other files, for use_skill with file: {', '.join(others)}]"
            return skills.front(skill.text)[1] + (listed if others else "")
        if file not in skill.files:  # (only a path on its list: no way out of the folder)
            raise ToolError(f"{file!r} is not a file of the skill {skill.name}")
        try:
            data = Path(skill.folder, file).read_bytes()
        except OSError as exc:
            raise ToolError(f"could not read {file!r}: {exc.strerror or exc}") from None
        text = data[:MAX_READ_BYTES].decode("utf-8", "replace")
        return text + ("\n[cut short: the file is longer]" if len(data) > MAX_READ_BYTES else "")

    def _skill_script(self: "AgentRunner", ctx: Ctx, args: dict) -> tuple[dict, bool]:
        """The command a skill's script runs as, and whether it has the user's leave to run
        without asking: the skill's, for a script that is still what was copied."""
        if "run_command" not in ctx.tools:
            raise ToolError(f"run_skill_script is not available to the {ctx.role} role")
        skill, script = self._skill_of(ctx, args.get("skill")), args.get("script")
        script = script.replace("\\", "/") if isinstance(script, str) else ""
        if script not in skill.scripts:  # (a path on its list only: none outside it)
            raise ToolError(
                f"{script!r} is not a script of the skill {skill.name}: its scripts are "
                f"{', '.join(skill.scripts) or 'none'}")
        with self._factory() as session:
            project = self._project(session, ctx.cid)
        if project is not None and project.exec_location == "docker":
            # shortcut: the container does not see KOLONİ's store; mount it read-only when
            # skills are wanted in Docker projects.
            raise ToolError("a skill's script does not run in a project that runs in Docker")
        # The leave is for the skill as it was copied: any file of it changed, it is asked.
        # Nor while web is off for one whose line reaches the internet (K-web-komut).
        # shortcut: by its line, which is only its path - a script that fetches is not seen.
        line = skills.script_line(skill.folder, script)
        leave = skill.scripts_run_unasked and skills.unchanged(skill.folder, skill.hashes) and (
            not web_off_reason(line, self._off()))
        return {"command": line}, leave

    async def _add_skill(self: "AgentRunner", ctx: Ctx, call_id: str, args: dict) -> tuple[str,  # noqa: C901
                         str]:
        """Propose a skill to the user - at every level, on a card: what it holds is read
        now and shown, and that, as it was read, is what is kept on their yes."""
        folder, github, wanted = args.get("folder"), args.get("github"), args.get("roles") or []
        if not all(isinstance(where, str | None) for where in (folder, github)) or not (
                isinstance(wanted, list) and all(isinstance(name, str) for name in wanted)):
            raise ToolError("folder and github must be strings and roles a list of role names")
        roles = []
        with self._factory() as session:
            for name in wanted:
                role = find_role(session, name)
                if role is None:
                    raise ToolError(f"there is no role named {name}")
                if is_team_lead(session, role):
                    raise ToolError(f"{role.name} is a team's coordinator: its skills are the "
                                    "user's to give, on the Agents page")
                roles.append(role.name)
        try:
            # (A folder in no place KOLONİ never opens; from GitHub only the listing, the
            # SKILL.md, the licence and the scripts: what the card shows.)
            found = await asyncio.to_thread(skills.take, folder, github)
        except skills.SkillError as exc:
            raise ToolError(str(exc)) from None
        with self._factory() as session:
            if skills.named(session, found.name) is not None:
                raise ToolError(
                    f"there is already a skill named {found.name}: the user gives it to a role "
                    "on the Agents page")
        refused = self._nobody_to_ask(ctx, "skill", f"add the skill {found.name}")
        if refused is not None:
            raise _NobodyToAsk(refused)
        proposal = {
            "tool_call_id": call_id, "run_id": ctx.run_id, "agent_id": ctx.agent_id,
            # (Off the loop: what its scripts say is read from up to 5 MB of text.)
            "roles": list(dict.fromkeys(roles)), **await asyncio.to_thread(found.shown),
        }
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._skill_requests[call_id] = (ctx.cid, proposal, future)
        self.bus.emit(ctx.cid, ctx.run_id, "skill_request.created", proposal)
        self._update_run(ctx.run_id, ctx.cid, status="waiting_approval")

        def resolved(*_heard) -> None:
            # Once, the moment the user has spoken (as for a role).
            if self._skill_requests.pop(call_id, None) is not None:
                self.bus.emit(
                    ctx.cid, ctx.run_id, "skill_request.resolved", {"tool_call_id": call_id})

        try:
            decision = await self._users_word(ctx, future, resolved)
        finally:
            resolved()
            self._update_run(ctx.run_id, ctx.cid, status="running")
        if decision == "reject":
            return "denied", SKILL_REJECTED.format(name=found.name)
        try:
            found = await asyncio.to_thread(skills.whole, found)  # (from GitHub: the rest)
        except skills.SkillError as exc:
            raise ToolError(str(exc)) from None
        with self._factory() as session:
            try:
                skill = skills.add(session, self.settings.runtime_root, found,
                                   unasked=decision != "ask_scripts")
            except skills.SkillError as exc:  # one of its name was added meanwhile
                raise ToolError(str(exc)) from None
            for name in proposal["roles"]:
                role = find_role(session, name)
                if role is not None and skill.name not in role.skills:
                    role.skills = [*role.skills, skill.name]
                    role.updated_at = now()
            session.commit()
            payload = {"id": skill.id, "name": skill.name, "roles": proposal["roles"]}
        self.bus.emit(ctx.cid, ctx.run_id, "skill.created", payload)
        given = f" and given to {', '.join(proposal['roles'])}" if proposal["roles"] else ""
        return "succeeded", f'added the skill "{found.name}"{given}.'

    def asks_skill(self: "AgentRunner", call_id: str) -> bool:
        """Whether this call waits for the user's word on a skill an agent asked to add."""
        return call_id in self._skill_requests

    def asks_outside(self: "AgentRunner", call_id: str) -> bool:
        """Whether this call waits for the user's word on a path outside the project."""
        return call_id in self._outside_asks

    def role_waits(self: "AgentRunner", call_id: str) -> bool:
        """Whether a role an agent asked to create, or a path outside the project, still
        waits for the user's word."""
        return (call_id in self._role_requests or call_id in self._outside_asks
                or call_id in self._skill_requests)

    def decide_role(self: "AgentRunner", call_id: str, decision: str) -> bool:
        """Deliver the user's word on a role an agent asked to create ("reject", or
        anything else for yes), or on a path outside the project: "reject", "folder", or
        "once" (a plain "approve" too)."""
        request = self._role_requests.get(call_id) or self._skill_requests.get(call_id)
        if request is not None:
            future: asyncio.Future[str] | None = request[2]
        else:
            future = self._outside_asks.get(call_id)
            if decision == "approve":
                decision = "once"  # a yes with no scope is for this call alone
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True
