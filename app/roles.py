"""Roles: what an agent is for and which tools it may use."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.db.models import Category, Flag, Role, RoleTeam, Team

# 28e: view_image reads a file too, so whoever reads files is given it.
READ = ("list_dir", "read_file", "search", "view_image")
WRITE = ("write_file", "edit_file")
# What alters files or runs commands.
CHANGES = (*WRITE, "run_command")
# What reaches outside this machine: a search and a request, which can be asked about, and
# a notification, which goes only where the user said (`app.web`).
WEB = ("web_search", "http_request")
# Slice 51: a headless browser of the agent's own, on this machine's previews alone; it runs
# unasked (it cannot reach out), so a role is given it or not (the Tools tab).
BROWSER = ("browser_open", "browser_screenshot", "browser_click", "browser_type", "browser_key",
           "browser_scroll", "browser_read", "browser_console")
# K-drawio: a draw.io diagram drawn as a picture beside it - a file written, unasked, as the
# user decided: given by role, to those who write documents, designs and code (not the
# Architect, told not to change files: the user may give it on the Tools tab).
DIAGRAM = ("diagram_image",)
# shortcut: `show` is offered to every agent at its own work whatever its role (slice 39), so
# a role's `show` only says what the role is for; make it a real grant when a role must be
# kept from showing files.
# add_skill only proposes: a skill is added on the user's card (slice 45); so does ask_folder
# a folder outside the project (slice 75). So do add_task and change_task: a task, or a
# change to one, waits on the user's card (slice 52); and propose_trigger a trigger (69).
# shortcut: the Lead holds every tool, so the backlog's four schemas (some 500 tokens) ride on
# each of its steps - it must have them to hand them on (`effective_tools`). Tell "may hand
# on" apart from "offered to itself" if small local models suffer for it.
ALL_TOOLS = (*READ, *WRITE, "show", *DIAGRAM, "run_command", *WEB, *BROWSER, "notify",
             "spawn_agent",
             "create_role", "add_skill", "ask_user", "ask_folder", "message_agent", "open_room",
             "discuss",
             "read_backlog", "add_task", "change_task", "assess_task", "propose_trigger",
             "post_note", "read_notes", "remember", "recall")
# Slice 61: KOLONİ's own tools the user may switch off on the Tools page - then no agent is
# offered one, whatever its role lists (`app.agent`, `_offered`). 28c's git and test tools
# join here.
# A CLI working natively loses its own of the same kind (`withheld` "search" / "fetch"): Claude
# Code's WebSearch / WebFetch, Codex's search; Copilot is given neither in any case.
# shortcut: agy's own web tools are not known by name - they are asked about as any tool of its
# KOLONİ does not know; and a CLI session is offered KOLONİ's once as it starts (one switched
# off later is refused when called). Name agy's when measured (K-cli-surface).
SWITCHABLE = ("web_search", "http_request", "read_attachment", "recall_output", *DIAGRAM)
# A Flag's name, before the tool's: there while the tool is off, so a missing row is on.
OFF = "tool_off:"


def tools_off(session: Session) -> frozenset[str]:
    """The tools switched off on the Tools page - of those it still switches: one that left
    `SWITCHABLE` is never kept off by a row left behind."""
    return frozenset(name.removeprefix(OFF) for name in session.scalars(
        select(Flag.name).where(Flag.name.startswith(OFF, autoescape=True)))) & frozenset(
        SWITCHABLE)


# The project's backlog: read it, and propose to it - nothing changes before the user's word.
BACKLOG = ("read_backlog", "add_task", "change_task", "assess_task")
# The shared notebook: a note changes nothing, so every role may write and read them.
NOTEBOOK = ("post_note", "read_notes")
# The project's memory: a note in its journal changes nothing in the project either.
MEMORY = ("remember", "recall")
LEAD = "Lead"
# K-uzman: an expert advises and reads only (`expert_tools`); `learn` is offered to it on top of its
# role's tools, as `show` is to every agent (`app.agent`), not one a role lists. What it may hold:
# reading, and talking with the team - no web of its own, no agent or role it opens.
LEARN = "learn"
# K-bilgi part 3: offered so too, to any role that uses a knowledge (`app.knows`) - it reads only
# that knowledge's pages. Not in `EXPERT_MAY`, as no role lists it.
LOOKUP = "lookup"
EXPERT_MAY = (*READ, "ask_user", "message_agent", "discuss", *NOTEBOOK, *MEMORY)
# Asked by KOLONİ itself, with no tools, about a sub-agent's report (slice 33b): never
# opened as an agent, so no agent is offered it.
OBSERVER = "Observer"
# K-kanit: a checking role's "verified" stands on a run of its own (migration 0131 for installs).
RAN = ("Say \"verified\" or \"works\" only of what you ran yourself in this turn, and list each "
       "test or command under \"ran:\" in your report; say \"not run\" of anything else.")


@dataclass(frozen=True)
class RoleSpec:
    description: str
    instructions: str
    tools: tuple[str, ...]
    # The group the Agents page draws it in (`Role.kind`). No tier: the Lead picks one for
    # each job (slice 79).
    kind: str


# The roles that are always there: no team holds them back, and they are never off (slice 62).
ALWAYS = frozenset({LEAD, "Planner", OBSERVER})
# KOLONİ's ready teams (slice 62), made once by migration 0065; a built-in role added later
# joins those of them that are still there.
READY_TEAMS = {
    "Web app": ("Coder", "UI designer", "Tester", "Reviewer", "Debugger", "Refactorer",
                # K-site-roller: no migration - `seed_builtin_roles` adds them on installs too.
                "SEO specialist", "Copywriter", "Accessibility reviewer"),
    "Backend / API": ("Coder", "Architect", "Database engineer", "Tester", "Reviewer",
                      "Security reviewer", "Performance engineer"),
    "Data": ("Data analyst", "Database engineer", "Researcher", "Reviewer"),
    "Docs": ("Docs writer", "Spec writer", "Translator", "Summarizer"),
    # (Named "Ops" until migration 0103, which renames the ready one where it still is.)
    "DevOps": ("DevOps", "Security reviewer", "Dependency keeper", "Performance engineer"),
    "Quality": ("Tester", "Reviewer", "Security reviewer", "Debugger"),
    "Research": ("Researcher", "Summarizer", "Spec writer"),
    "Product": ("Product owner", "Assistant product owner", "Spec writer"),
    "Maintenance": ("Refactorer", "Dependency keeper", "Debugger", "Tester"),
    # K-takim-duzen, made by migration 0103 (with the MLflow and Databricks experts in ML).
    "ML": ("Data scientist", "ML engineer", "Model evaluator", "MLOps engineer", "Tester"),
    "DataOps": ("Data engineer", "Database engineer", "Data analyst", "Tester"),
}
# A team's stages to begin with (slice 63a): today's kinds of work, a role in the one of its
# kind (`place_in_stages`).
STAGES = (("plan", "Plan"), ("build", "Build"), ("check", "Check"), ("write", "Write & keep up"))
# K-takim-duzen: the Data, ML and Ops categories (0103) are no stage of a team's - their roles
# work in Build; the Data scientist, who plans the experiment, in Plan.
STAGE_OF = {"data": "build", "ml": "build", "ops": "build"}
DATA_SCIENTIST = "Data scientist"
# Where a role made with no category (slice 63b) lands: the built-in "build", while it is there.
LANDING_KIND = "build"


def landing_kind(session: Session, kind: str = LANDING_KIND) -> str:
    """The category a role is put in: this one (a built-in role's own, "build" for one made with
    none) while it is there, else the first there is."""
    if session.get(Category, kind) is not None:
        return kind
    return session.scalar(select(Category.key).order_by(Category.position)) or kind
# A team's lead (slice 63a): a role its team names (`is_team_lead`), in no list of roles and
# opening no agent until teams run beside each other (84b). Its kind is drawn as "lead".
LEAD_KIND = "lead"
LEADS = select(Team.lead_role_id).where(Team.lead_role_id.is_not(None))
LEAD_DESCRIPTION = "Runs its team's stages when the team works beside another team."
# K-rol-cogul: a lead may open several agents of one role for a big job - and is not pushed to
# (B-192). Role instructions are the user's, in the record: migration 0105 adds it where they
# are still KOLONİ's words; a recipe's step says it too (`AgentRunner._where`).
SPLITS = ("When a job is big and splits into independent parts (separate files or modules), "
          "you may give each part its own agent{within}, asked for in one reply, never the same "
          "file to two; a small job {small}.")
WHO_SPLITS = SPLITS.format(within="", small="stays with you")
# B-202 (live): a team's lead has no tool that writes - told a small job stayed with it, one set
# out to write a page itself. Migration 0153 says it where its words are still KOLONİ's.
TEAM_SPLITS = SPLITS.format(within=", within what your step draws", small="goes to one agent")
LEAD_INSTRUCTIONS = ("Run your team's stages in order with the recipe you were given. Your roles "
                     "do the work: hand every file job and every finding to the right role - you "
                     f"write no file yourself; report to the Orchestrator. {TEAM_SPLITS}")
# (open_room and discuss: a team's lead meets its step's roles too, slice 84e.)
# shortcut: only a team made from here on has them - an older team's lead is given them on
# its card (Tools); add a migration if the ready teams' leads are to have them unasked.
LEAD_TOOLS = (*READ, "spawn_agent", "ask_user", "message_agent", "open_room", "discuss",
              *NOTEBOOK, *MEMORY)


BUILTIN_ROLES: dict[str, RoleSpec] = {
    LEAD: RoleSpec(
        "Talks with the user and carries the work, alone or by handing parts to sub-agents.",
        "Do small jobs yourself. Hand a part of the work to a sub-agent when it is a "
        "separate job for another role, and tell them everything they need: they see "
        f"only the task you write. {WHO_SPLITS}",
        ALL_TOOLS,
        "plan",
    ),
    "Planner": RoleSpec(
        "Breaks a job into steps and says who should do each one.",
        "Read enough of the project to plan well. Produce a short, ordered plan; do not "
        "make the changes yourself.",
        (*READ, "spawn_agent", "create_role", "ask_user", "ask_folder", "message_agent",
         "discuss", "propose_trigger", *NOTEBOOK, *MEMORY),
        "plan",
    ),
    "Coder": RoleSpec(
        "Writes and changes code.",
        "Make the change asked for, keep it small, and run the relevant checks before "
        "you report.",
        (*READ, *WRITE, *DIAGRAM, "run_command", *BROWSER, "spawn_agent", "ask_user",
         "message_agent", *NOTEBOOK, *MEMORY),
        "build",
    ),
    "Tester": RoleSpec(
        "Runs the tests and reports what passes and what fails.",
        "Run the checks you are asked to run and report the results exactly. Do not "
        f"change files. {RAN}",
        (*READ, "run_command", *BROWSER, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "check",
    ),
    "Reviewer": RoleSpec(
        "Reviews changes and reports problems.",
        "Read the code under review and report concrete problems with file and line. "
        f"Say plainly when you find none. Do not change files. {RAN}",
        (*READ, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "check",
    ),
    "Researcher": RoleSpec(
        "Finds things out in the codebase.",
        "Answer the question from what the files actually say, and name the files you "
        "relied on.",
        (*READ, *WEB, *BROWSER, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "plan",
    ),
    "Debugger": RoleSpec(
        "Finds why something fails and fixes the cause.",
        "Reproduce the failure first and say how. Find the cause before you change "
        "anything; fix the cause, not the symptom, and run the reproduction again before "
        "you report. You may have a Tester run the reproduction or a Coder make the fix with "
        "spawn_agent.",
        (*READ, *WRITE, "run_command", *BROWSER, "spawn_agent", "ask_user", "message_agent",
         *NOTEBOOK, *MEMORY),
        "build",
    ),
    "Architect": RoleSpec(
        "Designs how something should be built and weighs the options.",
        "Read enough of the project to design well. Lay out the options with what each "
        "costs and risks, and say which you would take and why. Do not change files. You may "
        "hand the parts of a design to Coders with spawn_agent.",
        (*READ, "spawn_agent", "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "plan",
    ),
    "Security reviewer": RoleSpec(
        "Reviews code for security problems.",
        "Read the code as an attacker would: what comes in from outside, what is trusted, "
        "where secrets go. Report concrete problems with file and line, and how each "
        f"could be used. Say plainly when you find none. Do not change files. {RAN}",
        (*READ, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "check",
    ),
    "Docs writer": RoleSpec(
        "Writes and updates documentation.",
        "Write what the code actually does, for the person who will read it: short, with "
        "a working example where one helps. Change only documentation files; if the code "
        "looks wrong, say so in your report and leave it.",
        (*READ, *WRITE, *DIAGRAM, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "write",
    ),
    "Refactorer": RoleSpec(
        "Simplifies code without changing what it does.",
        "Run the tests before you change anything and again after: they must pass both "
        "times. Change the shape of the code, never its behaviour, in small steps. Say so "
        "when what you are asked to simplify has no test.",
        (*READ, *WRITE, "run_command", "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "build",
    ),
    "UI designer": RoleSpec(
        "Designs and fixes how a page looks and reads: layout, contrast, accessibility.",
        "Look at the page as it is before you change it, and show what you made. Keep to "
        "the styles the project already has; check contrast and that every control can be "
        "reached from the keyboard and has a name.",
        (*READ, *WRITE, "show", *DIAGRAM, *BROWSER, "ask_user", "message_agent", *NOTEBOOK,
         *MEMORY),
        "build",
    ),
    "Data analyst": RoleSpec(
        "Reads data (CSV, SQL, notebooks), analyses it and shows the result as a chart.",
        "Say where the data came from and how much of it you read. Compute from the data, "
        "not from a guess, and show the chart or table you made; name what the data cannot "
        "tell.",
        (*READ, *WRITE, "show", "run_command", "ask_user", "message_agent", *NOTEBOOK,
         *MEMORY),
        "check",
    ),
    "DevOps": RoleSpec(
        "Looks after CI, Docker, build and deployment scripts.",
        "Read the pipeline and the scripts as they are before you change them. Keep each "
        "change small and run it where you can; never put a secret in a file, and say what "
        "you could not run here. You may have a Security reviewer or Dependency keeper look "
        "with spawn_agent.",
        (*READ, *WRITE, "run_command", "web_search", "spawn_agent", "ask_user", "message_agent",
         *NOTEBOOK, *MEMORY),
        "ops",
    ),
    "Spec writer": RoleSpec(
        "Makes a request precise: requirements, acceptance criteria and test scenarios.",
        "Read enough of the project to know what is there, and ask the user what the "
        "request leaves open. Write requirements that can be checked and scenarios a test "
        "can follow. Write only the document you are asked for (docs/..., say); never code. "
        "You may have a Researcher find things out with spawn_agent.",
        # (B-190: the spec file asked for is written by it - migration 0108 for installs.)
        (*READ, *WRITE, "spawn_agent", "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "write",
    ),
    "Performance engineer": RoleSpec(
        "Measures where time or memory goes and removes the bottleneck.",
        "Measure before you change anything and say how. Find the bottleneck from the "
        "numbers, keep the fix small, and measure again: report both numbers.",
        (*READ, *WRITE, "run_command", "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "check",
    ),
    "Database engineer": RoleSpec(
        "Works on the schema, migrations and queries without harming the data.",
        "Read the schema and the existing migrations first. Say plainly about every step "
        "that deletes or converts data, and write how to undo it.",
        (*READ, *WRITE, "run_command", "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "data",
    ),
    "Dependency keeper": RoleSpec(
        "Updates dependencies and checks their licences and security notices.",
        "Update one dependency at a time and run the tests after each. Check the licence "
        "and the known security notices of what you add or update, and name the source "
        "you checked.",
        (*READ, *WRITE, "run_command", "web_search", "ask_user", "message_agent", *NOTEBOOK,
         *MEMORY),
        "ops",
    ),
    "Translator": RoleSpec(
        "Translates interface text and documents, keeping the terms consistent.",
        "Use the terms the project already uses and keep each one the same throughout. "
        "Translate the meaning, not word by word; leave code, names and placeholders as "
        "they are.",
        (*READ, *WRITE, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "write",
    ),
    "Summarizer": RoleSpec(
        "Turns a long piece of work, a discussion or a record into a short summary.",
        "Keep what was decided, what is still open and who is doing what; leave out the "
        "rest. Post the summary as a note and keep what lasts in the project's memory. Write "
        "only the summary file you are asked for (docs/..., say), if one is; never code.",
        (*READ, *WRITE, "message_agent", *NOTEBOOK, *MEMORY),
        "write",
    ),
    "Product owner": RoleSpec(
        "Keeps the project's To-do list: breaks a goal into tasks, each with what makes it "
        "done, and puts them in order.",
        "Read enough of the project to know what is there. Break the goal into tasks small "
        "enough for one conversation each; say for every task, in plain words, what makes "
        "it done (it can be checked), and a priority. What you add or change waits for the "
        "user's approval; an assessment you write with assess_task is your opinion. Whether "
        "a task is done is the user's decision, never yours. You may have a Researcher find "
        "things out with spawn_agent.",
        (*READ, "spawn_agent", "ask_user", "message_agent", *BACKLOG, *NOTEBOOK, *MEMORY),
        "plan",
    ),
    "Assistant product owner": RoleSpec(
        "Helps keep the To-do list: splits vague tasks, asks what is missing, flags problems "
        "and assesses finished work against what makes it done.",
        "Split a vague task into smaller ones and ask the user what a task leaves open. Flag "
        "tasks written twice, tasks waiting a long time and tasks blocked by unfinished "
        "work. When a task's conversation has ended, compare what was done with what makes it "
        "done and write your view in two or three sentences with "
        "assess_task. What you add or change waits for the user's approval; your "
        "assessment is an opinion, and whether a task is done is the user's decision.",
        (*READ, "ask_user", "message_agent", *BACKLOG, *NOTEBOOK, *MEMORY),
        "plan",
    ),
    OBSERVER: RoleSpec(
        "Looks over a sub-agent's report, where the project asks for it, and says what of it "
        "the record shows. Asked with no tools; never opened as an agent.",
        "Compare what the report says with what is on record of the work: the calls made, "
        "the files changed and the check. Say what the record shows and what it does not, in "
        "at most three sentences. Give no score and do not guess.",
        (),
        "check",
    ),
    # K-takim-duzen: machine learning and data work, each with an existing role's tools.
    "Data engineer": RoleSpec(  # (the Coder's tools)
        "Builds and changes data pipelines: ingestion, ETL and the schemas they write.",
        "Read the pipeline and the data it touches before you change it. Keep each change small, "
        "run it on a sample where you can, and say plainly about every step that drops, "
        "rewrites or converts data.",
        (*READ, *WRITE, "run_command", "spawn_agent", "ask_user", "message_agent", *NOTEBOOK,
         *MEMORY),
        "data",
    ),
    "ML engineer": RoleSpec(  # (the Coder's tools)
        "Writes training and evaluation code, feature extraction and model packaging.",
        "Make the change asked for and keep it small. Fix the random seeds you can, run the "
        "training or evaluation on a small sample before you report, and say what you could "
        "not run here.",
        (*READ, *WRITE, "run_command", "spawn_agent", "ask_user", "message_agent", *NOTEBOOK,
         *MEMORY),
        "ml",
    ),
    DATA_SCIENTIST: RoleSpec(  # (the Researcher's tools: it writes no file)
        "Designs the experiment - the hypothesis, the metric that decides it, the baseline - "
        "and says what the results show.",
        "Read the data, the code and the earlier results before you plan. Write a short plan: "
        "the hypothesis, the metric that decides it and the baseline it is compared with. "
        "Reading results, say what they show and what they cannot. Do not change files.",
        (*READ, *WEB, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "ml",
    ),
    "Model evaluator": RoleSpec(  # (the Tester's tools)
        "Runs the model's evaluation and compares it with the model before: accuracy, drift, "
        "data leakage.",
        "Run the evaluation you are asked to run and compare each metric with the previous "
        "model's, both numbers side by side. Look for leakage between training and test data "
        f"and for drift. Report the results exactly. Do not change files. {RAN}",
        (*READ, "run_command", "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "check",
    ),
    "MLOps engineer": RoleSpec(  # (DevOps's tools)
        "Looks after the model registry, deployment, monitoring and experiment tracking "
        "(MLflow, say).",
        "Read the tracking, registry and deployment setup as it is before you change it. Keep "
        "each change small and run it where you can; never put a secret in a file, and say what "
        "you could not run here. You may have a Security reviewer or Dependency keeper look with "
        "spawn_agent.",
        (*READ, *WRITE, "run_command", "web_search", "spawn_agent", "ask_user", "message_agent",
         *NOTEBOOK, *MEMORY),
        "ops",
    ),
    # K-belge-ciktilari: what it makes is an output on the canvas (the UI designer's tools: a
    # role of its own, as the UI designer's words are the user's on every install).
    "Designer": RoleSpec(
        "Makes standalone designs - page mockups, one-pagers and slide decks - as HTML files, "
        "and shows them.",
        "Make each design one self-contained HTML file: every style and script inside it, "
        "nothing from the network (no CDN, web font or remote image - the preview loads none). "
        "A slide deck is one file, each slide a <section> drawn full-window, moved with the "
        "arrow keys. Show what you made. A document asked for as pdf, docx or pptx: say so in "
        "your report - an agent that runs commands makes it and shows it.",
        (*READ, *WRITE, "show", *DIAGRAM, *BROWSER, "ask_user", "message_agent", *NOTEBOOK,
         *MEMORY),
        "build",
    ),
    # K-site-roller: a site that is found, read and used - each looks at the built page. The two
    # who write are in Build, not Check or Write & keep up: the checks after them see their edits.
    "SEO specialist": RoleSpec(
        "Makes a site easy to find: titles, meta, sitemap, structured data.",
        "Read the pages as they are, and look at the built page with the browser tools where you "
        "can. Give each page its own title and meta description and one h1; add sitemap.xml, "
        "robots.txt, canonical links, schema.org JSON-LD and Open Graph tags where the site "
        "needs them; give images alt text, link related pages and keep URLs readable. Write for "
        "the reader, never stuff keywords, and say in a line why each change helps. Never give "
        "traffic or ranking numbers you did not measure.",
        (*READ, *WRITE, *BROWSER, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "build",
    ),
    "Copywriter": RoleSpec(
        "Writes a site's words: headlines, buttons, descriptions, messages.",
        "Read the site's pages and the words it already uses before you write, the built page "
        "too where you can. Write for its audience, in their language: short, plain, sentence "
        "case, one voice throughout; a button says what it does, an error what to do next. "
        "Change only the text, not the layout, styles or code around it; if those need a change, "
        "say so in your report.",
        (*READ, *WRITE, *BROWSER, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "build",
    ),
    "Accessibility reviewer": RoleSpec(
        "Reviews a site for accessibility to WCAG 2.2 AA.",
        "Hold the site to WCAG 2.2 AA. Read the code and try the built page with the browser "
        "tools where you can: every control reached from the keyboard in a sensible order, with "
        "visible focus; contrast; names and labels (ARIA only where HTML has none); alt text; "
        "headings in order; reduced motion; form errors that say what is wrong and where. Report "
        "each problem with file and line, the criterion it fails (or \"best practice\" where none "
        "applies) and the smallest fix. Say plainly when you find none. Do not change files. "
        f"{RAN}",
        (*READ, *BROWSER, "ask_user", "message_agent", *NOTEBOOK, *MEMORY),
        "check",
    ),
}


MAX_NAME = 60


NOT_A_ROLE = frozenset({"you", "user", "the user", "koloni", "koloni̇"})


def plain_name(name: str, what: str) -> str:
    """A name with tidy spacing, for a role, a provider or an agent. Agents are told these
    names as they are and address each other by them: one that holds anything that does
    not print (a control character, one that turns the direction of the text, one with no
    width) is refused with a ValueError, not tidied."""
    name = " ".join(name.split())
    if not name.isprintable():
        raise ValueError(f"{what} cannot contain control or invisible characters")
    return name


def shown_name(name: str) -> str:
    """A name from before that check, as agents are shown it: what does not print is left
    out. The record itself is not changed."""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in name).split())


# K-isimler: what people and agents read for the chat's top agent, and for a team's lead.
ORCHESTRATOR = "Orchestrator"
COORDINATOR = "coordinator"


def title_of(role_name: str, team: str | None = None) -> str:
    """A role's name in sentences and on screen (K-isimler): the Lead role is the Orchestrator,
    a team's lead (`team`: its team's name) is the "<Team> coordinator", any other role is its
    name as `shown_name` gives it. The role's name on record, in the API and in `spawn_agent`
    stays "Lead" / "<Team> lead".
    shortcut: a role of the user's own named "Orchestrator" clashes with the Lead's title in
    text only; refuse that name in `check_name` if a user is seen to make one."""
    if team:
        return f"{shown_name(team)} {COORDINATOR}"
    return ORCHESTRATOR if role_name == LEAD else shown_name(role_name)


def check_name(name: object) -> str:
    """A role name with tidy spacing; ValueError says what is wrong with it."""
    if not isinstance(name, str) or not " ".join(name.split()):
        raise ValueError("name is empty")
    name = plain_name(name, "a role name")
    if len(name) > MAX_NAME:
        raise ValueError(f"a role name has at most {MAX_NAME} characters")
    if name.casefold() in NOT_A_ROLE:
        # Agents are told who wrote a note or a message by name: no agent is "the user".
        raise ValueError(f"{name} cannot be a role's name: it would read as the user")
    return name


def check_tools(tools: object) -> list[str]:
    """The role's tools in their fixed order; ValueError names an unknown one."""
    if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        raise ValueError("tools must be a list of tool names")
    for tool in tools:
        if tool not in ALL_TOOLS:
            raise ValueError(f"unknown tool: {tool}")
    if not tools:
        raise ValueError("a role needs at least one tool")
    return effective_tools(tools, None)


