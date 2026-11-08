import asyncio
import contextlib
import weakref
from datetime import timedelta
from time import monotonic
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app import knows, roles, team
from app.api import knowledge_page
from app.api.deps import get_session, require_origin, require_own_origin
from app.api.providers import apply_choice
from app.db.models import (
    Agent,
    Category,
    Conversation,
    McpServer,
    Project,
    ProjectKnowledge,
    Provider,
    Role,
    Run,
    Skill,
    Team,
    now,
)
from app.model_client import EFFORTS, ModelUnavailable, OwnStop
from app.providers import (
    TIERS,
    NotListed,
    allowed,
    list_providers,
    works_with_own_tools,
)
from app.roles import BUILTIN_ROLES, shown_name
from app.room import NO_MEMBER_ON
from app.schemas import (
    AskedModel,
    ExpertIn,
    HistoryCount,
    HistoryJob,
    KnowledgeStateOut,
    LastRun,
    LearnIn,
    RoleIn,
    RoleJobOut,
    RoleJobsOut,
    RoleModelOut,
    RoleOut,
    RolePatch,
    RolesActivityOut,
    RolesHistoryOut,
    RunOn,
    Tier,
)
from app.team import (
    ONLY_IN_THE_PROJECT,
    ClosedToAgents,
    asked_how_hard,
    only_in_project,
    would_run,
)

router = APIRouter(prefix="/api/roles", tags=["roles"])

# (A reasoning level is one too: a higher one costs more, and is the user's to give. So is
# a window: a larger one than the model's is refused by its server.)
LIMITS = ("max_steps", "max_tokens", "effort", "max_effort", "context_window")


