"""Teams of roles (slice 62): a chat's teams limit which roles its agents may open (84b).
Made, renamed and deleted only from the app's own page; deleting one never deletes a role.
Slice 63a: a team's own stages in order, the stage each of its roles sits in, and its lead."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, literal_column, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_own_origin
from app.db.models import (
    Conversation,
    ConversationTeam,
    Project,
    Recipe,
    Role,
    RoleTeam,
    Team,
    TeamStage,
    now,
)
from app.roles import (
    LEAD,
    LEAD_DESCRIPTION,
    LEAD_INSTRUCTIONS,
    LEAD_KIND,
    LEAD_TOOLS,
    STAGES,
    effective_tools,
    find_role,
    is_observer,
    is_team_lead,
    list_roles,
)
from app.schemas import (
    ChatTeamIn,
    Placed,
    RoleOut,
    StageIn,
    StageOrder,
    StageOut,
    StagePatch,
    TeamIn,
    TeamOut,
    TeamPatch,
)
from app.serialize import conversation_out
from app.team import CONVERSATION

router = APIRouter(prefix="/api/teams", tags=["teams"])


def _out(session: Session, team: Team, roles: list[Role]) -> TeamOut:
    stage_of = {link.role_id: link.stage_id for link in session.scalars(
        select(RoleTeam).where(RoleTeam.team_id == team.id))}
    mine = [role for role in roles if role.id in stage_of]
    return TeamOut(
        id=team.id, name=team.name, roles=[role.name for role in mine],
        stages=[StageOut(id=stage.id, name=stage.name, together=stage.together,
                         roles=[role.id for role in mine if stage_of[role.id] == stage.id])
                for stage in team.stages],
        lead=RoleOut.model_validate(session.get_one(Role, team.lead_role_id)),
        lead_on=team.lead_on, lead_may_pick=team.lead_may_pick,
        default_recipe_id=team.default_recipe_id)


def _teams(session: Session) -> list[TeamOut]:
    teams = session.scalars(
        select(Team).order_by(Team.created_at, literal_column("teams.rowid"))).all()
    roles = list_roles(session)
    return [_out(session, team, roles) for team in teams]


def _team(session: Session, team_id: str) -> Team:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "team not found")
    return team


def chat_rows(session: Session, mode: str, rows: list[ChatTeamIn] | None) -> list[dict] | None:
    """The user's rows of a chat's (or a project's new chats') teams, once each team is there
    and once, and each recipe one of KOLONİ's (slice 84b); else a 422 that says which."""
    if rows is None:
        return None
    if mode != "manual" and rows:
        raise HTTPException(422, "teams are picked by hand only in Manual")
    if len({row.team_id for row in rows}) < len(rows):
        raise HTTPException(422, "a team is in the list twice")
    for row in rows:
        if session.get(Team, row.team_id) is None:
            raise HTTPException(422, "unknown team")
        if row.recipe_id is not None and session.get(Recipe, row.recipe_id) is None:
            raise HTTPException(422, "unknown recipe")
        if row.no_recipe and row.recipe_id is not None:
            raise HTTPException(422, "a team with no recipe names none")
    return [row.model_dump() for row in rows]


def _stage(team: Team, stage_id: str) -> TeamStage:
    stage = next((one for one in team.stages if one.id == stage_id), None)
    if stage is None:
        raise HTTPException(404, "stage not found")
    return stage


def _saved(session: Session, team: Team) -> TeamOut:
    session.commit()
    return _out(session, team, list_roles(session))


def _free(session: Session, name: str, team: Team | None = None) -> None:
    other = session.scalar(select(Team).where(func.lower(Team.name) == name.lower()))
    if other is not None and other is not team:
        raise HTTPException(409, f"there is already a team named {other.name}")
    # Its lead is named after it, and a role is opened by its name.
    lead = find_role(session, f"{name} lead")
    if lead is not None and (team is None or lead.id != team.lead_role_id):
        raise HTTPException(409, f"there is already a role named {lead.name}, the name of "
                                 "this team's lead")


@router.get("", response_model=list[TeamOut])
def teams(session: Session = Depends(get_session)):
    return _teams(session)


@router.post("", response_model=TeamOut, status_code=201)
def create_team(body: TeamIn, request: Request, session: Session = Depends(get_session)):
    require_own_origin(request)
    _free(session, body.name)
    lead = Role(name=f"{body.name} lead", description=LEAD_DESCRIPTION,
                instructions=LEAD_INSTRUCTIONS, tools=effective_tools(LEAD_TOOLS, None),
                kind=LEAD_KIND, tier=CONVERSATION)
    session.add(lead)
    session.flush()
    team = Team(name=body.name, lead_role_id=lead.id, stages=[
        TeamStage(name=title, position=at) for at, (_kind, title) in enumerate(STAGES)])
    session.add(team)
    return _saved(session, team)