def expert_tools(tools: list[str], knowledge: object) -> list[str]:
    """An expert's tools as they are kept: of `EXPERT_MAY` only. ValueError otherwise."""
    if knowledge is not None and (beyond := [one for one in tools if one not in EXPERT_MAY]):
        raise ValueError(f"an expert advises and reads only: it has no {', '.join(beyond)}")
    return tools


def find_role(session: Session, name: str) -> Role | None:
    """The role with this name, whatever its case - or, for a name from before names were
    checked, the role that is shown by this name."""
    found = session.scalar(select(Role).where(func.lower(Role.name) == name.lower()))
    if found is not None:
        return found
    shown = [
        role for role in session.scalars(select(Role))
        if role.name != shown_name(role.name)
        and shown_name(role.name).casefold() == name.casefold()
    ]
    # Two old names that read alike: there is no telling which is meant, and neither
    # is opened in the other's place.
    return shown[0] if len(shown) == 1 else None


def list_roles(session: Session) -> list[Role]:
    """Built-in roles first, in their fixed order, then the rest by creation. Not the teams'
    leads: each is its team's (`app.api.teams`)."""
    order = {name: index for index, name in enumerate(BUILTIN_ROLES)}
    roles = session.scalars(
        select(Role).where(Role.id.not_in(LEADS))
        .order_by(Role.created_at, literal_column("roles.rowid"))
    ).all()
    return sorted(roles, key=lambda r: (not r.builtin, order.get(r.name, 0)))


