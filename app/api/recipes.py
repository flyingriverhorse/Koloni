"""Recipes (slice 84a): KOLONİ's own, the three ready ones among them, and a folder's own in its
`.koloni/recipes/`. Each is saved only when it can run (`app.recipes.problems`), only from the
app's own page; a ready one is copied, never changed. "Or write it" asks a balanced model (else
the Lead's) once for a draft and saves nothing."""

from pathlib import Path as FsPath
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy import func, literal_column, select, update
from sqlalchemy.orm import Session

from app import recipes
from app.api.deps import get_session, require_own_origin
from app.api.usage import over_limit
from app.config import is_local
from app.db.models import (
    Agent,
    Conversation,
    ConversationTeam,
    Project,
    Provider,
    Recipe,
    Run,
    Team,
    now,
)
from app.model_client import UNREACHABLE, ModelUnavailable
from app.providers import LIST_DOWN_SECONDS, TIERS, ask_own, down_now, looked_down, mode_of
from app.roles import LEAD, agent_roles, find_role
from app.schemas import (
    RecipeDraftIn,
    RecipeDraftOut,
    RecipeGraph,
    RecipeIn,
    RecipeOut,
    RecipesOut,
)
from app.team import askable, would_run
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


NO_MODEL = "There is no model to ask: add a provider on the Models page."
# k-tarif-model: models that can be had, and none of them talks with its tools off.
NO_ONE = ("There is no model to ask: give a model a tier on the Models page, or pick a model in "
          "the chat.")
# ...or every one there is was passed over as not running (`down_now`), and how to fix it.
START = "Start {names} on the Models page, give a model a tier there, or pick a model in the chat."
NOT_RUNNING = "There is no model to ask: {names} {are} not running. {fix}"


def chat_of(session: Session, conversation_id: str | None,
            project_id: str | None = None) -> Conversation | None:
    """The chat the page is open on (k-tarif-model): its Orchestrator's model is asked - the one
    its model picker chose. None - none given, gone, or not of the page's project: as before."""
    chat = session.get(Conversation, conversation_id) if conversation_id else None
    return chat if chat is not None and project_id in (None, chat.project_id) else None


def writer(session: Session, conversation: Conversation | None = None
           ) -> tuple[Provider, str | None] | str:
    """The Lead's model - in `conversation`, the one that chat picked -, which "Or write it" asks
    - or why it cannot be asked now. What the page shows and what the request does are this one
    answer."""
    try:
        would = would_run(session, find_role(session, LEAD), conversation)
    except ModelUnavailable:
        return NO_MODEL
    if would.refused:
        return str(would.refused)
    over = over_limit(session, would.provider)
    if over:
        return f"The Lead's model is {over}."
    return would.provider, would.model_id


# Whom a draft is asked of, and how the page names it: (provider, model, "Balanced: Local · x").
Asked = tuple[Provider, str | None, str]


def askers(session: Session, providers, tier: str,
           conversation: Conversation | None = None,
           project_id: str | None = None) -> list[Asked] | str:
    """Whom a draft is asked of, in turn, each once: each model of `tier` the Lead may pick, as
    KOLONİ's other small requests go (`askable`: not one whose provider looked down when last
    read - a local model server not running -), then the other tiers' (fast, balanced,
    strongest); then the Lead's own in the chat the page is on (`writer`: that chat's model
    picker - k-tarif-model: the user's chats ran on another provider than the app's default,
    whose server was not running); then the model the newest chat ran on. Never a CLI that keeps
    its tools, nor one past its provider's limit. None: why nobody is asked."""
    try:
        would = would_run(session, find_role(session, LEAD), conversation)
    except ModelUnavailable:
        return NO_MODEL
    found: dict[tuple[str, str | None], Asked] = {}
    down = down_now(session)  # (a local server not running, as a tier passes it over)
    passed: list[str] = []

    def add(provider: Provider, model: str | None, label: str) -> None:
        key = (provider.id, model or provider.default_model)
        # (A model not named stands for whichever its provider gives: one already asked of it.)
        again = key in found or key[1] is None and any(one[0] == provider.id for one in found)
        if provider.id in down and provider.name not in passed:
            passed.append(provider.name)
        if not again and provider.id not in down and not over_limit(session, provider) and _talks(
                session, providers, provider, model):
            named = model or provider.default_model or "its default model"
            found[key] = (provider, model, f"{label}: {provider.name} · {named}")

    for one in (tier, *(other for other in TIERS if other != tier)):
        for entry, model in askable(session, would, providers, one):
            add(session.get_one(Provider, entry.provider_id), model, one.capitalize())
    can = writer(session, conversation)
    if not isinstance(can, str):
        add(*can, "the Orchestrator's model")
    if (newest := _newest_chats(session, project_id)) is not None:
        add(*newest, "the newest chat's model")
    if found:
        return list(found.values())
    if passed:
        return NOT_RUNNING.format(names=" and ".join(passed), are="is" if len(passed) == 1
                                  else "are", fix=START.format(names=" and ".join(passed)))
    return can if isinstance(can, str) else NO_ONE


