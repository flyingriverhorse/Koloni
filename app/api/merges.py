import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import git
from app.agent import CHECK_NOT_KEPT, as_shown, not_as_seen, unchosen, writes_nothing
from app.agent.words import OPEN
from app.api.deps import get_session, require_own_origin
from app.db.models import Compare, Merge, Run
from app.schemas import MergeChoices, MergeCommitIn, MergeOut
from app.serialize import merge_out

# Taking an agent's changes into the project is the user's to decide, on the app's own
# page: a request that does not say where it is from is not taken for the user. And so
# is whose side is taken where two clash, the check (KOLONİ runs a program) and the
# commit (it writes into the user's repository).
router = APIRouter(
    prefix="/api/merges", tags=["merges"], dependencies=[Depends(require_own_origin)]
)

DECISION_TIMEOUT = 5.0
NOT_AS_SEEN = "{files} changed since you looked: nothing was taken in. Check the card again"
PARTLY_AS_SEEN = (
    "{taken} taken in; {files} changed since you looked and {was} not. Check the card again"
)
OLD_CARD = "Reload the page: this card is from before an update"


def _some(merge: Merge, decision: str, only: list[str], card: dict[str, dict]) -> list[str]:
    """T93-01: a Take in of some of a card's files - the open ones of it alone, never none, not of
    a branch (merged whole) nor of a check (it runs on what Take in would take): 409 says why. The
    card's other open files, which stay on it."""
    open_ = [path for path, one in card.items() if one["state"] in OPEN]
    if decision != "approve" or merge.branch:
        raise HTTPException(409, "only Take in takes some of a card's files: all of it goes here")
    if not only:
        raise HTTPException(409, "choose at least one file to take in")
    if other := sorted(set(only) - set(open_)):
        raise HTTPException(409, f"not on this card to take: {', '.join(other[:20])}")
    return [path for path in open_ if path not in only]


def _to_decide(session: Session, merge_id: str, decision: str) -> Merge:
    """The card a decision is about; 404 where there is none, 409 where it is a comparison's."""
    merge = session.get(Merge, merge_id)
    if merge is None:
        raise HTTPException(404, "merge not found")
    compare_id = session.get_one(Run, merge.run_id).compare_id
    compare = session.get_one(Compare, compare_id) if compare_id else None
    if (
        compare is not None
        and compare.chosen_run_id != merge.run_id
        and (compare.status == "open" or decision != "reject")
    ):
        # A side of a comparison is taken in, or thrown away, by the user's choice of one:
        # afterwards the chosen side's card is decided here (what clashed), and any other
        # only thrown away - where that broke off at the choice, its copy is not stuck.
        raise HTTPException(409, "these changes are one side of a comparison: choose there")
    return merge


async def _decide_kept(
    merge: Merge,
    decision: str,
    choices: dict[str, str],
    request: Request,
    session: Session,
    only: list[str] | None = None,
) -> None:
    if decision == "check":
        raise HTTPException(409, CHECK_NOT_KEPT)
    # A copy kept over a restart: no agent task waits, the decision is carried out here.
    if not await request.app.state.runner.decide_kept(merge.id, decision, choices, only):
        raise HTTPException(409, "nothing of these changes can be decided like this")
    session.refresh(merge)


async def _acted(session: Session, merge: Merge, decided) -> None:
    # The agent task acts on the decision; answer once it has. (It may still be pending:
    # a file that changed since the card was shown is shown again, and nothing is taken -
    # and a check that was started runs on; how it went comes with the card's record.)
    deadline = asyncio.get_running_loop().time() + DECISION_TIMEOUT
    while True:
        await asyncio.sleep(0.01)
        session.refresh(merge)
        if merge.decided_at != decided or asyncio.get_running_loop().time() > deadline:
            return


