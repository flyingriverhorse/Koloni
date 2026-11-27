# Known limits

What KOLONİ does not do yet, or does only in part.

## An alpha

KOLONİ is an alpha (0.1.x): expect rough edges. Several paths were built against stand-ins only,
including the **Server** tab for llama.cpp, Copilot with a GitHub token, and some limit and credit
messages.

## Secrets

- A command that names a secret file, or searches the whole folder when the folder holds one (`grep -r`,
  `rg`, `gci | gc`), is asked about at every level, Full auto too. A script that opens a secret file
  without naming it (it builds the name, say) is not caught. Only Docker and Copilot's sandbox hide secret
  files from commands; KOLONİ's own commands on this machine, Claude Code, Codex and agy do not.
- When it runs **Native**, Codex asks KOLONİ before its commands - a read of `.env` too (measured on 27 Nov
  2026 with Codex 0.172.0: it asked before both `Get-Content readme.txt` and `Get-Content .env`; this guide
  said it ran its own safe commands unasked, and older versions were not measured again). A command an
  allow rule of Codex's own covers
  still runs without asking; KOLONİ records it after it ran, so no card stands in its way. agy reading with
  its own tools has no hook: its reads, of a secret file too, are not asked about at any level.
- A command you approve can still print, encode or send a secret it was given.
- An agent's request for a key on a hidden card is not available to CLIs working with their own tools.
- A branch deleted because it held a secret you gave still has its commits in git's reflog until git
  prunes them.

## Outside content

- Text from the web, MCP tools, Knowledge and GitHub issues is framed as data, but the frame only tells
  the model; a model can still follow what it says.
- Only KOLONİ's own tools frame what they bring in. A CLI's own web fetch, MCP servers or file reads
  are not framed.
- A forged end of the frame is not caught when it is written with look-alike letters from other scripts,
  with full-width or mathematical letters, with words joined by marks (`end-of-the`, `end_of_the`), or
  with markdown or HTML inside it. See [Security model](../security/model.md#outside-content).

## CLIs

- When a CLI runs **Native**, it runs its commands itself, so its model reads their raw output; KOLONİ
  masks keys only in what it records and shows. Measured once on Copilot (Native) with a made-up GitHub
  token (`ghp_…`) in a command's output: it was `***` in the model's answer and absent from Copilot's raw
  stream, so Copilot hid that kind of key itself; other kinds of key were not tried. Claude Code, Codex
  and agy run Native were not measured. With KOLONİ's tools (as a session, or one run per step),
  the keys KOLONİ knows and values shaped or named like keys are masked before the model reads the
  output.
- Copilot does not report which paths its PowerShell commands touch, so at Full auto a command that
  writes a protected file without naming it (a script, a path it builds) runs without a card. The same
  goes for KOLONİ's own commands at Full auto: one that names the file (`echo … > .claude/settings.json`)
  is asked about, but a script that writes `~/.claude/settings.json` is not. Such a file in the project
  is put back, and you are asked whether to keep it; one outside the project is not.
- Claude Code and agy run **Native** (and Copilot where it cannot sandbox its commands) have no
  sandbox of KOLONİ's: it can stop what they do only at their hook. A write with their own file tools
  outside the project and the folders it also works in (or that you allowed) is asked about on a card at
  every level, Full auto too (in a working copy, refused: it may write only in the copy); one into a CLI's own folder (`.claude`, `.gemini`, `.codex` or `.copilot` in
  your home folder) or another place KOLONİ never opens (`.ssh`, browser profiles) is refused. Their
  commands are judged by what they name: a command that writes outside the project, for example to the
  Startup folder or a PowerShell profile, runs without a card at Full auto, and at any level where an
  allow rule covers it, unless it names a CLI's settings folder such as `.claude` or `.gemini`, or a
  secret file, or it deletes or sends data off the machine.
