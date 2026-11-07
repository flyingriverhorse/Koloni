"""What KOLONİ knows of a provider's models before asking the provider: models.dev's facts
(`app.models_dev`) under `catalog.json`'s rules - tiers by family or name, the CLIs' own model
names and levels, hosts models.dev has no address for - and whether a CLI is signed in.

Each fact comes with where it came from ("models.dev", "catalog"); what neither says is None,
never a guess.
"""

import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

from app import models_dev
from app.config import REPO_ROOT, is_local
from app.model_cli import CliStepClient, level_in_name
from app.model_client import EFFORTS
from app.providers import (
    CLI_COMMANDS,
    CLI_NAMES,
    HTTP_KINDS,
    INPUTS,
    MAX_MODEL_NAME,
    MAX_MODEL_NOTE,
    MAX_MODELS,
    SERVER_CLIS,
)

_CATALOGUE = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
# The user's own catalogue, read after this one (design 60 §3; catalog.local.example.json):
# by a fill, the offered names, the Lead's notes and a model's facts (its tier and levels).
LOCAL = REPO_ROOT / "catalog.local.json"
# What each tier is for, in KOLONİ's words: the note a fill copies for a model of that tier.
NOTES: dict[str, str] = _CATALOGUE["notes"]
_RANK = {"strongest": 0, "balanced": 1, "fast": 2, None: 3}
_TIERS = ("strongest", "balanced", "fast")
# The service's levels KOLONİ sends: models.dev's "none" and "minimal" are not among them.
_SENT = tuple(level for level in EFFORTS if level != "off")
# The vendor's own sign-in status command, where its docs say there is one; it reads what
# is stored on this machine and calls no model. Others: whether they are signed in is unknown.
# shortcut: read from the docs and Codex's source, not measured against the real CLIs;
# run each by hand once (kalan-isler) and drop one that turns out to reach a model.
STATUS = {"claude_cli": ["auth", "status"], "codex_cli": ["login", "status"]}
STATUS_SECONDS = 10.0
FACTS = ("efforts", "context_window", "max_output", "price", "tier", "deprecated")


def _copy(copy: dict | None) -> dict:
    return models_dev.load(None) if copy is None else copy


def _cli(kind: str | None) -> dict:
    return _CATALOGUE["cli"].get(kind or "", {})


def catalogue_of(kind: str, base_url: str | None, copy: dict | None = None) -> str | None:
    """Which catalogue a provider's models are in: its kind's, or for an OpenAI-compatible
    server the models.dev service whose address has its host (catalog.json `hosts` where
    models.dev names none) - none for one on this machine or one not known. Copilot on a
    model server of the user's has that server's models, not GitHub's - as Claude Code and
    Codex on one have (K-cli-llama)."""
    if kind in ("copilot_cli", *SERVER_CLIS) and base_url:
        return None
    if kind != "openai_compat":
        return kind
    try:
        host = urlsplit(base_url or "").hostname or ""
    except ValueError:  # not a URL at all, so no known service's
        return None
    if not host or is_local(base_url):
        return None
    # catalog.json's hosts first: where it names one, it is KOLONİ's word over models.dev's.
    named = next((name for known, name in _CATALOGUE["hosts"].items()
                  if host == known or host.endswith("." + known)), None)
    if named:
        return named
    services = models_dev.services(_copy(copy))
    same = [name for name, service in services.items()
            if service["api"] and urlsplit(service["api"]).hostname == host]
    # A vendor's plan and its pay-as-you-go service can share a host: the one whose address
    # the server's begins with (path by path, whatever its case), else the first.
    address = (base_url or "").rstrip("/").lower() + "/"
    whole = [name for name in same
             if address.startswith(services[name]["api"].rstrip("/").lower() + "/")]
    return (whole or same or [None])[0]


def _service(key: str | None, copy: dict) -> tuple[str | None, dict]:
    """The models.dev service of a catalogue, and its models (none for a CLI's own names)."""
    if key is None:
        return None, {}
    name = models_dev.SERVICES.get(key, key)
    return name, (models_dev.services(copy).get(name) or {}).get("models", {})


