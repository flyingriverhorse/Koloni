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

0.1.10 makes KOLONİ smaller: Board, triggers, the Observer, the Office and 3D previews, rooms, the
notification address (Slack, Discord), the search by meaning, Usage's Cards and Codex's One run per model
step are gone, and eight of the eleven ready teams. At its first start the database is upgraded by eight
migrations, 0189 to 0196, after KOLONİ copies it to `runtime/data/backups/`. **Copy
`runtime/data/koloni.db` yourself before you update too** (with KOLONİ stopped): what these migrations
delete - your triggers, the Observer's role and its observations, the notification address, the search by
meaning's vectors, the eight ready teams - comes back only with such a copy, put back in place of
`runtime/data/koloni.db` under 0.1.9.

| Migration | What it does to your data (each is told below) |
|---|---|
| 0189 | Triggers are gone: your triggers and their records are deleted. |
| 0190 | The Observer is gone: its role, its switch and the observations on agents are deleted. |
| 0191 | The notification address is gone: deleted. |
| 0192 | The search by meaning is gone: its vectors and the model chosen for it are deleted. |
| 0193 | Rooms are gone: `open_room` is taken off every role, a recipe's Room step becomes an **All at once** group. |
| 0194 | Three ready teams: the other eight go where they are as they came. |
| 0195 | Feature, Model change and Pipeline change run fewer agents, where they are as KOLONİ made them. |
| 0196 | Project notes are Memory's: their lines are copied into Memory; a To-do task of no story gets a notebook. |

