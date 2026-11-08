"""K-bilgi: a project's Knowledge page - its knowledge (and every project's), which roles use it
and how (a role's Knowledge tab), Learn, Try it and copying a guide. How it is learned is
`app.knowledge`'s; `app.api.roles` reads and learns an expert's by these. Every change is the
user's, from the app's own page (`require_own_origin`): what KOLONİ fetches for a knowledge, and
what a learning or an answer spends, is the user's to start."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import code_map, knowledge, knows, koloni, project_notes, roles
from app import memory as kept
from app.agent import announce
from app.api.deps import get_session, require_own_origin
from app.api.usage import over_limit
from app.config import is_local
from app.db.models import Flag, NotesOffer, Project, ProjectKnowledge, Provider, Role, now
from app.model_client import ModelUnavailable
from app.providers import CLI_KINDS, NotListed, allowed, ask_own, mode_of, resolved
from app.schemas import (
    Knowledge,
    KnowledgeCopyIn,
    KnowledgeOut,
    KnowledgeStateOut,
    KnowledgeUser,
    KnowsIn,
    Learned,
    LearnIn,
    NotesAnswerIn,
    NotesOfferOut,
    RoleOut,
    TreeLimits,
    TryIn,
    TryOut,
)
from app.team import would_run
from app.views import Refused

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["knowledge"])
OWN = [Depends(require_own_origin)]

# The learnings at work, held on to until they end.
_learnings: set[asyncio.Task] = set()


def project_of(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return project


def row_in(session: Session, knowledge_id: str, project_id: str) -> ProjectKnowledge:
    """The knowledge, where it is seen from this project: its own or every project's."""
    row = session.get(ProjectKnowledge, knowledge_id)
    if row is None or row.project_id not in (None, project_id):
        raise HTTPException(404, "knowledge not found")
    return row


def users(session: Session, row: ProjectKnowledge) -> list[tuple[Role, str]]:
    """The roles that use it, and how, by their names."""
    return [(role, one["mode"]) for role in session.scalars(select(Role).order_by(Role.name))
            for one in role.knows or [] if one["knowledge_id"] == row.id]


def state(root: str, known: dict) -> KnowledgeStateOut:
    raw = knowledge.learned(root, known)
    try:
        record = Learned.model_validate(raw or {})
    except ValidationError:  # (none, or one written by hand that is not its shape)
        record = None
    return KnowledgeStateOut(
        learning=knowledge.learning(root, known), stale=knowledge.stale(root, known, raw),
        failed=knowledge.failed(root, known), learned=record,
        guide=knowledge.guide(root, known),
        folder=f"{koloni.FOLDER}/{knowledge.folder_of(known)}/",
        version_warning=knowledge.version_warning(raw), requests=knowledge.requests(raw))


def priced(session: Session, row: ProjectKnowledge, root: str) -> KnowledgeStateOut:
    """Its state, with what its next learning that adds to the guide costs at most - priced as
    `learn` prices it, without asking the model (a provider's default by its name).
    shortcut: learn's and copy's answers carry no estimate - the page reads it again a second
    later; price them there too if the gap shows. And what Try it answers on (B-372), said before
    the user asks, as `learner` finds it."""
    known = knows.knowledge_of(row)
    found = state(root, known)
    if knowledge.is_code(known):  # (answered from the scan: no model)
        return found
    try:
        provider, model = learner(session, row, answering=True)
    except HTTPException as exc:
        found.answers_refused = str(exc.detail)
        return found
    found.answers_on = f"{provider.name} · {model or 'its own default model'}"
    found.per_token = (provider.kind not in CLI_KINDS and not is_local(provider.base_url)
                       and not provider.plan)
    # (Learn has no fallback: a knowledge no role uses and with no learn-with has no price.)
    if knowledge.is_notes(known) or not (row.learn_with or users(session, row)):
        return found
    model = model or provider.default_model
    price = knowledge.price_of(session, provider, model) if model else None
    found.estimate = knowledge.estimate(known, knowledge.learned(root, known), price)
    return found


