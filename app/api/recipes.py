"""Recipes (slice 84a): KOLONİ's own, the three ready ones among them, and a folder's own in its
`.koloni/recipes/`. Each is saved only when it can run (`app.recipes.problems`), only from the
app's own page; a ready one is copied, never changed. "Or write it" asks the Lead's model once
for a draft and saves nothing."""

from pathlib import Path as FsPath

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy import func, literal_column, select, update
from sqlalchemy.orm import Session

from app import recipes
from app.api.deps import get_session, require_own_origin
from app.api.usage import over_limit
from app.db.models import ConversationTeam, Project, Provider, Recipe, Team, now
from app.model_client import ModelUnavailable
from app.providers import ask_own, mode_of
from app.roles import LEAD, agent_roles, find_role
from app.schemas import (
    RecipeDraftIn,
    RecipeDraftOut,
    RecipeGraph,
    RecipeIn,
    RecipeOut,
    RecipesOut,
)
from app.team import asked_how_hard, would_run
from app.views import DEVICES, Refused

router = APIRouter(tags=["recipes"])
OWN = [Depends(require_own_origin)]
# A folder's recipe by its file's name (`recipes.file_name`): nothing else reaches the disk.
File = Path(pattern=f"^{recipes.FILE_NAME.pattern}$", max_length=60)


def _out(recipe: Recipe) -> RecipeOut:
    return RecipeOut(id=recipe.id, name=recipe.name, ready=recipe.ready,
                     graph=RecipeGraph.model_validate(recipe.graph))


def _checked(session: Session, body: RecipeIn, request: Request) -> dict:
    """The graph as it is kept, once it can run; else a 422 that says where it cannot."""
    found = recipes.problems(session, body.graph, request.app.state.providers)
    # Two steps of one name (B-108): which one is meant would not be told. Checked as it is
    # saved only - one saved before still runs.
    names = [step.name.casefold() for step in body.graph.steps]
    found += [{"loc": ["body", "graph"], "type": "recipe", "at": step.id,
               "msg": f"Two steps are named {step.name}: give each its own name"}
              for step in body.graph.steps
              if step.name and names.count(step.name.casefold()) > 1]  # (none: said apart)
    if found:
        raise HTTPException(422, found)
    return body.graph.model_dump(mode="json", by_alias=True)


def _recipe(session: Session, recipe_id: str) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(404, "recipe not found")
    if recipe.ready:
        raise HTTPException(409, f"{recipe.name} is a ready recipe: save a copy to change it")
    return recipe


def _free(session: Session, name: str, recipe: Recipe | None = None) -> None:
    other = session.scalar(select(Recipe).where(func.lower(Recipe.name) == name.lower()))
    if other is not None and other is not recipe:
        raise HTTPException(409, f"there is already a recipe named {other.name}")


def _project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def writer(session: Session) -> tuple[Provider, str | None] | str:
    """The Lead's model, which "Or write it" asks - or why it cannot be asked now. What the
    page shows and what the request does are this one answer."""
    try:
        would = would_run(session, find_role(session, LEAD), None)
    except ModelUnavailable:
        return "There is no model to ask: add a provider on the Models page."
    if would.refused:
        return str(would.refused)
    over = over_limit(session, would.provider)
    if over:
        return f"The Lead's model is {over}."
    return would.provider, would.model_id


def asker(session: Session, providers, tier: str) -> tuple[Provider, str | None] | str:
    """Whom a draft is asked of: the first model of `tier` the Lead may pick, as KOLONİ's other
    small requests go, while under its provider's limit; none to be had, the Lead's own
    (`writer`, which also says why nobody is asked)."""
    can = writer(session)
    if isinstance(can, str):
        return can
    picked = asked_how_hard(session, would_run(session, find_role(session, LEAD), None),
                            providers, tier)
    if picked and not over_limit(session, other := session.get_one(
            Provider, picked[0].provider_id)):
        return other, picked[1]
    return can


async def ask_writer(request: Request, provider: Provider, model: str | None,
                     messages: list[dict], project_id: str | None = None) -> tuple[str, str]:
    """`messages` asked once, with no tools: what was said, and by which model. A 502 says why
    the provider did not answer."""
    client = request.app.state.providers.client(provider, model)
    try:
        model = model or (await client.info()).model_id  # as the Lead learns its own
        said, answer = await ask_own(request.app.state.session_factory, (
                provider.name, mode_of(provider)), client, model, messages, project_id=project_id)
    except ModelUnavailable as exc:
        reason = str(exc)
        if provider.api_key:
            reason = reason.replace(provider.api_key, "[key]")
        raise HTTPException(502, f"{provider.name} isn't answering ({reason}).") from None
    return said, getattr(answer, "model", None) or model


@router.get("/api/recipes", response_model=RecipesOut)
def list_recipes(project_id: str | None = None, session: Session = Depends(get_session)):
    """KOLONİ's own, the ready ones first; with a project, its folder's own after them."""
    kept = session.scalars(select(Recipe).order_by(
        Recipe.ready.desc(), Recipe.created_at, literal_column("recipes.rowid"))).all()
    found = [_out(recipe) for recipe in kept]
    broken: list[str] = []
    if project_id is not None:
        project = _project(session, project_id)
        files, broken = recipes.folder_recipes(project.root_path)
        found += [RecipeOut(id=file, name=one.name, ready=False, graph=one.graph,
                            project_id=project.id, file=file) for file, one in files]
    can = writer(session)
    return RecipesOut(recipes=found, broken=broken,
                      writer={"why": can if isinstance(can, str) else None})


