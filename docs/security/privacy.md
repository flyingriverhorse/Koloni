# Data and privacy

KOLONİ runs on your machine and listens on `127.0.0.1` only. It sends no telemetry.

## Where your data is

Everything KOLONİ keeps is under `runtime/` in its folder, or under `KOLONI_RUNTIME_ROOT` if you set it:

| Where | What |
|---|---|
| `data/koloni.db` | The database: chats, agents, providers, memory, triggers, usage, settings. |
| `data/backups/` | Copies of the database made before upgrades (the last five). |
| `logs/koloni.log` | KOLONİ's log. It rotates at 10 MB and keeps five old files. |
| `attachments/`, `skills/` | Files you attached, and KOLONİ's copies of skills. |
| `copies/` | Sub-agents' working copies. |

If `runtime/` is inside a git repository, working copies go to `%LOCALAPPDATA%\KOLONI\copies` on
Windows, or `~/.local/share/KOLONI/copies` elsewhere. MCP servers start in KOLONİ's own folder in your
cache (`%LOCALAPPDATA%\KOLONI\mcp` on Windows).

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
  Their messages, their agents' work and their usage go too.
- **Providers, triggers, roles, skills, MCP servers, teams, recipes, knowledge** and **To-do tasks** can
  each be deleted on their page.
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