- Claude Code run **Native** does not say where its commands run, so KOLONİ judges each one as
  run in the project folder. If the CLI keeps a `cd` from an earlier command, later relative paths are
  judged at the wrong place: after you approve `cd ..`, reading a file there by its name is taken for a
  read in the project and is not asked about below Full auto. Claude Code's Bash tool was
  measured not to keep one (2.1.325, Windows, run without its screen and as KOLONİ runs it: each
  Bash command starts in the project folder again, and KOLONİ starts it with the setting that asks for
  that); its PowerShell tool is said by the CLI to keep its folder, and other versions, Linux and macOS
  are not measured - so a `cd` into
  `.koloni/tmp/` by Claude Code's PowerShell tool is still asked. A command of its that
  itself names a folder to run in is asked at every level: KOLONİ cannot check it.
- GitHub Copilot CLI run **Native** does not say where its commands run either. On its newer protocol
  (Copilot 1.0.114 on) KOLONİ puts each PowerShell command in the project folder itself
  (a `Set-Location` into it before each, through its hook: where it cannot go there, the command
  does not run) and judges it there, so a
  `cd` into `.koloni/tmp/` runs without a card at Full auto; a delete inside `.koloni/tmp/` is still a
  card. Bash (Linux, macOS) gets no such prefix: there the `cd` is asked as before. On the older
  protocol, a Copilot version measured with KOLONİ - 1.0.105 so far, by the version Copilot itself
  reports - starts a command that names no shell of its own in a new shell in the project folder, with
  the same result; once a command has named a shell, the `cd` is asked as before. Any other version of
  the older protocol, and a Copilot that does not say its version, runs the old way (One session per
  agent), and its Models card says so. Copilot
  updates itself when you run it yourself, and that update reaches KOLONİ too: what KOLONİ judges is
  the version it runs. Only Windows was measured.
- A sub-agent on Claude Code run **Native** works in a working copy, but its commands are not
  sandboxed: at Full auto, one that writes into your project by a path it does not spell out (`..\..`, a
  script) changes the project directly. So do those of GitHub Copilot CLI run **Native** where it works
  in a working copy and its session has no sandbox - this machine cannot give it one, or the project
  does not hide its secret files. KOLONİ looks at the project after each of its commands and
  records such a change as made in the project by an unknown maker - one look over the project's files
  each time (some 0.1 s for 3,000 files, 0.4 s for 10,000, measured on Windows). With several such
  agents at work at once, a change can be recorded more than once - by each one's look that finds it,
  under its own agent; only the record changes, not your files.
- With Codex run **Native**, a command of Codex's own still at work after 11 minutes is ended as
  failed, and so is Codex's turn; one you allowed that Codex never says it started is ended as "never
  started" at the same 11 minutes.
- Codex run **Native** with **Sign-in: Its own for KOLONİ** goes on in its thread from the topic's
  previous turn. That is built on measurements of Codex 0.164 and tested with a stand-in only, not yet
  tried with a real Codex. On Codex 0.164 a new, empty KOLONİ folder also answered **read-only** when
  asked for its workspace-write sandbox (a turn is then refused before Codex acts), so a role that writes
  or runs commands might not run on such a provider until this is measured on a newer Codex. Codex has
  also been seen to answer while one of KOLONİ's tools it called still ran; why is not known. KOLONİ
  waits for that call. See [Codex](../models/setup-cli.md#codex).
- GitHub Copilot CLI's tokens and AI credits run as a session are counted from its usage checkpoint, as
  in **Native**; measured with `copilot -p` (CLI 1.0.103), not yet seen in a live session.
- Copilot's thinking levels on a model server of your own are not measured.
- A role run inside GitHub Copilot CLI (**Run inside the CLI**) is built on measurements of Copilot
  1.0.114 (27 Nov 2026: the roles it is given, its task tool's arguments, its hooks, requests and
  events for a sub-agent's tools and commands, KOLONİ's tool bridge shared with it). Its writes with
  Copilot's own file tools (create, edit, apply_patch) were not seen - it wrote with PowerShell - and
  are asked as the Orchestrator's are. Copilot does not run its commands where KOLONİ puts the
  Orchestrator's, in the project folder: where they run is taken as not known, so its git reads ask
  at **Ask** and its git lines go to the judge at **Full auto** (and more of its commands may ask). The role runs on the
  Orchestrator's model (a model of the role's own is not given), a turn that goes on in its kept
  session is given the roles anew (not measured that Copilot takes them so), and a Copilot on its
  older protocol is offered no role, with nothing said of it. A role that may list folders but not
  read files is not run inside Copilot (its one tool for both reads files too); one that does not
  run commands may not delete a file. Its tokens are counted in the turn - the larger of Copilot's
  own count for the turn and its model calls' sum, since whether the first holds the role's is not
  measured - but its AI credits only as Copilot's session count says them.
