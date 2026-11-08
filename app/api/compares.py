"""One message to two models side by side (slice 54).

Each side is a turn of the conversation on a model of the user's choosing, at work in a
working copy of its own (`app.copies`): nothing of either reaches the project. When a side
is over, what it changed is kept as a kept copy is (`AgentRunner._set_aside`); the user's
choice takes the chosen one in - by the rules that take any kept copy in - and throws the
other away. The sides run one after the other, as two messages of the conversation do.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import topics
from app.agent import (
    OUTSIDE_A_COPY,
    TERMINAL,
    AgentRunner,
    needs_full_auto,
    outside_a_copy,
    unchosen,
)
from app.api.conversations import new_turn
from app.api.deps import get_session, require_own_origin
from app.api.providers import _model
from app.api.runs import stop
from app.api.usage import over_budget, usage
from app.db.models import (
    Agent,
    Compare,
    Conversation,
    FileChange,
    Merge,
    Message,
    Project,
    Provider,
    Run,
    now,
)
from app.roles import shown_name
from app.schemas import CompareChoice, CompareIn, CompareOut, CompareStarted
from app.serialize import conversation_out, message_out, run_out, topic_out
from app.team import not_listed
from app.workspace import in_scratch

router = APIRouter(prefix="/api", tags=["compares"])


def _compare(session: Session, compare_id: str) -> Compare:
    compare = session.get(Compare, compare_id)
    if compare is None:
        raise HTTPException(404, "comparison not found")
    return compare


def cost_of(rows: list[dict]) -> list[dict] | None:
    """What a side cost, from what Usage says of each model it ran on, as the turn's summary
    adds it up: a sum for each currency (one is never added to another), "at least" where a
    part of it is not known (or a model of it has no price). None where nothing is priced."""
    costs = [row["cost"] for row in rows if row["cost"]]
    if not costs:
        return None
    unpriced = len(costs) < len(rows)
    sums = []
    for currency in dict.fromkeys(cost["currency"] for cost in costs):
        mine = [cost for cost in costs if cost["currency"] == currency]
        short = unpriced or any(cost.get("at_least") or cost.get("cache_unpriced") for cost in mine)
        sums.append({"amount": round(sum(cost["amount"] for cost in mine), 6),
                     "currency": currency, **({"at_least": True} if short else {})})
    return sums


def _kept(session: Session, run_id: str) -> Merge | None:
    """A side's kept copy while it waits for the user's choice."""
    return session.scalar(
        select(Merge).where(Merge.run_id == run_id, Merge.status == "interrupted",
                            Merge.kept_in.is_not(None))
    )


def _side(session: Session, side: dict) -> dict:
    run = session.get_one(Run, side["run_id"])
    lead = session.scalar(
        select(Agent.id).where(Agent.run_id == run.id, Agent.depth == 0).limit(1))
    answer = AgentRunner.last_answer(session, run.id, lead) if lead else None
    merge = session.scalar(
        select(Merge).where(Merge.run_id == run.id).order_by(Merge.created_at.desc()).limit(1))
    # (Without a card: what is in its copy still - not what a stopped side's copy held.)
    recorded = session.scalars(select(FileChange.path).where(
        FileChange.run_id == run.id, FileChange.status == "in_copy"))
    changed = [one["path"] for one in merge.files] if merge else sorted(
        {path for path in recorded if not in_scratch(path)})
    spent = usage(run_id=run.id, session=session)
    total = spent["by_conversation"][0] if spent["by_conversation"] else {}
    return {
        "run_id": run.id, "provider_id": side["provider_id"],
        "model_id": run.model_id or side["model_id"], "status": run.status,
        "answer": answer.content if answer else "", "error": run.error,
        "changed_files": changed, "kept": _kept(session, run.id) is not None,
        "input_tokens": total.get("input_tokens"), "output_tokens": total.get("output_tokens"),
        "cost": cost_of(spent["by_model"]),
        "seconds": (run.ended_at - run.started_at).total_seconds()
        if run.ended_at and run.started_at else None,
    }


def compare_out(session: Session, compare: Compare) -> dict:
    sides = [_side(session, side) for side in compare.sides]
    status = compare.status
    if status == "open":
        status = "ready" if all(side["status"] in TERMINAL for side in sides) else "running"
    return {
        "id": compare.id, "conversation_id": compare.conversation_id, "status": status,
        "chosen_run_id": compare.chosen_run_id, "sides": sides,
    }


@router.post(
    "/conversations/{conversation_id}/compare", response_model=CompareStarted,
    status_code=201, dependencies=[Depends(require_own_origin)],
)
async def start(  # noqa: C901
    conversation_id: str, body: CompareIn, request: Request,
    session: Session = Depends(get_session),
):
    """The user's own, from the app's page: two models are set to work on their message."""
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "conversation not found")
    if conversation.project_id is None:
        raise HTTPException(409, "each side of a comparison works in a copy of the chat's "
                                 "folder: this chat has no folder")
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "message is empty")
    sides, spends = [], []
    for side in body.sides:
        provider = session.get(Provider, side.provider_id)
        if provider is None:
            raise HTTPException(422, "unknown provider")
        model_id = _model(side.model_id) or provider.default_model
        refused = not_listed(provider, model_id)
        if refused is not None:
            raise HTTPException(422, str(refused))
        client = request.app.state.providers.client(provider, model_id)
        # Refused before anything starts, with why: what the side's turn would refuse.
        why = OUTSIDE_A_COPY if outside_a_copy(client) else needs_full_auto(
            client, conversation.permission_mode)
        if why:
            raise HTTPException(422, why.format(provider=shown_name(provider.name)))
        sides.append({"provider_id": provider.id, "model_id": model_id})
        spends.append(provider)
    # As a message is (slice 55), and each side's provider is held to its limit (81c); this
    # route is the user's own page already.
    over = over_budget(session, session.get_one(Project, conversation.project_id), spends=spends)
    if over and not body.over_budget:
        raise HTTPException(409, f"this project is {over}: say to go on over it")
    first = session.scalar(
        select(Message.id).where(Message.conversation_id == conversation_id).limit(1)
    ) is None
    try:
        topic, new = topics.for_message(
            session, conversation_id, content, body.topic_id, body.new_topic)
    except topics.Refused as exc:
        raise HTTPException(422, str(exc)) from None
    compare = Compare(conversation_id=conversation_id, sides=[])
    session.add(compare)
    session.flush()
    # The second is queued behind the first: the sides run one after the other, each timed
    # on its own and neither waiting for a file the other holds.
    turns = []
    for side in sides:
        turns.append(new_turn(session, conversation_id, topic.id, content,
                              compare_id=compare.id, model_id=side["model_id"]))
        side["run_id"] = turns[-1][0].id
    compare.sides = sides
    if first:
        conversation.title = " ".join(content.split())[:60]
    conversation.updated_at = now()
    session.commit()

    bus = request.app.state.bus
    if new:
        bus.emit(conversation_id, None, "topic.created", topic_out(topic))
    for run, message in turns:
        bus.emit(conversation_id, run.id, "run.started", run_out(run))
        bus.emit(conversation_id, run.id, "message.created", message_out(message))
    bus.emit(conversation_id, None, "conversation.updated", conversation_out(conversation))
    for run, _message in turns:
        if run.status == "running":
            request.app.state.runner.start(run.id)
    return {"compare_id": compare.id, "run_ids": [run.id for run, _message in turns]}


@router.get("/compares/{compare_id}", response_model=CompareOut)
def get_compare(compare_id: str, session: Session = Depends(get_session)):
    return compare_out(session, _compare(session, compare_id))


def _decided(session: Session, compare_id: str, ended: bool = True) -> Compare:
    """A comparison to decide on now: nothing decided yet - and, `ended`, both sides over."""
    compare = _compare(session, compare_id)
    if compare.status != "open":
        raise HTTPException(409, f"this comparison is {compare.status} already")
    runs = session.scalars(select(Run.status).where(Run.compare_id == compare.id))
    if ended and any(status not in TERMINAL for status in runs):
        raise HTTPException(409, "both sides have to end first")
    return compare


@router.post(
    "/compares/{compare_id}/choose", response_model=CompareOut,
    dependencies=[Depends(require_own_origin)],
)
async def choose(
    compare_id: str, body: CompareChoice, request: Request,
    session: Session = Depends(get_session),
):
    """Take the chosen side's changes into the project and throw the other's copy away.
    Where a file of the chosen side clashes with the project as it is now, nothing is chosen
    for the user: that side's kept card stays, asking whose side is taken of each (19b)."""
    compare = _decided(session, compare_id)
    if body.run_id not in [side["run_id"] for side in compare.sides]:
        raise HTTPException(422, "that turn is not a side of this comparison")
    # On record before anything is awaited: a second click is refused, not carried out.
    compare.status, compare.chosen_run_id = "chosen", body.run_id
    session.commit()
    runner = request.app.state.runner
    for side in compare.sides:
        merge = _kept(session, side["run_id"])
        if merge is None:
            continue  # it changed nothing
        if side["run_id"] != body.run_id:
            await runner.decide_kept(merge.id, "reject")
        elif not unchosen(merge.files, {}):
            await runner.decide_kept(merge.id, "approve")
    runner.note_chosen(body.run_id)  # (what it found stands now: into the journal)
    session.expire_all()
    return compare_out(session, compare)


@router.post(
    "/compares/{compare_id}/discard", response_model=CompareOut,
    dependencies=[Depends(require_own_origin)],
)
async def discard(compare_id: str, request: Request, session: Session = Depends(get_session)):
    """Throw both sides' copies away: nothing of either reaches the project. A side still at
    work, or queued, is stopped: a stopped side keeps nothing, and one that ends meanwhile
    sets nothing aside once this is on record (`AgentRunner.execute`)."""
    compare = _decided(session, compare_id, ended=False)
    compare.status = "discarded"
    session.commit()
    # The queued second first: the first's end would start it.
    for side in reversed(compare.sides):
        run = session.get_one(Run, side["run_id"])
        if run.status not in TERMINAL:
            stop(session, request, run)
    for side in compare.sides:
        merge = _kept(session, side["run_id"])
        if merge is not None:
            await request.app.state.runner.decide_kept(merge.id, "reject")
    session.expire_all()
    return compare_out(session, compare)
