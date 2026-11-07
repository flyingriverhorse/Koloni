"""What was spent and where: the tokens the agents' models reported, added up; and the
prices of models, from which alone money is shown: the user's, else the catalogue's."""

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import null, select, union_all
from sqlalchemy.orm import Session

from app import catalog, models_dev
from app.api.deps import get_session, require_own_origin
from app.db.models import Agent, Conversation, OwnRequest, Price, Project, Provider, Run
from app.providers import HTTP_KINDS
from app.roles import LEAD, find_role, shown_name
from app.schemas import BudgetOut, CataloguePriceOut, PriceIn, PriceOut, UsageOut

router = APIRouter(prefix="/api", tags=["usage"])


class _Sum:
    """What a set of agents reported: sums over what is known, None while nothing is."""

    def __init__(self, **named):
        self.named = named
        self.runs: set[str] = set()
        self.agents = self.unknown = 0
        self.sent: int | None = None
        self.made: int | None = None
        # Of what was sent: read again from a provider's cache, and written to it.
        self.read: int | None = None
        self.written: int | None = None
        self.cli = False
        # Of who started it: the same, by model - what its cost is made of.
        self.models: dict[tuple, _Sum] = {}

    def add(
        self, run_id: str | None, sent: int | None, made: int | None, cli: bool, cut: bool,
        read: int | None, written: int | None,
    ) -> None:
        if run_id is not None:  # (KOLONİ's own request with no turn: in no message)
            self.runs.add(run_id)
        self.agents += 1
        # `cut`: a step or a CLI run of it ended before saying what it spent - what is
        # on record for it is only part, whatever its earlier steps reported.
        self.unknown += sent is None or made is None or cut
        if sent is not None:
            self.sent = (self.sent or 0) + sent
        if made is not None:
            self.made = (self.made or 0) + made
        if read is not None:
            self.read = (self.read or 0) + read
        if written is not None:
            self.written = (self.written or 0) + written
        self.cli = self.cli or cli

    def row(self) -> dict:
        return {
            **self.named, "runs": len(self.runs), "agents": self.agents,
            "input_tokens": self.sent, "output_tokens": self.made,
            "cache_read_tokens": self.read, "cache_write_tokens": self.written,
            "unknown_agents": self.unknown,
        }


def _most_first(sums) -> list[_Sum]:
    return sorted(sums, key=lambda one: (one.sent or 0) + (one.made or 0), reverse=True)


def _cost(one: _Sum, price: Price | SimpleNamespace | None) -> dict | None:
    """What a model's row cost, from the price the user wrote for it or else the
    catalogue's (`price_from`); None without one, with nothing known to price, and for a
    CLI. Where an agent of the row is unknown the amount is only the least it cost, and
    says so (`at_least`).

    What was read again from a cache and written to one is part of what was sent, and
    has prices of its own: they differ by model and by provider. Without one those tokens
    are not counted at all - at the input price they would be counted for more, or less,
    than they cost - and the amount is then the least, and says why (`cache_unpriced`)."""
    if price is None or one.cli or (one.sent is None and one.made is None):
        return None
    read, written = one.read or 0, one.written or 0
    unpriced = bool(
        read and price.cache_read is None or written and price.cache_write is None)
    amount = (
        # (Never below nothing, should a provider say it read more than it was sent.)
        max((one.sent or 0) - read - written, 0) * price.input
        + read * (price.cache_read or 0)
        + written * (price.cache_write or 0)
        + (one.made or 0) * price.output
    ) / 1e6
    return {
        "amount": round(amount, 6), "currency": price.currency,
        **({"at_least": True} if one.unknown or unpriced else {}),
        **({"cache_unpriced": True} if unpriced else {}),
        **({"price_from": "models.dev", "price_read_on": price.read_on}
           if isinstance(price, SimpleNamespace) else {}),
    }


def _catalogue_price(provider: Provider | None, model_id: str | None,
                     copy: dict) -> SimpleNamespace | None:
    """models.dev's price of a model on a provider by the name it has now; None for one
    renamed or removed since, or one the catalogue has no price for. Another service's price
    for a model its own does not list ("models.dev (deepseek)") is none here: a plan that
    resells it is paid its own way (credits), and a budget is not to stop on that service's."""
    if provider is None or not model_id:
        return None
    told, said = catalog.facts(provider.kind, provider.base_url, model_id, copy)
    if said.get("price") != "models.dev":
        return None
    return SimpleNamespace(**told["price"], currency="USD", read_on=models_dev.read_on(copy))


