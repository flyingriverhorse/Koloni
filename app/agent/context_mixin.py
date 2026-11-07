"""An agent's context: the history a step is sent (`_history`, with the prompts it is built
from), compaction and the summary of a turn (`_compact`, `compact_now`, `_after_idle`), what a
turn found and is assessed by (`_note_what_it_found`, `_assess`) - `ContextMixin`.
"""

import asyncio
import contextlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from sqlalchemy import Row, and_, literal_column, or_, select
from sqlalchemy.orm import Session

from app import (
    attachments,
    backlog,
    board,
    browser,
    earlier,
    handoff,
    knowledge,
    knows,
    koloni,
    ledger,
    record,
    topics,
)
from app import memory as kept
from app import room as rooms
from app.agent.cards import _answer, _hands_back, _unasked, folders_of
from app.agent.ctx import Ctx, announce, announce_memory
from app.agent.summary import (
    _compacted,
    _in_words,
    _last_exchange,
    _Record,
    _sections,
    _size,
    _Summarised,
    _summarised,
    _Summary,
    _theirs,
    _trim_to_budget,
    compact_at,
)
from app.agent.words import FINDING_KINDS, FROM, IMAGE_HERE, IMAGE_MIME, IMAGE_SHOWN, UNFINISHED
from app.commands import recallable
from app.db.models import (
    Agent,
    BacklogTask,
    BoardPost,
    Conversation,
    FileChange,
    Message,
    Project,
    Provider,
    Question,
    Room,
    Run,
    ToolCall,
    project_of,
)
from app.executors.host import shell_name, shell_writes
from app.model_client import ModelInfo, ModelUnavailable, OwnStop, Transient
from app.providers import ask_once, list_providers
from app.roles import LEAD, LEARN, LOOKUP, find_role, shown_name, tools_off
from app.team import asked_how_hard, guide, quoted, would_run
from app.tools import NOT_A_MODEL, ToolError, parse_arguments
from app.workspace import WorkspaceError, in_scratch, never

if TYPE_CHECKING:
    from app.agent import AgentRunner

log = logging.getLogger("app.agent")

SYSTEM_PROMPT = """You are KOLONİ's coding agent, working inside one project folder: {root}

Use the tools to inspect files before you answer questions about them, and to make the
changes the user asks for. Paths are relative to the project folder. Read a file before you
edit it. Keep changes small and focused on the request. When a tool returns an error, read
the message and adjust. A change can come back "rejected": the user looked at it and said
no. That is not an error to work around — do not make that change another way. It is a no
to that change, not to the task: carry on with the rest, and say at the end what you could
not do. The same goes for a command the user declined to run.

Use run_command to run tests and builds and check your work. {where} A non-zero exit
code is information, not a tool failure: read the output and act on it.
When you are done, say briefly what you did and what you did not verify."""
# In its place in a plain chat (slice 86a), which has no folder.
PLAIN_PROMPT = (
    "You are KOLONİ's agent, in a chat with no folder: you have no tool that changes files or "
    "runs commands.{reads} Talk with the user, look things up on the web where you have the "
    "tools for it, and hand parts of the work to sub-agents. Where the work needs files, say "
    "so: the user picks a folder with the folder button at the top of the chat.\n"
    "When you are done, say briefly what you did and what you did not verify."
)
# In it, to an agent offered read_file (slice 86b). "~", not the home folder's path: that
# holds the user's name, which would go to the provider with every turn.
PLAIN_READS_PROMPT = (
    " A file or folder the user names you may read with read_file or list_dir by its full "
    "path; write the user's home folder as ~ (~\\Desktop\\notes.txt). The user is asked "
    "each time, and allows that one read only."
)

# Said to the lead only: a sub-agent's "user" is the agent that wrote its task. (The user
# wrote in Turkish and was answered in English; B-60 and B-68: a Lead went on in French after a
# refusal, and one wrote its notes in Turkish to a user who wrote English.)
LANGUAGE_PROMPT = (
    "Answer in the language the user writes in: that of their latest message, in every note "
    "and answer of this turn - not the language of a file, a tool's result or an earlier turn."
)
# K-cevap-dili: with "Answer in" set, every agent is told to write in it (`kept.write_in`, in the
# Lead's place of LANGUAGE_PROMPT) - all but what KOLONİ reads off its answer, kept in English.
# "Nothing" is said in English words (`summary.NOTHING_CHECKED`, `NO_FINDINGS`): told exactly.
# shortcut: what is read off free words in English (`handoff._ERROR`) goes unseen in another
# language; COULD_NOT knows Turkish too. Add that language's words where a missed one is met.
KEPT_ENGLISH = (
    "`## Findings`, a finding's `| kind: <kind> | role: <role> | blocking` (or `| suggestion`) "
    f"with its kind ({', '.join(FINDING_KINDS)}) and the role's name as given, `Checked:`, "
    "`Already failing before:`, `Pre-existing:`, `(pre-existing)`, `(already failing before)`, "
    "`| fixed:`, `| disputed:`, "
    + ", ".join(f"`## {heading}`" for heading in handoff.HEADINGS)
    + f", `{backlog.NOT_FINISHED}`, `{backlog.NEEDS_PROJECT}`, `Say:`, and the keys of JSON and "
    "StructuredOutput; for nothing found or nothing checked write exactly `Findings: none` or "
    "`Checked: none`"
)
# Told to the lead only, while its conversation has it hand code to sub-agents (slice 48):
# it is not given the tools that write files, and "Do small jobs yourself" is not for those.
HANDS_CODE_PROMPT = (
    "Hand every change to files to a sub-agent (a Coder for code; a Reviewer to review): "
    "you are not given the tools that write files, and do not write them through commands "
    "either. Read, plan, ask and check yourself."
)
# Told to the lead only, while its conversation has it decide (K-devret): it keeps its write tools.
DECIDES_PROMPT = (
    "Make a small change to files yourself (one or two files, a few lines). "
    "Hand bigger work to a sub-agent (a Coder for code; a Reviewer to review)."
)
# Told to the lead only, in a turn whose message asked for it: the user listens (slice 32a).
SAY_PROMPT = (
    "The user listens to your answer. End your final answer with one line of its own that "
    "starts with `Say:` and gives what to say aloud: in the language {language}, as people "
    "speak, at most two sentences, with no code, lists or addresses."
)
SAY_STYLE = "Say it as the user asked: {style}."

ASK_PROMPT = (
    "When the request is ambiguous, or a decision is the user's to make, ask with ask_user "
    "instead of guessing; do not ask what you can find out yourself."
)
SUB_AGENT_PROMPT = (
    "Your name here is {name}. Your task comes from the {parent} (your opener). When you are "
    "done, reply with a short report of what you found or did; it is returned to them."
)
# B-182 (live: a Codex Coder asked in its report and ended), after it to one that has ask_user.
ASK_NOT_REPORT = ("A question for the user goes in ask_user, never in your report: once you "
                  "report, your work is over and nobody answers it.")
# After it, to one that has post_note (R47: in a three-team run nobody wrote on the notebook).
NOTE_PROMPT = (
    "When you hand work on, or finish a step others build on, first leave a short note with "
    "post_note: what was done, and where."
)
FINDINGS_PROMPT = (
    "End your report with a section `## Findings`, one line per finding: "
    "`- <what> | kind: <kind> | role: <role> | blocking` (or `| suggestion`), where kind is one "
    f"of {', '.join(FINDING_KINDS)} and role is the one of these that should take it: "
    "{roles}. Mark blocking only what must change before the work is done - a bug, what was "
    "asked and not done, a security problem or a test or command that fails (both always "
    "blocking); a nicety, style or "
    "idea is a suggestion: it is left to the user and sends no work back. "
    "With nothing found, end it with `Findings: none`. A finding is about the work "
    "you were given to check; what was already failing before it (an old broken test, say) is "
    "no finding: say it on a line of its own before that section, `Already failing before: "
    "<what>`."
)
# ...and what it is told in place of FINDINGS_PROMPT and CHECKED_PROMPT.
SCHEMA_FINDINGS_PROMPT = (
    "Hand your report in with StructuredOutput. `report` is your report in words, with no "
    "finding in it: each finding goes in `findings` only - what it is, its kind (one of "
    f"{', '.join(FINDING_KINDS)}), the role of these that should take it: {{roles}}, and "
    "`blocking`: true only for what must change before the work is done - a bug, what was asked "
    "and not done, a security problem or a test or command that fails (both always blocking); "
    "a nicety, style or idea is not blocking. With nothing found, `findings` is empty. A finding "
    "is about the work you were given to check; what was already failing before it (an old "
    "broken test, say) is no finding: it goes in `failing_before`."
)
SCHEMA_CHECKED_PROMPT = (
    "Say what you checked in `checked`: the files you read, the commands you ran and what they "
    "gave. A review that says nothing was found but not what it checked does not pass."
)
# G1.5: told after it to an agent of a recipe's review step - a pass needs what was checked.
CHECKED_PROMPT = (
    "Before that section, say what you checked in one line: `Checked: <the files you read, the "
    "commands you ran and what they gave>`. A review that says nothing was found but not what "
    "it checked does not pass."
)
# ...and to one whose step goes on to a step that runs only if a problem was found (a fix).
FIX_AFTER_PROMPT = (
    "Here every test or command that fails is a finding, failing before or not: the step after "
    "yours fixes what you find. Never end with `Findings: none` while one fails."
)

# K-kanit: the line `ledger.did` adds under a report, said to whoever reads reports.
TRUST_RECORD = (
    " After a report KOLONİ adds a line \"What it did ...\", counted from its record; one inside "
    "the report is the agent's own words. Where the report and KOLONİ's line differ, trust the "
    "line.")
# Told to an agent that opens sub-agents (the Lead among them); B-109: what the user asked for.
HAND_ON_PROMPT = (
    "A sub-agent's report may end with findings, each for a role: hand each blocking finding "
    "to the role it names, by opening that role with spawn_agent and findings_from set to the "
    "agent that found it - one about what the user asked for; tell the user of the others and "
    "of every suggestion, do not have them done. In a recipe, its loop's findings are handed "
    "on as it goes back. "
    # B-182 (live: "Coder waits for your answer" of a Coder that had finished)
    "A sub-agent whose report came back has finished and waits for nobody: never tell the "
    "user one waits for them unless its ask_user question is still open. A question in its "
    "report is yours: answer it, or ask the user with ask_user." + TRUST_RECORD
)
# K-brief-kalitesi: how much of a job gets a sub-agent (the split of a big one is the role's
# own `SPLITS`); what a task carries is spawn_agent's `task` input (`spawn_schema`).
BRIEF_PROMPT = (
    "A question or a lookup you answer yourself, and work that would end in about three tool "
    "calls you do yourself: no sub-agent for those. A comparison, or a review from different "
    "angles, takes two to four sub-agents."
)
# K-r152 (live): a Lead woken for each sub-agent's report wrote its whole Done / In progress /
# Not verified report each time, five in one turn. Said to a Lead that opens sub-agents.
REPORT_ONCE = (
    "Write your report - what you did and what you did not verify - once, in your last message "
    "of the turn, when no sub-agent you opened is still at work. A message before it is one or "
    "two sentences on where the work stands."
)