- An agy model whose name ends in its level takes no other level. Only a name ending in `-low` was seen
  to refuse one; the other endings are read the same way, not measured.
- A word sent while a CLI works (**Send now**, an agent's Tell box) goes into its running turn on
  Claude Code (a second user line; 2.1.332), Codex (`turn/steer`; 0.172) and GitHub Copilot CLI run
  **Native** (`session.send` with mode "immediate"; 1.0.114) - each measured on 27 Nov 2026. agy
  takes it only after its turn (1.5.18): an agy agent's box sends your word to the Orchestrator, and
  an agy Orchestrator reads it in one more run of the same turn. A CLI run as a session reads it at
  its next run too. That a CLI Orchestrator wakes for each of its agents' ends is not done: it reads
  their reports once all are back (each wake would be a run of its CLI).
- What came of a word written into a CLI's turn - taken, not sent, unknown - is read from the CLI's
  own signs, measured on 27 Nov 2026 with short turns and tested with stand-ins only, not yet in a
  long live turn: Claude Code's echo of the line before its result (`--replay-user-messages`; the
  echo names no id of KOLONİ's, so two words alike in one turn are matched oldest first), Codex's
  answer to `turn/steer`, Copilot's `user.message` naming the id its send was answered with, before
  its idle. Only Codex's "no active turn to steer" (-32600) is read as not sent; any other no of a
  CLI's is unknown. An unknown word of Send now, Tell or an agent's message is never sent again: one
  Claude Code takes in one more turn after its result is still said unknown (that turn is read to
  its end), and one Copilot would take after its idle is not read (its run has ended); a Change of
  a decision or an answer is given again from the agent's next step. Claude Code is asked for its
  echo only from 2.1.332 on, the version it was measured on (`--version`, asked at each run), and
  not for a prompt over 8 MB (pictures): a word steered into such a turn is unknown.
- Talking while agents work: the Orchestrator's steps that answer your word are refused KOLONİ's
  Write files, Edit files, Diagram pictures, Run commands, a skill's script, Web requests and any MCP
  server's tool; a CLI Orchestrator's own tools are only told so. While it answers your word the
  Orchestrator waits for no room among the
  agents at work: it is counted at work in the project and on its provider (who comes next waits for
  it), but a provider let work at one at once gets one more request beside its agents' then, and the
  turn may have one more at work than the chat's setting until its next wait. A chat open in a hidden
  browser tab counts as watched: no desktop notice comes when a background agent ends.
- The line over the chat says the Orchestrator's step from the plan it shows (`update_plan`, or a
  Codex Orchestrator's own); Claude Code's own to-do list is not read, so a Claude Code Orchestrator
  shows no step. `ask_advisor` and `note_decision` have not been tried with a live model yet; what
  `read_pr_feedback` reads is as `gh` gave it on 27 Nov 2026 (`gh pr view --json` for reviews,
  comments and checks; `gh api` for the comments on lines, the first 100).

## Git

- A team's branch starts from your folder as it is only with git 2.40 or later (Apple's git is older),
  and when your folder has at most as many new files as a copy takes (20,000 files, 500 MB); otherwise
  it starts from your last commit and its card says so.