def _entry(key: str | None, name: str, copy: dict) -> dict | None:
    """A model's models.dev entry. A CLI's own name for a family (Claude Code's `opus`) is
    the newest model of that family that is not being retired."""
    _, models = _service(key, copy)
    if name in models:
        return models[name]
    family = _cli(key).get("models", {}).get(name)
    same: list[dict] = [m for m in models.values() if family and m.get("family") == family
            and m.get("status") != "deprecated"]
    return max(same, key=lambda m: m.get("release_date", "")) if same else None


def _domain(address: str | None) -> str:
    """The last two labels of an address's host ("aliyuncs.com"); empty for none."""
    try:
        return ".".join((urlsplit(address or "").hostname or "").split(".")[-2:])
    except ValueError:
        return ""


def _elsewhere(key: str | None, name: str, copy: dict,
               base_url: str | None) -> tuple[str, dict, bool] | None:
    """A model its own service does not know, by its exact id in another: a plan that resells
    others' models (Alibaba's has DeepSeek's and GLM) - the vendor's own service first, as
    its id begins the name (and whether it was that one); then one at the provider's own
    domain, the most like it (Alibaba China's for Alibaba's plan); then the first by id."""
    own = _service(key, copy)[0]
    domain = _domain(base_url)
    named = sorted(models_dev.services(copy).items(), key=lambda pair: (
        not name.lower().startswith(pair[0]),
        not domain or _domain(pair[1].get("api")) != domain, pair[0]))
    return next(((service, said["models"][name], name.lower().startswith(service))
                 for service, said in named if service != own and name in said["models"]), None)


def _efforts(entry: dict, takes_none: bool = False) -> list[str] | None:
    """The levels a model takes, of those KOLONİ sends: none where it does not reason or
    takes only a budget of tokens; None where models.dev does not say. `takes_none`: its
    "none" is KOLONİ's off (OpenAI's own service, which is sent it as that: `off_as`)."""
    if entry.get("reasoning") is False:
        return []
    options = entry.get("reasoning_options")
    if not isinstance(options, list):
        return None
    said = {value for one in options if one.get("type") == "effort" for value in one["values"]}
    if takes_none and "none" in said:
        said.add("off")
    return [level for level in (EFFORTS if takes_none else _SENT) if level in said]


# OpenAI's levels by model name, most particular first, where models.dev has none for a model:
# from the docs (reasoning guide, the gpt-5.5 model page, the latest-model guide), 3 Nov 2026,
# not measured. "off" is their "none"; GPT-6 Astra and GPT-6.1 Sol do not take it.
# shortcut: by the start of a name, for a model newer than the shipped catalogue; the
# catalogue wins wherever it has levels - drop a row once models.dev has all its models.
_OPENAI_LEVELS = (
    ("gpt-6-astra", EFFORTS[1:]), ("gpt-6.1-sol", EFFORTS[1:]), ("gpt-6", EFFORTS),
    ("gpt-5.6", EFFORTS), ("gpt-5.5", EFFORTS[:5]), ("o1", ("low", "medium", "high")),
)


def off_as(kind: str, base_url: str | None, model: str, copy: dict | None = None) -> str | None:
    """What KOLONİ's off is sent as to a model of OpenAI's own service: "none" where its
    levels say it takes that, else its lowest, "low"; None for any other model (and one with
    no levels known), which is sent off as before (`app.model_client._leveled`)."""
    copy = _copy(copy)
    key = catalogue_of(kind, base_url, copy)
    if key != "openai":
        return None
    levels = _catalogued(kind, base_url, model, copy, key)[0]["efforts"]
    return None if not levels else "none" if "off" in levels else "low"


def _priced(models: dict) -> list[float]:
    """The prices out of the service's models in use: what a tier by price is ranked among."""
    return [m["cost"]["output"] for m in models.values()
            if m.get("status") != "deprecated" and (m.get("cost") or {}).get("output")]