def is_observer(role: Role) -> bool:
    """The built-in Observer - not a role of the user's own that bears its name."""
    return role.builtin and role.name == OBSERVER


def agent_roles(session: Session) -> list[Role]:
    """The roles an agent may be opened in: all of them but the Observer."""
    return [role for role in list_roles(session) if not is_observer(role)]


def find_agent_role(session: Session, name: str) -> Role | None:
    """`find_role` for opening an agent: the Observer is no role one is opened in, nor a team's
    lead - only the Orchestrator opens one, by spawn_agent or in a room (`AgentRunner._team_lead`,
    84b)."""
    role = find_role(session, name)
    return None if role is None or is_observer(role) or is_team_lead(session, role) else role


def is_team_lead(session: Session, role: Role) -> bool:
    """Whether the role is a team's lead: its team says so, not its kind (a user's own kind
    of work may read "lead")."""
    return role.id is not None and session.scalar(
        select(Team.id).where(Team.lead_role_id == role.id)) is not None


def effective_tools(role_tools: Iterable[str], parent_tools: Iterable[str] | None) -> list[str]:
    """What an agent may use: its role's tools, never more than `parent_tools` (what its
    opener may hand on: the Orchestrator's, `AgentRunner._caps`)."""
    wanted = set(role_tools)
    if parent_tools is not None:
        wanted &= set(parent_tools)
    return [tool for tool in ALL_TOOLS if tool in wanted]


