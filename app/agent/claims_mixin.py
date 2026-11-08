"""Who holds which file (`app.claims`): an agent's line and name, its claims and what the other
agents are told of them, and their release when it or its turn stops - `ClaimsMixin`.
"""

import asyncio
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.agent.ctx import Ctx
from app.db.models import Agent, Conversation, Run
from app.team import quoted
from app.workspace import Workspace

if TYPE_CHECKING:
    from app.agent import AgentRunner


class ClaimsMixin:
    # --- who holds which file --------------------------------------------------

    def _line(self: "AgentRunner", ctx: Ctx) -> tuple[str, ...]:
        """The agents above this one in its own chain, the nearest first."""
        line: list[str] = []
        walk = ctx.parent_id
        while walk is not None and walk not in line:
            line.append(walk)
            parent = self._ctxs.get(walk)
            walk = parent.parent_id if parent else None
        return tuple(line)

    def _name_of(self: "AgentRunner", agent_id: str) -> str:
        """What an agent is called - one of any conversation: a file is the project's."""
        known = self._ctxs.get(agent_id)
        if known is not None:
            return known.name
        with self._factory() as session:
            return session.scalar(select(Agent.name).where(Agent.id == agent_id)) or "an agent"

    def _told_of(self: "AgentRunner", ctx: Ctx, agents: list[str]) -> str:
        """The agents an agent waited for, as it is told of them: by their names - and,
        where they are of another conversation, with that conversation's title: two
        conversations wanted one file, and the one that waited is told which the other
        was. (From the record: one whose work is over may still have held the file.)"""
        with self._factory() as session:
            known = {agent_id: (name, cid, title) for agent_id, name, cid, title in session.execute(
                select(Agent.id, Agent.name, Conversation.id, Conversation.title)
                .join(Run, Run.id == Agent.run_id)
                .join(Conversation, Conversation.id == Run.conversation_id)
                .where(Agent.id.in_(agents))
            )}
        said: dict[str, list[str]] = {}  # "" for this conversation, else the other's words
        for agent_id in agents:
            name, cid, title = known.get(agent_id, ("an agent", ctx.cid, ""))
            where = "" if cid == ctx.cid else f" (of the conversation {quoted(title)})"
            if name not in said.setdefault(where, []):
                said[where].append(name)
        return " and ".join(" and ".join(names) + where for where, names in said.items())

    def claims_of(self: "AgentRunner", root: str) -> list[dict]:
        """The files of a project that are held now, each with the agent holding it."""
        return [{"path": path, "agent_id": agent} for path, agent in self.claims.of(root)]

    def copy_workspace(self: "AgentRunner", owner: str) -> Workspace | None:
        """The working copy of `owner`'s line while it is there (`app.views`): None once it
        was taken in, turned down or stopped."""
        copy = self._copies.get(owner)
        return copy.workspace() if copy is not None else None

    def holds(self: "AgentRunner", root: str, path: str) -> tuple[str, str] | None:
        """The agent that holds a file of a project now, as (id, name); None for none."""
        holder = self.claims.holder(root, path)
        return (holder, self._name_of(holder)) if holder else None

    def _claims_changed(self: "AgentRunner", root: str | None, cid: str) -> None:
        """Tell the project's conversations who holds what, when that is no longer what
        they were last told. It is on record for the conversation it happened in; the
        others are told if someone is watching, and read it with their next snapshot.

        When only who waits for a file has changed - an agent began to wait, or its wait
        was stopped - the others are told to look again, and nothing goes on record: what
        they show of two conversations wanting one file is read from the board."""
        if root is None:  # (a plain chat holds no file)
            return
        held = self.claims_of(root)
        folder = str(Workspace(root).root).casefold()
        waited = self.claims.waited(root)
        same_held = self._claims_told.get(folder, []) == held
        if same_held and self._waits_told.get(folder, []) == waited:
            return
        if held:
            self._claims_told[folder] = held
        else:
            self._claims_told.pop(folder, None)
        if waited:
            self._waits_told[folder] = waited
        else:
            self._waits_told.pop(folder, None)
        with self._factory() as session:
            # The other conversations of this one's project, and of no other.
            project = select(Conversation.project_id).where(Conversation.id == cid)
            others = list(session.scalars(
                select(Conversation.id).where(
                    Conversation.project_id == project.scalar_subquery(),
                    Conversation.id != cid,
                )
            ))
        if not same_held:
            self.bus.emit(cid, None, "claims.changed", {"claims": held})
        for other in others:
            self.bus.emit_transient(other, "claims.changed", {"claims": held})

    def _release(self: "AgentRunner", agent_id: str) -> None:
        """An agent's work is over: the files it held are free, or are again the agent's
        it took them from, and the agents that waited for them are woken in their order."""
        self.claims.release(agent_id)
        known = self._ctxs.get(agent_id)
        if known is not None:
            self._claims_changed(known.root, known.cid)

    def _work_over(self: "AgentRunner", agent_id: str) -> None:
        """An agent's work is over: the files it held are let go - unless it changed
        them in a working copy that is still to be taken into the project. Then they
        stay held until that is decided (`_drop_copy`): its own stay its own, and the
        ones of an agent that worked in the copy of the agent above it go on to that."""
        known = self._ctxs.get(agent_id)
        self._close_browser(agent_id)
        owner = self._copy_owner(known) if known is not None else None
        if owner is None or self._copies.get(owner) is None:
            self._release(agent_id)
        elif owner != agent_id and known is not None:
            self.claims.release(agent_id, to=owner)
            self._claims_changed(known.root, known.cid)

    def _close_browser(self: "AgentRunner", agent_id: str) -> None:
        """Slice 51: an agent's browser ends with it (or with its run); its profile goes."""
        one = self._browsers.pop(agent_id, None)
        if one is not None:
            task = asyncio.ensure_future(one.close())
            self._browser_closing.add(task)
            task.add_done_callback(self._browser_closing.discard)

    def _release_run(self: "AgentRunner", run_id: str) -> None:
        mine = [a for a, known in self._ctxs.items() if known.run_id == run_id]
        for agent_id in mine:
            self._drop_copy(agent_id)
            self._close_browser(agent_id)
        for agent_id in mine:
            self._release(agent_id)