def out(session: Session, row: ProjectKnowledge, root: str) -> KnowledgeOut:
    known = knows.knowledge_of(row)
    return KnowledgeOut(
        id=row.id, project_id=row.project_id, knowledge=Knowledge.model_validate(known),
        used_by=[KnowledgeUser.model_validate({"role_id": role.id, "name": role.name, "mode": mode})
                 for role, mode in users(session, row)], state=priced(session, row, root))


def checked(session: Session, sent: Knowledge, root: str) -> dict:
    """A knowledge as it is kept (`app.knowledge.checked`), sent by the user for the project at
    `root` (a folder on this machine is theirs alone to add); HTTPException 422 says why not."""
    if sent.learn_with is not None and session.get(Provider, sent.learn_with.provider_id) is None:
        raise HTTPException(422, "unknown provider")
    try:
        return knowledge.checked(sent.model_dump(), by_user=True, root=root)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/projects/{project_id}/knowledge", response_model=list[KnowledgeOut])
def list_knowledge(project_id: str, session: Session = Depends(get_session)):
    """The project's knowledge and every project's, oldest first."""
    project = project_of(session, project_id)
    return [out(session, row, project.root_path) for row in session.scalars(
        select(ProjectKnowledge).where(or_(ProjectKnowledge.project_id.is_(None),
                                           ProjectKnowledge.project_id == project_id))
        .order_by(ProjectKnowledge.created_at, ProjectKnowledge.id))]


@router.post("/projects/{project_id}/knowledge", response_model=KnowledgeOut, status_code=201,
             dependencies=OWN)
def add_knowledge(project_id: str, body: Knowledge, session: Session = Depends(get_session)):
    project = project_of(session, project_id)
    row = added(session, project_id, body)
    session.commit()
    return out(session, row, project.root_path)


def added(session: Session, project_id: str, body: Knowledge) -> ProjectKnowledge:
    """A knowledge of the project, added (not committed); HTTPException 422 says why not."""
    known = checked(session, body, project_of(session, project_id).root_path)
    if taken := knows.folder_taken(session, project_id, known):
        raise HTTPException(422, taken)
    row = ProjectKnowledge(project_id=project_id, **knows.columns_of(known))
    session.add(row)
    session.flush()
    return row


