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

### 0.1.10

- **Pages and A test for the change are off unless ticked.** In Settings › This project › Checks
  and git › **Check by kind of work**, a project that never changed **Pages** has it off from now
  on, and **A test for the change** is a new box, off. A turn that wrote a page says "Not checked:
  pages switched off for this project", and one that changed code and no test says "Not checked: a
  test for the change switched off for this project". Tick them to have them as before (see
  [What KOLONİ checked](../use/checked.md#a-test-for-the-change)). Nothing in the database changes.
- **The Board page is gone.** How each chat stands is on the **Chats** list, what waits for you on
  **Ready for you**, and a file two chats want still shows above both of them. Its **Re-run the ones
  that failed** button went with it: ask the chat's Orchestrator to open those sub-agents again. Nothing
  in the database changes.
- **The Word, Excel, PowerPoint and 3D model previews are gone.** Such a file is still in the
  Workspace's files and opens there as any other file that is not a page or a picture: its text where
  it is text of 256 KB at most (an OBJ, a text STL, a glTF), else "Not text: there is no code to show."
  or "Too large to show: over 256 KB."; one only in an agent's working copy so far says "It could not
  be read." until its work is taken in. Open it in its own program from the project's folder. A Word, Excel or PowerPoint file an agent made is still listed among its outputs on the
  canvas and still checked; a 3D model is no longer an output, and an agent can no longer `show` one.
  Nothing in the database changes.
- **The Observer is gone.** At the first start the database is upgraded (migration 0190), after KOLONİ
  copies it to `runtime/data/backups/`: the built-in Observer role, the switch **Have a model look over
  each sub-agent's report** and the observations kept on agents are deleted, and an agent's window no
  longer shows one. What the Orchestrator was told then stays in its chat. A role of your own named
  "Observer" stays as it is. What a sub-agent's record shows is in **Checked** and **No file changed**
  (see [What KOLONİ checked](../use/checked.md)). To go back to 0.1.9, stop KOLONİ, return to 0.1.9 and
  put that copy back in place of `runtime/data/koloni.db`.
- **Triggers are gone.** At the first start the database is upgraded (migration 0189), after KOLONİ
  copies it to `runtime/data/backups/`: your triggers, their runs, their record and the triggers agents
  proposed are deleted, and **Propose triggers** is taken off every role, your own too. The turns triggers
  started stay in their chats as they were. What still starts by itself: ☾ Away's jobs, a chat's queue of
  To-do tasks and the day's summary. To go back to 0.1.9, stop KOLONİ, return to 0.1.9 and put that
  copy back in place of `runtime/data/koloni.db`; your triggers come back with it.
- **Codex's One run per model step is gone.** A Codex provider saved so runs as **One session per agent**,
  and its window shows that. On a model server of your own a Codex session is not yet measured: try it
  there knowing that, or set **How it runs** to **Native**. See
  [Set up a CLI](../models/setup-cli.md#how-it-runs).
- **The notification address is gone.** The database upgrade deletes a project's web hook address and
  the form it was posted in: notifications go to the desktop alone (Settings › This project ›
  Notifications › **Show a desktop notification**, Windows only). A project whose day's summary went
  only to the address has its summary's time emptied: switch the desktop on and set the time again.
  Going back to 0.1.9 brings neither back. The copies in `runtime/data/backups/` made before the
  upgrade and at the first start of a day still hold the address: delete them once you no longer
  need them if it is a secret.
- **The search by meaning is gone.** The database upgrade deletes the vectors it kept and the provider
  and model a project chose for it. Search deeper and an agent's recall match words, as before. Going
  back to 0.1.9 brings the setting back off.

### 0.1.8

- **The database** is upgraded at the first start (migrations 0176 to 0182), after KOLONİ copies it to
  `runtime/data/backups/`. Your chats and tasks are kept: To-do tasks become tasks of no story, a task
  left at work goes back to todo, and a Qoder provider is switched off, not removed. Only To-do's six
  Run settings are dropped (below). To go back to 0.1.7, stop KOLONİ and put that copy back in place of
  `runtime/data/koloni.db`.
- **To-do: Run the backlog, Runs by itself and Run settings are gone.** Tick tasks on To-do and press
  **Do in chat**: they wait in that chat's queue and run there one by one, your own messages first. A
  project whose To-do ran by itself stops; the Run settings (level, model, who changes the files) are
  not kept anywhere. See [Doing tasks in a chat](../automation/todo.md#doing-tasks-in-a-chat).
- **A To-do task's turn is its chat's**: at that chat's permission level and on its model (a CLI with
  tools of its own too), asking on its cards there - no longer under a night's rules. Look at the level
  of a chat before you give it tasks.
- **A story works on its own git branch** (`koloni/…`) in a project in git: nothing of it is in your
  project until **Close the story** checks the branch and merges it or opens a pull request. See
  [A story's branch](../automation/todo.md#a-storys-branch).
- **☾ Away** runs its jobs at the level of the chat you go away from, no longer the lower of it and the
  To-do page's. See [Work while you're away](../automation/overnight.md).
- **Copilot on your GitHub account**: once the Models page or the chat's model panel opens, KOLONİ asks
  your account what it offers and switches off the models your plan does not list ("not on your Copilot
  plan now"). Look at the Copilot provider's **Models** tab. See
  [Copilot on your GitHub account](../models/copilot.md#models).
- **Copilot run Native**, and **Codex run Native** with **Sign-in: Its own for KOLONİ**, now go on in their
  session from the topic's last turn. Press **New topic** for other work. See
  [Going on from the last turn](../models/setup-cli.md#going-on-from-the-last-turn).
- **Some Always run rules cover less.** A rule no longer covers ruff's or eslint's `--fix` past its words,
  nor another of their options that writes or loads code. A rule for a runner or tsc (`uv run ruff`,
  `pip install -e .`, `npm install`, `npx tsc`) no longer covers its line while an agent's write of a
  `pyproject.toml`, a lock (`uv.lock`, `package-lock.json`, …) or a `tsconfig*.json` in the project still
  stands, until your own edit or install replaces it. Below Full auto such a line asks on its card; in a
  trigger's turn it is not run. See [What a rule never covers](../use/permissions.md#what-a-rule-never-covers).
- **Work in a copy whose check by kind of work still fails** (a page, a document, a config file, a script)
  is no longer taken in, at any level: press **Take in anyway** or **Fix it**. See
  [What KOLONİ checked](../use/checked.md#what-each-line-means).
- **Kept working copies** are now listed in Settings › The app › [Your data](../settings.md#your-data). A
  trigger over its budget kept one at each run: discard what you no longer need.
- **Longest command**: every project keeps 10 minutes. Raise it in Settings › This project ›
  [Commands and secrets](../settings.md#commands-and-secrets) where your tests or a build take longer.
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
