# Glossary

KOLONİ's own words, as they appear on screen.

**Agent**
: One worker in a turn: a role running on a model. The canvas draws each agent as a small box: its
  name and model, its state, and what it did. Its tools, commands and files are in the Inspector.

**Agents may use**
: A switch for each model on the Models page. When it is on, agents may pick that model by
  themselves, not only you.

**Away (☾)**
: On a chat's status line: that chat finishes its turn, then the To-do tasks you tick are worked
  through, each in its own copy, until you press **I'm back** or write again. The Orchestrator decides
  for you what it safely can meanwhile. See [Work while you're away](../automation/overnight.md).

**Always run**
: A button on a command's card. It keeps a rule for that chat, so the same kind of command runs
  without a card next time. See [Permission levels](../use/permissions.md).

**Board**
: A page with every chat of the project in three columns: at work, waiting for you, and done
  today.

**Branch (a team's)**
: A git branch `koloni/<name>` that the Orchestrator can give a team's work. It starts from your folder
  as it is, your uncommitted files too, and its card carries the agent's work alone. Stopped, the
  agent's work stays committed there; told to go on, it goes on on the same branch. The card offers
  **Merge** or **Open pull request**. See [Branches](../use/workspace.md#branches).

**Candidates**
: A recipe step given to several agents at once, each in its own working copy. Each one's work is
  scored from 0 to 100 by the project's **Measure command**, and the best one is kept.

**Card**
: A box in the chat that waits for your answer, for example "Run this command?" with
  **Run once**, **Always run …** and **Reject**. There are cards for file changes, commands, web
  searches, secret files, opening a sub-agent, plans and more.

**Check what I said first**
: A switch in the permission level's menu, the project's: at Full auto, before a harmful-looking
  command waits for you on a card, a fast model reads your own words, and the command runs without a
  card only where a line of yours names it. See
  [Permission levels](../use/permissions.md#check-what-i-said-first).

**Compare**
: **Compare…** under **More** next to the message box. One message goes to two models side by
  side, each in its own working copy. Nothing reaches your project until you keep one.

**Coordinator**
: A team's own lead, shown as "*Team* coordinator". It runs its team's stages and reports to the
  Orchestrator.

**Core**
: The facts in a project's memory: what you approved or wrote yourself. See [Memory](../memory.md).

**Decided for you**
: Where you see the cards the Orchestrator decided for you: while you were away (☾ Away), or once a
  card waited the project's minutes (Settings › This project › Asking and away › **When you're
  away**); and the commands **Check what I said first** ran, or did not run, on a line of yours.

**Discussion**
: Several agents talking one question through in rounds, with nobody changing anything meanwhile.
  An agent starts one; it has a token budget.

**Fact**
: A short piece of memory that you approved or wrote, usually pointing to lines of a file. It is
  given to an agent whose task names its subject.

**Goal**
: On the To-do page, what a few stories are for together, with how many of them are done. See
  [Goals and stories](../automation/todo.md#goals-and-stories).

**Hive keeper**
: The built-in role that keeps the To-do list: it turns a goal into stories and tasks, each with what
  makes it done, and puts them in order. **Write it with the Hive keeper** on the To-do page asks for its
  way of writing a note as a goal, its stories and their tasks. See [To-do](../automation/todo.md).

**Journal**
: The notes in a project's memory: what agents wrote while they worked. Agents find notes only
  when they look.

**Knowledge**
: A page of expert topics, each read once from web pages or project files into pages and a guide.
  Roles that know a topic use it while they work.

**MCP server**
: A program on your machine that gives agents more tools. You add it on the Tools page, under
  **Servers**. Each tool asks before it runs unless you say otherwise.

**Measure command**
: A command, set under Settings › This project › Checks and git, whose last line of output is a score from 0 to
  100. It scores candidates.

**Memory**
: What a project remembers between chats: your preferences, the project's rules, facts and notes.
  See [Memory](../memory.md).

**Note**
: A piece of memory an agent wrote with its **Remember** tool. See [Memory](../memory.md).

**Observer**
: A built-in role that never works on its own. If you switch on **Have a model look over each
  sub-agent's report**, its model reads each sub-agent's report and says what the record shows.
  Its words are an opinion, not a fact.

**Orchestrator**
: The agent you talk to in a chat. It plans, asks and checks, and hands changes to files to
  sub-agents, unless you let it change files itself (Settings › This project › Agents › **Who
  changes the files**). (Behind the scenes its role is named Lead.)

**Outside content**
: Text that comes from outside your messages: web pages and searches, MCP tools' results, Knowledge
  pages and GitHub issues. KOLONİ frames it as data, not instructions, for the agents. See
  [Outside content](../security/model.md#outside-content).

**Page key**
: A secret that the KOLONİ page sends with every request, so that a program on your machine cannot
  approve cards or change settings in your place. It changes each time KOLONİ starts. Open KOLONİ
  from the link in its window.

**Part**
: In the project map, a folder with its own project file (such as `pyproject.toml` or
  `package.json`), with its language and test command. In a recipe drawing, a step or a group of
  steps.

**Permission level**
: What agents may do without asking: **Ask before changes**, **Auto-edit files** or **Full auto**.
  See [Permission levels](../use/permissions.md).

**Plain chat**
: A chat with no folder ("No folder · a plain chat"). It is only talk: no files and no commands.

**Plan first**
: A switch in the permission level's menu under the message box. Each new message first gets a plan
  to approve before anything changes.

**Project**
: A folder your agents work in. Each project has its own settings, memory and To-do list.

**Project notes**
: A Knowledge topic that KOLONİ fills from what you tick on the **Add to Project notes?** card at the
  end of a turn.

**Provider**
: Where a model runs: an OpenAI-compatible server, the Anthropic API, or a CLI you are signed in to
  (Claude Code, Codex, GitHub Copilot CLI, agy). You add providers on the Models page.

**Ready**
: A page on the rail that lists everything waiting for your word, with a count.

**Ready for you**
: The panel and page that list everything waiting for your word, in three parts: **Needs your
  answer**, **Ready to take in** and **Told you**.

**Recipe**
: The drawn steps of a piece of work: who does each step, what runs at once, where it loops back
  and how it ends. Recipes are on the Agents page.

**Role**
: What an agent is for: a description, instructions, the tools it may use and, if you like, its own
  model. KOLONİ comes with built-in roles such as Planner, Coder, Tester, Reviewer, Researcher,
  Debugger, Architect and Docs writer. You can add your own.

**Room**
: Two to six agents working on one goal at the same time, in one working copy. They share the work
  out first, and each file has one holder. You open one with **Work together…** under **More**.

**Scout**
: The built-in role that keeps watch on the To-do list: it splits vague tasks, asks what is
  missing, flags duplicates, stale and blocked tasks, and checks finished tasks against what makes
  them done. After a turn that did something, KOLONİ also makes one small model request with no
  tools in its name, which suggests at most three follow-up tasks, each with the words it came
  from; on the canvas that is a small box under the turn. See [Follow-up tasks](../automation/todo.md#follow-up-tasks).

**Skill**
: A folder with a `SKILL.md` and its files, in the form Claude Code reads. You add skills on the
  Tools page and give them to roles.

**Stop everything**
: The button in the top bar that stops every turn in every chat and holds triggers, To-do lists that run
  by themselves, and work while you're away. While it holds, it reads **Held · Resume**. See
  [Chat and canvas](../use/chat-and-canvas.md#writing-a-message).

**Story**
: On the To-do page, tasks and bugs that go on together. Its state comes from its tasks; it is done
  only when you close it. It has a short notebook, given to each of its turns as data, and its tasks go
  on in one topic of a chat. A **bug** is a task about something that works wrong. See
  [Goals and stories](../automation/todo.md#goals-and-stories) and
  [The story's notebook](../automation/todo.md#the-storys-notebook).

**Sub-agent**
: An agent that the Orchestrator (or another agent) opens for a part of the work. It works in its
  own working copy.

**Take in**
: Bringing finished work from a working copy into your project. Every card that does this says
  **Take in**.

**Team**
: A named group of roles with stages: Plan, Build, Check, and Write & keep up. A chat can work with
  teams, picked under **Teams for this chat**: **Orchestrator decides**, **Manual** or
  **No teams**.

**Teams' work is ready**
: The card where a recipe's work ends. It asks whether to take the work into the project, with
  **Take in**, **Fix the findings** and **Ask for changes**.

**Thinking**
: How hard a role's model thinks, set on its Model card: **Auto** (the agent that opens it picks a level
  for each task, up to a most) or **One fixed level**, on a ladder from Off to Max. See
  [Roles](../agents/roles.md#editing-a-role).

**Tier**
: How strong you say a model is: **fast**, **balanced** or **strongest**. You set it for each model on
  the Models page. A model with no tier is never picked by itself.

**To-do**
: A project's tasks, in your order: goals hold stories, stories hold tasks and bugs. Agents, and the
  Scout after a turn, propose tasks; you decide.

**Topic**
: The turns of a chat that go on with one piece of work. The Orchestrator is sent its own topic's
  turns, and the chat's other topics by name only; an agent of an earlier turn is gone on with only
  inside its topic. **New topic**, under the message box, starts one with your next message. A To-do
  story given to a chat goes on in a topic of its own, its tasks one after another. See
  [Topics](../memory.md#topics) and [Doing tasks in a chat](../automation/todo.md#doing-tasks-in-a-chat).

**Trigger**
: Something that starts a turn by itself: the clock, a change to the project's files, or a request
  from outside (a webhook). Nobody watches such a turn, so it may do only what the trigger allows.

**Turn**
: Everything that happens for one message: the Orchestrator's answer, the agents it opened, their
  tools, commands and changes. The canvas draws one turn at a time.

**Where the work is**
: The panel the git button in the top bar opens ("⑂ main · 4 changed"): your branch, the agents' copies
  in this chat, and other branches, each saying how the work stands. See
  [Branches](../use/workspace.md#branches).

**Workspace**
: The side window with the project's files, what agents changed, wrote or showed, and what waits
  for you.

**Working copy**
: A copy of your project, outside your folder, where a sub-agent makes its changes. Its work comes
  back to you on a card to take in or discard.

## How a CLI runs

A CLI provider has a setting **How it runs**:

| On screen | What it means |
|---|---|
| One session per agent, with KOLONİ's tools (recommended) | One CLI session per agent, using KOLONİ's tools. |
| One run per model step, with KOLONİ's tools | The CLI runs once for each model step: slower, and the answer arrives all at once. |
| Native: its own tools, in the project | The CLI uses its own tools in your folder and asks KOLONİ before each one. |
| Reads with its own tools; started without leave to write or run | agy only: it reads with its own tools and cannot change anything. |
