# Folder layout

## KOLONİ's own data: `runtime/`

In KOLONİ's folder, or wherever `KOLONI_RUNTIME_ROOT` says.

| Path | What it holds |
|---|---|
| `data/koloni.db` | The database. API keys are in it, in plain text. |
| `data/backups/` | Copies of the database made before upgrades and by the update script (the last five). |
| `logs/koloni.log` | The log; it rotates at 10 MB and keeps five old files. |
| `attachments/` | Files attached to messages, per chat. |
| `skills/` | KOLONİ's copies of skills. |
| `copies/` | Sub-agents' working copies (see below). |
| `cli-homes/` | Claude Code's and Codex's sign-in folders, one per provider, when you chose **Its own for KOLONİ**. Kept across restarts. |
| `server-homes/` | Empty settings folders for Claude Code and Codex when they run on a model server of your own, with none of your sign-in. |
| `agy-home/` | A new folder for each agy run, cleared when KOLONİ starts. |
| `models_dev.json` | The model catalogue, once updated. |
| `local-server.json` | The Server tab's settings. |
| `before-restore/` | Your data as it was before a restore. Never removed by KOLONİ. |

`runtime/` is in `.gitignore`.

## Outside `runtime/`

- **Working copies**: if `runtime/copies` would be inside a git repository (as it is in KOLONİ's own
  folder), copies go to `%LOCALAPPDATA%\KOLONI\copies` on Windows, or `~/.local/share/KOLONI/copies`
  elsewhere.
- **GitHub Copilot CLI** gets an empty settings folder inside each run's temporary folder, removed
  when the run ends. It signs in with the provider's token, or else with your own `gh` login.
- **Qoder** uses your own sign-in and settings folder (`~/.qoder`); KOLONİ gives it no folder of its own.
- **Claude Code and Codex** with **My own** sign-in use yours (`~/.claude`, `~/.codex`).
- **MCP servers** start in `%LOCALAPPDATA%\KOLONI\mcp` on Windows, `~/Library/Caches/KOLONI/mcp` on
  macOS, or `~/.cache/KOLONI/mcp` on Linux.

## In your project

KOLONİ's own files are under `.koloni/`; see [Recipe, role and skill formats](formats.md). KOLONİ never
changes your project's own `.gitignore`. Files you save from a message go to `docs/attachments/`.

## What an export holds

**Export everything** holds the database, `skills/`, `attachments/`, `models_dev.json` and
`local-server.json`. It does not hold your projects, their `.koloni/`, working copies, logs, CLI sign-ins
or the database backups. See [Backup and update](../backup-and-update.md).
