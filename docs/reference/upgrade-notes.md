# Upgrade notes

## What happens when you upgrade

1. **Back up first.** The update script backs the database up to `runtime/data/backups/` before it pulls
   the new version. For more, use Settings › The app › Your data › **Export everything**.
2. **Update**: stop KOLONİ, then run `./scripts/update.ps1` (Windows) or `./scripts/update.sh`. See
   [Backup and update](../backup-and-update.md).
3. **Start KOLONİ again.** If the new version changes the database, KOLONİ copies it to
   `runtime/data/backups/` and then upgrades it. It keeps the last five copies there, the update
   script's included; the copies it makes at the first start of a day (`daily-…`, the last three)
   are apart from those.

If something goes wrong, the copies in `runtime/data/backups/` are whole databases. Stop KOLONİ before you
put one back in place of `runtime/data/koloni.db`.

## Version by version

Only what needs your attention after an update; everything else is in the [Changelog](../changelog.md).

### 0.1.8

- **Qoder** is no longer run. A Qoder provider is kept, switched off for good, with its settings; its card
  says "no longer supported". If Qoder was your default provider (the first on the Models page), make
  another provider the default or delete Qoder: until then the chats, triggers and To-do turns that run on
  the default fail with that reason. A chat or a role set to Qoder fails the same way until you pick
  another model. See [Qoder is no longer supported](../models/setup-cli.md#qoder-is-no-longer-supported).
- **agy**, and Codex run **One run per model step**, are offered only with **Show experimental CLIs** on
  (Settings › The app › Agents). A provider already set up so keeps working, tagged Experimental. See
  [Experimental CLIs](../models/setup-cli.md#experimental-clis).

### 0.1.5

- **When you're away**: a new project lets the Orchestrator decide a waiting card after 5 minutes. A
  project from before keeps what it had: turn it on under Settings › This project › Asking and away.
  See [Answering for you](../automation/answering-for-you.md).
- **A harmful-looking command at Full auto** stays **Ask me**, and **Agents may delete what is
  disposable without asking** stays off, in every project, until you turn them on there. See
  [Check what I said first](../use/permissions.md#check-what-i-said-first) and
  [Disposable deletes](../use/permissions.md#disposable-deletes).
- The "While you're away" card is gone: press **☾ Away** on a chat's status line, or **Go away** on
  the Orchestrator's line. See [Work while you're away](../automation/overnight.md).
- **Plan first** is in the permission level's menu (or `/plan`); the button beside the level is gone.
- No agent's window opens by itself any more: open it from the window icon on its box, a double click,
  **Open window** in the Inspector, or the Orchestrator's name over its turn.
- GitHub Copilot CLI: KOLONİ runs the version Copilot itself reports, also after Copilot updated
  itself; from 1.0.114 on it runs **Native** again. See
  [Set up a CLI](../models/setup-cli.md#github-copilot-cli).
- A team's branch now starts from your folder as it is, your uncommitted files too, and its merge waits
  for your commit where the agent changed what you had not committed. Your repository's git hooks do
  not run for the agent's commits on its branch. See [Branches](../use/workspace.md#branches).

### 0.1.2 to 0.1.4

Nothing to do.

### 0.1.1

- A project that already had **Project notes** keeps them off for the Orchestrator: switch them on once
  on the Agents page, the **Lead** role, **Knowledge** tab. See [Project notes](../knowledge.md#project-notes).
- The Orchestrator no longer stops at a fixed count of steps. A limit of your own goes on the **Lead**
  role. See [Step limits](../agents/step-limits.md#the-orchestrator-no-step-count).