@router.get("/knowledge-limits", response_model=TreeLimits)
def tree_limits(session: Session = Depends(get_session)):
    files, size = knowledge.tree_limits(session)
    return {"max_files": files, "max_mb": size // 2**20}


@router.put("/knowledge-limits", response_model=TreeLimits, dependencies=OWN)
def set_tree_limits(body: TreeLimits, session: Session = Depends(get_session)):
    """The most files and MB a repository or a folder on this machine may hold to be learned, in
    every project - the user's to say; a learning at work keeps the ones it started with."""
    for name, value in ((knowledge.FILES_FLAG, body.max_files), (knowledge.MB_FLAG, body.max_mb)):
        if value is not None:
            session.merge(Flag(name=name, value=str(value)))
    session.commit()
    return tree_limits(session)


@router.get("/knowledge/{knowledge_id}", response_model=KnowledgeOut)
def get_knowledge(knowledge_id: str, project_id: str, session: Session = Depends(get_session)):
    project = project_of(session, project_id)
    return out(session, row_in(session, knowledge_id, project_id), project.root_path)


def change(session: Session, row: ProjectKnowledge, body: Knowledge, root: str) -> None:
    """Its sources and how it is learned; its topic names its folder, and stays."""
    known = checked(session, body, root)
    if knowledge.folder_of(known) != knowledge.folder_of(knows.knowledge_of(row)):
        raise HTTPException(422, "a topic names its folder: add a knowledge for another topic")
    for name, value in {**knows.columns_of(known), "topic": row.topic}.items():
        setattr(row, name, value)


@router.put("/knowledge/{knowledge_id}", response_model=KnowledgeOut, dependencies=OWN)
def put_knowledge(knowledge_id: str, project_id: str, body: Knowledge,
                  session: Session = Depends(get_session)):
    """Its sources and how it is learned - in every project, for every project's; not while it
    learns (its learning reads what it was). A repository's code kept here goes where it is a
    repository's no more."""
    project = project_of(session, project_id)
    row = row_in(session, knowledge_id, project_id)
    was = knows.knowledge_of(row)
    if knowledge.learning(project.root_path, was):
        raise HTTPException(409, "it is learning: change it once it is done")
    change(session, row, body, project.root_path)
    if not knowledge.is_repo(knows.knowledge_of(row)):
        forgotten(project.root_path, was)  # (before it is saved: a 409 here changes nothing)
    session.commit()
    return out(session, row, project.root_path)


def forgotten(root: str, known: dict) -> None:
    """`knowledge.forget`; HTTPException 409 where what it keeps could not be deleted."""
    try:
        knowledge.forget(root, known)
    except OSError as exc:
        raise HTTPException(409, f"its kept code could not all be deleted ({exc.strerror or exc})"
                            ) from None


@router.delete("/knowledge/{knowledge_id}", status_code=204, dependencies=OWN)
def delete_knowledge(knowledge_id: str, project_id: str, session: Session = Depends(get_session)):
    """Gone from the page and from the roles that used it; its guide stays in the folder - a
    repository's clone goes (K-bilgi-repo).
    shortcut: the clone of this project's folder only - one of every project's knowledge learned
    in another project stays there; delete it in each if that is missed."""
    project = project_of(session, project_id)
    row = row_in(session, knowledge_id, project_id)
    known = knows.knowledge_of(row)
    if knowledge.learning(project.root_path, known):
        raise HTTPException(409, "it is learning: delete it once it is done")
    forgotten(project.root_path, known)
    for role, _mode in users(session, row):
        role.knows = [one for one in role.knows if one["knowledge_id"] != row.id]
        role.updated_at = now()
    session.delete(row)
    session.commit()
    return Response(status_code=204)


def use(session: Session, role: Role, row: ProjectKnowledge, mode: str | None) -> None:
    """A role uses it so (None: no more). In full only a role of the user's own that reads only
    (an expert, in it alone where it applies: `knows.one_expertise`); as a map, any role."""
    if mode == knows.FULL:
        if role.builtin or roles.is_team_lead(session, role):
            raise HTTPException(422, "only a role of your own can be an expert")
        try:
            roles.expert_tools(role.tools, row)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        knows.one_expertise(session, role, row)
    was = role.knows or []
    if mode is None:
        role.knows = [one for one in was if one["knowledge_id"] != row.id]
    elif any(one["knowledge_id"] == row.id for one in was):  # (in its place)
        role.knows = [{**one, "mode": mode} if one["knowledge_id"] == row.id else one
                      for one in was]
    else:
        role.knows = [*was, {"knowledge_id": row.id, "mode": mode}]
    role.updated_at = now()


def _role(session: Session, role_id: str) -> Role:
    role = session.get(Role, role_id)
    if role is None:
        raise HTTPException(404, "role not found")
    return role


@router.put("/knowledge/{knowledge_id}/roles/{role_id}", response_model=RoleOut,
            dependencies=OWN)
def use_knowledge(knowledge_id: str, role_id: str, body: KnowsIn,
                  session: Session = Depends(get_session)):
    role = _role(session, role_id)
    use(session, role, _any_row(session, knowledge_id), body.mode)
    session.commit()
    return role


@router.delete("/knowledge/{knowledge_id}/roles/{role_id}", response_model=RoleOut,
               dependencies=OWN)
def stop_using(knowledge_id: str, role_id: str, session: Session = Depends(get_session)):
    role = _role(session, role_id)
    use(session, role, _any_row(session, knowledge_id), None)
    session.commit()
    return role


def _any_row(session: Session, knowledge_id: str) -> ProjectKnowledge:
    row = session.get(ProjectKnowledge, knowledge_id)
    if row is None:
        raise HTTPException(404, "knowledge not found")
    return row


def learner(session: Session, row: ProjectKnowledge,
            answering: bool = False) -> tuple[Provider, str | None]:
    """The model it learns (and answers Try it) with: its "learn with", else the model of a role
    that uses it - in full first - as an agent of it would run, with nobody's turn
    (`would_run`), else (`answering`: Try it, one question the user clicked for - B-372) what a
    new chat would run on. HTTPException 409 says why there is none."""
    chosen = row.learn_with
    try:
        if chosen:
            provider = session.get(Provider, chosen["provider_id"])
            if provider is None:
                raise HTTPException(409, "its learn-with model's provider is gone: choose another")
            allowed(provider, chosen["model_id"])
            model = chosen["model_id"]
        elif using := sorted(users(session, row), key=lambda one: one[1] != knows.FULL):
            would = would_run(session, using[0][0], None)
            if would.refused:
                raise HTTPException(409, str(would.refused))
            provider, model = would.provider, would.model_id
        elif answering:
            provider, model, _source = resolved(session, None, None)
            allowed(provider, model)
        else:
            raise HTTPException(409, "choose a model it learns with: no role uses it")
    except (NotListed, ModelUnavailable) as exc:  # (OwnStop too: no provider is set up)
        raise HTTPException(409, str(exc)) from None
    over = over_limit(session, provider)
    if over:
        raise HTTPException(409, f"Its model is {over}.")
    return provider, model


def start_learning(request: Request, session: Session, row: ProjectKnowledge,
                   project: Project) -> KnowledgeStateOut:
    """Learn (again): its sources read and its guide written in the project, in the background -
    the page reads how it went. What its requests spend is on Usage as "KOLONİ itself", in the
    project's budget (K-56)."""
    root, known = project.root_path, knows.knowledge_of(row)
    if knowledge.is_code(known):
        return scanning(root, known)
    if knowledge.is_notes(known):
        raise HTTPException(409, "Project notes are written from what you accept at a turn's "
                                 "end: nothing to learn")
    if project.exec_location == "docker" and not project.docker_network and (
            knowledge.reads_web(known)):
        raise HTTPException(409, "this project's network access is off: its commands run in "
                                 "Docker without a network")
    provider, model = learner(session, row)
    client = request.app.state.providers.client(provider, model)
    name, key, pid = provider.name, provider.api_key, provider.id
    asked = (name, mode_of(provider))  # (the guide is asked in the background, after this)
    factory = request.app.state.session_factory
    search = knowledge.searching(project)  # (the Learn click is the leave for its searches too)
    write_in = kept.write_in(session, knowledge.GUIDE_KEPT)
    tree = knowledge.tree_limits(session)  # (as it starts: a change after holds the next one)
    project_id = project.id
    try:
        knowledge.begin(root, known)
    except knowledge.LearnError as exc:
        raise HTTPException(409, str(exc)) from None

    async def ask(messages: list[dict]):
        nonlocal made
        made += 1
        return await ask_own(factory, asked, client, model_id, messages, project_id,
                             **knowledge.most_written(client))

    async def run() -> None:
        nonlocal model_id
        try:
            model_id = model or (await client.info()).model_id
            # (Priced by the model that answers: a provider's default is known only now.)
            with factory() as priced:
                price = knowledge.price_of(priced, priced.get_one(Provider, pid), model_id)
            record = await knowledge.learn(root, known, ask, price, f"{name} · {model_id}",
                                           search, write_in=write_in, tree=tree)
            # K-bilgi 7: a click's learning asks its guide what it does not know yet. (Its guide
            # stands whatever comes of that: nothing of it fails the learning, and `unknown` is
            # written only by a measure that ran to its end.)
            try:
                await knowledge.measure(root, known, record, ask, price, made)
            except Exception as exc:  # (its kind only, as a learning's)
                log.warning("knowledge %s: not measured: %s", known["topic"], type(exc).__name__)
        except knowledge.LearnError:
            pass  # (said by `knowledge.failed`)
        except ModelUnavailable as exc:
            reason = str(exc).replace(key, "[key]") if key else str(exc)
            knowledge.fail(root, known, f"{name} isn't answering ({reason})")
        except Exception as exc:  # (its kind only: nothing of what was read is repeated)
            knowledge.fail(root, known, f"it stopped ({type(exc).__name__})")
        finally:
            knowledge.end(root, known)

    model_id, made = model or "", 0
    task = asyncio.get_running_loop().create_task(run())
    _learnings.add(task)
    task.add_done_callback(_learnings.discard)
    return state(root, known)


def scanning(root: str, known: dict) -> KnowledgeStateOut:
    """K-bilgi 8: the project's code scanned (`code_map.scan`) in the background, as a learning
    is - no model, nothing spent."""
    try:
        knowledge.begin(root, known)
    except knowledge.LearnError as exc:
        raise HTTPException(409, str(exc)) from None

    async def run() -> None:
        try:
            await asyncio.to_thread(code_map.scan, root, known)
        except Refused as exc:
            knowledge.fail(root, known, str(exc))
        except Exception as exc:  # (its kind only, as a learning's)
            knowledge.fail(root, known, f"it stopped ({type(exc).__name__})")
        finally:
            knowledge.end(root, known)

    task = asyncio.get_running_loop().create_task(run())
    _learnings.add(task)
    task.add_done_callback(_learnings.discard)
    return state(root, known)


@router.post("/knowledge/{knowledge_id}/learn", response_model=KnowledgeOut, status_code=202,
             dependencies=OWN)  # (a request the user pays for)
async def learn(knowledge_id: str, body: LearnIn, request: Request,
                session: Session = Depends(get_session)):
    project = project_of(session, body.project_id)
    row = row_in(session, knowledge_id, body.project_id)
    start_learning(request, session, row, project)
    return out(session, row, project.root_path)


@router.post("/knowledge/{knowledge_id}/try", response_model=TryOut, dependencies=OWN)
async def try_it(knowledge_id: str, body: TryIn, request: Request,
                 session: Session = Depends(get_session)):
    """A question answered as an expert in it would, from its guide in the project and the parts
    of its pages a search for the question's words finds (`knowledge.looked_up`: no tool, nothing
    outside its folder), on the model it learns with (Usage: "KOLONİ itself")."""
    project = project_of(session, body.project_id)
    row = row_in(session, knowledge_id, body.project_id)
    known = knows.knowledge_of(row)
    if knowledge.is_code(known):  # (K-bilgi 8: answered from the scan itself - no model)
        if await asyncio.to_thread(code_map.graph, project.root_path) is None:
            raise HTTPException(409, "its code is not scanned in this project yet: Scan first")
        found = await asyncio.to_thread(code_map.lookup, project.root_path, body.question)
        return TryOut(answer="\n\n".join(f"**{where}**\n\n```\n{part}\n```"
                                         for where, part in found)
                      or "The scan has nothing of it: name a function, a class or a file.")
    if knowledge.guide(project.root_path, known) is None:
        raise HTTPException(409, "it has learned nothing in this project yet: Learn first")
    provider, model = learner(session, row, answering=True)
    client = request.app.state.providers.client(provider, model)
    asked = (provider.name, mode_of(provider))
    messages = await asyncio.to_thread(knowledge.asked_of, project.root_path, known,
                                       body.question)
    try:
        model = model or (await client.info()).model_id
        said, _answer = await ask_own(request.app.state.session_factory, asked, client, model,
                                      messages, project.id)
    except ModelUnavailable as exc:
        reason = str(exc).replace(provider.api_key, "[key]") if provider.api_key else str(exc)
        raise HTTPException(502, f"{provider.name} isn't answering ({reason})") from None
    if not row.learn_with and not users(session, row):  # (nobody chose it: say which it was)
        said += f"\n\n*No role uses it: answered on {provider.name} · {model}, a new chat's model.*"
    return TryOut(answer=said)


GUIDE_THERE = "there is a guide there already"  # (the page asks, and sends replace)


@router.post("/knowledge/{knowledge_id}/copy", response_model=KnowledgeStateOut,
             dependencies=OWN)  # (it writes into a project)
def copy_knowledge(knowledge_id: str, body: KnowledgeCopyIn,
                   session: Session = Depends(get_session)):
    """Its guide into another of the user's projects (`copy`)."""
    project = project_of(session, body.project_id)
    to = project_of(session, body.to_project_id)
    there = copy(session, row_in(session, knowledge_id, body.project_id), project, to,
                 body.replace)
    return state(to.root_path, knows.knowledge_of(there))


def copy(session: Session, row: ProjectKnowledge, project: Project, to: Project,  # noqa: C901
         replace: bool) -> ProjectKnowledge:
    """Its guide, and what its learning says of it - not the pages read, other people's - into
    another of the user's projects, deleting the pages its learning there kept. A project's
    knowledge is added there too (same topic, sources and users), where that project has none of
    its folder; every project's is there already. A guide there already is replaced only where
    `replace` says so. Returns the knowledge as it is there."""
    root, there = project.root_path, to.root_path
    if Path(root).resolve() == Path(there).resolve():
        raise HTTPException(422, "that is the project it was learned in")
    known = knows.knowledge_of(row)
    if knowledge.is_code(known):
        raise HTTPException(422, "a scan of the code is of its own project: scan it there")
    if knowledge.is_notes(known):
        raise HTTPException(422, "Project notes are of their own project's work")
    if knowledge.is_repo(known):  # (its guide names files of its clone, which stays here)
        raise HTTPException(422, "a repository or a folder is read in its own project: learn it "
                                 "there")
    # (A learning at work in either would write its own over the copy, or copy half of one.)
    if knowledge.learning(root, known) or knowledge.learning(there, known):
        raise HTTPException(409, "it is learning in one of the two projects: copy once it is done")
    if knowledge.guide(root, known) is None:
        raise HTTPException(409, "it has no guide in this project to copy")
    if knowledge.guide(there, known) is not None and not replace:
        raise HTTPException(409, f"{GUIDE_THERE}: replace it, and the pages read there?")
    target = row if row.project_id is None else next((
        one for one in session.scalars(select(ProjectKnowledge).where(or_(
            ProjectKnowledge.project_id.is_(None), ProjectKnowledge.project_id == to.id)))
        if knowledge.folder_of(knows.knowledge_of(one)) == knowledge.folder_of(known)), None)
    if target is None:
        target = ProjectKnowledge(project_id=to.id, **knows.columns_of(known))
        session.add(target)
        session.flush()
    if target is not row:  # (its roles know it there too, as an expert's guide followed it)
        there_already = {role.id for role, _mode in users(session, target)}
        for role, mode in users(session, row):
            if role.id not in there_already:
                # (A copy does not change what a role is an expert in there: Map where it is one.)
                full_there = mode == knows.FULL and knows.used_here(
                    session, role, to.id, knows.FULL)
                use(session, role, target, knows.MAP_MODE if full_there else mode)
    try:
        if not knowledge.copy_to(root, there, known):
            raise HTTPException(409, "it has no guide in this project to copy")
    except Refused as exc:
        raise HTTPException(exc.status, str(exc)) from None
    session.commit()
    return target


@router.get("/conversations/{cid}/notes-offers", response_model=list[NotesOfferOut])
def notes_offers(cid: str, session: Session = Depends(get_session)):
    """K-bilgi 6: the "Add to Project notes?" offers under the chat's turns, decided or not."""
    return project_notes.offers_of(session, cid)


@router.post("/notes-offers/{offer_id}/answer", response_model=NotesOfferOut,
             dependencies=OWN)  # (it writes into the project's knowledge)
async def answer_notes_offer(offer_id: str, body: NotesAnswerIn, request: Request,
                             session: Session = Depends(get_session)):
    """The user's word on an offer, whenever they give it: the lines it ticks (`add`) written as
    notes, none ticked is Not now - and the offer is decided either way. `lines`: what its card
    showed; 409 where the offer has others now (the card reads it again), 422 for a tick that is
    not on it - it waits on (`project_notes.decide`)."""
    offer = session.get(NotesOffer, offer_id)
    if offer is None:
        raise HTTPException(404, "offer not found")
    project = project_of(session, offer.project_id)
    try:
        offer = project_notes.decide(session, offer_id, body.lines, body.add, project.root_path)
    except Refused as exc:
        raise HTTPException(exc.status, str(exc)) from None
    session.commit()
    announce(request.app.state.session_factory, request.app.state.bus, project.id,
             project_notes.OFFERED)
    return project_notes.out(offer)