- A file Git LFS keeps comes into a branch, and back, as its pointer text: KOLONİ runs no filter of your
  repository's. A submodule's own changes are not taken into a branch.
- A junction deep inside a new folder is not taken, but git reads through it while the branch is made;
  one that leads to a large folder can make the branch start from your last commit instead.
- A branch's start from your folder, and a ☾ Away job's commit on its branch, leave a file out by its
  name alone: a secret's name (`.env`, `.env.local`, `env.production`, a key file, `credentials.json`,
  `client_secret….json`, `serviceAccountKey.json`, `.secrets`, `secret.txt`, `access_token.txt`), a
  data file named `credentials`, `api_keys` / `api-key` or `token` (`.json`, `.yaml`, `.toml`,
  `.txt`), a copy of a `.env` but `.env.example` (`.env.sample`, `.env.template`,
  `.env.local.example`), and what is in a folder named `credentials` or `secrets` but source code and
  docs. Code and Markdown so named go in (`credentials.py`, `api-keys.ts`, `tokens.py`), and so does
  `tokens.json` (design tokens). A team's pull request asks first for every such file. A secret under
  any other name - `password.txt`, `.vault_pass`, an npm token in `.yarnrc.yml`, a name spelt with a
  look-alike letter - is left out only where it holds one KOLONİ knows. A file in a folder named like
  an installed one (`venv`, `node_modules`, `site-packages`) is never judged by its name. In a
  `credentials` or `secrets` folder a config, data or text file is left out even where it is no
  secret (`secrets/README`, `k8s/secrets/deployment.yaml`), and so is a test's
  `tests/fixtures/credentials.json`. A team's or a story's branch commits what its agents wrote under
  such a name: its merge stays on this machine. A file left out is never deleted.