def _tier(rules: dict, name: str, entry: dict, priced: list[float]) -> tuple[str | None, str]:
    """A model's tier, and from where: a rule of catalog.json that names a word of its family
    or name; else its price out among the service's (dearest third strongest, middle third
    balanced, cheapest fast; one price, one tier); else none. A model whose name says it
    cannot chat (`not_chat`) has none."""
    if not _chats_by_name(name):
        return None, "catalog"
    words = set(re.split(r"[^a-z0-9]+", f"{entry.get('family') or ''} {name}".lower()))
    ruled = next((tier for word, tier in rules.items() if word in words), None)
    if ruled:
        return ruled, "catalog"
    price = (entry.get("cost") or {}).get("output")
    if not price or not priced:
        return None, "models.dev"
    dearer = sum(other > price for other in priced)
    # (With one or two priced models there is no middle: one is strongest, two are
    # strongest and balanced - nothing is fast until a third is cheaper.)
    return _TIERS[min(dearer * 3 // len(priced), 2)], "models.dev"


def _rules(key: str | None) -> dict:
    tiers = _CATALOGUE["tiers"]
    return tiers.get(key or "") or tiers.get(models_dev.SERVICES.get(key or "", ""), {})


def _mine(key: str | None, provider: str | None) -> list[dict]:
    """The user's own catalogue's rows for a provider: its catalogue's, then its name's
    (the later wins)."""
    told = local()[0]
    # (Merged, a fact at a time; `models_for` offers names from one list or the other.)
    return [*(told.get("models", {}).get(key or "") or []),
            *(told.get("providers", {}).get(provider or "") or [])]


def local_stamp() -> int | None:
    """When catalog.local.json last changed; None without one (`Providers.client`)."""
    try:
        return LOCAL.stat().st_mtime_ns
    except OSError:
        return None


def facts(kind: str, base_url: str | None, model: str, copy: dict | None = None,
          provider: str | None = None) -> tuple[dict, dict]:
    """What the catalogue says of a model, and where each fact came from; what it does not
    say is None; over it, the user's own catalogue's tier and levels (`_mine`), said to be
    "you"'s. A CLI's levels are its own (catalog.json), whatever its model - but where its
    name fixes its level, which takes none (B-404: `level_in_name`); a model on
    a CLI's plan has no price. A model an OpenAI-compatible service does not know is looked
    for in the others: what is found there is said to be that service's ("models.dev
    (deepseek)") - its price too, which is that service's own and is shown, never counted
    (`app.api.usage`)."""
    copy = _copy(copy)
    key = catalogue_of(kind, base_url, copy)
    told, said = _catalogued(kind, base_url, model, copy, key)
    # (Only for a caller naming the provider: one asking for a price or retiring per model
    # does not read the file each time.)
    for row in _mine(key, provider) if provider else []:
        if row["name"] != model:
            continue
        if row.get("tier"):
            told["tier"], said["tier"] = row["tier"], "you"
        # shortcut: levels only where they are what is sent (an OpenAI-compatible client);
        # a CLI's are catalog.json's and Anthropic's its Models API's. Pass them on if asked.
        if kind == "openai_compat" and row.get("efforts") is not None:
            told["efforts"] = [level for level in EFFORTS if level in row["efforts"]]
            said["efforts"] = "you"
    return told, said


def _catalogued(kind: str, base_url: str | None, model: str, copy: dict,  # noqa: C901
                key: str | None) -> tuple[dict, dict]:
    told: dict = dict.fromkeys(FACTS)
    said: dict = {}
    if key is None:
        return told, said
    entry, dev, near = _entry(key, model, copy), "models.dev", True
    # Only for a server found by its address (one on this machine has none); a CLI's names
    # and Anthropic's are their own.
    found = None if entry is not None or kind != "openai_compat" else _elsewhere(
        key, model, copy, base_url)
    if found:
        dev, entry, near = f"models.dev ({found[0]})", found[1], found[2]
    # The window agents are compacted against and the levels sent come only from the vendor's
    # own service. shortcut: another's (a reseller's) is shown for nothing that is run; take
    # it too once a plan is seen to serve a model as that service does.
    own = key == "openai" and not found
    if level_in_name(kind, model):
        told["efforts"], said["efforts"] = [], (
            "Copilot picks it (auto)" if kind == "copilot_cli" else "its name says its level")
    elif "efforts" in _cli(kind):
        told["efforts"], said["efforts"] = list(_cli(kind)["efforts"]), "catalog"
    elif entry is not None and near and _efforts(entry, own) is not None:
        told["efforts"], said["efforts"] = _efforts(entry, own), dev
    elif key == "openai":
        docs = next((levels for start, levels in _OPENAI_LEVELS if model.startswith(start)), None)
        if docs is not None:
            told["efforts"], said["efforts"] = list(docs), "docs"
    if entry is not None:
        limit, cost = entry.get("limit") or {}, entry.get("cost") or {}
        for fact, value in (("context_window", limit.get("context")),
                            ("max_output", limit.get("output"))):
            if value and (near or fact == "max_output"):
                told[fact], said[fact] = int(value), dev
        if kind in HTTP_KINDS and "input" in cost and "output" in cost:
            told["price"] = {part: cost.get(part) for part in models_dev.COSTS}
            said["price"] = dev
        if not found:  # (another service retiring it says nothing of this one's)
            told["deprecated"], said["deprecated"] = entry.get("status") == "deprecated", dev
    tier, source = _tier(_rules(key), model, entry or {}, _priced(_service(key, copy)[1]))
    if model in _cli(key).get("extra", {}):  # (a CLI's own name: its tier is catalog.json's)
        tier, source = _cli(key)["extra"][model]["tier"], "catalog"
    if tier:
        told["tier"], said["tier"] = tier, dev if source == "models.dev" else source
    return told, said


def no_tool_calls(provider, model: str, copy: dict | None = None) -> bool:
    """K-skill-uyum: the catalogue says this model makes no tool calls. A model it does not
    know, or says nothing of, may: it is not counted against."""
    copy = _copy(copy)
    key = catalogue_of(provider.kind, provider.base_url, copy)
    return key is not None and (_entry(key, model, copy) or {}).get("tool_call") is False


def inputs(provider, model: str, copy: dict | None = None) -> dict[str, tuple[bool, str]]:
    """What a model takes besides text (slice 85b), each kind with who said so, the later
    over the earlier: "models.dev", "you" (catalog.local.json, then the model's own row) and
    "tried" (KOLONİ sent it one, `Provider.tried_inputs`). A kind nobody said is left out:
    unknown, never a guess."""
    copy = _copy(copy)
    key = catalogue_of(provider.kind, provider.base_url, copy)
    entry = _entry(key, model, copy) if key else None
    if entry is None and key and provider.kind == "openai_compat":
        entry = (_elsewhere(key, model, copy, provider.base_url) or (None, None))[1]
    said = ((entry or {}).get("modalities") or {}).get("input")
    told = {kind: (kind in said, "models.dev") for kind in INPUTS} if isinstance(said, list) else {}
    rows = [*_mine(key, provider.name), *(provider.models or [])]
    for row in rows:
        if row.get("name") == model and isinstance(row.get("inputs"), list):
            told |= {kind: (kind in row["inputs"], "you") for kind in INPUTS}
    tried = (provider.tried_inputs or {}).get(model) or {}
    told |= {kind: (bool(took), "tried") for kind, took in tried.items() if kind in INPUTS}
    return told


def model_key(provider, model: str | None) -> str:
    """The name a model's tried inputs are kept and looked up by: the one a run names, else
    its provider's default - the same for a run, the Check and the Models page."""
    return model or provider.default_model or ""


def inputs_words(takes: dict[str, tuple[bool, str]]) -> str | None:
    """What a model is known to take, as the Lead's guide says it: "sees images and video"."""
    seen = [{"image": "images", "pdf": "PDFs"}.get(kind, kind)
            for kind in INPUTS if takes.get(kind, (False,))[0]]
    return f"sees {' and '.join(seen)}" if seen else None


def _row(row) -> bool:
    return (isinstance(row, dict) and isinstance(row.get("name"), str)
            and 0 < len(row["name"].strip()) <= MAX_MODEL_NAME
            and row.get("tier") in (*_TIERS, None)
            and (row.get("note") is None or isinstance(row["note"], str)
                 and len(row["note"]) <= MAX_MODEL_NOTE)
            and (row.get("inputs") is None or isinstance(row["inputs"], list)
                 and all(kind in INPUTS for kind in row["inputs"]))
            and (row.get("efforts") is None or isinstance(row["efforts"], list)
                 and all(level in EFFORTS for level in row["efforts"])))


def local() -> tuple[dict, str | None]:
    """The user's own catalogue - {"providers": {a provider's name: rows}, "models": {a
    catalogue's name: rows}}, a row {"name", "tier", "note", "inputs", "efforts"} - and why
    it is not read: a broken one is not, and stops nothing. Read each time: an edit counts
    at once."""
    try:
        told = json.loads(LOCAL.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except OSError as exc:  # (its words, not the path: the file is named)
        return {}, f"catalog.local.json is not read: {exc.strerror or type(exc).__name__}"
    except ValueError as exc:
        return {}, f"catalog.local.json is not read: {exc}"
    parts = [told.get(part, {}) for part in ("providers", "models")] if isinstance(
        told, dict) else [None]
    if not all(isinstance(lists, dict) and all(
            isinstance(rows, list) and all(_row(row) for row in rows) for rows in lists.values())
            for lists in parts):
        return {}, ("catalog.local.json is not read: its providers and models are each lists "
                    "of {name, tier, note, inputs, efforts} by name, a tier strongest, "
                    f"balanced, fast or null, a note of {MAX_MODEL_NOTE} characters at most, "
                    f"inputs a list of {', '.join(INPUTS)}, efforts a list of {', '.join(EFFORTS)}")
    return told, None


def models_for(key: str | None, copy: dict | None = None,
               provider: str | None = None) -> list[dict]:
    """The catalogued models of a catalogue: a CLI's own names as catalog.json has them, or
    the service's models that take tools and are not being retired - strongest first, a
    tier by a family rule before one by price, the newest first. None for a server of
    one's own. `family`: the service's family of a model, by which a fill keeps one.
    Then the user's own catalogue's (`local`) for the provider by its name, else for the
    catalogue: a model of the same name is the user's."""
    copy = _copy(copy)
    service, models = _service(key, copy)
    rules, priced = _rules(key), _priced(models)
    own = _cli(key).get("models")
    if own is not None:
        source = _cli(key)["source"]
        named = [(name, _entry(key, name, copy) or {}) for name in own]
    else:
        doc = (models_dev.services(copy).get(service or "") or {}).get("doc")
        source = {"url": doc or models_dev.URL, "read_on": models_dev.read_on(copy)}
        named = sorted(((name, m) for name, m in models.items()
                        if m.get("status") != "deprecated" and m.get("tool_call") is not False),
                       key=lambda pair: pair[1].get("release_date", ""), reverse=True)
    rows: list[dict] = []
    for name, entry in named:
        tier, by = _tier(rules, name, entry, priced)
        rows.append({"name": name, "tier": tier, "note": NOTES.get(tier or ""),
                     "source": source, "family": None if own is not None else entry.get("family"),
                     "ruled": by == "catalog"})
    # A CLI's own names beside its service's (catalog.json `extra`: Copilot's auto), which a
    # refresh of models.dev's copy leaves as they are.
    extra = _cli(key).get("extra", {})
    rows = [row for row in rows if row["name"] not in extra] + [
        {"name": name, "tier": row["tier"], "note": row["note"],
         "source": _cli(key)["extra_source"], "family": None, "ruled": True}
        for name, row in extra.items()]
    told = local()[0]
    # (One list, the provider's name's else its catalogue's; `_mine` merges both for facts.)
    mine = (told.get("providers", {}).get(provider or "")
            or told.get("models", {}).get(key or "") or [])
    if mine:
        kept = {row["name"]: row for row in rows}  # (one of the same name keeps its place)
        for row in mine:
            kept[row["name"]] = {
                "name": row["name"], "tier": row.get("tier"),
                "note": row.get("note") or NOTES.get(row.get("tier") or ""),
                "source": {"url": LOCAL.name, "read_on": None}, "family": None, "ruled": True}
        rows = list(kept.values())
    if own is None:
        rows.sort(key=lambda row: (_RANK[row["tier"]], not row["ruled"]))
    return rows


def suggest(kind: str, base_url: str | None, copy: dict | None = None) -> dict:
    """For a provider not added yet: its catalogue's model names, and for a service spoken
    to with a key, its name, address and the name its own docs give the key; for an
    OpenAI-compatible one, the addresses known: models.dev's services' (not those a kind of
    provider has as its own, as GitHub's) and the plans' catalog.json names."""
    copy = _copy(copy)
    key = catalogue_of(kind, base_url, copy)
    services = models_dev.services(copy)
    service = services.get(_service(key, copy)[0] or "")
    served = service if kind in HTTP_KINDS else None
    known = [{"name": one["name"], "api": one["api"]} for name, one in services.items()
             if one["api"] and name not in models_dev.SERVICES.values()]
    return {"models": [row["name"] for row in models_for(key, copy)],
            "service": served and served["name"], "api": served and served["api"],
            "env": served["env"] if served else [],
            "addresses": known + _CATALOGUE["addresses"] if kind == "openai_compat" else []}


def install(kind: str) -> dict | None:
    """The vendor's install command for this machine, and where it is documented."""
    told = _CATALOGUE["cli"].get(kind, {}).get("install")
    if told is None:
        return None
    return {"command": told["windows" if sys.platform == "win32" else "unix"], "docs": told["docs"]}


def sign_in(kind: str) -> dict | None:
    return _CATALOGUE["cli"].get(kind, {}).get("sign_in")


def signed_in_from(kind: str, exit_code: int | None, output: str) -> bool | None:
    """Signed in, not, or not known, from what the status command said. Nothing else of
    the account (its id, an email, a masked key) is kept."""
    said = output.strip()
    if kind == "codex_cli":
        # Read in its source: "Logged in using …" exits 0, "Not logged in" exits 1.
        if exit_code == 0 and said.startswith("Logged in"):
            return True
        return False if exit_code == 1 and said == "Not logged in" else None
    if kind == "claude_cli":
        # Its docs: a JSON object, exit 0 when logged in and 1 when not.
        try:
            told = json.loads(said)
        except ValueError:
            return None
        if not isinstance(told, dict):
            return None
        if exit_code == 0 and told.get("loggedIn") is True:
            return True
        return False if exit_code == 1 else None
    return None


# The plan Claude Code's status names (`subscriptionType`, measured 3 Nov 2026: "max"), as a
# word: nothing else of the account is read.
PLAN_WORD = re.compile(r"[a-z][a-z0-9_]{0,19}")


def plan_from(kind: str, exit_code: int | None, output: str) -> str | None:
    """The plan a signed-in Claude Code names (`subscriptionType`); None for any other answer
    or CLI. (Its email, organisation and their ids are never read.)"""
    if kind != "claude_cli" or exit_code != 0:
        return None
    try:
        told = json.loads(output.strip())
    except ValueError:
        return None
    if not isinstance(told, dict) or told.get("loggedIn") is not True:
        return None
    plan = told.get("subscriptionType")
    return plan if isinstance(plan, str) and PLAN_WORD.fullmatch(plan) else None


def installed(kind: str, executable: str | None) -> bool:
    return shutil.which(executable or CLI_COMMANDS[kind]) is not None


async def signed_in(kind: str, executable: str | None, home: Path | None = None) -> bool | None:
    return (await status(kind, executable, home))[0]


async def status(
    kind: str, executable: str | None, home: Path | None = None
) -> tuple[bool | None, str | None]:
    """Ask the CLI's own status command - only once its free --help shows it has one: an
    older CLI could take the words for a prompt and spend a model call on them. Signed in or
    not (`signed_in_from`), and the plan it names (`plan_from`). `home`: the provider's own
    sign-in folder (`limits.cli_home`), asked there."""
    if kind not in STATUS:
        return None, None
    client = CliStepClient(executable)
    client.command, client.label, client.home = CLI_COMMANDS[kind], CLI_NAMES[kind], home
    try:
        _, helped, _ = await client.run_status(["--help"], STATUS_SECONDS)
        # shortcut: the subcommand is looked for as an indented line of the help, as both
        # print it today; a help laid out otherwise reads as "not known" - fine to miss.
        if not re.search(rf"^\s+{STATUS[kind][0]}\b", helped, re.MULTILINE):
            return None, None
        code, printed, complaint = await client.run_status(STATUS[kind], STATUS_SECONDS)
    except Exception:  # not started, or no answer in time: not known, and nothing logged
        return None, None
    # Each says it on one stream (Codex on stderr); nothing of either is kept past here.
    said = complaint if kind == "codex_cli" else printed
    return signed_in_from(kind, code, said), plan_from(kind, code, said)


def fill(kind: str | None, saved: list[dict], listed: list[str],
         copy: dict | None = None, provider: str | None = None) -> tuple[list[dict], int]:
    """A team guide for the provider: the user's own rows first, each blank note or tier
    filled from the catalogue, then the catalogue's and the provider's own other models,
    strongest first, up to MAX_MODELS. Of a service's family only its newest of each tier
    is proposed: agents read the guide at every step. A provider that lists its models is
    offered only those; a model that cannot chat is never offered (the user may still add it).
    Returns it and how many were left out, those among them."""
    copy = _copy(copy)
    said = set(listed)
    known = {entry["name"]: entry for entry in models_for(kind, copy, provider)}
    kept = []
    for row in saved:
        entry = known.get(row["name"], {})
        kept.append({"name": row["name"], "note": row.get("note") or entry.get("note"),
                     "tier": row.get("tier") or entry.get("tier"),
                     **({"agents": row["agents"]} if "agents" in row else {}),
                     **({"inputs": row["inputs"]} if row.get("inputs") is not None else {}),
                     **({"context": row["context"]} if row.get("context") else {})})
    mine = {row["name"] for row in kept}
    # A model added follows the provider's way: agents may use it if they may use one of its own.
    way = any(row.get("agents", True) for row in saved) if saved else True
    offered = [e for e in known.values() if not said or e["name"] in said]
    newest = {}  # (family, tier) -> its first name: the catalogue lists the newest first
    for e in offered:
        newest.setdefault((e.get("family") or e["name"], e.get("tier")), e["name"])
    more: list[dict] = [
        {"name": e["name"], "note": e.get("note"), "tier": e.get("tier"), "agents": way}
        for e in offered if e["name"] not in mine and e["name"] in newest.values()]
    # A name a server lists that could not be saved as it is is not offered; one the
    # catalogue does not know gets its tier from the service's rules (catalog.json), by name.
    for name in dict.fromkeys(listed):
        if (name not in mine and name not in known and name == name.strip()
                and name.isprintable() and 0 < len(name) <= MAX_MODEL_NAME):
            tier = _tier(_rules(kind), name, {}, [])[0]
            more.append({"name": name, "note": NOTES.get(tier or ""), "tier": tier, "agents": way})
    chat = [row for row in more if _chats(kind, row["name"], copy)]
    chat.sort(key=lambda row: _RANK[row["tier"]])
    room = max(MAX_MODELS - len(kept), 0)
    return kept + chat[:room], len(chat[room:]) + len(more) - len(chat)


def _chats(key: str | None, name: str, copy: dict) -> bool:
    """Whether a model can chat: no word of its name says otherwise (catalog.json's
    `not_chat`), and models.dev, where it knows it, says it writes text."""
    out = ((_entry(key, name, copy) or {}).get("modalities") or {}).get("output")
    return _chats_by_name(name) and (out is None or "text" in out)


def _chats_by_name(name: str) -> bool:
    """No word of the name (its letters) is one of catalog.json's `not_chat`."""
    return not set(re.split(r"[^a-z]+", name.lower())) & set(_CATALOGUE["not_chat"])