# Without what was not set: a cost that is whole has no `at_least` at all.
@router.get("/usage", response_model=UsageOut, response_model_exclude_unset=True)
def usage(
    project_id: str | None = None, since: datetime | None = None, run_id: str | None = None,
    until: datetime | None = None, conversation_id: str | None = None,
    session: Session = Depends(get_session),
):
    """The agents that ran in turns started at or after `since` (all of them without it),
    and before `until` where it is given, in one project or in all - or in one chat
    (`conversation_id`) or one turn (`run_id`: its summary in the chat). An agent that was
    never started is not among them. What KOLONİ asked a model itself for one of them
    (`OwnRequest`) is counted like one more agent, under the provider and model that were
    asked - not where its agent ran; what it asked with no turn (made at or after `since`,
    in the project) too, as "KOLONİ itself" - though not in one chat's or one turn's."""
    turns = []  # what narrows the turns asked about
    own: list | None = []  # and KOLONİ's own requests with no turn
    if project_id:
        turns.append(Conversation.project_id == project_id)
        own.append(OwnRequest.project_id == project_id)
    if conversation_id:
        # shortcut: no page asks by chat yet (the Usage page sums by project, the chat by
        # turn); give the Usage page a chat's view on this when one is wanted.
        if session.get(Conversation, conversation_id) is None:
            raise HTTPException(404, "conversation not found")
        turns.append(Conversation.id == conversation_id)
        own = None
    if run_id:
        turns.append(Run.id == run_id)
        own = None
    for moment, after in ((since, True), (until, False)):
        if moment is None:
            continue
        # Times are kept in UTC without a zone: one that names another is brought there.
        try:
            kept = moment.astimezone(UTC) if moment.tzinfo else moment
        except OverflowError:  # the first or last year there is, in a zone that leaves it
            raise HTTPException(422, f"{'since' if after else 'until'} is out of range") from None
        turns.append(Run.created_at >= kept if after else Run.created_at < kept)
        if own is not None:
            own.append(OwnRequest.created_at >= kept if after else OwnRequest.created_at < kept)
    models, talks, starts = _sums(session, turns, own)
    cost = _coster(session)
    # Which provider a row is now (the record keeps the name, which follows a rename).
    ids = {provider.name: provider.id for provider in session.scalars(select(Provider))}
    return {
        "by_model": [{**one.row(), "provider_id": ids.get(one.named["provider_name"]),
                      "cost": cost(one)} for one in _most_first(models.values())],
        "by_conversation": [one.row() for one in _most_first(talks.values())],
        "by_start": [{**one.row(), "cost": _start_cost(cost, one)}
                     for one in _most_first(starts.values())],
    }


def money(amount: float) -> str:
    """An amount of money as a line says it: two decimals; four under a cent, so a tiny
    cost is not "0.00"; "0" only where it is nothing.
    shortcut: under 0.0001 it is still "0.0000"; show more where such a cost is seen."""
    if amount == 0:
        return "0"
    return f"{amount:.2f}" if abs(amount) >= 0.01 else f"{amount:.4f}"


def _start_cost(cost, one: _Sum) -> dict | None:
    """What a "Who started it" row cost: its models' costs, each as its row by model has it
    (`cost`), added up - so the rows add up to what those do. None where none of its models
    has one, or they are in two currencies; the least it cost where one of them has none."""
    found = [cost(model) for model in one.models.values()]
    priced = [each for each in found if each]
    if not priced or len({each["currency"].upper() for each in priced}) > 1:
        return None
    least = len(priced) < len(found) or any(each.get("at_least") for each in priced)
    return {"amount": round(sum(each["amount"] for each in priced), 6),
            "currency": priced[0]["currency"], **({"at_least": True} if least else {})}


