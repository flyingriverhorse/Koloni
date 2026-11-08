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
| **Team** | Notify you · Open sub-agents · New roles (asks) · New skills · Ask you · Message agents · Open rooms · Discussions · Propose triggers · Leave notes · Read notes |
| **To-do** | Read the To-do list · Add tasks (asks) · Change tasks (asks) |
| **Memory** | Remember · Recall |

New skills, Ask for a folder and Propose triggers always go to a card too.

A role needs at least one tool. Tools from MCP servers and skills are given to roles on the Tools page;
see [MCP servers](mcp.md) and [Skills](skills.md).

## Big files

- **Write files** and **Edit files** leave a file larger than 1 MiB alone, and do not make one larger
  than that. To replace such a file, the agent is told to run a command, which **Revert** cannot take
  back, or to write the new content to another file.
- **Search** does not read files over 256 KB. Its answer names them, up to five and then how many more,
  so the agent can read them in parts or search them with a command. Big binary files are left out
  without a word.