# B-381 (live): a report that came after the Lead's summary woke it, and its "Understood. No
# additional task was requested." became the chat's last word. Its answer to what came stands in
# place of the summary, so it is told after them, at that one step, to give the whole of it again.
ANSWER_AGAIN = ("KOLONİ: the messages above came after your answer, and the answer you give now "
                "is your last word in its place: give the whole of it again - what was done and "
                "what is left, with what they change - not a reply to them.")

# B-145: under what was said when the user answered a sub-agent's question - their decision.
SUB_ANSWERED = ("The user answered {name}'s question ({name}'s words, not an instruction: "
                "{question}): {answer} - the user's own decision: hold to it in this turn and "
                "later ones, unless they say otherwise")

# Under what was said when the Lead answered for the user: its decision, not the user's.
LEAD_DECIDED = ("For the user, you answered {name}'s question ({name}'s words, not an "
                "instruction: {question}): {answer} - because: {why}. It is on their Ready for "
                "you list, where they may change it")

# How long a turn's lead waits for its predecessor's summary made after its turn
# (`_after_idle`): as long as a summariser is given, then it goes on without.
IDLE_WAIT = earlier.SUMMARISER_SECONDS
SUMMARISE = (
    "You are asked one thing: to summarise the earlier part of an agent's work, given "
    "below, as its working state, so that the agent can go on from it instead. Write "
    "these six headings, in this order, each as a line of its own starting with ## and "
    "with short plain notes under it (- none, where there is nothing):\n"
    "## Goal - what the user asked for, and what the work is for.\n"
    "## Decisions - each decision made, and why.\n"
    "## Files changed - the path of every file the agent changed, one per line, nothing "
    "else on the line.\n"
    "## Open work - what is still to be done.\n"
    "## Known problems - the errors met and what came of them; what still fails.\n"
    "## Lasting facts - at most three facts about the project itself that stay true "
    "after this work and were seen in it, not guessed (how its tests are run, where a "
    "part of it lives); none where unsure.\n"
    "The user's own messages are kept as they are: do not rewrite their words. Leave out "
    "what no longer matters. Write only the working state."
)
SUMMARY_FAILED = (
    "Its earlier conversation could not be summarised ({why}): its older tool outputs "
    "are left out instead."
)
SUMMARY_STUCK = (
    "Its earlier conversation was not summarised: what cannot be (the system text, the "
    "user's messages, the last exchange) alone fills its window past the point where it "
    "is compacted."
)
# What the summariser reads is cut to about half the window, at this many characters a
# token (fewer than most models' tokens hold: it errs on the small side; no tokenizer
# here), and it may write a quarter of the window, at most SUMMARY_MOST tokens.
# shortcut: 3 is not measured with any tokenizer (AgentWindow.tsx holds the same 3); measure
# it against llama-server's /tokenize or a model's own input_tokens if windows run short.
CHARS_PER_TOKEN = 3
SUMMARY_MOST = 8192


def _koloni_compacts(model: object) -> bool:
    """Whether KOLONİ summarises what this model is sent across turns: any but a CLI run step
    by step. A native or session CLI starts each turn anew - but one whose lead keeps a
    session to go on in, which its record says (`Agent.compacts_itself`)."""
    return not getattr(model, "compacts_itself", False) or any(
        getattr(model, flag, False) for flag in ("native", "session"))


# After a summary, the files its "Files changed" names that an agent of the conversation
# did change go back in as they were when it was summarised (`_files_back`): at most
# FILES_BACK, together in at most an eighth of the window; the older copies in tool outputs
# are gone with the rest. Read once, not at every step: the prompt stays the same (cached),
# and what changes later is in the steps after it.
FILES_BACK = 5
FILES_NOW = (
    "\n\nThe files changed in that earlier work, as they were when it was summarised (copies "
    "of them from before are out of date; one changed since is to be read again):"
)
FILE_TOO_LARGE = "\n\n{path}: too large to put back here; read it again if you need it."

STILL_RUNNING = "still running: this call has not returned yet"
CALL_RETURNED = (
    "The call you were waiting on has returned; its result is above, before the message "
    "you answered. Carry on with your work."
)
MESSAGE_PROMPT = (
    "You can talk to the other agents of this turn with message_agent: carry on with a "
    "sub-agent that has finished, or ask the agent you work for when your task is unclear."
)
# Said to an agent that can open sub-agents, with or without a team guide: asked for a
# provider that is not there, it says what there is rather than run into the tool's error.
PROVIDERS_PROMPT = (
    "If the user asks for a provider or model that spawn_agent does not list, say "
    "which ones it lists - or that it lists none - instead of trying it."
)
TEAM_PROMPT = (
    "Give a sub-agent another model from the list in spawn_agent only when the user asks "
    "for it by name, when the job is beyond your own model, or when it is the kind of job "
    "a note there describes; otherwise leave provider and model out."
)
# Said once to an agent that is offered tools of the user's MCP servers, not with each tool:
# a server may have forty. Such a tool is not run where the agent works. {root}: the folder
# the agent works in as this is said - the project, or its working copy once it has one.
MCP_PROMPT = (
    "The tools named server__tool are tools of MCP servers the user added. They do not run "
    "in the project folder and are not held to it: a path relative to it means nothing to "
    "them, so give them full paths. The folder you work in has the full path {root}"
)
# Said to a CLI in a project that is a git repository (slice 70), as git was when the turn
# began: the branch is the repository's, and quoted.
GIT_PROMPT = (
    "Git: the project is a git repository, on {branch}. {where} Don't switch branches, open "
    "worktrees, commit or merge - KOLONİ does that. If you must, ask the user first, and say "
    "why and which branch it should be merged into.{report}"
)
GIT_IN_PROJECT = "You work in the project itself."
GIT_IN_COPY = (
    "You work in a copy of it, which is not a git repository: KOLONİ takes your changes "
    "into the project when your work is over."
)
GIT_REPORT = " If you did any of it, call report_git right after."


def git_prompt(branch: str, in_copy: bool, reports: bool) -> str:
    """The git section of a CLI's instructions (slice 70)."""
    return GIT_PROMPT.format(
        branch=f"branch {quoted(branch)}" if branch else "no branch (a detached HEAD)",
        where=GIT_IN_COPY if in_copy else GIT_IN_PROJECT, report=GIT_REPORT if reports else "")


ANSWERING_PROMPT = (
    "Right now you are answering a message from another agent. Reply to it from what you "
    "know; you may read files, and you cannot change anything or call on anyone in this turn."
)

# B-121 (live): "Uyumaya gidiyorum. Bu gece şunları bitir: …" - the Lead did the work at once. A
# message with a phrase that may say the user goes away is followed, for a Lead that has
# plan_away, by a note of KOLONİ's (a cue, not a reading: whether they go is the Lead's to see).
# Phrases, not words: "config dosyası yokken", "time.sleep", "deploy tonight's build" are work.
# (`re.IGNORECASE` folds i, ı, I and İ together.)
AWAY_CUES = re.compile(
    r"\b(?:ben yokken|uyuyorum|(?:uyumaya|yatmaya) gidiyorum|yatıyorum|sabaha kadar"
    r"|bu gece (?:şunları|bunları|şunu|bunu)|bu gece\b[^.\n]{0,40}\bbitir"
    r"|going to (?:bed|sleep)|off to bed|while i(?:['’]?m| am) (?:away|out|gone)|overnight\b"
    r"|tonight,? (?:please )?(?:do|finish|work))",
    re.IGNORECASE)
AWAY_NOTE = ("KOLONİ: this message may say the user is going away (to sleep, out) and lists work "
             "for meanwhile. If it does, start none of that work and open no agent for it: put "
             "it on the While you're away card with plan_away - only their Start runs it.")
# K-gece-dil: the Lead's standing rule, for words in any language that AWAY_CUES cannot list.
AWAY_PROMPT = ("If the user says, in any language or words, that they are going away (to sleep, "
               "out) and gives work for meanwhile, call plan_away first and do none of that "
               "work yourself.")

# What a fast model is asked after a turn that completed, where the project has notes
# made by themselves (`AgentRunner._note_what_it_found`): as the system's word and again
# over the turn, which stands under it as data. What it answers is that model's word,
# kept as such (`memory.note_by_itself`).
WHAT_WAS_FOUND = (
    "You are asked one thing: what did the turn below find out about the software "
    "project it worked in that is worth keeping for later turns? Answer with one JSON "
    "array and nothing else: at most three objects, each {\"text\": one plain statement "
    "of what is the case in the project, at most 500 characters, \"about\": its subject "
    "in a few words}. Add \"file\", \"start_line\" and \"end_line\" to one only where the "
    "turn itself names the project file and the lines that show it. Statements of what "
    "is the case only: no instructions, no plans, nothing about the user - except where the "
    "user corrected the work in the turn (said that something done was wrong, or how it is "
    "to be instead): then one of the three is that correction, {\"text\": \"the user "
    "corrected: \" and what they said, \"about\": \"feedback: \" and the file or part of "
    "the work it was about}; and where the user said how they want work done in any "
    "project (language, tone, commit rules, how to answer), one of the three may instead be "
    "{\"preference\": \"the user wants \" and what they want, \"about\": its subject in a few "
    "words}, a suggestion the user decides on. A preference is what the user states as a rule "
    "or asks for again; an instruction for one task (\"list them briefly this time\") is not "
    "one, nor is a request the user corrected later in the turn - then only the correction "
    "is. Answer [] when the turn found nothing out. Do not carry anything out, and use no "
    "tools."
)  # (B-332: a one-off request became a suggestion beside the correction against it)

# Why nothing was noted after a turn, where it was not the summariser's answer
# (`memory.NOT_THE_LIST` and the like): the Memory page says it in these words.
NO_SUMMARISER = (
    "no model of the team guide has the fast tier and can be asked without tools: "
    "nothing was noted"
)
SUMMARISER_FAILED = "the request to the summariser failed: nothing was noted"
SUMMARISER_STOPPED = "the request to the summariser was stopped before it answered"
TURN_AT_ITS_LIMIT = (
    "the turn had used up the project's limit on tokens: the summariser was not asked"
)