def _sums(
    session: Session, turns: list, own: list | None = None,
) -> tuple[dict[tuple, _Sum], dict[str, _Sum], dict[str, _Sum]]:
    """What the agents of the turns `turns` narrows to reported: by model, by
    conversation and by who started the turn. With `own`, also the requests KOLONİ made
    with no turn that it narrows to (`OwnRequest`'s own columns): "KOLONİ itself"."""
    of_turn = (Run.unattended, Conversation.id, Conversation.project_id, Conversation.title)
    asked = union_all(
        select(
            Agent.run_id, Agent.provider_name, Agent.model_id, Agent.provider_mode,
            Agent.input_tokens_total, Agent.output_tokens, Agent.cut_short,
            Agent.cache_read_tokens, Agent.cache_write_tokens, *of_turn,
        )
        .join(Run, Run.id == Agent.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(Agent.started_at.is_not(None), *turns),
        select(
            OwnRequest.run_id, OwnRequest.provider_name, OwnRequest.model_id,
            OwnRequest.provider_mode, OwnRequest.input_tokens, OwnRequest.output_tokens,
            OwnRequest.cut_short, OwnRequest.cache_read_tokens,
            OwnRequest.cache_write_tokens, *of_turn,
        )
        .join(Run, Run.id == OwnRequest.run_id)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(*turns),
        *([] if own is None else [select(
            OwnRequest.run_id, OwnRequest.provider_name, OwnRequest.model_id,
            OwnRequest.provider_mode, OwnRequest.input_tokens, OwnRequest.output_tokens,
            OwnRequest.cut_short, OwnRequest.cache_read_tokens,
            OwnRequest.cache_write_tokens, null(), null(), OwnRequest.project_id, null(),
        ).where(OwnRequest.run_id.is_(None), *own)]),
    )
    models: dict[tuple, _Sum] = {}
    talks: dict[str, _Sum] = {}
    starts: dict[str, _Sum] = {}
    for (
        rid, provider, model, mode, sent, made, cut, read, written, unattended, cid, pid,
        title,
    ) in session.execute(asked):
        by = "koloni" if rid is None else "trigger" if unattended else "user"
        start = starts.setdefault(by, _Sum(started_by=by))
        for one in (
            models.setdefault((provider, model), _Sum(provider_name=provider, model_id=model)),
            *([] if cid is None else [talks.setdefault(
                cid, _Sum(conversation_id=cid, project_id=pid, title=title))]),
            start,
            start.models.setdefault((provider, model), _Sum(
                provider_name=provider, model_id=model)),
        ):
            one.add(rid, sent, made, mode is not None, cut, read, written)
    return models, talks, starts


def _coster(session: Session):
    """A model's sum at the user's price for it, or the catalogue's where they set none."""
    prices = {price.model_id: price for price in session.scalars(select(Price))}
    copy = models_dev.load(session.info.get("runtime_root"))
    served = {provider.name: provider for provider in session.scalars(select(Provider))}

    def cost(one: _Sum) -> dict | None:
        provider = served.get(one.named["provider_name"])
        if provider is not None and provider.plan:
            return None  # a key that is a plan counts no money, whatever its price (81c)
        return _cost(one, prices.get(one.named["model_id"]) or _catalogue_price(
            provider, one.named["model_id"], copy))

    return cost


def month_start(at: datetime | None = None) -> datetime:
    """The first moment of `at`'s calendar month (now's without it) by this machine's
    clock - KOLONİ runs on the user's own - in UTC without a zone, as times are kept."""
    # shortcut: the machine's zone, as triggers count days; a page in another zone sees the
    # server's month, take a `tz` when KOLONİ is reached from elsewhere.
    local = (at or datetime.now(UTC)).astimezone()
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return first.astimezone(UTC).replace(tzinfo=None)  # (a naive local time, its own offset)


def day_start() -> datetime:
    """Today's first moment by this machine's clock, as `month_start`'s."""
    local = datetime.now(UTC).astimezone()
    first = local.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return first.astimezone(UTC).replace(tzinfo=None)


def spend(session: Session, turns: list, own: list | None = None) -> dict:
    """What the turns `turns` narrows to cost at the user's prices; with `own`, and KOLONİ's
    own requests with no turn that it narrows to (`_sums`)."""
    return _spent(session, _sums(session, turns, own)[0])


def _spent(session: Session, models: dict[tuple, _Sum]) -> dict:
    """What these models' sums cost at the user's prices. A row with no cost (no price, a
    CLI, a plan, nothing reported) is counted apart, never guessed."""
    cost = _kept(session, "coster", lambda: _coster(session))
    own = _kept(session, "currencies", lambda: _currencies(session))
    # The catalogue's price is in USD: where the user prices in another currency, a model at
    # the catalogue's price counts as unpriced rather than leave the budget unsummed.
    priced = [(one, None if not found or (found.get("price_from") and own - {"USD"}) else found)
              for one in models.values() for found in [cost(one)]]
    costs = [found for _, found in priced if found]
    # With nothing priced yet: the catalogue's currency, which its prices will be in.
    currencies = {found["currency"].upper() for found in costs} or own or {"USD"}
    # Amounts in two currencies are never added: with prices in several, nothing is summed.
    # shortcut: costs in several currencies hold nothing back (the page says the budget is
    # not enforced); ask which currency the budget is in if prices mix.
    currency = currencies.pop() if len(currencies) == 1 else None
    spent = round(sum(cost["amount"] for cost in costs), 6) if currency or not costs else None
    return {
        "currency": currency, "spent": spent,
        # An amount of a model with an unknown agent, or unpriced cache tokens, is the least.
        "at_least": any(cost.get("at_least") for cost in costs),
        # A turn on two models with no price is one turn.
        "unpriced_runs": len(set().union(*(one.runs for one, found in priced if not found))),
    }


def _kept(session: Session, key, make):
    """What `make` gives, made once for this session: what a provider's limit is checked
    against is read once a request, however many times a request asks (`would_run`)."""
    # shortcut: a price or a turn written later in the same session is not seen by it; drop
    # session.info["spend_kept"] after such a write if one ever needs it.
    kept = session.info.setdefault("spend_kept", {})
    if key not in kept:
        kept[key] = make()
    return kept[key]


def _currencies(session: Session) -> set[str]:
    return {price.currency.upper() for price in session.scalars(select(Price))}


def unkept(session: Session) -> str | None:
    """Why no provider's limit of spend can be kept now, or None. A limit is in USD, as the
    page writes it, and what is spent is at the user's prices: with prices in another
    currency the two are never compared (the Models page says the same)."""
    own = _kept(session, "currencies", lambda: _currencies(session))
    return (f"This limit can't be kept: your prices are in {' and '.join(sorted(own))}"
            if own - {"USD"} else None)


def month_spend(session: Session, project: Project) -> dict:
    """This calendar month's turns of a project at the user's prices, against its budget -
    and what KOLONİ asked for the project itself (the day's words, a role's guide)."""
    start = month_start()
    found = spend(session, [Conversation.project_id == project.id, Run.created_at >= start],
                  [OwnRequest.project_id == project.id, OwnRequest.created_at >= start])
    budget, spent = project.monthly_budget, found["spent"]
    # (Rounded: 0.72 of 0.9 is 80%, not 0.7999999999999999.)
    share = round(spent / budget, 9) if budget and spent is not None else None
    return {**found, "budget": budget, "share": share,
            "warn": share is not None and share >= 0.8, "over": share is not None and share >= 1}


def over_limit(session: Session, provider: Provider) -> str | None:
    """Why a turn on this provider waits for the user's word - "over Local's limit of 5.00
    USD a day (10.50 spent today)" - or None: under its limits, none set, or none that can
    be kept (`unkept`). What it spent in every project, by its name, at the user's prices,
    as a budget counts it. Once a session for each provider."""
    if (provider.day_limit is None and provider.month_limit is None) or unkept(session):
        return None
    return _kept(session, ("over", provider.id), lambda: _over_limit(session, provider))


def _over_limit(session: Session, provider: Provider) -> str | None:
    for most, since, per, when in (
        (provider.day_limit, day_start, "a day", "today"),
        (provider.month_limit, month_start, "a month", "this month"),
    ):
        if most is None:
            continue
        # One reading of the record a session, for every provider: by model, by provider.
        models = _kept(session, ("sums", per), lambda since=since: _sums(
            session, [Run.created_at >= since()], [OwnRequest.created_at >= since()])[0])
        # (By the provider's name, as Usage's rows are: a rename takes its record along.)
        found = _spent(session, {k: one for k, one in models.items() if k[0] == provider.name})
        if found["spent"] is not None and found["spent"] >= most:
            return (f"over {provider.name}'s limit of {money(most)} {found['currency']} {per} "
                    f"({money(found['spent'])} spent {when})")
    return None


def past_its_limit(session: Session, provider: Provider) -> str | None:
    """Why no agent is opened on this provider now (a sub-agent, a room's member), in an
    agent's words; None where it is under its limits."""
    over = over_limit(session, provider)
    return (f"{shown_name(provider.name)} is {over}: no agent is opened on it now. Choose "
            "another model, or do this part yourself.") if over else None


def over_month(session: Session, project: Project | None) -> str | None:
    """Why a new turn of `project` waits for the user's word - "over this month's budget
    (10.50 of 10.00 USD)" - or None: under it, or no budget (nothing is added up then). A
    plain chat (no project) is in no project's budget (slice 86a)."""
    if project is None or project.monthly_budget is None:
        return None
    found = month_spend(session, project)
    return (f"over this month's budget ({money(found['spent'])} of {money(found['budget'])} "
            f"{found['currency']})") if found["over"] else None


def lead_over_limit(session: Session, conversation: Conversation | None) -> str | None:
    """`over_limit` of the provider a turn's Lead opens on in `conversation` (a new one's
    without it)."""
    limited = select(Provider.id).where(
        (Provider.day_limit.is_not(None)) | (Provider.month_limit.is_not(None))).limit(1)
    if session.scalar(limited) is None:
        return None  # (nobody set one: who the Lead runs on is not even looked for)
    from app.team import would_run  # here: app.team asks this module of a limit

    # shortcut: the Lead as it opens; one whose model follows the message (`lead_auto`) may
    # then move to another provider - it is asked of the one it opens on.
    return over_limit(session, would_run(session, find_role(session, LEAD), conversation).provider)


def over_budget(
    session: Session, project: Project | None, conversation: Conversation | None = None,
    spends: list[Provider] | None = None,
) -> str | None:
    """Why a new turn of `project` waits for the user's word: over this month's budget, or
    over the limit of a provider that spends in it - `spends`, where the caller knows them
    (a comparison's sides, the model asked for the day's words), else the one its Lead
    opens on in `conversation`. None: under them, or none set."""
    if over := over_month(session, project):
        return over
    if spends is None:
        return lead_over_limit(session, conversation)
    return next(filter(None, (over_limit(session, provider) for provider in spends)), None)


@router.get("/projects/{project_id}/budget", response_model=BudgetOut)
def project_budget(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    return month_spend(session, project)


def _prices(session: Session) -> list[Price]:
    return list(session.scalars(select(Price).order_by(Price.model_id)))


# A price is listed as it was written: without a cache price nobody wrote.
@router.get("/prices", response_model=list[PriceOut], response_model_exclude_none=True)
def list_prices(session: Session = Depends(get_session)):
    return _prices(session)


@router.get("/prices/catalogue", response_model=list[CataloguePriceOut])
def catalogue_prices(session: Session = Depends(get_session)):
    """models.dev's price of each model that ran on a provider with a price for a token, or
    that such a provider names (its default model, its team guide): the price used where
    the user wrote none, which the user can write over (`/prices`)."""
    copy = models_dev.load(session.info.get("runtime_root"))
    served = {p.name: p for p in session.scalars(select(Provider)) if p.kind in HTTP_KINDS}
    ran = session.execute(union_all(
        select(Agent.provider_name, Agent.model_id), select(OwnRequest.provider_name,
                                                            OwnRequest.model_id))).all()
    named = [(p.name, name) for p in served.values()
             for name in [p.default_model, *(m["name"] for m in p.models or [])]]
    told: dict[str, dict] = {}
    for provider_name, model_id in [*named, *ran]:
        if not model_id or model_id in told:  # a price is the model name's, whoever runs it
            continue
        price = _catalogue_price(served.get(provider_name), model_id, copy)
        if price is not None:
            told[model_id] = {"model_id": model_id, "provider_name": provider_name,
                              **vars(price)}
    return sorted(told.values(), key=lambda row: row["model_id"])


@router.put(
    "/prices", response_model=list[PriceOut], response_model_exclude_none=True,
    dependencies=[Depends(require_own_origin)],
)
def set_price(body: PriceIn, session: Session = Depends(get_session)):
    """Write, or write over, the price of one model; answers with every price there is."""
    session.merge(Price(**body.model_dump()))
    session.commit()
    return _prices(session)


@router.delete(
    "/prices", response_model=list[PriceOut], response_model_exclude_none=True,
    dependencies=[Depends(require_own_origin)],
)
def delete_price(model_id: str, session: Session = Depends(get_session)):
    price = session.get(Price, model_id)
    if price is not None:
        session.delete(price)
        session.commit()
    return _prices(session)