- A branch's worktree, and in a project with no git a copy, is in the project's own `.koloni/`
  ([where](../use/workspace.md#where-copies-and-worktrees-are)): a CLI started there reads your
  project's `AGENTS.md`, `CLAUDE.md` or `GEMINI.md` from the folders above it as well as the copy's own -
  the same words twice (a `.claude/` folder of the project's above it is not measured). A copy of a
  project that gets git after the copy was made has no `.git` of its own: git started there as KOLONİ
  starts it finds no repository (it looks no higher than the copies folder; measured with git 2.53),
  but a command that clears git's environment would reach the new one. The next copy is made outside
  the project.
- A command a script runs in your project's root (`rg x`, `grep -r x .`) reads KOLONİ's copies and
  worktrees in `.koloni/` too, where your search tools do not: a secret file in one counts as the
  project's for such a search's card.
- `git clean -fdx` in the project removes KOLONİ's records of its worktrees under `.koloni/` (what
  each was made from, its hooks folder); `-ffdx` removes the worktrees themselves. A worktree whose
  record is gone is left as it is at the next start - with its uncommitted work, and git's record
  of it - for you to look at and delete. An agent that deletes that record of its own worktree
  (a command in it can reach the folder beside it) keeps it there the same way.
- A command row that names an agent's own tree by its full path may still say "Names .koloni…" on
  the page, though it ran with no card: the page reads the line again without knowing whose tree it
  is.

## GitHub

- Reading a GitHub issue with a real `gh` is not measured yet: the fields KOLONİ asks gh for are taken
  from gh's manual.

## Models

- Other OpenAI-compatible servers, such as Ollama, should work but are not tested. The local server
  that is measured is llama.cpp's `llama-server`.

## Commands

- Some harmful commands are not on the list yet: `kubectl delete`, `terraform destroy`,
  `rsync --delete`, `robocopy /MIR`, `mail`, `ssh host 'command'`.
- At Full auto, the harm check sees honest commands only; a command written to hide what it does is not
  seen. See [Security model](../security/model.md).
- A command that writes into `.idea/` without naming it is not seen: KOLONİ puts back files that steer
  later turns after a command, but does not look into `.idea/`, which a JetBrains IDE rewrites itself.
- Below Full auto, a `git` read whose folder KOLONİ does not know - Claude Code's PowerShell or Monitor,
  and many of Copilot's commands - is judged as run at the project's top, where it runs unasked; at Full
  auto it goes to the judge.
- [Full auto's judge](../use/permissions.md#full-autos-judge) is a net, not a wall:
    - It is a model's decision: it can call a risky command fine, and then the command runs, as it did
      at Full auto before the judge.
    - Text aimed at the judge inside a command, an agent's earlier action (a file it wrote, the
      arguments of a tool it called) or a program an agent wrote can still sway the model: the judge
      is told it is an agent's data, and a few known phrases make a card without asking, but other
      wordings reach it. What a tool gave back - a file read, a command's output, a page - never
      reaches it; but an agent can copy such text into what it writes.
    - It reads the same agent's last 8 actions, each cut to 300 characters: an earlier one, or what an
      action held past its first 300 characters, is not seen.
    - Hidden work may not be seen: a tool an agent changed but did not write, a program past its first
      4 KB, a program that imports another file.
    - Test runners and build tools load the project's test and settings code by design - a
      `conftest.py`, test files, an eslint or mypy plugin a setting names, `build.rs`, a cargo runner -
      so `pytest -q` or `cargo build` runs what an agent wrote there with no judge.
    - A file an agent made by copying another (`cp x.txt x.py`) is not known as the agent's: the judge
      is not shown it.
    - **Don't ask about this line again here** cannot be listed or undone in the app yet; what it keeps
      goes with the project.
    - A Run on its card, and **Don't ask about this line again here**, keep only a line whose whole run
      KOLONİ knows - a project file it runs in a plain form, hashed, or one plain `curl`, `wget` or file
      command. Any other form - `git`, a wrapper, a shell's code, `npx`, a line sent to another folder,
      a variable set on make's line, a package's `__main__.py`, a Python line without `-I` or `-E` in a
      working copy (or with `PYTHONPATH` set), a runner KOLONİ does not know, a file it did not find, a
      folder it does not know - is asked about every time, and its card has no box: it fails closed, at
      the cost of more questions.
    - A command the judge could not look at - too long, orders in it, no model to ask or no room to ask,
      no answer in time or none it could read, its program changed while it looked - is never kept: a
      Run on its card runs it once, and its card has no box. With no model to ask at all, every command
      it would look at is such a card (it fails closed): pick a Judge model, or turn the judge off.
    - What a kept program imports in turn is not looked at - not even a file in its folder that shadows
      a standard module (a `json.py` beside `x.py`): a changed import does not make `python x.py`
      another line.
    - For a CLI run **Native**, KOLONİ - and so the judge - sees only the command the CLI reports.
    - Each command it looks at waits for one model request and a few seconds; where only a CLI can be
      asked, from that CLI's quota, and each such command waits for the CLI to start.
    - A narrow **Always run** rule (`npm run build`, `make build`) lets its very line by with no
      judge, at the project's root, as Claude Code's auto mode does: what that script, target or
      tool then runs - a `package.json` script or a Makefile recipe you wrote, a script that recipe
      calls, a tool's settings - is not looked at (a Makefile, a `package.json` or a script it is
      handed that an agent wrote is). A broad rule (`npm`, `make`, `python`, `pytest -x`, `npm
      install`, `docker run`, `git remote`) does not; a sub-command KOLONİ does not list as taking
      whatever it is handed counts as narrow.
    - A file an agent made with a command - `cp`, `tar`, `git clone`, a download - is not on record
      as the agent's: a narrow rule whose line runs it, or the user's own test command, lets it by
      with no judge, and the judge is not shown its text.
    - Three refusals in a row ask you; any command of the turn that starts ends a row - an agent
      that runs something harmless between refusals is asked only at 20 refusals in the turn.
    - Since 0.1.10 it decides a delete in the project, git work thrown away and a stop by name,
      written as a plain line, in place of the list's card (in a chat you watch at Full auto, its
      switch on): a "fine" there deletes
      with no card. KOLONİ looks at the disk on the way to what a delete names (a link or a junction
      there is a card), not inside a folder it deletes - a link deep in one is not looked at -, and the
      judge can be led to call a delete fine that it should not: a file of yours written over
      first and then deleted as the agent's own, work moved into the scratch and then deleted, a path
      that only looks like a build folder (`build/../src`). Run once on such a card keeps nothing.
    - cmd's `rd /s /q x` and `del /s x` stay the list's card at Full auto, the judge on too: their `/s`
      and `/q` read as paths from the drive's root. So does any delete that is not a plain line - a
      quote, an escape, a wildcard, a pipe, a wrapper (`bash -c "rm -rf build"`, `sudo`, `… | xargs
      rm`) -, even where its target is plainly in the project; and a `\` is a path's separator only in
      KOLONİ's own PowerShell, so a CLI's `del src\app.py` is a card. A plain delete beside any
      command that is not one (`rm -rf build; npm install`), git's work where the project is not its
      repository's top folder, and a Windows short name (`ENV~1`) are cards too.
    - Since 0.1.11 it decides [a plain push of your feature branch](../use/permissions.md#a-push-of-your-feature-branch)
      to its origin: a "fine" pushes with no card. Its prompt counts sending work off the machine as
      risky, and no model was measured on pushes yet: expect some pushes to be refused or carded
      (one you asked for is carded, quoting you, never refused). A bare `git push` (and `origin
      HEAD`) pushes the branch checked out as it runs: KOLONİ looks again just before it runs, but a
      switch of the project's branch by your own hand in that moment is not seen. The judge is not
      told the branch's name, only the line and what the agent did before it. Before it is asked,
      and again after its fine, KOLONİ asks origin what it holds and which branch is its default, as
      the push would - a network request each time, and origin's own time limit. A
      push that changes git's settings (`git push -u`, a branch made to track one) makes the next push
      of that turn a card; so does a turn begun below Full auto, a push of more than 50 commits, an
      origin that holds none of the branch, `main`, `master` or its default branch, and any
      `pre-push` or `reference-transaction` hook - yours too: a repository with husky or Git LFS
      gets a card for every push. Each Full auto turn in a repository begins with a few more git
      calls (what a push goes by is read then).
    - Its short way for ordinary work is a small table (test runners, compilers and checkers, local
      git, `npm run`): other everyday commands - an install, a build tool it does not list - are each
      asked about.
- `.koloni/`'s free folders (`tmp/`, `worktrees/`, `copies/`) are told apart by how a path is spelt:
  `.koloni/t*`, a short name (`KOLONI~1`) or `.koloni/./tmp` is `.koloni`, and asked; and a `cd` into
  one is free only plainly spelt, by a relative path, at the line's start - `git -C <a tree>` or `cd
  /d …` is asked. A look into a worktree or copy from outside it is told from a write by the programs
  the line runs (readers, listers, searches, no redirection). An agent's own tree by its full path is
  known by how it is spelt there (a short name is not). A link inside a free folder is written through
  as it is spelt: KOLONİ does not resolve it when it reads the line.
- Commands cannot be given input while they run.
- In Docker on Linux and macOS, commands run as your user, not as root. A command that needs root in
  the container, such as `apt-get install`, fails. On Linux, files an older version of KOLONİ made as
  root in the project may no longer be writable; see
  [Troubleshooting](../troubleshooting.md#commands-and-docker). Under rootless Docker, the files a
  command makes belong to another user id on the host.

## Work while you're away

- In the morning **Run** does not look at what the job changed in its copy: you see that at Take in.
- A line that runs a program an agent wrote is refused after **Run** too. A script given to an
  interpreter (`python tool.py`, `node x.js`) is not read so: it runs on your **Run** - but only as it
  was when the line was parked (the list says "Runs a file an agent wrote", of any part of a chained,
  piped, wrapped or grouped line too - `python hello.py && python q.py`, `cmd /c "python q.py"` - and
  "maybe" where it cannot read all of the line, or the line runs code no word of it names as a file:
  a shell or an interpreter handed its code on stdin or on the line (`cat x.sh | sh`, `python -c`),
  `iex`, `npx`, find's `-exec`, a test runner - the tests an agent wrote).
- A branch's commit, merge and push look for a secret KOLONİ knows byte for byte, in a file's content
  and its name: one an agent wrote base64'd, reversed, or split across files or in parts is not
  found. A saved key made of lowercase words alone (a provider's `not-needed`, `correct-horse`) is
  not looked for, nor a file's path given under a secret's name (`GOOGLE_APPLICATION_CREDENTIALS`,
  `*_FILE`); of an MCP server's variables, and the environment's (what a project passes to its
  commands among them), only those a secret's name or a secret's shape holds (`..._TOKEN`,
  `..._KEY`, a password; `ghp_…`, `sk-…`, a password in an address) - and the token or the
  address's password such a value holds alone, unless it reads as a word
  (`postgres://postgres:postgres@…` makes no secret of `postgres`). A key whose shape KOLONİ does
  not know - it knows GitHub's, `sk-…`, Slack's, AWS's, a JWT, GitLab's `glpat-…`, Google's
  `AIza…`, Hugging Face's `hf_…`, npm's `npm_…` and Stripe's `sk_live_…` - is looked for only by
  its variable's name. A word under a secret's name is a secret all the same
  (`POSTGRES_PASSWORD=postgres`): a file holding it (`psycopg2  # postgresql driver`) is left out
  of KOLONİ's commit and stays in the branch's worktree - never deleted - and KOLONİ says which.