async def _decide(
    merge_id: str,
    decision: str,
    request: Request,
    session: Session,
    body: MergeChoices | None = None,
) -> dict:
    merge = _to_decide(session, merge_id, decision)
    choices: dict[str, str] = dict(body.choices) if body else {}
    if decision == "approve" and choices and body and body.shown is None:
        # Choices from a page that does not say what its card showed: they may be of
        # another file than the one there now.
        raise HTTPException(409, OLD_CARD)
    card = {one["path"]: one for one in merge.files}
    # What the card the user said yes to showed; of a Take in that shows no files, what
    # the card was last shown with.
    seen = body.shown if body and body.shown is not None else as_shown(card)
    before, taken_before = as_shown(card, how=True), _taken(merge.files)
    keep = [path for path, one in card.items() if writes_nothing(one, choices)]
    if (only := body.files if body else None) is not None:
        keep += _some(merge, decision, only, card)  # (what stays on the card is not asked about)

    def as_seen(after: bool = False) -> None:
        # (A file not as it was seen: nothing of the card is taken, and it is shown again.)
        if decision != "approve" or merge.status not in ("pending", "interrupted"):
            return
        moved = (
            not_as_seen(merge.files, before, keep, how=True)
            if after
            else (not_as_seen(merge.files, seen, keep))
        )
        if not moved:
            return
        files, taken = ", ".join(moved[:20]), sorted(_taken(merge.files) - taken_before)
        raise HTTPException(
            409,
            PARTLY_AS_SEEN.format(
                taken=", ".join(taken[:20]),
                files=files,
                was="was" if len(moved) == 1 else "were",
            )
            if taken
            else NOT_AS_SEEN.format(files=files),
        )

    as_seen()
    left = [
        path
        for path in (unchosen(merge.files, choices) if decision != "reject" else [])
        if only is None or path in only
    ]
    if left:
        # Nothing is chosen for the user, and nothing is taken (or checked) without it.
        raise HTTPException(409, f"say whose side is taken of: {', '.join(left[:20])}")
    if decision == "resolve" and not (
        merge.status == "pending" and (merge.branch or {}).get("resolve")
    ):
        raise HTTPException(409, "no agent can resolve conflicts on these changes")
    decided = merge.decided_at
    if merge.status == "interrupted":
        await _decide_kept(merge, decision, choices, request, session, only)
        as_seen(after=True)
        return merge_out(merge)
    if decision == "check" and not (merge.check or {}).get("command"):
        # (0.1.7: none written, or none its part's command can run alone - the card says why)
        raise HTTPException(409, "no test of its own can be run before it is added")
    said = {"keep_branch": body.keep_branch, "way": body.way, "only": only} if body else None
    if not request.app.state.runner.decide_merge(merge_id, decision, choices, said):
        if merge.status == "pending" and (merge.check or {}).get("state") == "running":
            # Nothing is asked while its check runs: the card asks again with the result.
            raise HTTPException(409, "the check is still running: decide when it is over")
        raise HTTPException(409, "these changes are no longer waiting for a decision")
    await _acted(session, merge, decided)
    as_seen(after=True)
    return merge_out(merge)


def _taken(files: list[dict]) -> set[str]:
    return {one["path"] for one in files if one["state"] == "applied"}


@router.post("/{merge_id}/approve", response_model=MergeOut)
async def approve(
    merge_id: str,
    request: Request,
    body: MergeChoices | None = None,
    session: Session = Depends(get_session),
):
    return await _decide(merge_id, "approve", request, session, body)


@router.post("/{merge_id}/reject", response_model=MergeOut)
async def reject(merge_id: str, request: Request, session: Session = Depends(get_session)):
    return await _decide(merge_id, "reject", request, session)


@router.post("/{merge_id}/continue", status_code=202)
async def go_on(merge_id: str, request: Request, session: Session = Depends(get_session)):
    """K-devam-butce: Continue on the kept card of an agent that stopped at a step limit - it
    gets the project's `continue_steps` more and goes on in its kept copy; the card is
    withdrawn as it does (events say so). 409 with why it cannot."""
    if session.get(Merge, merge_id) is None:
        raise HTTPException(404, "merge not found")
    if why := await request.app.state.runner.continue_kept(merge_id):
        raise HTTPException(409, why)


@router.post("/{merge_id}/check", response_model=MergeOut)
async def check(
    merge_id: str,
    request: Request,
    body: MergeChoices | None = None,
    session: Session = Depends(get_session),
):
    """Run the project's check command on what the card would take. The click is the
    command's leave: nobody is asked a second time."""
    return await _decide(merge_id, "check", request, session, body)


@router.post("/{merge_id}/resolve", response_model=MergeOut)
async def resolve(merge_id: str, request: Request, session: Session = Depends(get_session)):
    """K-dal-takim D2: an agent puts the files a branch clashes on together, in the branch's
    worktree; the card asks again with what came of it."""
    return await _decide(merge_id, "resolve", request, session)


@router.post("/{merge_id}/commit", response_model=MergeOut)
async def commit(
    merge_id: str,
    body: MergeCommitIn,
    request: Request,
    session: Session = Depends(get_session),
):
    """Commit the files that were taken, they alone, with this message: once."""
    merge = session.get(Merge, merge_id)
    if merge is None:
        raise HTTPException(404, "merge not found")
    try:
        await request.app.state.runner.commit_taken(merge_id, body.message, body.hooks)
    except git.Refused as exc:
        raise HTTPException(409, f"not committed: {exc}") from None
    session.refresh(merge)
    return merge_out(merge)