@router.patch("/{team_id}", response_model=TeamOut)
def change_team(
    team_id: str, body: TeamPatch, request: Request, session: Session = Depends(get_session)
):
    require_own_origin(request)
    team = _team(session, team_id)
    if body.name is not None and body.name != team.name:
        _free(session, body.name, team)
        team.name = body.name
        lead = session.get_one(Role, team.lead_role_id)
        lead.name, lead.updated_at = f"{body.name} lead", now()
    if body.lead_on is not None:
        team.lead_on = body.lead_on
    if body.lead_may_pick is not None:
        team.lead_may_pick = body.lead_may_pick
    if "default_recipe_id" in body.model_fields_set:  # null takes it away
        if body.default_recipe_id is not None and session.get(
                Recipe, body.default_recipe_id) is None:
            raise HTTPException(422, "that is not one of KOLONİ's recipes")
        team.default_recipe_id = body.default_recipe_id
    return _saved(session, team)


@router.delete("/{team_id}", status_code=204)
async def delete_team(team_id: str, request: Request, session: Session = Depends(get_session)):
    require_own_origin(request)
    team = _team(session, team_id)
    # Its roles stay (the links go with the team), and so do a chat's other rows: one with
    # no row left works with every team (slice 84b). Its lead goes with it. (Its rows go as
    # the foreign key would: said here too, whatever the connection's settings.) Nor is it a
    # project's default for its new chats any more.
    chats = session.scalars(select(ConversationTeam.conversation_id)
                            .where(ConversationTeam.team_id == team.id)).all()
    session.execute(delete(ConversationTeam).where(ConversationTeam.team_id == team.id))
    for project in session.scalars(select(Project)):
        if any(row["team_id"] == team.id for row in project.teams):
            project.teams = [row for row in project.teams if row["team_id"] != team.id]
    lead = session.get(Role, team.lead_role_id) if team.lead_role_id else None
    session.delete(team)
    if lead is not None:
        session.delete(lead)
    session.commit()
    session.expire_all()  # (read again: the rows went by a statement)
    for cid in set(chats):  # (its window shows the rows left)
        request.app.state.bus.emit(cid, None, "conversation.updated",
                                   conversation_out(session.get_one(Conversation, cid)))
    return Response(status_code=204)


@router.post("/{team_id}/stages", response_model=TeamOut, status_code=201)
def add_stage(team_id: str, body: StageIn, request: Request,
              session: Session = Depends(get_session)):
    require_own_origin(request)
    team = _team(session, team_id)
    team.stages.append(TeamStage(name=body.name, position=len(team.stages)))
    return _saved(session, team)


@router.patch("/{team_id}/stages/{stage_id}", response_model=TeamOut)
def change_stage(team_id: str, stage_id: str, body: StagePatch, request: Request,
                 session: Session = Depends(get_session)):
    require_own_origin(request)
    team = _team(session, team_id)
    stage = _stage(team, stage_id)
    if body.name is not None:
        stage.name = body.name
    if body.together is not None:
        stage.together = body.together
    return _saved(session, team)


@router.put("/{team_id}/stages", response_model=TeamOut)
def order_stages(team_id: str, body: StageOrder, request: Request,
                 session: Session = Depends(get_session)):
    require_own_origin(request)
    team = _team(session, team_id)
    if sorted(body.order) != sorted(stage.id for stage in team.stages):
        raise HTTPException(422, "the order names every stage of the team, each once")
    for stage in team.stages:
        stage.position = body.order.index(stage.id)
    team.stages.sort(key=lambda stage: stage.position)
    return _saved(session, team)


@router.delete("/{team_id}/stages/{stage_id}", response_model=TeamOut)
def delete_stage(team_id: str, stage_id: str, request: Request,
                 session: Session = Depends(get_session)):
    """A stage goes; its roles stay in the team, in the first stage left."""
    require_own_origin(request)
    team = _team(session, team_id)
    stage = _stage(team, stage_id)
    if len(team.stages) == 1:
        raise HTTPException(409, "a team keeps at least one stage")
    first = next(one for one in team.stages if one is not stage)
    # (Before the stage goes: its links would be emptied with it.)
    session.execute(update(RoleTeam).where(RoleTeam.stage_id == stage.id)
                    .values(stage_id=first.id))
    team.stages.remove(stage)
    for at, kept in enumerate(team.stages):
        kept.position = at
    return _saved(session, team)


@router.put("/{team_id}/roles/{role_id}", response_model=TeamOut)
def place_role(team_id: str, role_id: str, body: Placed, request: Request,
               session: Session = Depends(get_session)):
    """A role in this stage of the team: in the team too, if it was not. One stage a team."""
    require_own_origin(request)
    team = _team(session, team_id)
    role = session.get(Role, role_id)
    if role is None:
        raise HTTPException(404, "role not found")
    # (The Lead runs every team, the Observer is asked, no agent opened in it: neither sits in one.)
    if is_team_lead(session, role) or is_observer(role) or (role.builtin and role.name == LEAD):
        raise HTTPException(422, f"the {role.name} is in no team's stage")
    if not any(stage.id == body.stage_id for stage in team.stages):
        raise HTTPException(422, "that stage is not one of this team's")
    link = session.get(RoleTeam, (role.id, team.id))
    if link is None:
        session.add(RoleTeam(role_id=role.id, team_id=team.id, stage_id=body.stage_id))
    else:
        link.stage_id = body.stage_id
    return _saved(session, team)
