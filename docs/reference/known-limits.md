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
- When it runs **Native**, Codex runs the commands its own rules count as safe (a read of `.env`, or of a
  file outside the project) without asking KOLONİ, at every level; KOLONİ records them after they ran, so
  no card stands in their way. agy reading with its own tools has no hook: its reads, of a secret file
  too, are not asked about at any level.
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
  every level, Full auto too, and refused in a turn nobody watches (in a working copy, refused: it may
  write only in the copy); one into a CLI's own folder (`.claude`, `.gemini`, `.codex` or `.copilot` in
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
  script) changes the project directly. KOLONİ looks at the project after each of its commands and
  records such a change as made in the project by an unknown maker - one look over the project's files
  each time (some 0.1 s for 3,000 files, 0.4 s for 10,000, measured on Windows).
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
- Triggers do not start a turn on a CLI that works with its own tools (Native, or agy).
- GitHub Copilot CLI's tokens and AI credits run as a session are counted from its usage checkpoint, as
  in **Native**; measured with `copilot -p` (CLI 1.0.103), not yet seen in a live session.
- Copilot's thinking levels on a model server of your own are not measured.
- An agy model whose name ends in its level takes no other level. Only a name ending in `-low` was seen
  to refuse one; the other endings are read the same way, not measured.

## Git

- A team's branch starts from your folder as it is only with git 2.40 or later (Apple's git is older),
  and when your folder has at most as many new files as a copy takes (20,000 files, 500 MB); otherwise
  it starts from your last commit and its card says so.
- A file Git LFS keeps comes into a branch, and back, as its pointer text: KOLONİ runs no filter of your
  repository's. A submodule's own changes are not taken into a branch.
- A junction deep inside a new folder is not taken, but git reads through it while the branch is made;
  one that leads to a large folder can make the branch start from your last commit instead.

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
- [Full auto's judge](../use/permissions.md#full-autos-judge) is a net, not a wall:
    - It is a model's decision: it can call a risky command fine, and then the command runs, as it did
      at Full auto before the judge.
    - Text aimed at the judge inside a command or a program an agent wrote can still sway the model:
      the judge is told it is an agent's data, and a few known phrases make a card without asking,
      but other wordings reach it.
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
    - A command the judge could not look at - too long, orders in it, no room to ask, no answer in time
      or none it could read, its program changed while it looked - is never kept: a Run on its card
      runs it once, and its card has no box.
    - What a kept program imports in turn is not looked at - not even a file in its folder that shadows
      a standard module (a `json.py` beside `x.py`): a changed import does not make `python x.py`
      another line.
    - For a CLI run **Native**, KOLONİ - and so the judge - sees only the command the CLI reports.
    - Each command it looks at waits for one model request and a few seconds; where only a CLI can be
      asked, from that CLI's quota, and each such command waits for the CLI to start.
    - Its short way for ordinary work is a small table (test runners, compilers and checkers, local
      git, `npm run`): other everyday commands - an install, a build tool it does not list - are each
      asked about.
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
  was when the line was parked (the list says "Runs a file an agent wrote").
- If anything in the job's copy changed after a line was parked, **Run** does not run it - so a test
  line parked early in a job is usually closed by the work after it: run it yourself. What a parked
  line uses outside the copy (the project's linked dependency folders, files outside the project) is
  not looked at, and a command that runs none of the project's code is not closed by changes at all.
- KOLONİ looks at the whole copy for this, each time a line is parked and just before each runs: about
  a second on a copy of 2,000 files (measured on Windows), the first look longer.
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
- A job tried twice parked its lines in two copies: each line runs in its own, the going-on turn in the
  newest.
- KOLONİ closed while the morning's lines run: the task is stopped, and what has not run is not run
  again - **Try again** works it in its chat.
- **Usage › Cards** counts a parked card as not answered.
- `git` in the middle of a line - `cd sub && git push` - needs the project: Take in first; in a copy
  there is no git.

## Recipes

- Recipes do not run in triggers' turns.
- A chat cannot open a room while a recipe runs.
- A team as a step's "Who" runs its stages as slots of one step, not one after another.

## The page

- Canvas positions are worked out from the record each time and are not saved.
- At phone width, the top bar wraps to two lines.
- Desktop notifications are on Windows only.

## Systems

macOS, Linux and the Docker image have been tested less than Windows. See
[Install](../getting-started/install.md#how-well-each-system-is-tested).
