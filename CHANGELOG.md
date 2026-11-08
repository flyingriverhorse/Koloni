# Changelog

All notable changes to KOLONİ are listed here, newest first. English only.

<!--
How to write an entry (every release looks the same):

- One version heading: `## [X.Y.Z] - YYYY-MM-DD`. Unreleased work goes under `## [Unreleased]` and
  moves under the version when it is tagged. Versions follow Semantic Versioning (semver.org).
- Inside a version, only these sections, always in this order, and only the ones that have entries:
  ### Added · ### Changed · ### Fixed · ### Security · ### Removed · ### Deprecated
- One line per entry: `- **Area**: what the user can now do or will notice, in plain words.`
  Area is the page or part the user knows: Canvas, Chat, Ready, To-do, Agents, Models, Tools, Memory,
  Knowledge, Triggers, Usage, Settings, CLIs, Workspace, Install, Docs.
- Say what changed for the user, not how it was built. No commit hashes, no internal names
  (K-…, B-…, train-…). A breaking change starts with **Breaking:**.
- A migration that changes saved data says so in the entry ("existing settings keep their value").
- Links to the docs where a feature is explained, by their path in the repository, such as
  `([docs](docs/use/ready.md))`; the release notes point them at the version's tag.
-->

## [Unreleased]

### Changed