def can_change_things(tools: Iterable[str]) -> bool:
    """Whether an agent with these tools can alter files or run commands."""
    return any(tool in tools for tool in CHANGES)


def names_said(names: Iterable[str], said: str | None) -> frozenset[str]:
    """The roles (of `names`) the user's message names, casefolded: each as a word, whatever
    its case (slice 62: "Translator", "Translator'ı", what `/Translator` sends). The longest
    first, its words then taken out: "Security reviewer" does not name the Reviewer too."""
    found, rest = set(), said or ""
    for name in sorted(names, key=len, reverse=True):
        rest, hits = re.subn(rf"(?<!\w){re.escape(name)}(?!\w)", " ", rest, flags=re.IGNORECASE)
        if hits:
            found.add(name.casefold())
    return frozenset(found)


class Door(NamedTuple):
    """The teams a chat's agents keep to (slice 84b): its rows, the user's or the Lead's; none:
    any role. `unpicked`: Lead decides before the Lead picks - any role but one only in teams
    the Lead may not pick."""

    teams: list[Team]
    unpicked: bool = False
    # Slice 84b-2: while a row's recipe runs, the roles (casefolded) its opener may open now in
    # place of the teams', and where the recipe is, as its opener is told.
    step: tuple[frozenset[str], str] | None = None