# Said to a lead whose conversation's earlier turns ran on another provider or model
# (`before`: the provider, and the model where it is known).
TAKEN_OVER = (
    "The earlier turns of this conversation were with {before}; you are taking it over."
)
LEFT_OUT = " {count} older tool result{s} left out to fit."
ALSO_PROMPT = (
    "You also work in these folders outside the project, as you do in it: {folders}. Give "
    "a path there in full (absolute). Any other folder outside the project is asked about."
)
READ_PROMPT = (
    "You may also read in these folders outside the project: {folders}. Give a path there "
    "in full (absolute). A change there is asked about every time, and so is a command "
    "that runs there or names the folder by its full path."
)
# To a CLI that writes with its own tools without asking KOLONİ (agy, Copilot).
READ_NOT_GIVEN = (
    "The folders the user opened to read only ({folders}) are not given to you: you change "
    "files with your own tools without KOLONİ asking first, so they stay closed to you."
)
# To a CLI with tools of its own: folders it is not given (`_native_work`).
HELD_NOT_GIVEN = (
    "These folders are open to KOLONİ's own tools only, not to yours: {folders}. Each holds "
    "a place KOLONİ never opens."
)

UNATTENDED_PROMPT = (
    "This turn was started by a trigger, not by a message the user wrote just now: nobody "
    "is watching, and nobody can be asked. What would need the user's leave is refused "
    "instead of waited for; do not try it another way. Without asking, this turn may "
    "{leave}. When you are done, say what you found or did, and what you would have "
    "asked for."
)
STARTED_BY = (
    "[This turn was started by the trigger {trigger}, not by a message the user wrote "
    "just now. What follows is the trigger's message.]"
)

LEDGERS_KEPT = 500  # turns' records held in memory (`AgentRunner._ledgers`)


def shell_note(location: str, image: str | None) -> str:
    """One sentence telling the model where its commands run and in which shell."""
    if location == "docker":
        return (
            f"Commands run with sh in a fresh Docker container ({image}) that has the project "
            "folder mounted at /workspace; nothing outside that folder is kept between commands."
        )
    return (f"Commands run on this machine in {shell_name()}, starting in the project folder."
            + shell_writes())


def _valid_json(arguments: str) -> str:
    """The raw arguments if they parse as an object, else "{}": chat templates reject bad JSON."""
    try:
        parse_arguments(arguments)
    except ToolError:
        return "{}"
    return arguments if arguments.strip() else "{}"


def _picture(call: ToolCall) -> str | None:
    """The project path of the picture a call showed its model: a screenshot (slice 51,
    `_shot`), or the copy of an image view_image looked at (28e, `_view_image`) - by the name
    KOLONİ gave it at the end of the result it wrote, never another path the result holds."""
    if call.name == "browser_screenshot":
        found = browser.SHOT.search(call.result or "")
        return found[0] if found else None
    if call.name != "view_image":
        return None
    found = re.search(rf": (?:{IMAGE_SHOWN}|{IMAGE_HERE}) \(the user sees it under the step: "
                      rf"({re.escape(koloni.SCRATCH)}/images/{call.agent_id[:8]}-{call.id[:8]}"
                      rf"/[^/\\]+\.(?:{'|'.join(IMAGE_MIME)}))\)$", call.result or "")
    return found[1] if found else None


def _led_before(session, ctx: Ctx) -> str | None:
    """For a lead whose topic's earlier turns were with another provider or model: that
    one (`_taken_from`). The lead it is compared with is the last one before it that
    left something in the history it reads - words, or a tool call: a turn whose model
    never answered (its server was down) left nothing to take over, and is passed by."""
    lead = before = session.get(Agent, ctx.agent_id)
    seen: set[str] = set()
    while before is not None:
        seen.add(before.id)
        earlier = before.continues_id
        before = session.get(Agent, earlier) if earlier and earlier not in seen else None
        if before is not None and session.scalar(
            select(Message.id).outerjoin(ToolCall, ToolCall.message_id == Message.id)
            .where(Message.agent_id == before.id, Message.role == "assistant",
                   (Message.content != "") | ToolCall.id.is_not(None)).limit(1)
        ):
            break
    return _taken_from(before, lead)


def _taken_from(before: Agent | None, lead: Agent | None) -> str | None:
    """The provider a lead takes a conversation over from, and its model where it is
    known ("Local · qwen"), read off the two leads' records. None when it goes on with
    its own conversation - or when that cannot be told.

    A CLI names its model itself once it has run, by another name than the one it was
    asked by: on one provider only the names of an API (which are the ones KOLONİ asked
    by) are told apart. The provider is known by its name, which is all that is on
    record: one renamed since reads as another.
    """
    if before is None or lead is None or not before.provider_name:
        return None

    def named(agent: Agent) -> str | None:
        known = agent.model_id and agent.model_from is None and agent.model_id not in NOT_A_MODEL
        # (Whatever a server named itself: one plain line of it, as `who_line` shows it.)
        return kept.one_line(agent.model_id)[:200] if known else None

    was, now_on = named(before), named(lead)
    if before.provider_name == lead.provider_name and (
        before.provider_mode or lead.provider_mode or not was or not now_on or was == now_on
    ):
        return None
    return " · ".join(part for part in (shown_name(before.provider_name), was) if part)


@dataclass
class _Said:
    """What the parts of `_history` share once its session is over: what its rows are read
    with, and `messages` with what is kept of where things are in it."""
    ctx: Ctx
    has: set[str]
    replays: bool
    links: list[tuple[Agent, int]]
    family: dict[str, tuple[str, str | None]]
    messages: list[dict]
    off: frozenset[str]
    read_how: str
    told_files: dict[str | None, tuple[str, list[dict]]]
    told_of_rooms: dict[str, str]
    far: dict[str, str | None]
    notes_of: dict[str, BoardPost]
    prompted: bool = False
    # For a chain: where each link's part of the history begins, in step with `links`.
    begins: list[int] = field(default_factory=list)
    # each result's message, its call, hinted
    results: list[tuple[dict, ToolCall, bool]] = field(default_factory=list)
    # where in the messages each screenshot (True) or image (28e) of this turn is
    shots: list[tuple[int, bool]] = field(default_factory=list)
    takes_images: bool | None = None  # (slice 51: asked once, at the first screenshot)


def _is_above(family: dict[str, tuple[str, str | None]], agent_id: str | None,
              other: str | None) -> bool:
    walk = family.get(other or "", ("", None))[1]
    while walk is not None:
        if walk == agent_id:
            return True
        walk = family.get(walk, ("", None))[1]
    return False


