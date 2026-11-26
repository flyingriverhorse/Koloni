# Built-in tools

Tools are what agents can do: read files, run commands, search the web and more. Open **Tools** on the
left rail. The page has three tabs: **Built-in**, **Servers** and **Skills**. The **Add** button next
to the heading adds a server or a skill.

## The Built-in tab

"KOLONİ's own tools; one switched off is given to no agent." Five of them can be switched off for
every agent at once:

| Tool | What it does |
|---|---|
| **Search the web** | "Looks things up on the web: a few results with their addresses" |
| **Web requests** | "Calls an address on the internet and reads its answer" |
| **Read attached files** | "Reads the text of files you attach to a message: code, PDF, Word" |
| **Read earlier output again** | "Reads the whole output of an earlier command or tool in this chat that was cut short" |
| **Diagram pictures** | "Draws a draw.io diagram of the project as a PNG or SVG picture beside it" |

A tool switched off here is given to no agent, whatever its role says. Claude Code's and Codex's own
web tools switch off with **Search the web** and **Web requests**. While either is off, a command that
reaches the internet (`curl`, `git clone`, an `https` address) asks you on a card at every level, Full
auto too.

## Every tool, by group

Which tools an agent has is set per role, on the role's **Tools** tab on the Agents page. There they
are grouped like this. "Asks" means it waits for your card, as the chat's permission level says (see
[Permission levels](../use/permissions.md)).

| Group | Tools |
|---|---|
| **Files** | List folders · Read files · Search · Look at images · Write files (asks) · Edit files (asks) · Show you a file · Diagram pictures · Ask for a folder |
| **Commands** | Run commands (asks) |
| **Web** | Search the web (asks) · Web requests (asks) |
| **Browser** | Open a page · Screenshots · Click · Type · Press keys · Scroll · Read the page · Console |
| **Team** | Notify you · Open sub-agents · New roles (asks) · New skills · Ask you · Message agents · Discussions · Leave notes · Read notes |
| **To-do** | Read the To-do list · Add tasks (asks) · Change tasks (asks) |
| **Memory** | Remember · Recall |

New skills and Ask for a folder always go to a card too.

A role with **Run commands** also gets two tools for a command that keeps running in the chat (a dev
server), in a turn you watch: one reads what it printed since, the other stops it - only one the agent
started itself. See
[Preview](../use/chat-and-canvas.md#preview).

The Orchestrator, at its own work in a project, also has **run_checks**: KOLONİ's checks of its work
now - the tests, the type and style checks, the Reviewer and the live try, as the turn's end runs
them -, waited for. Its answer starts with `CHECKS: green`, `CHECKS: red` or `CHECKS: not complete`.
Say "if the tests pass, commit it" and the Orchestrator commits only on green. A red answer is no fix
round, and the turn's end still runs its own checks. See
[Checks on asking](../use/checked.md#checks-on-asking).

It also has **read_status**, which only reads: KOLONİ's records of this project, now - what waits for
you (cards, what a night parked, the morning's push, To-do proposals, tasks at "done?"), work kept and
not taken in, the `koloni/` branches on record with their commits where KOLONİ counted them, this
month's spend against the budget - turns with no price said apart, never a made-up zero - (and a
night's against its money limit while you're away), and the
newest 10 decisions taken for you. It never reads another project's, nor git or the network. Every
command, path, question, title and reason in it is an agent's or your words: masked, cut and quoted
as data, with KOLONİ's note where it reads like orders. Its answer is at most 3 KB; past that, whole
lines are left out and a last line says how many. A sub-agent is not given it, nor a side of a
comparison, nor an Orchestrator
whose role has no To-do tools.

A role needs at least one tool. Tools from MCP servers and skills are given to roles on the Tools page;
see [MCP servers](mcp.md) and [Skills](skills.md).

## Big files

- **Write files** and **Edit files** leave a file larger than 1 MiB alone, and do not make one larger
  than that. To replace such a file, the agent is told to run a command, which **Revert** cannot take
  back, or to write the new content to another file.
- **Search** does not read files over 256 KB. Its answer names them, up to five and then how many more,
  so the agent can read them in parts or search them with a command. Big binary files are left out
  without a word.