def clean_name(name: str) -> str:
    try:
        return roles.check_name(name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def clean_tools(tools: list[str]) -> list[str]:
    try:
        return roles.check_tools(tools)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def clean_expert(role: Role) -> None:
    try:
        roles.expert_tools(role.tools, knows.in_full(role) or None)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


find_by_name = roles.find_role


def _role(session: Session, role_id: str) -> Role:
    role = session.get(Role, role_id)
    if role is None:
        raise HTTPException(404, "role not found")
    return role


def apply_limits(session: Session, request: Request, role: Role, body) -> None:
    """Set what may be picked for a role's sub-agents, and how far one agent of it may
    go, from what the request sent (null: every provider of the guide; no limit)."""
    sent = body.model_fields_set
    if "pick_from" in sent:
        picks = None if body.pick_from is None else list(dict.fromkeys(body.pick_from))
        if any(session.get(Provider, provider_id) is None for provider_id in picks or ()):
            raise HTTPException(422, "unknown provider")
        role.pick_from = picks
    if "models" in sent:
        # K-rol-model-sirasi: in the user's order, the same pair once; empty is no list.
        listed = [{"provider_id": provider_id, "model_id": model_id} for provider_id, model_id
                  in dict.fromkeys((one.provider_id, one.model_id.strip())
                                   for one in body.models or [])]
        providers = {pid: session.get(Provider, pid)
                     for pid in {one["provider_id"] for one in listed}}
        if any(provider is None for provider in providers.values()):
            raise HTTPException(422, "unknown provider")
        # B-330: judged as at run time (`team.guide`), where such an entry is passed over. One
        # switched off is kept, not refused: passed over until it is switched on again.
        on = [p for p in providers.values() if p and p.enabled is not False]
        if len(team.guide(on)) < len(on):
            raise HTTPException(422, "a provider of the list is not used for sub-agents")
        if any(not one["model_id"] or not one["model_id"].isprintable() for one in listed):
            raise HTTPException(422, "a model name is one line of printable text")
        role.models = listed or None
    for limit in LIMITS:
        if limit in sent and getattr(body, limit) != getattr(role, limit):
            # As a project's limit on a turn's tokens: the user's to change from the
            # app's own page, not a command's that an agent runs against the app's address.
            require_own_origin(request)
            setattr(role, limit, getattr(body, limit))
    if role.effort and role.max_effort and (
        EFFORTS.index(role.effort) > EFFORTS.index(role.max_effort)
    ):
        raise HTTPException(422, "the default level is above the most a sub-agent may get")


def apply_place(session: Session, request: Request, role: Role, body) -> None:
    """Set a role's kind of work, tier rule, on / off and teams from what the request sent.
    All of these are the user's to change from the app's own page (slices 62, 81b) - not a
    command's an agent runs against the app's address; and the Lead, the Planner and the
    Observer are never off."""
    sent = body.model_fields_set
    # A team's lead is its team's (slice 63a): it keeps its kind, is in no team, and is on or off
    # with its team's switch. (Its form sends them unchanged.)
    if roles.is_team_lead(session, role) and (
            ("kind" in sent and body.kind not in (None, role.kind))
            or ("enabled" in sent and body.enabled is not None and not body.enabled)
            or ("teams" in sent and body.teams)):
        raise HTTPException(422, "a team's lead keeps its kind, is in no team, and is turned "
                                 "on or off on its team")
    for field in ("kind", "tier", "tier_min", "tier_max"):
        if field in sent and (field != "kind" or body.kind is not None):
            if getattr(body, field) != getattr(role, field):
                require_own_origin(request)
                # A role's kind is one of the categories (slice 63b); a lead's, unchanged, is none.
                if field == "kind" and session.get(Category, body.kind) is None:
                    raise HTTPException(422, "unknown category")
            setattr(role, field, getattr(body, field))
    if role.tier_min and role.tier_max and TIERS.index(role.tier_min) > TIERS.index(role.tier_max):
        raise HTTPException(422, "the lowest tier is above the highest")
    # (A new role is on: saying so asks nothing.)
    was_on = role.enabled is not False
    if "enabled" in sent and body.enabled is not None and body.enabled != was_on:
        require_own_origin(request)
        if role.builtin and role.name in roles.ALWAYS and not body.enabled:
            raise HTTPException(422, f"the {role.name} is always there: it cannot be off")
        role.enabled = body.enabled
    # 89g: its work then runs inside a Lead, not stoppable alone - the user's to say, too.
    if "inside_cli" in sent and body.inside_cli is not None and (
            body.inside_cli != bool(role.inside_cli)):
        require_own_origin(request)
        role.inside_cli = body.inside_cli
    if "teams" in sent and body.teams is not None and set(body.teams) != {t.id for t in role.teams}:
        require_own_origin(request)
        teams = [session.get(Team, team_id) for team_id in dict.fromkeys(body.teams)]
        if None in teams:
            raise HTTPException(422, "unknown team")
        role.teams = cast(list[Team], teams)


def own_if_limited(request: Request, role: Role) -> None:
    """One rule for a role's limit: it is set, changed or taken away only from the app's
    own page - by a new role or an edit (`apply_limits`), and here by what takes the
    limit away with the role's name: a reset, deleting the role, or renaming it (a role
    is opened by its name, and one made again under the old name would have none)."""
    if any(getattr(role, limit) is not None for limit in LIMITS):
        require_own_origin(request)


@router.get("", response_model=list[RoleOut])
def list_roles(session: Session = Depends(get_session)):
    return roles.list_roles(session)


# Agents that never ran: proposed and not yet answered, or turned down by the user.
NEVER_RAN = ("proposed", "rejected")
DAYS = 30


@router.get("/activity", response_model=RolesActivityOut)
def activity(session: Session = Depends(get_session)):
    """What the Agents page draws from the record: each role's latest agent, its agents at
    work now, and the agents the Lead (a turn's own, not a sub-agent's) opened in each role
    in the last 30 days."""
    ran = Agent.status.not_in(NEVER_RAN)
    latest = select(
        Agent.role_name, Agent.provider_name, Agent.model_id, Agent.tier,
        func.row_number().over(partition_by=Agent.role_name, order_by=(
            Agent.created_at.desc(), literal_column("agents.rowid").desc())).label("n"),
    ).where(ran).subquery()
    last = {
        row.role_name: LastRun(provider_name=row.provider_name, model_id=row.model_id,
                               tier=row.tier)
        for row in session.execute(select(latest).where(latest.c.n == 1))
    }
    running = {role: count for role, count in session.execute(
        select(Agent.role_name, func.count()).where(Agent.status == "running")
        .group_by(Agent.role_name))}
    return RolesActivityOut(last=last, running=running)


# How a job or a team's run ended, in the History's three colours; anything else is in progress.
AGENT_ENDS = {"completed": "done", "failed": "failed", "cancelled": "failed",
              "interrupted": "failed"}
TEAM_ENDS = {"in": "done", "ready": "done", "done": "done", "failed": "failed",
             "stopped": "failed", "interrupted": "failed"}
HISTORY_JOBS = 200


def _counted(counts: dict[str, HistoryCount], name: str, end: str, n: int = 1) -> None:
    one = counts.setdefault(name, HistoryCount(name=name))
    setattr(one, end, getattr(one, end) + n)


def _most_first(counts: dict[str, HistoryCount]) -> list[HistoryCount]:
    return sorted(counts.values(), key=lambda one: -(one.done + one.failed + one.running))


@router.get("/history", response_model=RolesHistoryOut)
def history(days: int = Query(DAYS, ge=1, le=DAYS), session: Session = Depends(get_session)):
    """The Agents page's History, read from the record as it is: no new table, nothing guessed."""
    since = now() - timedelta(days=days)
    teams: dict[str, HistoryCount] = {}
    recipes: dict[str, HistoryCount] = {}
    of: dict[str, tuple[list[str], list[str]]] = {}  # agent id -> its teams, its recipes
    named = dict(session.execute(select(Team.id, Team.name)).tuples().all())
    for kept in session.scalars(select(Run.teams).where(
            Run.created_at >= since, Run.teams.is_not(None))):
        for row in kept or []:
            state = row.get("state")
            if not state:  # picked, never run
                continue
            end = TEAM_ENDS.get(state["status"], "running")
            team_name = state.get("team") or named.get(row["team_id"]) or "a team no longer kept"
            _counted(teams, team_name, end)
            if state.get("recipe"):  # "" for a team with no recipe
                _counted(recipes, state["recipe"], end)
            for agent_id in state.get("agents", []):
                mine = of.setdefault(agent_id, ([], []))
                mine[0].append(team_name)
                if state.get("recipe"):
                    mine[1].append(state["recipe"])
    # One clock for both halves: the turn's start (a job is of the turn it was opened in).
    ran = [Agent.status.not_in(NEVER_RAN), Run.created_at >= since]
    by_role: dict[str, HistoryCount] = {}
    for role_name, status, count in session.execute(
            select(Agent.role_name, Agent.status, func.count()).join(Run, Agent.run_id == Run.id)
            .where(*ran, Agent.depth > 0).group_by(Agent.role_name, Agent.status)):
        _counted(by_role, role_name, AGENT_ENDS.get(status, "running"), count)
    # A turn's own Lead is the turn, not a job of the Lead role (as `/activity` keeps it).
    lead_turns = session.scalar(select(func.count()).select_from(Agent).join(
        Run, Agent.run_id == Run.id).where(*ran, Agent.depth == 0)) or 0
    jobs = session.execute(
        select(Agent.id.label("agent_id"), Agent.role_name, Agent.status, Agent.provider_name,
               Agent.model_id, Agent.created_at, Conversation.id.label("conversation_id"),
               Conversation.title)
        .join(Run, Agent.run_id == Run.id)
        .join(Conversation, Run.conversation_id == Conversation.id)
        .where(*ran, Agent.depth > 0)
        .order_by(Agent.created_at.desc(), literal_column("agents.rowid").desc())
        .limit(HISTORY_JOBS)).all()
    return RolesHistoryOut(
        days=days, lead_turns=lead_turns, jobs_limit=HISTORY_JOBS,
        roles=_most_first(by_role),
        teams=_most_first(teams),
        recipes=_most_first(recipes),
        jobs=[HistoryJob(
            id=row.agent_id, role_name=row.role_name, conversation_id=row.conversation_id,
            conversation_title=row.title, status=row.status, provider_name=row.provider_name,
            model_id=row.model_id,
            created_at=row.created_at, teams=of.get(row.agent_id, ([], []))[0],
            recipes=of.get(row.agent_id, ([], []))[1],
        ) for row in jobs],
    )


@router.get("/{role_id}/jobs", response_model=RoleJobsOut)
def jobs(role_id: str, session: Session = Depends(get_session)):
    """A role's latest agents (20 at most) with their conversations, and its last 30 days."""
    role = _role(session, role_id)
    mine = [Agent.role_name == role.name, Agent.status.not_in(NEVER_RAN)]
    rows = session.execute(
        select(Agent, Conversation.id, Conversation.title)
        .join(Run, Agent.run_id == Run.id)
        .join(Conversation, Run.conversation_id == Conversation.id)
        .where(*mine)
        .order_by(Agent.created_at.desc(), literal_column("agents.rowid").desc()).limit(20))
    recent = session.scalars(
        select(Agent).where(*mine, Agent.created_at >= now() - timedelta(days=DAYS))).all()
    told = [a for a in recent if a.input_tokens_total is not None or a.output_tokens is not None]
    return RoleJobsOut(
        jobs=[RoleJobOut(
            id=agent.id, conversation_id=cid, conversation_title=title, status=agent.status,
            provider_name=agent.provider_name, model_id=agent.model_id, tier=agent.tier,
            chosen_why=agent.chosen_why, task=agent.task, created_at=agent.created_at,
        ) for agent, cid, title in rows],
        days30={
            "jobs": len(recent), "failed": sum(a.status == "failed" for a in recent),
            "tokens": sum((a.input_tokens_total or 0) + (a.output_tokens or 0) for a in told),
            "unreported": len(recent) - len(told),
        },
    )


# A model's levels, asked of its provider for the Agents page: one that does not answer
# holds the page this long at most, and is not asked again for a while.
LEVELS_SECONDS = 3.0
LEVELS_FAILED_FOR = 60.0
_failed: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()  # client -> when


async def _levels(client) -> tuple[list | None, int | None]:
    """The levels a client's model takes: [] where it takes none (nothing is sent to it),
    None where asking failed; and its window as found, None where unknown. Only a client
    whose asking spends nothing (`free_info`) is asked; any other carries its levels: a
    CLI's from catalog.json, an OpenAI-compatible service's from the catalogue
    (`app.catalog.facts`, as `/model-facts` says them). A llama-server says its window and
    levels without a cost (`found_window`)."""
    if not getattr(client, "free_info", False):
        found, window = getattr(client, "found_window", None), None
        with contextlib.suppress(TimeoutError):  # held no longer than the levels are
            window = await asyncio.wait_for(found(), LEVELS_SECONDS) if found else None
        # (A hosted service has no `/props`: its catalogue's window, as its agents use it.)
        return (list(getattr(client, "efforts", None) or ()),
                window or getattr(client, "catalogued_window", None))
    if client in _failed and monotonic() - _failed[client] < LEVELS_FAILED_FOR:
        return None, None
    try:
        info = await asyncio.wait_for(client.info(), LEVELS_SECONDS)
    except (ModelUnavailable, TimeoutError):
        _failed[client] = monotonic()
        return None, None
    return list(info.efforts or ()), info.context_window


@router.get("/models", response_model=list[RoleModelOut])
async def role_models(
    request: Request, conversation_id: str | None = None, levels: bool = False,
):
    """Who uses what: for every role, the provider and model an agent of it would run on
    now in this conversation (without one: in a new one), where that comes from, and the
    providers an agent may pick for it instead - with what stands in the way of either
    now, in the words an agent that asks for it is told. Read off `would_run`, which is
    what `spawn_agent` acts on. And, where the conversation has its lead's model follow
    the message, whom the Lead's question would go to (`asked_how_hard`). `levels`: also
    the levels each model takes and its window (`_levels`), asked once per client and all
    at once."""
    # Off the event loop, as a plain endpoint is; done before the levels are waited for,
    # so a stalled provider holds no connection.
    told, clients = await asyncio.to_thread(_who_uses_what, request, conversation_id)
    if levels:
        distinct = list(dict.fromkeys(clients))
        takes = dict(zip(distinct, await asyncio.gather(*map(_levels, distinct)), strict=True))
        for row, client in zip(told, clients, strict=True):
            row.efforts, row.context_window = takes[client]
            row.level_named = getattr(client, "level_named", False) is True
    return told


def _run_on(session: Session, providers) -> list[tuple[str, RunOn, object]]:
    """Every provider, by its shown name, with the model an agent given it would run with: its
    default, else the first of its listed models it may run (`allowed`); none where it may run
    with neither. And its client: whether a role's agent could be a step there is the role's
    (`only_in_project` with its tools, B-301)."""
    found = []
    for provider in list_providers(session):
        for model in [provider.default_model, *(m["name"] for m in provider.models or [])]:
            try:
                allowed(provider, model)
            except NotListed:
                continue
            client = providers.client(provider, model)
            found.append((shown_name(provider.name), RunOn(
                provider_id=provider.id, model_id=model, step=not only_in_project(client),
                room=not works_with_own_tools(provider)), client))
            break
    return found


def _who_uses_what(request: Request, conversation_id: str | None) -> tuple[list, list]:
    """Each role's row of who uses what, and the client its agent would run on."""
    told, clients = [], []
    with request.app.state.session_factory() as session:
        conversation = None
        if conversation_id is not None:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                raise HTTPException(404, "conversation not found")
        # The role a turn's question is asked for (`AgentRunner._by_how_hard`).
        auto = conversation is not None and conversation.lead_auto
        lead = roles.find_role(session, roles.LEAD) if auto else None
        run_on = _run_on(session, request.app.state.providers)
        for role in roles.list_roles(session):
            try:
                would = would_run(session, role, conversation)
            except OwnStop as exc:  # no provider at all: there is nothing to say of any role
                raise HTTPException(409, str(exc)) from None
            asks = None
            if lead is not None and role.id == lead.id:
                asks = asked_how_hard(session, would, request.app.state.providers)
            client = request.app.state.providers.client(would.provider, would.model_id)
            clients.append(client)
            on = shown_name(would.provider.name)
            cannot_step = None
            if only_in_project(client, role.tools):
                # B-301: as a recipe's step it is moved to the next provider that can be one
                # (`would_run`'s `step`), where there is one: said with where, and why.
                stepped = would_run(session, role, conversation,
                                    step=request.app.state.providers)
                cannot_step = ONLY_IN_THE_PROJECT.format(provider=on) + (
                    f". As a step it runs on {shown_name(stepped.provider.name)} · "
                    f"{stepped.model_id or 'its default'} ({stepped.moved})"
                    if stepped.moved and stepped.provider.id != would.provider.id else "")
            told.append(RoleModelOut(
                cannot_step=cannot_step,
                cannot_room=NO_MEMBER_ON.format(provider=on, role=shown_name(role.name))
                if works_with_own_tools(would.provider) else None,
                role=role.name, provider_name=would.provider.name, model_id=would.model_id,
                source=would.source, tier=cast(Tier | None, would.tier), moved=would.moved,
                pick_from=[entry.name for entry in would.pick_from],
                # (B-385: what the user does about a model closed to agents, in its words)
                cannot_run=str(would.refused) if isinstance(would.refused, ClosedToAgents)
                else would.refused.to_agent if would.refused else would.cannot_open,
                cannot_pick=would.cannot_pick,
                # (less those an agent of it could not be opened on in this chat)
                run_on=[one.model_copy(update={"step": not only_in_project(its, role.tools)})
                        for name, one, its in run_on if name not in would.cannot_pick],
                asks_how_hard=AskedModel(provider_name=asks[0].name, model_id=asks[1])
                if asks else None,
            ))
    return told, clients


@router.post("", response_model=RoleOut, status_code=201,
             dependencies=[Depends(require_own_origin)])
def create_role(body: RoleIn, request: Request, session: Session = Depends(get_session)):
    role = new_role(session, request, body)
    session.commit()
    return role


@router.post("/experts", response_model=RoleOut, status_code=201,
             dependencies=[Depends(require_own_origin)])  # (what KOLONİ fetches for it: the user's)
def create_expert(body: ExpertIn, request: Request, session: Session = Depends(get_session)):
    """K-bilgi: an expert at once - the role, its knowledge on the project's Knowledge page, and the
    role using it in full; all or nothing (a name taken leaves no knowledge behind)."""
    knowledge_page.project_of(session, body.project_id)
    role = new_role(session, request, body.role)
    knowledge_page.use(session, role, knowledge_page.added(session, body.project_id,
                                                           body.knowledge), knows.FULL)
    session.commit()
    return role


def new_role(session: Session, request: Request, body: RoleIn) -> Role:
    """A role of the user's, added (not committed)."""
    name = clean_name(body.name)
    existing = find_by_name(session, name)
    if existing:
        raise HTTPException(409, f"there is already a role named {existing.name}")
    role = Role(
        name=name,
        description=body.description.strip(),
        instructions=body.instructions.strip(),
        tools=clean_tools(body.tools),
        kind=roles.landing_kind(session, roles.LANDING_KIND),
    )
    clean_expert(role)
    apply_choice(session, role, body)
    apply_place(session, request, role, body)
    apply_limits(session, request, role, body)
    session.add(role)
    roles.place_in_stages(session)  # (its teams' stages)
    return role


@router.patch("/{role_id}", response_model=RoleOut, dependencies=[Depends(require_origin)])
def patch_role(  # noqa: C901
    role_id: str, body: RolePatch, request: Request, session: Session = Depends(get_session)
):
    role = _role(session, role_id)
    if body.name is not None and clean_name(body.name) != role.name:
        if role.builtin:
            raise HTTPException(422, "built-in roles keep their name")
        if roles.is_team_lead(session, role):
            raise HTTPException(422, "a team's lead is named after its team: rename the team")
        own_if_limited(request, role)
        name = clean_name(body.name)
        other = find_by_name(session, name)
        if other and other.id != role.id:
            raise HTTPException(409, f"there is already a role named {other.name}")
        role.name = name
    if body.description is not None:
        role.description = body.description.strip()
    if body.instructions is not None:
        role.instructions = body.instructions.strip()
    if body.tools is not None and body.tools != role.tools:
        if roles.is_observer(role):
            # It is asked one question, never with tools: a tool would say otherwise.
            raise HTTPException(422, "the Observer has no tools: it is asked with none")
        # (As they were is no change: the Observer has none, and is saved with none.)
        role.tools = clean_tools(body.tools)
    clean_expert(role)
    apply_choice(session, role, body)
    # (The tier rule and the kind under the same guard as the role's model: the route's.)
    apply_place(session, request, role, body)
    if body.mcp is not None and set(body.mcp) != set(role.mcp):
        # Which programs a role's agents may have started is the user's to say, from the
        # app's own page - as a role's limits are, and not as its tools: not a command's
        # that an agent runs against the app's address. Kept in the servers' own order.
        require_own_origin(request)
        known = session.scalars(select(McpServer.name).order_by(
            McpServer.created_at, literal_column("mcp_servers.rowid"))).all()
        if not set(body.mcp) <= set(known):
            raise HTTPException(422, "unknown MCP server")
        role.mcp = [name for name in known if name in body.mcp]
    if body.skills is not None and set(body.skills) != set(role.skills):
        # As its servers: a skill's text is what its agents are told, and its scripts may
        # run unasked - the user's to give, from the app's own page.
        require_own_origin(request)
        rows = session.execute(select(Skill.id, Skill.name).order_by(
            Skill.created_at, literal_column("skills.rowid"))).all()
        kept = [name for _id, name in rows]
        # (R125: a skill by its id too, as the Tools page lists it; the role keeps its name)
        named = {id_: name for id_, name in rows}
        wanted = {named.get(said, said) for said in body.skills}
        if not wanted <= set(kept):
            raise HTTPException(422, "unknown skill")
        role.skills = [name for name in kept if name in wanted]
    apply_limits(session, request, role, body)
    role.updated_at = now()
    roles.place_in_stages(session)  # (its stage in a team it was put in)
    session.commit()
    return role


@router.delete("/{role_id}", status_code=204, dependencies=[Depends(require_own_origin)])
def delete_role(role_id: str, request: Request, session: Session = Depends(get_session)):
    role = _role(session, role_id)
    if role.builtin:
        raise HTTPException(409, "built-in roles cannot be deleted")
    if roles.is_team_lead(session, role):
        raise HTTPException(409, "a team's lead goes only with its team")
    own_if_limited(request, role)
    session.delete(role)
    session.commit()
    return Response(status_code=204)


@router.post("/{role_id}/reset", response_model=RoleOut,
             dependencies=[Depends(require_own_origin)])
def reset_role(role_id: str, request: Request, session: Session = Depends(get_session)):
    role = _role(session, role_id)
    spec = BUILTIN_ROLES.get(role.name)
    if not role.builtin or spec is None:
        raise HTTPException(409, "only built-in roles can be reset")
    own_if_limited(request, role)
    role.description, role.instructions = spec.description, spec.instructions
    role.tools = list(spec.tools)
    role.provider_id, role.model_id, role.models = None, None, None
    role.kind = roles.landing_kind(session, spec.kind)
    role.tier, role.tier_min, role.tier_max = None, None, None  # the Lead picks, fast to strongest
    role.pick_from, role.max_steps, role.max_tokens = None, None, None
    role.effort, role.max_effort, role.context_window = None, None, None
    role.mcp = []  # as it came: with no server of the user's
    role.skills = []  # nor any skill (slice 45: built-in roles come with none)
    role.inside_cli = False
    role.updated_at = now()
    session.commit()
    return role


# --- an expert's knowledge (K-uzman), in a project: its Knowledge tab (K-bilgi: the knowledge
# it uses in full there, `app.api.knowledge_page`) -----------------------------------------------


def _expert_in(session: Session, role_id: str, project_id: str) -> tuple[ProjectKnowledge, Project]:
    role = _role(session, role_id)
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    found = knows.used_here(session, role, project_id, knows.FULL)
    if not found:
        raise HTTPException(409, f"{role.name} is no expert here: it uses no knowledge in full")
    return found[0], project


@router.get("/{role_id}/knowledge", response_model=KnowledgeStateOut)
def knowledge_state(role_id: str, project_id: str, session: Session = Depends(get_session)):
    """What an expert knows in a project: its guide, what was read and skipped and why."""
    row, project = _expert_in(session, role_id, project_id)
    return knowledge_page.priced(session, row, project.root_path)


@router.post("/{role_id}/learn", response_model=KnowledgeStateOut, status_code=202,
             dependencies=[Depends(require_own_origin)])  # (a request the user pays for)
async def learn(role_id: str, body: LearnIn, request: Request,
                session: Session = Depends(get_session)):
    """Learn (again), as on the Knowledge page."""
    row, project = _expert_in(session, role_id, body.project_id)
    return knowledge_page.start_learning(request, session, row, project)