- **New worktrees and copies go into your project's `.koloni/`.** A branch's worktree (a ☾ Away job's,
  a team's on a branch) is made in `.koloni/worktrees/`, and in a project with no git a sub-agent's copy
  in `.koloni/copies/`; in a project in git copies stay outside it, as before. The first worktree adds
  `/.koloni/worktrees/` and `/.koloni/copies/` to the repository's `.git/info/exclude`, so `git status`
  stays clean. Copies and worktrees kept from before stay where they were made and are decided there
  (see [Where copies and worktrees are](../use/workspace.md#where-copies-and-worktrees-are)). Nothing
  in the database changes.
- **`KOLONI_TRIGGER_CLOCK` is now `KOLONI_CLOCK`.** A `.env` that sets the old name keeps working for
  one more release; rename it to `KOLONI_CLOCK` (see [Environment variables](environment.md)).
- **Settings' sections have new names.** This project's eleven sections are seven, by job: **How agents
  work** (what was Agents, New chats start with and Slash commands), **When you're asked** (Asking and away,
  Runs without asking - its rules behind **Show the rules** - and Commands and secrets), **When the work is
  done** (Checks and git), then Limits and money, Memory and web, Notifications and This folder as they were.
  No setting is gone: the ones few change, Docker and the secret variables among them, are under a
  section's **More**. Ctrl+K and the links still find a section by its old name. Nothing in the database
  changes (see [Settings](../settings.md#this-project)).
- **Full auto's judge with no model to ask makes cards.** At **Full auto**, where no **Judge model** can be
  asked and the Fast tier has none, each command the judge would look at now waits for you on a card - it
  ran unasked before. Fill the Fast tier on the Models page, or turn the judge off for the project to have
  Full auto as it was before the judge (see [Full auto's judge](../use/permissions.md#full-autos-judge)).
- **At Full auto the judge decides a plain delete in the project.** In a chat you watch at **Full auto**
  with the judge on, a delete or an emptying in the project, git work thrown away and a stop by name,
  written as a plain line, go to the judge instead of a card: **fine** runs, **risky** is refused (or its
  card, with **Ask me**). Whatever reaches out of the project, a line that is not plain, and every level
  below Full auto keep their cards; a git remote's branches overwritten or deleted (`git push --force`)
  wait on a card at every level, whatever your words say (see
  [What the judge decides in place of the list](../use/permissions.md#what-the-judge-decides-in-place-of-the-list)).
- **Native is experimental.** Claude Code, Codex and Copilot offer **Native** under **Experimental**
  in **How it runs** only with **Show experimental features** on (Settings › The app › Agents; the switch
  that was **Show experimental CLIs**, kept as you had it). A provider you already run Native keeps working
  as before, its card tagged **Experimental**. Nothing in the database changes.
- **Pages and A test for the change are off unless ticked.** In Settings › This project › When the
  work is done › **More** › **Check by kind of work**, a project that never changed **Pages** has it off from now
  on, and **A test for the change** is a new box, off. A turn that wrote a page says "Not checked:
  pages switched off for this project", and one that changed code and no test says "Not checked: a
  test for the change switched off for this project". Tick them to have them as before (see
  [What KOLONİ checked](../use/checked.md#a-test-for-the-change)). Nothing in the database changes.
- **Project notes are Memory's.** At the first start the database is upgraded (migration 0196), after
  KOLONİ copies it to `runtime/data/backups/`: where the Orchestrator had a project's **Project notes** on
  (Agents › **Lead** › **Knowledge**), their lines, as the folder's
  `.koloni/knowledge/project-notes/learned.json` lists them, are copied into the second box under
  **This project's rules** in Memory's **Your words** - the newest that fit in 4 000 characters. Notes you had
  switched off, or never switched on, are not copied. The folder is only read; the knowledge and its pages
  stay in the database and in the folder, but no role is given it and the Knowledge page no longer lists it.
  Lines not copied are still in the folder's `pages/`: add them in the box if you want them. From now on the
  box is the switch: what is in it, the Orchestrator is given every turn. A To-do task of no story gets a notebook of
  its own (empty). Going back to 0.1.9 drops both, and 0.1.9 has its Project notes knowledge as it was:
  Project notes you keep and tasks' notebooks written after the upgrade go with them (the copy in
  `runtime/data/backups/` is the database as it was before the upgrade, without them).
- **Knowledge is the Memory page's second part.** The rail's **Knowledge** is gone: press **Memory**,
  then its tab **Sources to look things up in** (or Ctrl+K, **Knowledge**). Agents look things up with
  **Recall**, which also reads the pages of a role's knowledge; a role, recipe or prompt of yours that
  names `lookup` keeps working in 0.1.10 - name **recall** instead before the next release. Nothing in
  the database changes.
- **The Board page is gone.** How each chat stands is on the **Chats** list, what waits for you on
  **Ready for you**, and a file two chats want still shows above both of them. Its **Re-run the ones
  that failed** button went with it: ask the chat's Orchestrator to open those sub-agents again. Nothing
  in the database changes.
- **Ready is Work, with To-do in it.** The rail's **Ready** is now **Work**, and its **To-do** is gone:
  Work has two tabs, **Ready for you** and **To-do**, each story on To-do a card that opens in a panel
  (Ctrl+K's **Work › To-do** and a chat's **Open it in To-do** bring you to that tab). What waits for your
  word on To-do is in Ready for you's one list; the rough note's button is **Split into tasks**. Nothing in the database changes (see [To-do](../automation/todo.md)).
- **To-do has no goal level.** Your stories stand at the top of the tree, those a goal held too; a
  story's **⋯** no longer offers **Goal**, and the Hive keeper writes a note as stories and tasks only.
  Your goals are not deleted: they stay in the database, and nothing in it changes.
- **Three ready teams.** At the first start the database is upgraded (migration 0194), after KOLONİ
  copies it to `runtime/data/backups/`: of the ready teams only **Web app**, **Quality** and **Docs**
  stay as they were. Backend / API, Data, DevOps, Research, Product, Maintenance, ML and DataOps go
  where they are as they came, with their stages and coordinators; one you changed or use (picked in a
  chat in **Manual**, kept for a project's new chats, named by a recipe's step) stays as your own team.
  Every role and recipe stays. Fourteen built-in roles are now in no ready team (Architect, Database
  engineer, Performance engineer, Data analyst, Researcher, DevOps, Dependency keeper, Hive keeper,
  Scout, Data scientist, ML engineer, Model evaluator, MLOps engineer and Data engineer). The
  Orchestrator still opens them where the work needs one: with **Orchestrator decides** the teams it
  picks are where it starts, not a fence, and any built-in role opens beside them (not while a recipe's
  step holds it to its roles). In **Manual** it reaches one only when you name it, a recipe's step names
  it, or you put it in one of the chat's teams
  ([Which roles the Orchestrator opens](../agents/teams.md#which-roles-the-orchestrator-opens)).
  Going back to 0.1.9 does not bring the eight teams back: only that copy
  does - stop KOLONİ, return to 0.1.9 and put the copy back in place of `runtime/data/koloni.db`.
- **The Word, Excel, PowerPoint and 3D model previews are gone.** Such a file is still in the
  Workspace's files and opens there as any other file that is not a page or a picture: its text where
  it is text of 256 KB at most (an OBJ, a text STL, a glTF), else "Not text: there is no code to show."
  or "Too large to show: over 256 KB." - one only in an agent's working copy so far is read there, as
  its preview was. Open it in its own program from the project's folder. A Word, Excel or PowerPoint file an agent made is still listed among its outputs on the
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
- **Three ready recipes run fewer agents.** The database upgrade (migration 0195) redraws **Feature**,
  **Model change** and **Pipeline change** where they are still as KOLONİ made them, without their Tester
  and general Reviewer steps: KOLONİ's own Checks step at a recipe's end already runs the tests and has a
  big or security-touching change reviewed. Feature is Write the spec → Build it → UI review; Model change
  keeps its plan, its experts' review, the build and Compare the metrics; Pipeline change is Change the
  pipeline → Check the data quality. The three check their tests and a review themselves, even in a project
  at **Nothing**. Your copies keep their steps: copy one again and add a step to have a Tester or a Reviewer
  of the recipe's own (see the [Recipe cookbook](../agents/recipe-cookbook.md)). Going back to 0.1.9 draws
  them as before.
- **Codex's One run per model step is gone.** A Codex provider saved so runs as **One session per agent**,
  and its window shows that. On a model server of your own a Codex session is not yet measured: try it
  there knowing that, or set **How it runs** to **Native**. See
  [Set up a CLI](../models/setup-cli.md#how-it-runs).
- **The notification address is gone.** The database upgrade (migration 0191) deletes a project's web hook address and
  the form it was posted in: notifications go to the desktop alone (Settings › This project ›
  Notifications › **Show a desktop notification**, Windows only). A project whose day's summary went
  only to the address has its summary's time emptied: switch the desktop on and set the time again.
  Going back to 0.1.9 brings neither back. The copies in `runtime/data/backups/` made before the
  upgrade and at the first start of a day still hold the address: delete them once you no longer
  need them if it is a secret.
- **The search by meaning is gone.** The database upgrade (migration 0192) deletes the vectors it kept and the provider
  and model a project chose for it. Search deeper and an agent's recall match words, as before. Going
  back to 0.1.9 brings the setting back off.
- **Rooms are gone.** At the first start the database is upgraded (migration 0193), after KOLONİ copies
  it to `runtime/data/backups/`: `open_room` is taken off every role, your own too; what a room may
  spend is taken off every project and chat; each Room step of your saved recipes becomes an **All at
  once** group in its place, a step for each of its roles (its arrows and loops kept); a room left
  running is ended; and each turn that had a room gets one line in its chat, "A room was opened here.
  Rooms were removed in 0.1.10 …". The steps of a converted group are named "<the step's name> ·
  <role>". The rooms themselves and what was said in them stay in the database,
  untouched. A recipe file in a folder's `.koloni/recipes/` is read the same way as it loads, and is
  written in the new form the next time you save it. In a Room step that reviewed, a role that does the
  recipe's work at a step of its own works in the group and the others review - where every role does,
  all of them keep reviewing and the recipe says which "would check its own work": take that role out.
  A Room step that ran only if a problem was found now always runs. A saved recipe that no longer reads
  (a Room step near the 60-step limit, as a group past it) is listed under the recipes that are not
  read, with why. A room between teams no longer leaves its decision on the notebook or in
  `.koloni/shared/decisions/`; the files there stay readable, and teams agree through `contracts/`.
  For agents talking a question through, ask for a [discussion](../agents/discussions.md); for
  work at the same time, sub-agents or a recipe's **All at once** step. To go back to 0.1.9, stop
  KOLONİ, return to 0.1.9 and put that copy back in place of `runtime/data/koloni.db` - a downgrade of
  the database alone gives the room budgets back at their defaults, not the values you had.

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
  [When you're asked › More](../settings.md#commands-and-secrets) (Commands and secrets before 0.1.10) where your tests or a build take longer.
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
  project from before keeps what it had: turn it on under Settings › This project › When you're asked
  (Asking and away before 0.1.10).
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