- If anything in the job's copy changed after a line was parked, **Run** does not run it - so a test
  line parked early in a job is usually closed by the work after it: run it yourself. What stays out
  of that look: the dependency folders a copy links to the project's own (`node_modules`, `.venv`,
  `venv`), files outside the project, and the caches that hold no code (`.pytest_cache`,
  `.ruff_cache`, `.mypy_cache`, `.git`). A command that runs none of the project's code is not closed
  by changes at all.
- KOLONİ looks at the whole copy for this, each time a line is parked and just before each runs: about
  a second on a copy of 2,000 files (measured on Windows), the first look longer. A large `build` or
  `dist` folder in the copy (or a big scratch) makes each look slower: every file in it is read.
- Between that last look and the line's start there is a moment - under a second - in which a process
  an earlier **Run** left behind (on Linux or macOS), or another task's going-on turn, could still
  change a file: that gap is not closed.
- A line a CLI ran in its own shell is not run in the morning (**Reject** it, or run it yourself), nor
  is a server line.
- KOLONİ hard-stopped (killed, not closed) while the morning's lines run, or in the turn that went on
  after them: at the next start the task is stopped, and says which; what had not run is not run again.
- A line whose folder its CLI did not say does not run: **Reject** it, or run it yourself.
- Where you took some of a job's copy in, its going-on turn works in a fresh copy, and the lines you
  said **Run** run in the project itself.