def chat_teams(session: Session, conversation) -> Door:
    """The door of `closed` for a conversation's agents now."""
    if conversation.teams_mode == "none":
        return Door([])
    rows = [session.get_one(Team, row.team_id) for row in conversation.teams]
    return Door(rows, unpicked=conversation.teams_mode == "lead" and not rows)


def pickable(session: Session) -> list[Team]:
    """The teams the Lead may pick itself (slice 84b: "The Lead may pick it"), in the Agents
    page's order."""
    return list(session.scalars(select(Team).where(Team.lead_may_pick).order_by(
        Team.created_at, literal_column("teams.rowid"))))


def team_roles(session: Session, team: Team) -> list[str]:
    """Its roles that are on, by name, as spawn_agent takes them."""
    return list(session.scalars(select(Role.name).join(RoleTeam, RoleTeam.role_id == Role.id)
                                .where(RoleTeam.team_id == team.id, Role.enabled)
                                .order_by(Role.name)))


def stage_roles(session: Session, team: Team) -> list[tuple[str, tuple[str, ...]]]:
    """Its stages in their order, each with its roles that are on, by name (slice 63a)."""
    return [(stage.name, tuple(session.scalars(
        select(Role.name).join(RoleTeam, RoleTeam.role_id == Role.id).where(
            RoleTeam.team_id == team.id, RoleTeam.stage_id == stage.id, Role.enabled)
        .order_by(Role.name)))) for stage in team.stages]