@router.post("/api/recipes", response_model=RecipeOut, status_code=201, dependencies=OWN)
def create_recipe(body: RecipeIn, request: Request, session: Session = Depends(get_session)):
    _free(session, body.name)
    recipe = Recipe(name=body.name, graph=_checked(session, body, request))
    session.add(recipe)
    session.commit()
    return _out(recipe)


@router.put("/api/recipes/{recipe_id}", response_model=RecipeOut, dependencies=OWN)
def change_recipe(recipe_id: str, body: RecipeIn, request: Request,
                  session: Session = Depends(get_session)):
    recipe = _recipe(session, recipe_id)
    _free(session, body.name, recipe)
    graph = _checked(session, body, request)
    recipe.name, recipe.graph, recipe.updated_at = body.name, graph, now()
    session.commit()
    return _out(recipe)


@router.delete("/api/recipes/{recipe_id}", status_code=204, dependencies=OWN)
def delete_recipe(recipe_id: str, session: Session = Depends(get_session)):
    recipe = _recipe(session, recipe_id)
    # (As the foreign key would: said here too, whatever the connection's settings.)
    session.execute(update(Team).where(Team.default_recipe_id == recipe.id)
                    .values(default_recipe_id=None))
    session.execute(update(ConversationTeam).where(ConversationTeam.recipe_id == recipe.id)
                    .values(recipe_id=None))
    session.delete(recipe)
    session.commit()
    return Response(status_code=204)


def _in_folder(project: Project, file: str, body: RecipeIn | None) -> None:
    try:
        recipes.write_file(project.root_path, file, body)
    except Refused as refused:
        raise HTTPException(refused.status, str(refused)) from None


def _folder_out(project: Project, file: str, body: RecipeIn) -> RecipeOut:
    return RecipeOut(id=file, name=body.name, ready=False, graph=body.graph,
                     project_id=project.id, file=file)


def _there(project: Project, file: str) -> bool:
    # (A broken one's too: never written over by another recipe. `file` is letters, digits
    # and dashes alone, `File`.)
    return (FsPath(project.root_path) / recipes.FOLDER / f"{file}.json").exists()


@router.post("/api/projects/{project_id}/recipes", response_model=RecipeOut, status_code=201,
             dependencies=OWN)
def create_folder_recipe(project_id: str, body: RecipeIn, request: Request,
                         session: Session = Depends(get_session)):
    """Kept in the folder's `.koloni/recipes/`, in git with it, under a file named after it."""
    project = _project(session, project_id)
    file = recipes.file_name(body.name)
    if not file:
        raise HTTPException(422, "a recipe kept in the folder needs a letter or a digit in "
                                 "its name: its file is named after it")
    if DEVICES.fullmatch(file):
        raise HTTPException(422, f"“{file}” is a name Windows keeps for a device, and the "
                                 "folder's file is named after the recipe: give it another name")
    _checked(session, body, request)
    if _there(project, file):
        raise HTTPException(409, f"this folder already has a recipe in {recipes.FOLDER}/"
                                 f"{file}.json")
    _in_folder(project, file, body)
    return _folder_out(project, file, body)


@router.put("/api/projects/{project_id}/recipes/{file}", response_model=RecipeOut,
            dependencies=OWN)
def change_folder_recipe(project_id: str, body: RecipeIn, request: Request, file: str = File,
                         session: Session = Depends(get_session)):
    """shortcut: a recipe renamed keeps its file's name; rename the file too if that confuses
    someone reading the folder."""
    project = _project(session, project_id)
    _checked(session, body, request)
    if not _there(project, file):
        raise HTTPException(404, "recipe not found")
    _in_folder(project, file, body)
    return _folder_out(project, file, body)


@router.delete("/api/projects/{project_id}/recipes/{file}", status_code=204, dependencies=OWN)
def delete_folder_recipe(project_id: str, file: str = File,
                         session: Session = Depends(get_session)):
    project = _project(session, project_id)
    if not _there(project, file):
        raise HTTPException(404, "recipe not found")
    _in_folder(project, file, None)
    return Response(status_code=204)


@router.post("/api/recipes/draft", response_model=RecipeDraftOut,
             dependencies=OWN)  # a request the user pays for: their click
async def draft_recipe(body: RecipeDraftIn, request: Request,
                       session: Session = Depends(get_session)):
    """A balanced model (else the Lead's) asked once, with no tools, to draw the user's
    sentence as a recipe: the draft is shown on the board, and saved only when the user saves
    it.
    shortcut: not held back by a project's budget (the Agents page is no project's), only by
    the provider's own limit; hold it there too if recipes are drafted often. What it spends is
    on Usage as "KOLONİ itself", and counts toward that provider's limits (K-56)."""
    # The first balanced model: a recipe's graph is more than a line of words (B-69: it was
    # drawn by the strongest model).
    can = asker(session, request.app.state.providers, "balanced")
    if isinstance(can, str):
        raise HTTPException(409, can)
    provider, model = can
    roles = [role.name for role in agent_roles(session) if not (
        role.builtin and role.name == LEAD)]
    question = recipes.draw_question(session, body.text, roles)
    said, model_id = await ask_writer(request, provider, model, [
        {"role": "system", "content": recipes.DRAW},
        # Said again over the sentence, which stands under it as data: a CLI's own rules
        # tell it to do what the user's turn asks.
        {"role": "user", "content": question},
    ])
    try:
        drawn = recipes.drafted(said)
    except ValueError as exc:
        raise HTTPException(502, f"the model's answer is not a recipe: {exc}") from None
    return RecipeDraftOut(name=drawn.name, graph=drawn.graph, provider_name=provider.name,
                          model_id=model_id)
