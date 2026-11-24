# Data and privacy

KOLONİ runs on your machine and listens on `127.0.0.1` only. It sends no telemetry.

## Where your data is

Everything KOLONİ keeps is under `runtime/` in its folder, or under `KOLONI_RUNTIME_ROOT` if you set it:

| Where | What |
|---|---|
| `data/koloni.db` | The database: chats, agents, providers, memory, triggers, usage, settings. |
| `data/backups/` | Copies of the database made before upgrades (the last five) and at the first start of a day (the last three). |
| `logs/koloni.log` | KOLONİ's log. It rotates at 10 MB and keeps five old files. |
| `attachments/`, `skills/` | Files you attached, and KOLONİ's copies of skills. |
| `copies/` | Sub-agents' working copies. |
| `cli-homes/<provider id>/` | The sign-in folder of a Claude Code or Codex provider set to **Sign-in: Its own for KOLONİ**: its login and its settings. Claude Code run **Native** keeps its sessions there (each one's `projects/…/<session>.jsonl` and `file-history/<session>`), for a topic's next turn to go on in ([Topics](../memory.md#topics)). A session no turn will go on in is removed; the last one of each topic stays until its chat is deleted. |
| `cli-homes/copilot-sessions/<id>/` | The home (`COPILOT_HOME`) of a GitHub Copilot session run **Native**, one folder per session: Copilot's own record of it (`session-state/`), kept for the topic's next turn to go on in ([Topics](../memory.md#topics)). Removed when a turn starts a new session instead, when the session grows past its bound (see [Going on from the last turn](../models/setup-cli.md#going-on-from-the-last-turn)), when a turn of yours starts in another topic (**New topic**, or back in an older one; a trigger's topic keeps its own), with its chat or project, and at KOLONİ's start for one no agent goes on in (left by a turn KOLONİ was closed in). An agent's command that names it is asked about at every level, as one naming a sign-in folder. |
| `server-homes/` | Empty homes for Claude Code or Codex run on your own model server, so that none of your own sign-in or settings is used. They are not removed. |
| `agy-home/` | agy's home for one run, removed after it and at each start. |

If `runtime/` is inside a git repository, working copies go to `%LOCALAPPDATA%\KOLONI\copies` on
Windows, or `~/.local/share/KOLONI/copies` elsewhere. MCP servers start in KOLONİ's own folder in your
cache (`%LOCALAPPDATA%\KOLONI\mcp` on Windows).

GitHub Copilot never uses your own `~/.copilot`. Run **Native**, a new session starts in an empty home
of its own under `cli-homes/copilot-sessions/` (above), kept while its topic goes on. Run as a session -
and in a discussion, where a Native Copilot speaks as a session - its home is an empty `home` in a
`koloni-cli-…` folder in the system's temp folder (`koloni-limits-…`
for KOLONİ's own short questions: its version, what is left of your plan), removed when its run ends. On
GitHub's plan it signs in with the token you gave the provider, or else your own `gh` login.

KOLONİ's own files in a project are under `.koloni/`: rules, settings, recipes and Knowledge.

**API keys are kept in plain text** in the database and its backups. They are never sent back to the
browser, and they are hidden in logs and in command output. Keep `runtime/` private.

## What leaves your machine

Only these, and each only when you set it up or an agent is allowed to:

1. **Model providers**: your messages and the agents' work go to the providers you add. CLIs talk to
   their own vendors.
2. **Search by meaning**: text goes to the provider you picked for it on the Memory page.
3. **Web searches**: to your own SearXNG if you set one, then DuckDuckGo and a CLI's search, in the
   order you set, and last the Anthropic API with a provider's key. Below Full auto a search asks first,
   unless you allowed searching in that chat.
4. **Web requests** agents make, to public addresses, after a card or a rule.
5. **The agents' browser**: previews on this machine, and sites you allowed.
6. **Notifications**, to the address you set.
7. **Voice**: Gemini's voices send the text they read to Google, only with your key. Speech recognition
   is your browser's: in Chrome and Edge what you say is sent to Google's or Microsoft's service. A
   system voice marked online sends what it reads to its maker. KOLONİ keeps no sound and sends none.
8. **The model catalogue** (models.dev): when you press **Update catalogue**, and at a start once your
   copy is a week old, unless **Keep the catalogue fresh** is off or `KOLONI_CATALOGUE_REFRESH=0`.
9. **Skills from GitHub**, when you read or add one.
10. **Checking an MCP package**: its name to npm or PyPI, and to osv.dev for known malware, when you
    ask.
11. **Knowledge**: the pages a topic learns from, its research searches, and a repository cloned
    from GitHub when you press **Learn**.
12. **Pull requests**: pushing a branch and opening a pull request, when you choose that.
13. **Plan and balance checks**: when you press **Check now** or **Read now**.
14. **What agents' commands and MCP servers reach.** MCP servers run with your own rights, outside
    KOLONİ's cards.

## Deleting

- **Chats**: archive them first, then delete them from the archive. "This cannot be undone in KOLONİ."
  Their messages, their agents' work and their usage go too, and the Claude Code sessions their agents
  kept under `cli-homes/` (each one's transcript and file history; anything else Claude Code keeps of a
  session stays), and their Copilot sessions' homes under `cli-homes/copilot-sessions/`, whole.
- **Providers, triggers, roles, skills, MCP servers, teams, recipes, knowledge** and **To-do tasks** can
  each be deleted on their page. A provider's sign-in folder under `cli-homes/` goes with it, its login
  and kept sessions with it.
- **Memory** is never deleted from the page: removing a fact hides it from agents and keeps it in
  History.
- **A project** is deleted in Settings › This project › This folder, once you type its name: its chats, memory,
  knowledge, To-do tasks, triggers and usage go, with the files KOLONİ kept of its chats under `runtime/`
  (attachments, CLI sessions), as a chat's delete takes them. Its folder, its git and its `.koloni/` stay.
- **Old live updates** go by themselves: at each start, KOLONİ deletes the events older than 30 days that
  it sent to the page, each tool call with its arguments and result among them. Chats, messages and the
  agents' work are kept apart and stay. **Text tried to give orders** warnings are kept.

To remove everything, stop KOLONİ and delete its `runtime/` folder, and KOLONİ's folders named above
(`KOLONI` under `%LOCALAPPDATA%` or your cache), if they were used.