def stage_order(session: Session, team: Team) -> str:
    """B-171: its stages that hold a role, in order, as a team's lead with no recipe is told
    them: "Plan (Spec writer) → Build (Coder)"; "" with fewer than two - no order to say."""
    held = [f"{name} ({', '.join(roles)})" for name, roles in stage_roles(session, team) if roles]
    return " → ".join(held) if len(held) > 1 else ""


def closed(role: Role, door: Door, named: frozenset[str]) -> str | None:
    """Why no agent of `role` is opened now, in the words its opener is told; None: it may
    be. It is off, or outside the chat's teams (`chat_teams`) - unless the user names it in
    the turn's own message (`named`: `names_said`). The Lead, the Planner and the Observer
    always may. While a recipe runs, its step's roles are the door (`Door.step`), whatever
    team they are in.
    shortcut: a CLI working with its own tools (Claude Code's Agent/Task) opens sub-agents of
    its own that never pass here: the chat's teams do not hold them; keep such a CLI from them
    while a chat has teams if that is met."""
    if door.step is not None and role.builtin and role.name == LEAD:
        # B-110 (live): refused the Coder at the spec step, the Lead opened a "Lead 2" to write it.
        return f"{door.step[1]}: no Lead is opened under the Orchestrator while a recipe runs"
    if role.builtin and role.name in ALWAYS or role.name.casefold() in named:
        return None
    if not role.enabled:
        return (f"the {role.name} role is off: it is opened only when the user names it in "
                "their message")
    if door.step is not None:
        allowed, where = door.step
        # (B-191, live: refused the Coder, the Lead asked the user which role to open.)
        return None if role.name.casefold() in allowed else (
            f"{where}: the {role.name} role is not one of its roles now - open the step's role "
            "named there now, with spawn_agent; do not ask the user which")
    if door.unpicked and role.teams and not any(team.lead_may_pick for team in role.teams):
        return (f"the {role.name} role is only in teams the Orchestrator may not pick "
                f"({', '.join(team.name for team in role.teams)}): the user picks those in "
                "Teams for this chat (Manual)")
    if door.teams and not any(team in role.teams for team in door.teams):
        return (f"the {role.name} role is in none of this chat's teams "
                f"({', '.join(team.name for team in door.teams)}): open one of their roles. The "
                "user changes the teams in Teams for this chat")
    return None