class ContextMixin:
    async def _note_what_it_found(self: "AgentRunner", ctx: Ctx) -> None:
        """After a turn that completed, where its project has notes made by themselves
        (`auto_notes`): the first fast model that can be asked with no tools - the one a
        lead's "how hard is this" goes to - is given what was said in the turn and asked
        for at most three notes, which go into the journal as that model's
        (`memory.note_by_itself`). How it went is kept on the project, for its Memory
        page: also why nothing was noted.

        The turn is over before this starts and nothing waits for it: its lead holds no
        place, and the request holds one of its own only while it is out, on the provider
        it goes to - standing in line for it like any model step, with nothing of that
        put on the lead's record. What it spent is on a record of its own under the model
        that was asked (`_own_request`). It never fails the turn: whatever goes wrong
        here is why nothing was noted. The app going down ends it."""
        with self._factory() as session:
            project = self._project(session, ctx.cid)
            if project is None or not project.auto_notes:
                return
            project_id = project.id
        # The turn's own clock is not what this request runs on: a trigger's minutes
        # are for its turn.
        unwatched = self._unwatched.pop(ctx.run_id, None)
        if unwatched is not None and unwatched.timer is not None:
            unwatched.timer.cancel()
        self._give(ctx)
        outcome = {"noted": 0, "skipped": 0, "note": SUMMARISER_STOPPED}
        try:
            outcome = await self._summarised(ctx)
        except Exception:
            outcome["note"] = SUMMARISER_FAILED
        finally:
            # Also when it is cut short, which is not an Exception: the page then says so.
            with contextlib.suppress(Exception):
                with self._factory() as session:
                    session.get_one(Project, project_id).last_auto = {
                        "run_id": ctx.run_id, **outcome}
                    session.commit()
                announce_memory(self._factory, self.bus, project_id)

    async def _assess(self: "AgentRunner", ctx: Ctx, task_id: str) -> None:
        """The Assistant product owner's view of a backlog task whose turn just ended:
        asked of the first fast model with no tools, as notes made by themselves are
        (`_summarised`), given the task, what was said in the turn and the changes it took
        into the project - in two or three
        sentences, kept as the task's `assessment`, an opinion. What it spent is KOLONİ's
        own request (`_own_request`). Nobody to ask, or no answer: no view - nothing made
        up. It never fails the turn.
        shortcut: with no fast model to ask (no model has the fast tier, ticked for
        agents) no view is ever written and the page does not say why; fall back to the
        Lead's model, as the day's words do, if users miss it. Who wrote a view is not
        kept either: the card says "an agent's view" for this one and assess_task's.
        shortcut: this view replaces one an agent wrote with assess_task in the turn; keep
        both if users want the agent's own word too.
        shortcut: a trigger's turn is never a task's, so no trigger's timer is stopped here."""
        try:
            self._give(ctx)  # (the turn is over: its lead holds no place)
            with self._factory() as session:
                conversation = session.get_one(Conversation, ctx.cid)
                project = project_of(session, conversation)
                if project is None:  # (a plain chat has no backlog)
                    return
                limit = project.turn_token_limit
                if limit and self._turn_spent(session, ctx.run_id)[0] > limit:
                    return
                would = would_run(
                    session, find_role(session, LEAD), conversation, tools=ctx.tools)
                fast = asked_how_hard(session, would, self.providers)
                task = session.get(BacklogTask, task_id)
                if fast is None or task is None:
                    return
                asking, mode = self._on(session, ctx, *fast)
                # (B-123: a job while the user was away, what it kept in its copy too.)
                seen = ("applied", "in_copy") if task.away_run_id else ("applied",)
                given = backlog.to_assess(task, self._turn_in_words(session, ctx), [
                    one for one in session.scalars(select(FileChange).where(
                        FileChange.run_id == ctx.run_id, FileChange.status.in_(seen))
                        .order_by(literal_column("file_changes.rowid")))
                    if not in_scratch(one.path)])
                project_id = task.project_id
            before = self._ctxs[ctx.agent_id]
            self._ctxs[ctx.agent_id] = asking  # its place is counted where the request goes
            try:
                async with self._working(asking, shown=False):
                    try:
                        async with asyncio.timeout(earlier.SUMMARISER_SECONDS):
                            said, answer = await ask_once(asking.model, fast[1], [
                                {"role": "system", "content": backlog.ASSESS},
                                {"role": "user", "content": given},
                            ])
                    except BaseException:
                        self._own_request(ctx, asking, mode, None)  # sent, not heard out
                        raise
                    self._own_request(ctx, asking, mode, answer)
            finally:
                self._ctxs[ctx.agent_id] = before
            said = _answer(said).strip()[:backlog.MAX_ASSESSMENT]
            with self._factory() as session:
                task = session.get(BacklogTask, task_id)
                # Not where the task has gone on since: another turn's, or deleted.
                if not said or task is None or task.conversation_id != ctx.cid:
                    return
                task.assessment = said
                session.commit()
            announce(self._factory, self.bus, project_id, "backlog.changed")
        except Exception as exc:  # (ModelUnavailable, a timeout, ...: no view)
            log.warning("task %s: no assessment: %r", task_id, exc)

    async def _summarised(self: "AgentRunner", ctx: Ctx) -> dict:
        """Ask the summariser about a turn and keep what it noted: {"noted", "skipped",
        "note"} (`note`: why nothing was noted). Never for a plain chat: its one caller,
        `_note_what_it_found`, returns first for a chat with no project."""
        nothing = {"noted": 0, "skipped": 0}
        with self._factory() as session:
            run = session.get_one(Run, ctx.run_id)
            conversation = session.get_one(Conversation, ctx.cid)
            project = session.get_one(Project, conversation.project_id)
            # What KOLONİ asks a model for a turn counts in what the turn may spend.
            limit = project.turn_token_limit
            if limit and self._turn_spent(session, ctx.run_id)[0] > limit:
                return {**nothing, "note": TURN_AT_ITS_LIMIT}
            would = would_run(session, find_role(session, LEAD), conversation, tools=ctx.tools)
            fast = asked_how_hard(session, would, self.providers)
            if fast is None:
                return {**nothing, "note": NO_SUMMARISER}
            asking, mode = self._on(session, ctx, *fast)
            turn = self._turn_in_words(session, ctx)
            unattended = run.unattended
            write_in = kept.write_in(session, f"the JSON keys, `{kept.FEEDBACK}`")
        before = self._ctxs[ctx.agent_id]
        self._ctxs[ctx.agent_id] = asking  # its place is counted where the request goes
        try:
            async with self._working(asking, shown=False):
                try:
                    # A time of its own: the place it holds may be the one the next turn
                    # waits for. (Not a task of its own: nothing else is waited for here.)
                    async with asyncio.timeout(earlier.SUMMARISER_SECONDS):
                        said, answer = await ask_once(asking.model, fast[1], [
                            {"role": "system",
                             "content": "\n\n".join(filter(None, (WHAT_WAS_FOUND, write_in)))},
                            # Said again over the turn, which stands under it as data.
                            {"role": "user",
                             "content": f"{WHAT_WAS_FOUND}\n\nThe turn:\n{turn}"},
                        ])
                except BaseException:
                    self._own_request(ctx, asking, mode, None)  # sent, and not heard out
                    raise
                self._own_request(ctx, asking, mode, answer)
        except (ModelUnavailable, TimeoutError):
            return {**nothing, "note": SUMMARISER_FAILED}
        finally:
            self._ctxs[ctx.agent_id] = before
        with self._factory() as session:
            return kept.note_by_itself(
                session, session.get_one(Project, project.id), _answer(said),
                run_id=ctx.run_id, conversation_id=ctx.cid, unattended=unattended,
                # The model as it was asked for, as on a lead that was asked how hard.
                noted_by={"provider_name": asking.provider, "model_id": asking.model_name},
            )

    async def _compact(
        self: "AgentRunner", ctx: Ctx, info: ModelInfo, history: list[dict], window: int | None,
        sent: int | None = None, shown: bool = True,
    ) -> list[dict]:
        """The history an agent is sent, its older part summarised by its own model: the
        part before the last exchange, but the user's messages (`_theirs`), with the
        summary before it (`_compacted`); from this step on (`_summaries`). The summariser
        reads the user's messages in their places, and what fits half the window; what it
        spends is the agent's. Where no summary comes, the older tool outputs are left out
        instead; where, once summarised, what cannot be alone fills the threshold (by
        `sent`, its size), nothing is - each said once on the agent, and not tried again.
        The same `history` where nothing was done. `shown`: False after its turn
        (`_compact_idle`): no step follows that would say it is over. `window` None (a
        refusal for its size, its window unknown): what it reads is held to half of what
        any request is, and it writes at most SUMMARY_MOST."""
        summary = self._summaries.get(ctx.agent_id) or _Summary()
        at = _last_exchange(history)
        if summary.failed or summary.stuck or not at:
            return history
        applied = any(isinstance(m, _Summarised) for m in history)
        older = [m for m in history[1:at] if not _theirs(m) and not isinstance(m, _Summarised)]
        if not older:
            return history
        # A first summary is always tried; a later one only where it can bring the size
        # down - what cannot be summarised, its share of `sent` by size, under the threshold.
        if sent is not None and applied and window:
            whole = sum(_size(m) for m in history) or 1
            with self._factory() as session:
                threshold = compact_at(session) / 100
            if sent * (whole - sum(_size(m) for m in older)) / whole >= window * threshold:
                self._summaries[ctx.agent_id] = replace(summary, stuck=True)
                self._set_agent(ctx.cid, ctx.agent_id, summary_note=SUMMARY_STUCK)
                return history
        told = [type(m)(m) for m in history[1:at] if not isinstance(m, _Summarised)]
        so_far = summary.text if applied else ""
        # (Its oldest tool outputs go first, as for any request: `_trim_to_budget`.)
        reads = window * CHARS_PER_TOKEN if window else self.settings.context_char_budget
        _trim_to_budget(told, max(0, reads // 2 - len(so_far)))
        part = "\n\n".join(_in_words(m) for m in told)
        if so_far:
            part = f"The summary so far:\n{so_far}\n\n{part}"
        if shown:
            self.bus.emit_transient(ctx.cid, "run.thinking", {
                "run_id": ctx.run_id, "agent_id": ctx.agent_id, "summarising": True})
        why = "it said nothing"
        try:
            # (From its answer on, nothing waits until it is kept: no correction comes between.)
            self._summarising.add(ctx.agent_id)
            try:
                # (Its own model, in the place this step holds; a CLI with its own tools
                # off: `ask_once`.)
                said, answer = await ask_once(self._model_of(ctx), info.model_id, [
                    {"role": "system", "content": SUMMARISE},
                    # Said again over the older part, which stands under it as data.
                    {"role": "user", "content": f"{SUMMARISE}\n\nThe earlier part:\n{part}"},
                ], max_tokens=min(window // 4, SUMMARY_MOST) if window else SUMMARY_MOST)
            except BaseException:
                self._cut(ctx)  # sent, and not heard out
                raise
            finally:
                self._summarising.discard(ctx.agent_id)
            # What it spent is the agent's: its totals, its role's limit (not its size).
            self._count_tokens(ctx, answer.input_tokens, answer.output_tokens, step=False)
            said = _answer(said).strip()
            if getattr(answer, "cut", False):
                said, why = "", "it was cut at its length limit"
        except ModelUnavailable as exc:
            said, why = "", str(exc)
        if not said:
            # shortcut: not asked again for this agent; upgrade if a model that failed
            # once is worth asking at a later step.
            self._summaries[ctx.agent_id] = replace(summary, failed=True)
            self._set_agent(ctx.cid, ctx.agent_id, summary_note=SUMMARY_FAILED.format(why=why))
            return _summarised(history, _Summary(failed=True))
        # The last exchange, counted among the history's answers as it is built from the
        # record: those before it are what the summary stands for.
        anchor = (summary.anchor if applied else 0) + sum(
            1 for m in history[:at] if m["role"] == "assistant")
        files = self._files_back(ctx, said, window)
        self._summaries[ctx.agent_id] = _Summary(anchor, said, files=files)
        with self._factory() as session:
            # (A summary no longer applied - its history cut down since - is not counted
            # again with the one that replaces it.)
            before = session.get_one(Agent, ctx.agent_id).summarised if applied else 0
        # (Why an earlier one could not be made no longer stands.)
        self._set_agent(ctx.cid, ctx.agent_id, summarised=before + len(older), summary=said,
                        summary_anchor=anchor, summary_note=None)
        self._propose_lasting(ctx, said)
        return _compacted(history, at, said, files)

    def _propose_lasting(self: "AgentRunner", ctx: Ctx, state: str) -> None:
        """What a working state calls lasting facts is put forward for the project's core,
        for the user to decide on (`memory.propose_lasting`) - never in a turn nobody
        watches, where there is nobody to ask."""
        facts = _sections(state).get("Lasting facts")
        if not facts or not self._watched(ctx.run_id):
            return
        with self._factory() as session:
            project_id = session.get_one(Conversation, ctx.cid).project_id
            if project_id is None:  # (a plain chat has no project's core to keep them in)
                return
            if not kept.propose_lasting(session, project_id, facts, agent_id=ctx.agent_id,
                                        run_id=ctx.run_id, conversation_id=ctx.cid):
                return
        self.bus.emit(ctx.cid, ctx.run_id, "memory.changed", {"project_id": project_id})
        announce_memory(self._factory, self.bus, project_id, but=ctx.cid)

    def _goes_on_from_summary(self: "AgentRunner", ctx: Ctx, window: int | None) -> None:
        """A later turn's lead goes on from the summary of the lead before it, as the user
        may have corrected it, with the files in it read again now; the count goes with it.
        Not for a sub-agent: its chain is cut down to fit (`topics.fit`), and the answers
        the summary stands for may no longer be there to count."""
        if (ctx.depth or not ctx.continues_id or ctx.agent_id in self._summaries
                or not _koloni_compacts(ctx.model)):
            return
        with self._factory() as session:
            earlier = session.get(Agent, ctx.continues_id)
            if earlier is None or not earlier.summary or earlier.summary_anchor is None:
                return
            said, anchor, count = earlier.summary, earlier.summary_anchor, earlier.summarised
        self._summaries[ctx.agent_id] = _Summary(
            anchor, said, files=self._files_back(ctx, said, window))
        self._set_agent(ctx.cid, ctx.agent_id, summarised=count, summary=said,
                        summary_anchor=anchor)

    def _idle_after(self: "AgentRunner", ctx: Ctx) -> asyncio.Event | None:
        """After a watched turn that completed, where its lead's last step sent COMPACT_AT
        of its window or more and the turn is within its project's token limit: its older
        part is to be summarised while the user reads, not before the next turn's first
        step. What it is made of is taken now, while the turn still holds it, built
        without handing anything over or putting anything on record (`quiet`); the work
        starts once the turn has let go of everything (the Event it returns, set then).
        shortcut: a lead's only - a sub-agent's summary would reach no later turn, which fits
        its chain instead (`_goes_on_from_summary`); hand that over first if sub-agents need it.
        A CLI's lead only where its next turn starts anew, sent the whole history (none kept to
        go on in: `Agent.compacts_itself`), measured by that history's size - what its CLI
        reports counts its own instructions, cache and steps. Against its role's window: a CLI
        names none of its own, so where the role sets none only Compact now compacts it."""
        if not _koloni_compacts(ctx.model):
            return None
        cli = getattr(ctx.model, "native", False) or getattr(ctx.model, "session", False)
        with self._factory() as session:
            lead = session.get_one(Agent, ctx.agent_id)
            if lead.compacts_itself:
                return None
            # (A CLI's lead has its role's window only in its ctx: no step put it on record.)
            sent, window = lead.input_tokens, lead.context_window or ctx.context_window
            # What KOLONİ asks a model for a turn counts in what the turn may spend.
            project = self._project(session, ctx.cid)
            limit = project.turn_token_limit if project else None
            spent = self._turn_spent(session, ctx.run_id)[0] if limit else 0
            threshold = compact_at(session) / 100
        history = self._history(ctx, None, quiet=True) if cli and window else None
        if history is not None:
            sent = sum(_size(m) for m in history) // CHARS_PER_TOKEN
        if not window or not sent or sent < window * threshold or (limit and spent > limit):
            return None
        ready = asyncio.Event()
        self._idle[ctx.agent_id] = asyncio.ensure_future(self._compact_idle(
            ctx, ready, history or self._history(ctx, None, quiet=True), window, sent,
            self._summaries.get(ctx.agent_id)))
        return ready

    async def _compact_idle(
        self: "AgentRunner", ctx: Ctx, ready: asyncio.Event, history: list[dict],
        window: int | None,
        sent: int | None, summary: "_Summary | None",
    ) -> Exception | None:
        """A lead's older part summarised after its turn (`_idle_after`, `compact_now`), in a
        place of its own on its provider: the lead is counted at work while it holds it.
        Whatever goes wrong is logged, and returned, and leaves the next turn to compact as
        before."""
        try:
            await ready.wait()
            self._ctxs[ctx.agent_id] = ctx
            self._slots[ctx.run_id] = asyncio.Semaphore(1)
            if summary is not None:
                self._summaries[ctx.agent_id] = summary
            async with self._working(ctx, shown=False):
                info = await self._model_of(ctx).info()
                await self._compact(ctx, info, history, window, sent, shown=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("agent %s: its earlier work was not summarised after its turn: %r",
                        ctx.agent_id, exc)
            return exc
        finally:
            self._idle.pop(ctx.agent_id, None)
            self._ctxs.pop(ctx.agent_id, None)
            self._summaries.pop(ctx.agent_id, None)
            self._slots.pop(ctx.run_id, None)

    def compacting(self: "AgentRunner", agent_id: str) -> bool:
        """Whether an agent's older part is being summarised right now: a lead's after its
        turn, or any agent's at a step."""
        return agent_id in self._idle or agent_id in self._summarising

    async def compact_now(self: "AgentRunner", agent_id: str) -> None:
        """The user's Compact now on a lead whose turn is over (the caller checks that): its
        older part summarised now, whatever its size, as after a turn (`_compact_idle`), on
        the model it ran on; a next turn's lead waits for it and goes on from it. What came
        of it is on the agent's record (`summarised`, `summary_note`); ModelUnavailable where
        it could not be asked at all, or a next turn waited too long for it.
        shortcut: its model is found by the provider's name and the model it reported, as
        its record has them; a provider renamed since is not found (OwnStop)."""
        with self._factory() as session:
            agent = session.get_one(Agent, agent_id)
            run = session.get_one(Run, agent.run_id)
            if run.id in self._slots:
                # Its turn still holds its places (its notes, what it found): what a summary
                # after a turn waits for too (`_idle_after`).
                raise OwnStop("its turn is still being closed: try again in a moment")
            ctx = self._ctx_after(session, agent, run)
            summary = (_Summary(agent.summary_anchor, agent.summary)
                       if agent.summary and agent.summary_anchor is not None else None)
        # Its history as the next turn's lead would be sent it: with its summary applied.
        if summary is not None:
            self._summaries[agent_id] = summary
        try:
            history = self._history(ctx, None, quiet=True)
        finally:
            self._summaries.pop(agent_id, None)
        ready = asyncio.Event()
        ready.set()
        work = self._idle[agent_id] = asyncio.ensure_future(self._compact_idle(
            ctx, ready, history, ctx.context_window, None, summary))
        await asyncio.wait({work})  # (cancelled by a next turn that waited too long: no error)
        failed = None if work.cancelled() else work.result()
        if work.cancelled() or failed is not None:
            raise ModelUnavailable("a next turn did not wait for it" if failed is None
                                   else str(failed) or repr(failed))

    def _ctx_after(self: "AgentRunner", session, agent: Agent, run: Run) -> Ctx:
        """A lead whose turn is over, as it ran, for what is done of it after (`compact_now`,
        `note_chosen`); OwnStop where the provider it ran on is no longer set up."""
        project = self._project(session, run.conversation_id)
        provider = session.scalar(
            select(Provider).where(Provider.name == agent.provider_name).limit(1))
        if provider is None:
            raise OwnStop("the provider it ran on is no longer set up")
        # (Asked for auto, it asks for auto again: not the model Copilot's auto picked, `_ran_on`.)
        model_name = "auto" if agent.model_from == "auto" else agent.model_id
        return Ctx(
            run.id, run.conversation_id, project.root_path if project else None, agent.id,
            agent.role_name,
            tuple(agent.tools), agent.depth, model=self.providers.client(
                provider, model_name), provider=provider.name, name=agent.name,
            provider_id=provider.id, model_name=model_name,
            continues_id=agent.continues_id, mcp=tuple(agent.mcp),
            context_window=agent.context_window,
        )

    def note_chosen(self: "AgentRunner", run_id: str) -> None:
        """What the chosen side of a comparison found is noted now (`_note_what_it_found`),
        as after any turn that completed - not at its end, where the other side would read
        it. Nothing waits for it: it starts once the side's turn, and a summary of its lead
        being made (`compact_now`), are over - their places are their own.
        shortcut: a side whose files clash is noted before the user takes them in, so its
        notes name none of them; note it again at that card's Apply if that is missed."""
        async def note() -> None:
            try:
                await self.wait(run_id)
                with self._factory() as session:
                    run = session.get_one(Run, run_id)
                    lead = session.scalar(select(Agent).where(
                        Agent.run_id == run_id, Agent.depth == 0).limit(1))
                    if run.status != "completed" or lead is None:
                        return
                    ctx = self._ctx_after(session, lead, run)
                if (busy := self._idle.get(ctx.agent_id)) is not None:
                    await asyncio.wait({busy})
                self._ctxs[ctx.agent_id], self._slots[run_id] = ctx, asyncio.Semaphore(1)
                try:
                    await self._note_what_it_found(ctx)
                finally:
                    self._ctxs.pop(ctx.agent_id, None)
                    self._slots.pop(run_id, None)
            except Exception as exc:  # (OwnStop: its provider is gone)
                log.warning("run %s: the chosen side's findings were not noted: %r", run_id, exc)

        self._noting.add(task := asyncio.ensure_future(note()))
        task.add_done_callback(self._noting.discard)

    async def _after_idle(self: "AgentRunner", ctx: Ctx) -> None:
        """A turn's lead waits for the summary of the lead it goes on from while that is
        still being made after its turn (`_compact_idle`) - half made, on a server with one
        place, it would be lost, and this lead would wait for that place anyway - for at
        most IDLE_WAIT; then it is cancelled, and this turn compacts as before."""
        idle = self._idle.get(ctx.continues_id or "") if ctx.depth == 0 else None
        if idle is not None and not (await asyncio.wait({idle}, timeout=IDLE_WAIT))[0]:
            idle.cancel()

    async def correct_summary(self: "AgentRunner", cid: str, agent_id: str, state: str) -> None:
        """The user's words for an agent's working state, in the place of its summary: what
        it is sent from its next step on, and what a later turn's lead goes on from. Refused
        by the caller while a summary is being made (`compacting`): it would write over it."""
        live = self._summaries.get(agent_id)
        if live is not None and live.text:
            self._summaries[agent_id] = replace(live, text=state)
        self._set_agent(cid, agent_id, summary=state)

    def _files_back(self: "AgentRunner", ctx: Ctx, state: str, window: int | None) -> str:
        """The files a working state says were changed, as they are now in the place the
        agent works (its working copy, where it has one) - only those an agent of this
        conversation is on record as having changed: the model's word alone opens no file.
        The latest changed first, FILES_BACK of them, those that fit an eighth of the
        window whole; "" for none."""
        named = {
            note.split()[0].strip("`'\"").replace("\\", "/")
            for note in _sections(state).get("Files changed", ()) if note.split()
        }
        if not named or ctx.root is None:  # (a plain chat changed no file)
            return ""
        with self._factory() as session:
            changed = session.scalars(
                select(FileChange.path).join(Run, FileChange.run_id == Run.id)
                # (In effect where the agent works: not one proposed, rejected or undone.)
                .where(Run.conversation_id == ctx.cid,
                       FileChange.status.in_(("applied", "in_copy")))
                .order_by(FileChange.created_at.desc())
            ).all()
        paths = [path for path in dict.fromkeys(changed) if path in named][:FILES_BACK]
        room = (window * CHARS_PER_TOKEN if window else self.settings.context_char_budget) // 8
        ws, said = self._ws(ctx), ""
        for path in paths:
            try:
                if ws.resolve(path).stat().st_size > room:
                    said += FILE_TOO_LARGE.format(path=path)
                    continue
                content = ws.read_text(path)
            except (OSError, WorkspaceError):
                continue  # gone since, or not text: nothing to put back
            if len(content) > room:
                said += FILE_TOO_LARGE.format(path=path)
                continue
            room -= len(content)
            said += f"\n\n{path}:\n```\n{content}\n```"
        return FILES_NOW + said if said else ""

    def _history(self: "AgentRunner", ctx: Ctx, offered: list[dict] | None, quiet: bool = False,  # noqa: C901
                 skills: bool = True) -> list[dict]:
        """What this agent has seen, as chat-completions messages trimmed to the budget.

        The lead agent sees the whole conversation between the user and lead agents; a
        sub-agent sees only its own work. `offered` are the tool schemas that go out
        with this request (none for a model that takes no tools): the memory and the
        list of providers are spoken of only to an agent that has the tool for them.
        `quiet`: no step follows (`_compact_idle`): nothing is handed to it or put on record.
        `skills`: False - its skills are not in its instructions here (native Claude Code's
        go with `run_native`, which knows how it gives them).
        """
        has = {schema["function"]["name"] for schema in offered or ()}
        # An answer that thought goes back as it came, to the client that takes it back - to no
        # other: another model's server, a CLI's prompt would be sent its signatures.
        replays = getattr(ctx.model, "replays_blocks", False)
        # A step is about to be taken: the notes left for this agent are its to read now
        # (not in the middle of a discussion: they wait for its own work).
        if not ctx.discussion and not quiet:
            self._deliver(ctx)
        # And what it was given from memory when it started is looked at again.
        if not quiet:
            self._no_longer_given(ctx)
        briefing, given = self._briefing(ctx, "recall" in has)
        speech = set(ctx.speech_ids or ())
        # For a lead: whose conversation it takes over, when its earlier turns were
        # another's. Made at its first step of the turn and said the same at every later one.
        # (Not where no step follows: nothing is kept for a step that never comes.)
        first = ctx.depth == 0 and ctx.agent_id not in self._handed and not quiet
        taken_from: str | None = None
        cid = ctx.cid
        with self._factory() as session:
            # Slice 61: what is switched off on the Tools page is not spoken of either.
            off = tools_off(session)
            # The lead sees its own topic: the turns that go on with the same work, and
            # of the conversation's other topics nothing but their names.
            turn = session.get(Run, ctx.run_id)
            topic_id = turn.topic_id if turn else None
            in_topic = Run.topic_id == topic_id if topic_id else Run.topic_id.is_(None)
            # An agent that goes on from an earlier one starts with what that one did
            # and said, and the ones before it: the chain, oldest first.
            links = (
                topics.chain(session, ctx.agent_id)
                if ctx.depth > 0 and ctx.continues_id else []
            )
            if len(links) < 2:
                links = []
            mine = (
                ((Message.agent_id.is_(None)) | (Agent.parent_agent_id.is_(None))) & in_topic
                if ctx.depth == 0
                else Message.agent_id.in_([link.id for link, _turn in links]) if links
                else (Message.agent_id == ctx.agent_id)
            )
            others = (
                topics.titles_line(topics.earlier_titles(session, turn), quoted)
                if ctx.depth == 0 and turn else ""
            )
            system, write_in = self._history_system(session, ctx, has, turn)
            # Who sent what to whom, for the messages agents sent each other.
            family = {
                agent.id: (agent.name, agent.parent_agent_id)
                for agent in session.scalars(
                    select(Agent).join(Run, Run.id == Agent.run_id)
                    .where(Run.conversation_id == cid)
                )
            }
            if ctx.depth == 0:
                system = self._history_lead(session, ctx, system, others)
                messages: list[dict] = [{"role": "system", "content": system}]
                if first:
                    taken_from = _led_before(session, ctx)
            else:
                messages = self._history_sub(session, ctx, has, system, off, links)
            self._history_told(ctx, has, messages, briefing, write_in, skills)
            # The triggers that started turns of this conversation, by the turn.
            started_by = dict(session.execute(
                select(Run.id, Run.trigger_name)
                .where(Run.conversation_id == cid, Run.unattended)
            ).all())
            # For the lead: what it was given of each room of the conversation that is
            # over, by the turn - it stands after that turn's message, which was its goal.
            told_of_rooms = dict(session.execute(
                select(Room.run_id, Room.told).join(Run, Run.id == Room.run_id)
                .where(Run.conversation_id == cid, Room.told.is_not(None))
            ).all()) if ctx.depth == 0 else {}
            rows = session.scalars(
                select(Message)
                .join(Run, Run.id == Message.run_id)
                .outerjoin(Agent, Agent.id == Message.agent_id)
                # Only turns that actually started: a message still queued, or removed
                # from the queue, was never given to the agent.
                .where(Message.conversation_id == cid, Run.started_at.is_not(None))
                .where(Message.status == "complete")
                .where(mine, topics.in_history(ctx.run_id))
                # What it said in a discussion is in the shared place, not here - but
                # the speech it is making right now is.
                .where(Message.discussion_id.is_(None) | Message.id.in_(speech))
                # Turn by turn: a message queued during an earlier turn is older than
                # that turn's later replies, but belongs after them.
                .order_by(
                    Run.created_at,
                    literal_column("runs.rowid"),
                    Message.created_at,
                    literal_column("messages.rowid"),
                )
            ).all()
            # B-145 (live): a Coder asked whether to fix old failures, the user said "Leave them,
            # I'm done" - and the next turn's Lead handed it just those. The user's answers to the
            # agents below it are the Lead's to hear, as the user's own, where they were given.
            # K-vekil-karar: what it answered for the user while they were away, as its own - also
            # KOLONİ's cards (its own question's answer is in its tool's result).
            answered = session.execute(
                select(Question.question, Question.answer, Question.answered_at, Question.run_id,
                       Agent.name, Question.lead_why, Question.leave).join(
                    Agent, Agent.id == Question.agent_id).where(
                    Question.run_id.in_({row.run_id for row in rows}),
                    Question.status == "answered", or_(
                        and_(Question.lead_why.is_(None), Agent.depth > 0, ~Question.leave),
                        and_(Question.lead_why.is_not(None),
                             or_(Agent.depth > 0, Question.leave))))).all() if (
                ctx.depth == 0) else []
            read_how, told_files, seen = self._history_files(session, ctx, off, rows, messages)
            carried = self._history_carried(session, ctx, family)
            calls: dict[str, list[ToolCall]] = {}
            for call in session.scalars(
                select(ToolCall)
                .join(Run, Run.id == ToolCall.run_id)
                .where(Run.conversation_id == cid)
                .order_by(ToolCall.seq)
            ):
                calls.setdefault(call.message_id, []).append(call)
            # A note from an agent that is not of this conversation: of another one of
            # the project (what KOLONİ said of a file both work on).
            far = {
                row.from_agent_id: session.scalar(
                    select(Agent.name).where(Agent.id == row.from_agent_id))
                for row in rows
                if row.role == "agent" and row.from_agent_id
                and row.from_agent_id not in family
            }
            notes_of = {post.id: post for post in session.scalars(select(BoardPost).where(
                BoardPost.id.in_([row.board_post_id for row in rows if row.board_post_id])))}
            records = self._history_records(session, ctx, rows, links)
        h = _Said(ctx, has, replays, links, family, messages, off, read_how, told_files,
                  told_of_rooms, far, notes_of)
        nudged = self._history_nudged(ctx, answered, rows)
        turn_before = self._history_walk(h, rows, calls, records, nudged, started_by, speech,
                                         carried)
        self._history_walk_end(h, records, nudged, turn_before)
        self._history_now(h, quiet)
        if first:
            self._handed[ctx.agent_id] = (
                "\n\n" + TAKEN_OVER.format(before=taken_from) if taken_from else "")
        messages[0]["content"] += self._handed.get(ctx.agent_id, "")
        if ctx.agent_id in self._summaries:
            # What it was summarised to stands for the older part, before the budget is.
            messages = _summarised(messages, self._summaries[ctx.agent_id])
        left_out = _trim_to_budget(messages, self.settings.context_char_budget, h.results)
        if first and taken_from and left_out:
            # Said in the same place, to the model that was not there when they came -
            # counted now, when every result in the history is an earlier turn's: what
            # is cut of its own work later in the turn is no part of the handing over.
            more = LEFT_OUT.format(count=left_out, s=" is" if left_out == 1 else "s are")
            self._handed[ctx.agent_id] += more
            messages[0]["content"] += more
        if given is not None and not quiet:
            # Only now: a request that could not be built gave the agent nothing.
            self._briefed_with(ctx, briefing, given)
        if skills and not quiet and "use_skill" not in has:
            self._given_in_brief(ctx)  # (R190: its skills whole in its instructions)
        if not quiet:
            self._showing[ctx.agent_id] = seen  # (on the cards once the request is made)
        return messages

    def _history_system(self: "AgentRunner", session: Session, ctx: Ctx, has: set[str],
                        turn: Run | None) -> tuple[str, str]:
        """`_history`'s instructions as every agent has them, and its "Answer in" line."""
        cid, root = ctx.cid, ctx.root
        project = session.scalar(
            select(Project)
            .join(Conversation, Conversation.project_id == Project.id)
            .where(Conversation.id == cid)
        )
        where = shell_note(project.exec_location, project.docker_image) if project else ""
        reads = PLAIN_READS_PROMPT if "read_file" in has else ""
        # Where it works right now, said again at each step: its copy's folder from the
        # step after the copy is made - the project's path would lead into the project.
        # (That breaks the prompt cache's prefix once per sub-agent, at that step: taken.)
        copy = self._copy_of(ctx)
        here = copy.root if copy is not None else root
        system = (PLAIN_PROMPT.format(reads=reads) if root is None
                  else SYSTEM_PROMPT.format(root=here, where=where))
        system = self._history_folders(session, ctx, project, system)
        # K-cevap-dili: "Answer in", the same for every agent (added after its briefing).
        write_in = kept.write_in(session, KEPT_ENGLISH)
        if ctx.depth == 0:
            if not write_in:
                system += "\n\n" + LANGUAGE_PROMPT
            # (Not in a discussion, nor answering a sub-agent: only its answer is said.)
            if turn is not None and turn.spoken and not ctx.in_turn:
                # (K-cevap-dili: in "Answer in" where set - one language for all it writes.)
                system += "\n\n" + SAY_PROMPT.format(
                    language=kept.answer_in(session) or turn.spoken["language"])
                if turn.spoken.get("style"):
                    system += " " + SAY_STYLE.format(style=quoted(turn.spoken["style"]))
        if "ask_user" in ctx.tools and self._watched(ctx.run_id):
            system += "\n\n" + ASK_PROMPT
        if "plan_away" in has:
            system += "\n\n" + AWAY_PROMPT
        if "message_agent" in ctx.tools:
            system += "\n\n" + MESSAGE_PROMPT
        if "spawn_agent" in has:
            system = self._history_team(session, ctx, turn, system)
        if any("__" in name for name in has):  # (none of KOLONİ's own tools is named so)
            system += "\n\n" + MCP_PROMPT.format(root=here)
        if (seen := self._git_of(ctx)) is not None:
            system += "\n\n" + git_prompt(
                seen["branch"], copy is not None, self._reports_git(ctx))
            # A CLI told of git: one of the turn's, named for what git shows at its end.
            self._git_clis.setdefault(ctx.run_id, {})[ctx.agent_id] = ctx.provider or "A CLI"
        return system, write_in

    def _history_folders(self: "AgentRunner", session: Session, ctx: Ctx,
                         project: Project | None, system: str) -> str:
        """`system` with the conversation's other folders said."""
        conversation = session.get_one(Conversation, ctx.cid)
        also = folders_of(project, conversation, "write")
        read = [f for f in folders_of(project, conversation, "read") if f not in also]
        # A CLI with tools of its own is given no folder that holds a place never opened.
        held = [f for f in [*also, *read] if never(Path(f))] if getattr(
            ctx.model, "native", False) else []
        also, read = [f for f in also if f not in held], [f for f in read if f not in held]
        if also:
            system += "\n\n" + ALSO_PROMPT.format(folders=", ".join(also))
        if held:
            system += "\n\n" + HELD_NOT_GIVEN.format(folders=", ".join(held))
        if read:
            # (Not given to a CLI that changes files unasked: `_native_work`.)
            said = READ_NOT_GIVEN if _unasked(ctx.model) else READ_PROMPT
            system += "\n\n" + said.format(folders=", ".join(read))
        return system

    def _history_team(self: "AgentRunner", session: Session, ctx: Ctx, turn: Run | None,
                      system: str) -> str:
        """`system` with how an agent that opens others does it."""
        system += "\n\n".join(("", PROVIDERS_PROMPT, HAND_ON_PROMPT, BRIEF_PROMPT))
        if ctx.depth == 0:
            system += "\n\n" + REPORT_ONCE
        if guide(list_providers(session)):
            system += "\n\n" + TEAM_PROMPT
        if ctx.depth == 0 and turn is not None and turn.started_at is not None:
            # As it stood when the turn began, made once: the same at every step.
            measured = self._measured.get(ctx.run_id)
            if measured is None:
                measured = self._measured[ctx.run_id] = record.as_it_began(
                    session, turn.started_at)
            if measured:
                system += "\n\n" + measured
        return system

    def _history_lead(self: "AgentRunner", session: Session, ctx: Ctx, system: str,
                      others: str) -> str:
        """`system` with what only a lead is told."""
        cid = ctx.cid
        if ctx.instructions:
            system += (f"\n\nYou are the {self._titled(session, cid, ctx.role, 'agent')}. "
                       f"{ctx.instructions}")
        if kept_work := self._kept_recipes(session, ctx):
            system += "\n\n" + kept_work
        work = self._lead_work(ctx)
        if work == "delegates":
            system += "\n\n" + HANDS_CODE_PROMPT
        elif work == "decides":
            system += "\n\n" + DECIDES_PROMPT
        if others:
            system += "\n\n" + others
        if told := self._map_told(ctx):
            system += "\n\n" + told
        return system

    def _history_sub(self: "AgentRunner", session: Session, ctx: Ctx, has: set[str], system: str,
                     off: frozenset[str], links: list[tuple[Agent, int]]) -> list[dict]:
        """A sub-agent's first messages: `system` with what only it is told, and its task."""
        cid = ctx.cid
        # A sub-agent starts clean: its role, where its task comes from, the task.
        system += (
            f"\n\nYou are the {self._titled(session, cid, ctx.role, 'sub-agent')}. "
            f"{ctx.instructions}".rstrip()
            + "\n"
            + SUB_AGENT_PROMPT.format(
                name=ctx.name, parent=self._title(session, cid, ctx.parent_role or ""))
            # K-devir-1: at its task only, whose report is read for what it left.
            + (" " + handoff.REPORT_PROMPT
               if not ctx.in_turn and not ctx.discussion else "")
            + (" " + NOTE_PROMPT if "post_note" in ctx.tools else "")
            + (" " + ASK_NOT_REPORT if "ask_user" in ctx.tools
               and self._watched(ctx.run_id) else "")
        )
        # Only at its task, whose report is read: not in a turn on a message or a speech.
        kind_of = find_role(session, ctx.role)
        here = session.get_one(Conversation, ctx.cid).project_id
        if (known := knows.known_here(session, kind_of, here)) is not None:
            # K-uzman: its guide as it is now - learned again a step ago, it is this one.
            known = known if "web_search" not in off else {
                **known, "search_answering": False}
            system += "\n\n" + knowledge.brief(
                ctx.root, known, LEARN in ctx.tools, ctx.tools)
        if mapped := knows.map_of(session, kind_of, here, ctx.root, LOOKUP in has):
            system += "\n\n" + mapped
        if about := self._about.get(ctx.agent_id):
            system += "\n\n" + about
        if self._tells_findings(session, ctx):
            schema = _hands_back(ctx)  # (89p: in REPORT_SCHEMA, not in words)
            system += " " + (SCHEMA_FINDINGS_PROMPT if schema else FINDINGS_PROMPT).format(
                roles=", ".join(self._open_roles(session, ctx))) + (
                " " + (SCHEMA_CHECKED_PROMPT if schema else CHECKED_PROMPT)
                if ctx.agent_id in self._reviews else "") + (
                " " + FIX_AFTER_PROMPT if ctx.agent_id in self._before_fix else "")
        room = self._rooms.get(ctx.run_id)
        if room is not None and ctx.agent_id in room.members and not ctx.answering:
            # A member of a room is told how a room works, once: where its own
            # stands is said before each of its steps (below).
            system += "\n\n" + rooms.PROMPT.format(others=", ".join(
                other.ctx.name for other in room.members.values()
                if other.ctx.agent_id != ctx.agent_id)) + (
                " " + rooms.BETWEEN.format(teams=", ".join(room.between))
                if room.between else "") + (
                " " + rooms.FOLLOWS.format(opener=room.lead.name)
                if room.reads else "")
        if links:
            # Unless it goes on from an earlier agent: then its history begins
            # with that one's task, put there link by link further down.
            system += "\n\n" + topics.CONTINUES.format(
                turns=topics.turns_in_words([number for _link, number in links[:-1]]))
        messages = [{"role": "system", "content": system}]
        if not links:
            messages.append({"role": "user", "content": ctx.task or ""})
        return messages

    def _history_told(self: "AgentRunner", ctx: Ctx, has: set[str], messages: list[dict],
                      briefing: str, write_in: str, skills: bool) -> None:
        """What every agent's instructions end with."""
        if briefing:
            # The user's rules and the core of the project's memory, as they stood
            # when this agent started. With neither, nothing is added.
            messages[0]["content"] += "\n\n" + briefing
        if write_in:
            messages[0]["content"] += "\n\n" + write_in
        if skills:
            messages[0]["content"] += self._skills_told(ctx, "use_skill" in has)
        if not self._watched(ctx.run_id):
            # Every agent of an unattended turn is told how it runs, and what the
            # trigger allows as things stand at this step.
            messages[0]["content"] += "\n\n" + UNATTENDED_PROMPT.format(
                leave=self._leave_in_words(ctx.run_id))

    def _history_files(self: "AgentRunner", session: Session, ctx: Ctx, off: frozenset[str],
                       rows: Sequence[Message], messages: list[dict],
                       ) -> tuple[str, dict[str | None, tuple[str, list[dict]]], dict[str, str]]:
        """How to read an attached file; what the lead is told of files, by the message they
        came with; and those shown - a sub-agent's said in `messages` now."""
        # The files the user attached (slice 85b): the Lead is told of each with the
        # message it came with; a sub-agent of those handed to it, after its task.
        files = self._files_of(session, ctx)
        read_how = "" if "read_attachment" in off else attachments.READ_HOW
        told_files: dict[str | None, tuple[str, list[dict]]] = {}
        seen: dict[str, str] = {}  # (put on record below: `_shown`)
        if ctx.depth == 0:
            turn_of = {row.id: row.run_id for row in rows}
            for sent_with in dict.fromkeys(one.message_id for one in files):
                if sent_with in turn_of:
                    told, parts, of = self._told_files(
                        session, ctx, [one for one in files if one.message_id == sent_with],
                        now=turn_of[sent_with] == ctx.run_id, off=off)
                    told_files[sent_with], seen = (told, parts), seen | of
        elif files:
            told, parts, seen = self._told_files(session, ctx, files, now=True, off=off)
            messages.append({
                "role": "user", "content": attachments.LISTED.format(
                    to=" and that were handed to you", read=read_how) + "\n" + told,
                **({"files": parts} if parts else {})})
        return read_how, told_files, seen

    def _history_carried(self: "AgentRunner", session: Session, ctx: Ctx,
                         family: dict[str, tuple[str, str | None]]) -> str | None:
        """For the lead: of the notebook of the turn before this one, one short block (G7)."""
        cid = ctx.cid
        carried = None
        if ctx.depth == 0:
            try:
                before = self._notes_before(session, ctx)
                carried = board.pushed(before, {
                    agent_id: name for agent_id, (name, _parent) in family.items()
                }, self._still_waiting(
                    session, cid, before[0].run_id if before else None, but=ctx.run_id))
            except Exception as exc:  # (it fails no turn: the Lead goes without it)
                log.warning("agent %s: no block of the turn before: %r", ctx.agent_id, exc)
        return carried

    def _history_records(self: "AgentRunner", session: Session, ctx: Ctx, rows: Sequence[Message],
                         links: list[tuple[Agent, int]]) -> dict[str, str | None]:
        """K-gecmis-zengin: what each earlier turn of its history did, said after it - for a
        lead the whole turn's, for any other agent its own (its chain's) work there."""
        whose = None if ctx.depth == 0 else frozenset(
            [link.id for link, _turn in links] if links else [ctx.agent_id])
        over = session.scalars(select(Run.id).where(
            Run.id.in_({row.run_id for row in rows} - {ctx.run_id}),
            Run.ended_at.is_not(None))).all()
        records = {}
        for run_id in over:
            if (run_id, whose) not in self._ledgers:
                self._ledgers[run_id, whose] = ledger.of_turn(session, run_id, whose)
                if len(self._ledgers) > LEDGERS_KEPT:  # (the oldest made goes)
                    del self._ledgers[next(iter(self._ledgers))]
            records[run_id] = self._ledgers.get((run_id, whose))
        return records

    def _history_take_up(self: "AgentRunner", h: _Said, agent_id: str | None) -> None:
        """Begin the part of every link not begun yet, up to this agent's: with what
        the link was asked. The first was given a task; each later one a message
        from the agent it works for, and reads it as one."""
        ctx, messages, links, begins, family = h.ctx, h.messages, h.links, h.begins, h.family
        while len(begins) < len(links) and agent_id not in [
            link.id for link, _turn in links[: len(begins)]
        ]:
            link, _turn = links[len(begins)]
            begins.append(len(messages))
            asked = link.task or ""
            if len(begins) > 1:
                above = family.get(link.parent_agent_id or "", ("the agent above", None))[0]
                asked = f"Message from {above} ({FROM['above']}):\n\n{asked}"
            messages.append({"role": "user", "content": asked})
            if link.id != ctx.agent_id and link.facts_given:
                # What the memory gave it then is not what the memory holds now.
                messages.append({
                    "role": "user", "content": topics.given_then(len(link.facts_given)),
                })

    def _history_nudged(self: "AgentRunner", ctx: Ctx, answered: Sequence[Row],
                        rows: Sequence[Message]) -> dict[str | None, list[str]]:
        """What is said after each message (its id; None: at the end)."""
        # What KOLONİ told it after an answer that was no end (B-83, B-90), where it was told.
        nudged: dict[str | None, list[str]] = {}
        for at, words in self._nudges.get(ctx.agent_id, ()):
            nudged.setdefault(at, []).append(words)
        for question, answer, when, run_id, name, why, leave in answered:
            at = next((row.id for row in reversed(rows) if row.run_id == run_id and (
                when is None or row.created_at <= when)), None)
            nudged.setdefault(at, []).append(LEAD_DECIDED.format(
                name="KOLONİ" if leave else name, question=quoted(question[:300]),
                answer=quoted(answer[:300]), why=quoted(why)) if why else SUB_ANSWERED.format(
                name=name, question=quoted(question[:300]), answer=answer[:300]))
        return nudged

    def _history_walk(self: "AgentRunner", h: _Said, rows: Sequence[Message],
                      calls: dict[str, list[ToolCall]], records: dict[str, str | None],
                      nudged: dict[str | None, list[str]], started_by: dict[str, str | None],
                      speech: set[str], carried: str | None) -> str | None:
        """`_history`'s messages, row by row. The turn of the last row."""
        ctx, messages = h.ctx, h.messages
        before = ""  # (no message's id)
        turn_before: str | None = None
        for row in rows:
            messages.extend({"role": "user", "content": words} for words in nudged.pop(before, ()))
            if turn_before not in (None, row.run_id) and (said := records.get(turn_before)):
                messages.append(_Record(role="user", content=said))
            before, turn_before = row.id, row.run_id
            made = calls.get(row.id, [])
            self._history_take_up(h, row.agent_id)
            if row.id in speech and not h.prompted:
                messages.append({"role": "user", "content": self._shared_place(ctx)})
                h.prompted = True
            if carried and row.run_id == ctx.run_id:
                messages.append({"role": "user", "content": carried})
                carried = None
            if row.role == "memory":
                # That a fact it was given no longer stands: said to this agent, in this
                # turn. A later turn is given what stands then.
                if row.run_id == ctx.run_id and row.agent_id == ctx.agent_id:
                    messages.append({"role": "user", "content": row.content})
                continue
            if row.role == "agent":
                self._history_agent_row(h, row)
                continue
            if row.role in ("away", "git", "koloni", "landed"):
                continue  # (KOLONİ's line in the chat - a night's end, git: the user's to read)
            if row.role == "trigger":
                # What started an unattended turn: the trigger's message, said to be one.
                head = STARTED_BY.format(trigger=quoted(started_by.get(row.run_id) or ""))
                messages.append({"role": "user", "content": f"{head}\n\n{row.content}"})
                continue
            if row.role == "user" or not made:
                self._history_user_row(h, row)
                continue
            self._history_calls_row(h, row, made)
        return turn_before

    def _history_agent_row(self: "AgentRunner", h: _Said, row: Message) -> None:
        """A message an agent (or KOLONİ) sent this one, as it reads it."""
        ctx, messages, family = h.ctx, h.messages, h.family
        if row.delivered_at is None:
            return  # a note it never read, in a turn that is over
        if row.room_post_id:
            # A post of its room, as KOLONİ handed it over then: said so in it.
            messages.append({"role": "user", "content": row.content})
            return
        if row.board_post_id and row.run_id != ctx.run_id:
            return  # an earlier turn's notebook: the block before the next turn has it
        if row.board_post_id:
            # From the notebook: information from another agent of the turn, or
            # from the user - never a task, whoever opened whom.
            writer = row.from_agent_id
            post = h.notes_of[row.board_post_id]
            messages.append({"role": "user", "content": board.handed(
                board.labelled(family.get(writer, ("another agent", None))[0], post)
                if writer else None, self._note_from(ctx, writer, post), row.content,
                post.koloni,
            )})
            return
        if row.from_agent_id is None:
            messages.append({"role": "user", "content": row.content})  # (KOLONİ's word)
            return
        sender = row.from_agent_id
        relation = (
            "below" if _is_above(family, row.agent_id, sender)
            else "above" if _is_above(family, sender, row.agent_id)
            else "other"
        )
        name = family.get(sender or "", ("another agent", None))[0]
        if sender in h.far:
            relation, name = "elsewhere", h.far[sender] or name
        messages.append({
            "role": "user",
            "content": self._from(ctx, row.id, sender, name, relation, row.content),
        })

    def _history_user_row(self: "AgentRunner", h: _Said, row: Message) -> None:
        """The user's message, or an agent's that made no call."""
        ctx, messages = h.ctx, h.messages
        if row.role == "user" and row.id in h.told_files:
            told, parts = h.told_files[row.id]
            now = row.run_id == ctx.run_id
            said = "\n".join(filter(None, [
                attachments.LISTED.format(to=" to this message", read=h.read_how), told,
                attachments.LINKS if "http_request" not in h.off and re.search(
                    r"https?://", row.content) else "",
                attachments.ONE_LINE if now else ""]))
            messages.append({"role": "user", "content": (
                f"{row.content}\n\n{said}" if row.content else said),
                **({"files": parts} if parts else {})})
        elif row.content:
            messages.append({"role": row.role, "content": row.content, **(
                {"blocks": row.blocks} if h.replays and row.blocks else {})})
        if (row.role == "user" and row.run_id == ctx.run_id and "plan_away" in h.has
                and AWAY_CUES.search(row.content)):
            # (Under its words, as what KOLONİ says of its files is: it stays the last.)
            messages[-1] = {**messages[-1],
                            "content": f"{messages[-1]['content']}\n\n{AWAY_NOTE}"}
        if row.role == "user" and row.run_id in h.told_of_rooms:
            messages.append({"role": "user", "content": h.told_of_rooms[row.run_id]})

    def _history_calls_row(self: "AgentRunner", h: _Said, row: Message,
                           made: list[ToolCall]) -> None:
        """An agent's message with its calls, and their results."""
        ctx, messages, has, root = h.ctx, h.messages, h.has, h.ctx.root
        messages.append({
            "role": "assistant",
            "content": row.content,
            "tool_calls": [
                {
                    "id": call.provider_call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": _valid_json(call.arguments)},
                }
                for call in made
            ],
            **({"blocks": row.blocks} if h.replays and row.blocks else {}),
        })
        for call in made:
            messages.append({
                "role": "tool",
                "tool_call_id": call.provider_call_id,
                # An agent answering a message still has a call out: its own
                # sub-agent, or the message it is waiting on a reply to.
                "content": (
                    # What the memory held in an earlier turn is not what it holds now.
                    kept.looked_up_earlier(call.result, "recall" in has)
                    if call.name == "recall" and call.status == "succeeded"
                    and call.result and call.run_id != ctx.run_id
                    else call.result
                )
                or (STILL_RUNNING if call.status in ("pending", "running") else UNFINISHED),
            })
            # (Its id said only where recall_output would give it back.)
            h.results.append((messages[-1], call, "recall_output" in has and recallable(
                call.name, call.outside_folder, call.why_asked,
                ledger.argument(call.arguments, "command")
                if call.name == "run_command" else None)))
            # Slice 51: a screenshot of this turn goes to a model that takes images as a
            # picture after its call's result (`_shot`), the way an attached file does - and
            # so does the copy of an image view_image looked at (28e, `_view_image`).
            if (call.status == "succeeded" and call.run_id == ctx.run_id and root
                    and (found := _picture(call))):
                if h.takes_images is None:
                    with self._factory() as session:
                        h.takes_images = "image" in self._takes(session, ctx)[0]
                if h.takes_images:
                    shot = call.name == "browser_screenshot"
                    h.shots.append((len(messages), shot))
                    messages.append({
                        "role": "user", "content": "The screenshot:" if shot else "The image:",
                        "files": [{
                            "id": call.id, "name": PurePosixPath(found).name, "kind": "image",
                            "mime": IMAGE_MIME[found.rsplit(".", 1)[1]],
                            "path": str(Path(root) / found), "frames": []}]})

    def _history_walk_end(self: "AgentRunner", h: _Said, records: dict[str, str | None],
                          nudged: dict[str | None, list[str]], turn_before: str | None) -> None:
        """After `_history_walk`: older pictures put away, what is left said, and a chain
        too long for the budget cut down."""
        ctx, messages, links, begins = h.ctx, h.messages, h.links, h.begins
        # shortcut: every step sends the turn's pictures again (as with attached files), so
        # only the last two screenshots and images go as pictures; send more if a model is seen
        # to need an older one.
        for at, shot in h.shots[:-2]:
            messages[at] = {"role": "user", "content": "(An earlier screenshot, not shown again: "
                            "take a new one if you need to look.)" if shot else
                            "(An earlier image, not shown again: view it again if you need to.)"}
        if turn_before not in (None, ctx.run_id) and (said := records.get(turn_before)):
            messages.append(_Record(role="user", content=said))
        # (After its last message, or - one it never wrote - at the end.)
        messages.extend({"role": "user", "content": words}
                        for told in nudged.values() for words in told)
        self._history_take_up(h, None)
        if links:
            # A chain too long for the budget: its oldest links are cut down to their
            # task and report, off the record, before anything of the newest work is.
            budget = self.settings.context_char_budget
            share = topics.share_of(budget, len(links) - 1)
            earlier = [
                (messages[begins[at]:begins[at + 1]],
                 topics.reduced(number, link.task, link.report, share) + (
                     f"\n\n{records[link.run_id]}" if records.get(link.run_id) else ""))
                for at, (link, number) in enumerate(links[:-1])
            ]
            now_on = messages[begins[-1]:]
            rest = _size(messages[0]) + sum(_size(message) for message in now_on)
            messages[1:] = topics.fit(earlier, rest, budget, _size) + now_on

    def _history_now(self: "AgentRunner", h: _Said, quiet: bool) -> None:
        """What goes with this step only, at the end of `_history`'s messages."""
        ctx, messages = h.ctx, h.messages
        # What is said below goes with this step only (`Transient`): the next one does not
        # send it again, so a cache keeps what is before it.
        if ctx.discussion and not h.prompted:
            messages.append(Transient(role="user", content=self._shared_place(ctx)))
        # A member of a room is told how the room stands before each step of its own
        # work - as it is now, and so not kept in its conversation: nothing piles up.
        stands = "" if ctx.answering or ctx.discussion else self._room_now(ctx)
        if stands:
            messages.append(Transient(role="user", content=stands))
        near = "" if ctx.answering or ctx.discussion or quiet else "\n\n".join(
            filter(None, (self._near_a_limit(ctx), self._near_budget(ctx))))
        if near:
            messages.append(Transient(role="user", content=near))
        if not (ctx.answering or ctx.discussion or quiet) and ctx.agent_id in self._answer_again:
            # B-381: after what woke it, so that it is the last thing it reads.
            self._answer_again.discard(ctx.agent_id)
            messages.append(Transient(role="user", content=ANSWER_AGAIN))
        if ctx.discussion:
            pass  # the shared place says what a speaker may and may not do
        elif ctx.answering:
            messages[0]["content"] += "\n\n" + ANSWERING_PROMPT
        elif messages[-1]["role"] == "assistant" and not messages[-1].get("tool_calls"):
            # It answered a message while a call of its own was out, and that call has
            # returned since. A request that ends on its own words would be taken as a
            # reply to go on writing (or refused), so it is told where things stand.
            messages.append(Transient(role="user", content=CALL_RETURNED))