- **Chat**: the Orchestrator no longer stops at a fixed count of steps; it stops when its work is done, when it goes round in circles (it is told once to try another way; then a card asks you **Go on** or **Stop here**, tells you on the desktop and at the project's notification address, and ends the turn with its work kept if nobody answers in 10 minutes), or at a limit you set on the Lead role or a trigger. **Steps an agent may take** now holds sub-agents ([docs](docs/agents/step-limits.md#the-orchestrator-no-step-count)).
- **To-do**, **Triggers**: in a run nobody watches, an Orchestrator going round in circles ends with the reason on record, and a night or the To-do run goes on with the next job or task; such a turn ends once nothing has moved for **Stuck after this many minutes with no progress** (Settings › The app, 30 unless you change it), and a To-do task's turn or a night's job after **An unattended turn runs at most (hours)** (8; empty: no limit) - a night's job no longer stops at 60 minutes ([docs](docs/agents/step-limits.md#when-the-orchestrator-goes-round-in-circles)).

### Fixed

- **Ready**: a team whose coordinator KOLONİ stopped while one of its agents was still at work keeps running until that agent is back, and its work is offered at **Ready for you**; **Ready for you** is also asked before the Orchestrator ends its turn where nobody asked it earlier.

## [0.1.0] - 2026-11-07

### Added

- **Chat**: talk to the Orchestrator in a folder of yours, or in no folder for a plain chat; messages sent while agents work wait their turn ([docs](docs/use/chat-and-canvas.md)).
- **Chat**: the Chats list, a **Board** with every chat in columns, and a chat started **From a GitHub issue…** with the issue attached, read with your own `gh` ([docs](docs/use/chats.md)).
- **Chat**: other folders can join a chat, each read only or read & write ([docs](docs/use/chat-and-canvas.md#the-folder-button)).
- **Chat**: three permission levels, **Ask before changes**, **Auto-edit files** and **Full auto**, with "Always run" rules you can see and remove ([docs](docs/use/permissions.md)).
- **Chat**: **Plan first** gives each new message a plan to approve before anything changes ([docs](docs/use/plan-first.md)).
- **Chat**: **Undo these changes** and **Restore to before this message**, each showing first what goes back.
- **Chat**: **Stop** and **Stop everything** stop the work and keep what was half done, to take in or discard; **Stop everything** also holds triggers, To-do and work while you're away until **Resume**.
- **Chat**: under the Orchestrator's last answer of a turn that changed files, KOLONİ says from its own records where the work is: in the project, waiting in Ready for you, or nowhere ([docs](docs/use/ready.md#when-a-turn-ends-stops-or-koloni-restarts)).
- **Chat**: work that was open when KOLONİ stopped is marked interrupted, and nothing is run again by itself ([docs](docs/use/ready.md#when-a-turn-ends-stops-or-koloni-restarts)).
- **Chat**: while you're away, the Orchestrator plans jobs on a card; each runs in its own copy after your **Start**, and you decide what comes in when you are back ([docs](docs/automation/overnight.md)).
- **Chat**: work while you're away has a stop time and a spend limit only if you set them; the project's monthly budget still holds.
- **Chat**: **Compare** sends one message to two models side by side, and you keep the work of one ([docs](docs/use/compare.md)).
- **Chat**: attach files, screenshots and videos (sent as frames), and save attachments into the project ([docs](docs/use/attachments.md)).
- **Chat**: a long context is summarised past **Summarise a long context at (%)**, for API models and most CLI modes; the **context** button shows how full it is, with **Compact now** ([docs](docs/use/chat-and-canvas.md#the-context-button)).
- **Chat**: slash commands of your own, a command palette on Ctrl+K, and an agent's dev server shown as a preview, on this machine only ([docs](docs/use/command-palette.md)).
- **Chat**: dictation and answers read aloud ([docs](docs/use/voice.md)).
- **Canvas**: each turn is drawn from its record: every agent a box, with lines for work handed on, talk, findings and waiting; a legend explains every line and sign ([docs](docs/use/chat-and-canvas.md#the-canvas)).
- **Canvas**: teams in frames, rooms and discussions between teams in a lane of their own, and a step's earlier rounds folded into one line each.
- **Canvas**: click an agent for its report, waiting approvals, changes and tokens; **Open window** shows what it did step by step, with **Details** below.
- **Agents**: ready roles (Orchestrator, Planner, Coder, Reviewer, Tester, Product owner and more) and your own, each with its tools and skills ([docs](docs/agents/roles.md)).
- **Agents**: three ready roles for a website, in the Web app team: SEO specialist, Copywriter and Accessibility reviewer ([docs](docs/agents/roles.md)).
- **Agents**: a role's Model cards: which model, how hard it thinks (**Auto** lets the agent that opens it choose), and how much it reads.
- **Agents**: teams with steps, picked per chat; a team can wait for another one ([docs](docs/agents/teams.md)).
- **Agents**: recipes with steps, loops, branches and conditions, drawn, copied or described in a sentence; the ready ones include Feature, Bugfix, Review only and Evolve ([docs](docs/agents/recipes.md)).
- **Agents**: candidates: one job given to 2 to 5 agents, each scored by your measure command; a card lists the scores and you pick, and at Full auto the best goes on by itself ([docs](docs/examples/candidates.md)).
- **Agents**: rooms: two to six agents on one goal at once, with a budget, Pause, Resume and End ([docs](docs/agents/rooms.md)).
- **Agents**: a room an agent opens gets at least 60,000 tokens, so a small budget no longer ends it before anyone posts. Change the number under **Tokens, at least** in Settings › This project › New chats start with; the most still wins. Existing projects and chats get 60,000 too ([docs](docs/settings.md#new-chats-start-with)).
- **Agents**: discussions: agents talk one question through in rounds, and you can join in ([docs](docs/agents/discussions.md)).
- **Agents**: reviewers end with findings that go to the role they name; the **Observer**, when on, says what each sub-agent's record shows ([docs](docs/agents/observer.md)).
- **Agents**: tell an agent something while it works; at its step limit a card offers **Continue (+25 steps)** or **Stop here**, and **Steps an agent may take** sets the limit ([docs](docs/agents/step-limits.md)).
- **Agents**: when you are away, the Orchestrator answers the safe questions, if you switch it on (Settings › This project › Asking and away), and shows them under **Decided for you** ([docs](docs/automation/answering-for-you.md)).
- **Models**: an OpenAI-compatible server with tool calls, such as llama.cpp's llama-server or a hosted API, the Anthropic API, and CLIs, side by side; each agent shows the provider and model it really ran on ([docs](docs/models/providers.md)).
- **Models**: start, stop and restart your llama.cpp server from KOLONİ, with its output and NVIDIA GPU memory and load ([docs](docs/models/setup-local.md)).
- **Models**: tiers (fast, balanced, strongest) tried in your order, so a role or a job can ask for a tier; **Agents may use** keeps a model to your own picks ([docs](docs/models/tiers.md)).
- **Models**: limits per provider, in dollars per day or month or as a plan, and stepping down a tier when a plan runs low ([docs](docs/models/limits.md)).
- **CLIs**: Claude Code, Codex, GitHub Copilot CLI, Qoder and agy on your own plans, signed in by you in your own terminal ([docs](docs/models/setup-cli.md)).
- **CLIs**: under **How it runs**, a CLI runs with KOLONİ's tools and cards (**One session per agent**, now Codex too, or **One run per model step**), agy **Reads with its own tools**, or **Native** with its own tools: Claude Code, Qoder and agy ask KOLONİ before every tool, Codex before commands and patches, Copilot before commands, writes and reads ([docs](docs/models/setup-cli.md#how-it-runs)).
- **CLIs**: a Codex provider added from now on runs as **One session per agent** (recommended), but as **One run per model step** on a model server of your own, where its session is not yet measured; one saved before keeps its way of running ([docs](docs/models/setup-cli.md#how-it-runs)).
- **CLIs**: several Claude Code or Codex accounts side by side, each with its own sign-in for KOLONİ ([docs](docs/models/setup-cli.md#sign-in-for-claude-code-and-codex)).
- **CLIs**: Copilot's thinking levels Off to Max, its `auto` model, and its tokens and AI credits in each agent's record ([docs](docs/models/setup-cli.md#github-copilot-cli)).
- **CLIs**: agy is added switched off, and its card warns that Google's terms forbid using it through another app ([docs](docs/models/subscription-rules.md)).
- **CLIs**: while a Qoder free model waits in its queue, the agent says so ([docs](docs/models/setup-cli.md#qoders-free-models)).
- **Workspace**: agents work in their own working copies; **Take in** brings the work into your folder and **Discard** drops it; **Run the test** tries the project's test on the copy first, and at Auto-edit and Full auto work comes in by itself only when that test passed ([docs](docs/use/workspace.md#taking-work-in)).
- **Workspace**: **Changes** groups every change by what it needs from you, with **Approve**, **Reject** and **Revert** ([docs](docs/use/workspace.md#the-workspace)).
- **Workspace**: a team's work can get a git branch, merged or sent as a pull request from its card; an agent told to go on goes on in its own branch ([docs](docs/use/workspace.md#branches)).
- **Workspace**: **Where the work is** shows your branch, the agents' copies and other branches; KOLONİ commits when you ask ([docs](docs/use/workspace.md#committing)).
- **Ready**: everything that waits for you in **Ready for you**: **Needs your answer**, **Ready to take in** and **Told you** ([docs](docs/use/ready.md)).
- **Ready**: every card has a title, one sentence, the same verbs (**Take in**, **Reject**, **Approve**, **Discard**) and folded **Details**.
- **To-do**: a project's tasks in your order, each run in a chat of its own, by hand or one after another with **Run the backlog**; you decide when a task is done ([docs](docs/automation/todo.md)).
- **To-do**: **Write it with the Product owner** turns a rough note into draft tasks, saved only when you add them.
- **To-do**: after a turn that did something, the Assistant PO suggests at most three follow-up tasks to **Add**, **Edit** or **Reject**; a task added for you never runs without your OK ([docs](docs/automation/todo.md#follow-up-tasks)).
- **Triggers**: start work by the clock, when files change, or from a webhook, each with its own permissions and budget ([docs](docs/automation/triggers.md)).
- **Triggers**: a trigger is not saved on a chat whose Orchestrator would run on a CLI working with its own tools, and the form says why ([docs](docs/automation/triggers.md#what-a-triggers-run-never-does)).
- **Memory**: facts that rest on lines of files and are checked again each time, proposals you approve, your preferences, and search by meaning ([docs](docs/memory.md)).
- **Knowledge**: experts that learn a source, such as docs or the project's code, and that agents ask; learning again reads only what changed ([docs](docs/knowledge.md)).
- **Knowledge**: a role is Full in one knowledge of a project; choosing another turns the first to Map, and an expert asked about a topic it does not use looks in all its knowledge instead ([docs](docs/knowledge.md#giving-knowledge-to-a-role)).
- **Knowledge**: a public GitHub repository: cloned outside the project with nothing of it run, its code mapped for free, and guides written from its docs and from how its code works; **Learn more** goes on with more code files ([docs](docs/knowledge.md#a-repository)).
- **Knowledge**: a folder on this machine, git or not, learned as a repository is: read in place with nothing written into it or run in it, added only by you; the most files and MB a repository or a folder may hold are yours to set in Settings ([docs](docs/knowledge.md#a-folder-on-this-machine)).
- **Knowledge**: **Add KOLONİ’s own guide** makes this guide a knowledge your roles can be given ([docs](docs/knowledge.md#kolonis-own-guide)).
- **Knowledge**: after a turn, **Add to Project notes?** keeps fixed findings and docs changes in a Project notes knowledge ([docs](docs/knowledge.md#project-notes)).
- **Tools**: built-in tools by group (files, commands, web, a browser on the sites you allow, team, To-do, memory), given to each role on its Tools tab; five can be switched off for every agent ([docs](docs/tools/built-in.md)).
- **Tools**: MCP servers; **What does it do?** looks inside an `npx` or `uvx` package before you add it ([docs](docs/tools/mcp.md)).
- **Tools**: skills from a folder or GitHub, given to roles, with a record of how each did ([docs](docs/tools/skills.md)).
- **Usage**: tokens and known cost by turn, day and month, and a monthly budget per project ([docs](docs/money/usage.md)).
- **Usage**: plan meters for Claude Code, Codex, agy and Copilot, from what each CLI last reported ([docs](docs/money/usage.md#plan-meters)).
- **Settings**: one place in three levels, **This chat**, **This project** and **The app**, with a short sheet for the chat under the message box ([docs](docs/settings.md)).
- **Settings**: a folder's rules and run settings live in the folder and go into git; settings from another machine are asked about before they are used (**Use them** / **Not now**) ([docs](docs/settings.md#settings-kept-in-the-folder)).
- **Settings**: **Export everything** and **Restore from a file…** ([docs](docs/backup-and-update.md)).
- **Settings**: notifications to a webhook (Slack, Discord, ntfy), a desktop notification on Windows only, and a daily summary ([docs](docs/settings.md#notifications)).
- **Settings**: **Delete project…** removes KOLONİ's record of a project, never its folder ([docs](docs/settings.md#delete-project)).
- **Install**: Python 3.12 to 3.14 on Windows (tested daily) and Linux (automatic tests, less daily use); macOS not tested yet; a Docker image, the newest and least tested ([docs](docs/getting-started/install.md)).
- **Install**: the update scripts back up the database, update, and rebuild the guide where Zensical is installed ([docs](docs/backup-and-update.md)).
- **Install**: licensed AGPL-3.0-or-later ([docs](LICENSE)), with a commercial license for those who cannot meet its terms ([docs](COMMERCIAL-LICENSE.md)).
- **Docs**: a user guide in English, published on GitHub Pages and, after one build with the optional Zensical package, served by KOLONİ itself at `/guide/`, offline and matching the version you run; hints link to it with **Learn more →** ([docs](docs/getting-started/install.md#this-guide-inside-koloni)).
- **Docs**: pictures of the main screens, short videos, diagrams, and pages for KOLONİ in 5 minutes, Which way to work, troubleshooting and known limits ([docs](docs/getting-started/concepts.md)).

### Security

- **Install**: KOLONİ listens on 127.0.0.1 only and sends no telemetry; every request to its API needs the page key, so a plain or injected command an agent runs cannot approve its own cards ([docs](docs/security/model.md#the-page-key)).
- **Install**: exports and backups are downloaded without the page key in their address, so it stays out of your browser's history.
- **Settings**: an export without keys also leaves out secret files you attached to a chat (a `.env`, a key file); the chat keeps their name ([docs](docs/backup-and-update.md#export-everything)).
- **Install**: a link with a wrong key, from a web page or an agent's answer, no longer locks the page out: the page keeps its key unless KOLONİ accepts the new one, and links in agents' answers and diagrams open in a new tab.
- **Ready**: reading secret files, writing most files that steer agents, and commands that delete or send data off the machine stop at a card at every level, with a few exceptions for CLIs run with their own tools ([limits](docs/reference/known-limits.md#secrets)); at Full auto these checks are for honest commands, not a wall ([docs](docs/security/model.md#where-protection-ends)).
- **Ready**: a command an agent runs is judged together with the folder it runs in, so a relative path inside `.claude` or another protected folder stops at a card as if it were named; Claude Code and Qoder don't say where their shell stands, so their commands are judged at the project root (a `cd` into a protected folder is itself a card).
- **Ready**: KOLONİ's own cards have fixed titles and say **KOLONİ asks**; an agent's question says **The agent asks**, so it cannot pass for one of KOLONİ's.
- **Workspace**: sub-agents work in working copies, not in your folder, until you take their work in.
- **Agents**: your home folder and a drive's root cannot be a project, and KOLONİ's own folder is never opened, even inside a project; a CLI's own Grep and Glob cannot search it either ([docs](docs/security/model.md#places-agents-never-open)).
- **Agents**: web pages, search results, MCP results, knowledge, a GitHub issue and a learned repository's code reach agents framed as data, not instructions; the frame tells the model, it is not a wall; text that tries to give orders shows a **Text tried to give orders** card ([docs](docs/security/model.md#outside-content)).
- **Settings**: secret files open only on your **Allow once** and searches skip them (at Full auto a command that doesn't name the file can still read it); keys in command output show as `***`; variables with secret names are kept from commands and CLIs unless you name them ([docs](docs/security/model.md#secrets)).
- **Settings**: a planted test key stops a command, web request, browser or MCP call that would send it out.
- **Chat**: an agent asks for a key on a **Give a secret to its commands?** card; the value never reaches the model or the record, and never leaves on a branch ([docs](docs/security/model.md#a-secret-you-give-on-a-card)).
- **Triggers**: turns nobody watches may do only what the trigger allows, and never start a CLI that works with its own tools ([docs](docs/use/permissions.md#turns-nobody-watches)).
- **Tools**: commands can run in a fresh Docker container, with the network off unless you allow it ([docs](docs/security/model.md#other-walls)).
- **Tools**: MCP servers get only their own variables and what programs need to run, none of KOLONİ's or a CLI's sign-in; one you have not trusted asks before every call ([docs](docs/tools/mcp.md)).
- **Tools**: web searches and requests reach only public addresses; the agents' browser opens only previews and the sites you allow.
- **CLIs**: on Windows, a CLI and everything it starts run in a Windows job that is ended on Stop or when KOLONİ closes.
- **Docs**: the guide at `/guide/` loads its scripts, styles, fonts and pictures only from KOLONİ itself.
- **Docs**: report a security problem privately through GitHub's Security tab ([docs](SECURITY.md)).