def seed_builtin_roles(session: Session) -> None:
    """Add any built-in role that is missing; existing ones are left as the user has them -
    also a role of the user's own that has a built-in one's name, whatever its case (a
    role is opened by its name: `find_role`). One that is added joins the ready teams that
    hold it, where they are still there - never a team of the user's own by such a name."""
    existing = {name.casefold() for name in session.scalars(select(Role.name))}
    # (Migration 0093's rule: the ready teams are the first ever made, 0103's given their time.)
    first = select(func.min(Team.created_at)).scalar_subquery()
    teams = {team.name: team for team in session.scalars(select(Team).where(
        Team.created_at == first))}
    for name, spec in BUILTIN_ROLES.items():
        if name.casefold() not in existing:
            session.add(Role(
                name=name,
                description=spec.description,
                instructions=spec.instructions,
                tools=list(spec.tools),
                kind=landing_kind(session, spec.kind),
                builtin=True,
                teams=[teams[team] for team, held in READY_TEAMS.items()
                       if name in held and team in teams],
            ))
    place_in_stages(session)
    session.commit()


def place_in_stages(session: Session) -> None:
    """Give each role put in a team without a stage one: the stage named after its kind of work
    where the team still has it, else the team's first (slice 63a).
    shortcut: matched by the stage's name, so once the user renames "Build" to "Code" a new
    build role lands in the first stage; keep the kind a stage began as if that is felt."""
    session.flush()
    loose = session.execute(
        select(RoleTeam, Role.kind, Role.name).join(Role, Role.id == RoleTeam.role_id)
        .where(RoleTeam.stage_id.is_(None))).all()
    titles = dict(STAGES)
    for link, kind, name in loose:
        stages = session.get_one(Team, link.team_id).stages
        kind = "plan" if name == DATA_SCIENTIST else STAGE_OF.get(kind, kind)
        named = next((s for s in stages if s.name == titles.get(kind)), None)
        link.stage_id = (named or stages[0]).id if stages else None
    session.flush()