- A job tried twice in a copy (not on a branch) keeps each try's copy: each line runs in the copy it
  was parked in, and the going-on turn goes on in the newest copy any of its lines was parked in - a
  try that parked nothing keeps its copy for your Take in. A job that parked only questions goes on in
  the newest copy the turns that asked them kept.
- KOLONİ closed while the morning's lines run: the task is stopped, and what has not run is not run
  again - **Try again** works it in its chat.
- `git` in the middle of a line - `cd sub && git push` - needs the project: Take in first; in a copy
  there is no git.

### Away on a branch

- A job on its branch works in a worktree of your own repository: its `.git` is shared. A script or a
  test that runs git there can reach your branches, tags, stash and config - KOLONİ reads only the
  git lines the agent itself writes. Your branches, stash, tags, remotes and git's config are compared
  as the job starts and ends, and what changed is on its row; nothing is undone.
- A plain push from a script fails there because KOLONİ sets git's `pushInsteadOf` for the job's
  commands. Measured with git 2.53: `git push` to the remote's name, a path or a `file://` address
  fails, a fetch works. It is no wall, and the job's own script can get past it: `git send-pack`, its
  own `-c url.<x>.pushInsteadOf=...`, a `remote.origin.pushurl` it sets first, or git's environment
  replaced (`GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_COUNT`) all push - and so does a `pushurl` or a longer
  `pushInsteadOf` of your own. Each of these the agent types itself is refused or asked on a card;
  what a script it runs does is not read.