def _talks(session: Session, providers, provider: Provider, model: str | None) -> bool:
    """`askable`'s rule for a model asked outside a tier: a CLI at work with its own tools speaks
    with them off - one that still has them then is passed over."""
    client = providers.client(provider, model)
    if getattr(client, "native", False):
        client = client.talker()
    return not getattr(client, "native", False)


def _newest_chats(session: Session, project_id: str | None = None,
                  ) -> tuple[Provider, str | None] | None:
    """The model the newest chat's Orchestrator ran on, as it was last used - of `project_id`'s
    chats where a project asks (its text goes to no model only another project's chat used);
    None: no chat ran, or its provider is gone."""
    of_project = [] if project_id is None else [Agent.run_id.in_(select(Run.id).join(
        Conversation, Conversation.id == Run.conversation_id).where(
        Conversation.project_id == project_id))]
    lead = session.scalars(select(Agent).where(
        Agent.depth == 0, Agent.provider_name.is_not(None), *of_project).order_by(
        Agent.created_at.desc(), literal_column("agents.rowid").desc()).limit(1)).first()
    provider = session.scalar(select(Provider).where(
        Provider.name == lead.provider_name)) if lead is not None else None
    return (provider, lead.model_id) if provider is not None and lead is not None else None


async def asked_once(request: Request, provider: Provider, model: str | None,
                     messages: list[dict], project_id: str | None = None) -> tuple[str, str]:
    """`messages` asked once, with no tools: what was said, and by which model. ModelUnavailable
    says why the provider did not answer, its key masked."""
    client = request.app.state.providers.client(provider, model)
    try:
        model = model or (await client.info()).model_id  # as the Lead learns its own
        said, answer = await ask_own(request.app.state.session_factory, (
                provider.name, mode_of(provider)), client, model, messages, project_id=project_id)
    except ModelUnavailable as exc:
        reason = str(exc)
        raise ModelUnavailable(reason.replace(provider.api_key, "[key]") if provider.api_key
                               else reason) from None
    return said, getattr(answer, "model", None) or model


async def ask_in_turn(request: Request, session: Session, can: list[Asked],
                      messages: list[dict], project_id: str | None = None,
                      ) -> tuple[Provider, str, str]:
    """`messages` asked of `askers`' models in turn (`asked_once`) until one answers: by whom,
    what it said, and its model. A local server not running is passed over for each of its
    models, here and by a tier's pick for a while (one started later is asked again); with none
    answering, a 502 names each one asked and why."""
    tried: list[str] = []
    stopped: set[str] = set()
    for provider, model, _named in can:
        if provider.id in stopped:
            continue
        try:
            said, model_id = await asked_once(request, provider, model, messages, project_id)
            return provider, said, model_id
        except ModelUnavailable as exc:
            reason = str(exc)
            if is_local(provider.base_url) and reason.startswith(UNREACHABLE):
                looked_down(session)[provider.id] = ("not answering",
                                                     monotonic() + LIST_DOWN_SECONDS)
                reason = "not running"
                stopped.add(provider.id)
            tried.append(f"{provider.name}{f' · {model}' if model else ''} ({reason})")
    # (k-tarif-model: how to fix it, in KOLONİ's words)
    names = [one.name for one in session.scalars(select(Provider).where(Provider.id.in_(stopped)))]
    fix = START.format(names=" and ".join(names)) if names else (
        "Give a model a tier on the Models page, or pick a model in the chat.")
    raise HTTPException(502, f"No model answered: {', '.join(tried)}. {fix}")


@router.get("/api/recipes", response_model=RecipesOut)
def list_recipes(request: Request, project_id: str | None = None,
                 conversation_id: str | None = None, session: Session = Depends(get_session)):
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
    can = askers(session, request.app.state.providers, "balanced",
                 chat_of(session, conversation_id, project_id))
    return RecipesOut(recipes=found, broken=broken, writer={
        "why": can if isinstance(can, str) else None,
        "asks": None if isinstance(can, str) else can[0][2]})


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
    # drawn by the strongest model) - the next where one does not answer, then the Lead's.
    can = askers(session, request.app.state.providers, "balanced",
                 chat_of(session, body.conversation_id))
    if isinstance(can, str):
        raise HTTPException(409, can)
    roles = [role.name for role in agent_roles(session) if not (
        role.builtin and role.name == LEAD)]
    question = recipes.draw_question(session, body.text, roles)
    provider, said, model_id = await ask_in_turn(request, session, can, [
        {"role": "system", "content": recipes.DRAW},
        # Said again over the sentence, which stands under it as data: a CLI's own rules tell it
        # to do what the user's turn asks.
        {"role": "user", "content": question},
    ])
    try:
        drawn = recipes.drafted(said)
    except ValueError as exc:
        raise HTTPException(502, f"the model's answer is not a recipe: {exc}") from None
    return RecipeDraftOut(name=drawn.name, graph=drawn.graph, provider_name=provider.name,
                          model_id=model_id)