- Before any branch's push - ☾ Away's in the morning, a team's pull request - KOLONİ asks origin
  itself what its branches hold, and never reads your remote-tracking branches (`origin/*`) for it: a
  ref written in your repository (a script's `git update-ref`, a symbolic ref) cannot make your own
  unpushed commits look pushed - a commit only such a ref says is pushed counts as yours. Stale ones
  (a branch deleted on origin, a teammate's push you have not fetched, a force-pushed branch) do not
  matter. Where origin's branch the push goes into holds commits you have not fetched, it asks you to
  fetch first; where git's config rewrites the address the push goes to (an `insteadOf` or
  `pushInsteadOf` rule that matches it - what origin is asked and where the push goes could be two
  repositories), or origin has more than one push address, nothing is pushed. No KOLONİ git call reads
  an object through `git replace` or a graft of `info/grafts`, and the push's ancestry is read without
  the commit-graph file. Origin is asked only once a branch's way is a pull request, never at the end
  of a turn that may still be a merge. Between that look and the push itself there is a moment in which
  another process could still change your repository: that gap is not closed.
- ☾ Away compares every job's push with the repository as you went away (its refs, git's config in
  every scope, its hooks, where a push goes): what an earlier job of the night changed is noted on a
  later one's push too. The branches of that night's own jobs are not counted.
- **Try again** on a job a day later still compares its push with the night's repository: what you
  changed since is noted on it too, to be seen and Run anyway.
- The worktree holds what git tracks; what it ignores (`.env`, data, build output) is not there, and a
  test that reads such a file may fail. A project with a git submodule or Git LFS works in a copy.
- The commits of a branch that was deleted, or of a job's first try, stay in git's objects until git
  cleans them up (`git gc`).
- Your own `pre-commit` and `pre-push` hooks run neither for the job's commits nor for KOLONİ's push.
- KOLONİ's checks run before its last commit at the job's end; that commit holds the same files,
  apart from one holding a secret KOLONİ knows or named as one (left out, and its push row says so) or
  a new file your project already has.
- The branch's name is told to the job before its worktree is made: where a branch of that name was
  there already, the worktree is on the next free name, and its row says which.

## Recipes

- A team as a step's "Who" runs its stages as slots of one step, not one after another.
- The eight ready teams 0.1.10 took away (Backend / API, Data, DevOps, Research, Product, Maintenance,
  ML, DataOps) are not followed where something else named one: a night while you're away planned with
  one runs without it, a recipe file of a folder's own (`.koloni/recipes`) whose step names one is
  refused when it runs, as naming no team here, and a recipe run the Orchestrator had started on one in
  a chat is lost with it.

## The page

- Canvas positions are worked out from the record each time and are not saved.
- At phone width, the top bar wraps to two lines.
- Desktop notifications are on Windows only.

## Systems

macOS, Linux and the Docker image have been tested less than Windows. See
[Install](../getting-started/install.md#how-well-each-system-is-tested).
