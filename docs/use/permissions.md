# Permission levels

The permission level decides what agents may do without asking you first. It stands in the message box's
row as three comb cells and its name (**Ask** one cell, **Auto-edit** two, **Full auto** three): a click
lists the levels, each with a line on what it does - Ask before changes: "Each file change and command waits
for your card"; Auto-edit files: "Writes files at once (revertible); commands still ask"; Full auto: "Changes
and commands run; only harmful or risky actions ask" - **Plan first**, and in a project's chat **Test and
review changes** ([what KOLONİ checks after a change](checked.md#for-one-chat), on or off for this chat; off, the
level says "· no checks"). Each chat has its own level.

| Level | In short |
|---|---|
| **Ask before changes** | Each file change and each command waits for your card. |
| **Auto-edit files** | File changes are written at once and can be reverted. Commands still ask. |
| **Full auto** | Changes and commands run without asking. Only harmful or risky actions still ask. |

## What asks at each level

"Card" means the agent stops and waits until you answer on a card in the chat.
"Runs" means it goes ahead without asking.

[![Permission and approval flow: what asks at each level, the card, Always run rules, the harm check and who may answer a card](../diagrams/permissions.svg)](../diagrams/permissions.svg)

*The levels at a glance; the table below has every case.*

| Action | Ask before changes | Auto-edit files | Full auto |
|---|---|---|---|
| Reading, listing or searching files in the project | Runs | Runs | Runs |
| Changing a file | Card | Runs | Runs |
| A command that only reads, such as `cat`, `ls` or `git status` (every path it names - an option's value (`--file=x`, `-Path:'x'`) and a name written in quoted pieces (`.e'nv'`) too - followed through links and junctions, inside the project and no secret file - else it is any other command) | Runs | Runs | Runs |
| Any other command | Card, unless a rule covers it | Card, unless a rule covers it | Runs, unless [Full auto's judge](#full-autos-judge) finds it risky |
| A command that keeps running, such as a dev server | Card, every time | Card, every time | Runs |
| A command that deletes or empties files in the project, or throws away git work, written as a plain line (`rm -rf src`, `Remove-Item`, `git reset --hard`, `git clean -fd`, `git checkout -- .`, `git stash drop`, `git branch -D`) | Card | Card | Runs, unless [Full auto's judge](#full-autos-judge) finds it risky - a card with the judge off or no judge model to answer ([which](#what-the-judge-decides-in-place-of-the-list)) |
| A command that sends data off the machine (`git push`, `scp`, a `curl` that posts data, …) | Card | Card | Card, unless [Check what I said first](#check-what-i-said-first) finds a line of yours that names it |
| A delete out of the project or of all of it (`rm -rf ../x`, `rm -rf .`, `find . -delete`, `git clean -fdx`), one not written as a plain line (`bash -c "rm -rf build"`, `… \| xargs rm`, `rm -rf .gi\t`), a worktree removed, git's recovery pruned (`git gc --prune=now`, `git reflog expire`), a Docker delete, or a git remote's branches overwritten or deleted (`git push --force`, `git push origin :x`) | Card | Card | Card |
| A delete KOLONİ checks is disposable - a build folder git ignores, a clean worktree of yours, a merged branch - where you allowed [such deletes](#disposable-deletes) | Card | Runs | Runs |
| A command handed to a shell (`cmd /c`, `powershell -c`, `sh -c`) | Card, every time | Card, every time | Runs, unless Full auto's judge finds it risky; a card where what it runs deletes, sends or is asked at every level |
| Reading a secret file (`.env`, keys, …) | Card | Card | Card |
| A command that names a secret file, or searches a folder that holds one | Card | Card | Card |
| Writing a file that steers agents' later turns (`.claude/`, `.codex/`, `.git/`, `.github/`, `.vscode/`, `.mcp.json`, …) | Card | Card | Card |
| Writing `AGENTS.md`, `CLAUDE.md` or `GEMINI.md` | Card | Card | Runs |
| Writing in the folder's `.koloni/` - or a command that names it - but in its scratch `tmp/`, and a look into `worktrees/` or `copies/` ([which](#the-folders-koloni)) | Card | Card | Card |
| A web search | Card, unless you allowed searching in this chat | Card, unless you allowed searching in this chat | Runs |
| A web request that only fetches a page (a plain GET) | Card, unless you allowed that site | Card, unless you allowed that site | Runs |
| Any other web request (one that sends data) | Card | Card | Card |
| A tool of an MCP server you have not trusted yet | Card | Card | Card |
| A tool of a trusted MCP server | Card, unless the tool is set to run without asking | Card, unless the tool is set to run without asking | Card, unless the tool is set to run without asking |
| A file outside the project | Card | Card | Card |
| A change in a folder added to the chat for reading only | Card | Card | Card |
| A command that stops programs by their name (`taskkill /IM`, `pkill`, `killall`, `Stop-Process -Name`), or looks a process up and stops it | Card | Card | In the project, runs unless Full auto's judge finds it risky (a card with the judge off or no judge model to answer); a card always for python, node, uvicorn, an agent's CLI, the terminal, shell or system KOLONİ stands on (WindowsTerminal, conhost, OpenConsole, powershell, pwsh, cmd, bash, explorer, lsass, csrss, svchost, wininit, winlogon, services), a filter, a wildcard, `kill -1` or a process looked up |
| A sub-agent's command in its copy that names another agent's copy, a worktree of the project or a place above its copy (`../..`), or writes in or installs into the linked `node_modules`, `.venv` or `venv` | Card | Card | Card |
| A sub-agent's command in a branch's worktree that finds your repository's own path (`git rev-parse --git-dir`), or writes to a place built when it runs (`> "$D/…"`, `cp x "$D/…"`, `Set-Content (Join-Path …)`) or links to one - it may be your repository's own `.git` | Card | Card | Card |

A plain `git` command counts as read-only only when it runs at the top of the project and the
project holds no secret file.

The secret-file rows have exceptions for CLIs run with their own tools (Codex's own safe commands,
agy's reads): see [Known limits](../reference/known-limits.md#secrets).

### The folder's `.koloni/`

| In `.koloni/` | A command naming it, or a write there |
|---|---|
| `tmp/` - the agents' scratch | Judged as any path: no card of `.koloni`'s, at every level |
| `worktrees/`, `copies/` - KOLONİ's worktrees and copies ([where](workspace.md#where-copies-and-worktrees-are)) | A look - `ls`, `cat`, a search, the Files window - is judged as any; a write, a delete or a program run there is a card at every level |
| Everything else: `rules.md`, `settings.json`, `recipes/`, `knowledge/`, the teams' `shared/` folder | Card at every level, Full auto too |

- Each worktree and copy is one agent's work. That agent works in it as its own folder - by its full
  path too (`cd C:/…/.koloni/worktrees/<id>/<agent>/tree`, Git Bash's `/c/…`) - with no card of
  `.koloni`'s; any other agent, or a command at the project's root, only reads there. A write, a
  `tee`, `cp` or `mv` into one, a file tool's write (also at Auto-edit and Full auto), a delete, a
  program run from one, or pytest's `--basetemp` there is asked at every level.
- A search is a look only while it only reads. Its options are read as the shell joins them, so a quote
  or a backslash inside one changes nothing: `find src -de""lete` is a delete, and `-fpr""intf`,
  `-ex""ec`, rg's `--p""re=` and `--hostname-bin`, and ag's and ack's `--pager` make it no read. A `find`
  word in bash's ANSI-C quotes (`$'-de\x6cete'`), which KOLONİ does not decode, is taken for a delete,
  and ag or ack is no look into a tree. In a worktree or a copy such a line is asked at every level.
- What is inside the scratch is still judged as any path: a `.claude/settings.json` there asks as it
  does anywhere, and a `git` line that names a free folder (`git add -f .koloni/tmp/x`) asks.
- A line that climbs from a free folder into the rest - `cat .koloni/tmp/../rules.md`, `cd
  .koloni/worktrees; echo x > ../rules.md`, a path built from where it stands - asks at every level, its
  card saying "Climbs out of .koloni/tmp…".
- A delete is a card at Ask and Auto-edit as any delete is; at Full auto a plain delete inside `tmp/`
  runs with no card - inside `worktrees/` or `copies/` it is a card.
- The teams' `shared/` folder is not free: who writes where there is the teams' own rule (`write_shared`
  writes a team's folder only, and each file says who wrote it); agents read and write it with their
  `read_shared` and `write_shared` tools.

## The cards

<video src="../videos/approval.webm" poster="../../videos/approval.jpg" controls muted loop playsinline preload="none" style="width: 100%; height: auto" aria-label="Video: at Ask before changes the Orchestrator asks to run python check.py, and Run once lets it run"></video>

*An agent asks, you approve: **Run once** on its card, and the turn goes on.*

- **A file change** shows the diff, with **Approve** and **Reject**. After it is written you can
  still **Revert** it.
- **"Run this command?"** offers **Run once**, **Always run …** and **Reject**. **Always run**
  keeps a rule for this chat, so the same kind of command runs without a card next time. Some
  commands never get a rule; their card says "This command is asked every time." A rejected command
  ends that one action, not the task. If you reject a command that writes a file or applies a patch,
  the agent is told to make the change with its file tools instead, so it comes to you as a file change.
- A delete KOLONİ found disposable also offers **Allow such deletes in this project**
  (see [Disposable deletes](#disposable-deletes)).
- **"Search the web?"** offers **Search once**, **Always allow searching in this conversation**
  and **Reject**.
- **"Make this request?"** offers **Send once**, **Always allow GET to …** (for that site) and
  **Reject**.
- **"Read a secret file?"** offers **Allow once** and **Reject**. There is no rule for secret files.
- **"Read outside the project?"** offers **Allow once**, **Allow reading this folder**, **Allow changes in
  this folder** and **Reject**.
- When an agent wants another folder, **"Add a folder to this chat?"** offers **Add to this chat**,
  **This time** and **Reject**.
- An MCP tool asks with **Allow** and **Reject**.

You can see and remove the rules you made under Settings › This project › When you're asked ›
**Runs without asking** › **Show the rules**.

## What a rule never covers

**Always run** is offered only for plain commands. It is never offered, and never matches, for:

- a command that is chained, piped or redirected, or handed to a shell or another program;
- a command that deletes or cannot be undone;
- a command that names a secret file, `.koloni/`, or a file that steers agents;
- an option after the rule's words that makes the program run another program, fetch code or
  write outside the folder, alone or in a bundle (`pytest -qo …`): pytest's `--basetemp`, `-p`,
  `--rootdir`, `--confcutdir`, `-o`, `-c`, and `--junitxml` outside the folder; go's `-exec`,
  `-toolexec` and `-C`; cargo's `--config` and `--manifest-path`; gradle's `-I`, `-p` and `-b`;
  npm's `--script-shell`, `--prefix`, `--package`, `--userconfig` and `--node-options`; make's
  `SHELL=` and `-f`; tox's `-c`; maven's `-Dmaven.ext…`; uv's and pipx's `--with`, `-w`, `--from`,
  `--spec`; ruff's `--config`, `--fix`, `--fix-only`, `--unsafe-fixes` and `--add-noqa`; mypy's
  `--config-file`, `--python-executable` and `--install-types`, and its `--cache-dir`,
  `--junit-xml` and `--…-report` outside the folder; eslint's `-c`, `--rulesdir`,
  `--resolve-plugins-relative-to`, `--plugin`, `--parser`, `--fix`, `--init`, `--inspect-config`,
  `--suppress-all`, `--suppress-rule`, `--prune-suppressions` and a `--format` other than its own
  (`stylish`, `json`, `json-with-metadata`, `html`), and its `-o`, `--cache-location`,
  `--cache-file` and `--suppressions-location` outside the folder - a long one in any spelling
  (`--outputFile`); tsc's `--incremental`, `--composite`, `--noEmit false`, `--generateTrace`, `-b`
  and `--build` (but `false` and `null`, which write nothing: `--incremental false`), and its `-p`,
  `--outDir`, `--outFile`, `--tsBuildInfoFile`, `--declarationDir` and `--generateCpuProfile`
  outside the folder - in any case (`--OUTDIR`, `--p`); an option or its value written in pieces a
  shell joins (`fal""se`, `".."/x`), and a word of its own so (`make 'SHELL=/x'`, `SH""ELL=/x`); a
  shell handed a line (`bash -c`). A rule for `python -m pytest` still covers
  `python -m pytest -q tests`, `-p no:cacheprovider` (a plugin turned off) and `-o log_cli=true`,
  but not `python -m pytest -p plugin`. Words after `--` are the script's own (`npm test --
  --prefix x` is covered), and past a rule that names a runner's package (`npx tsc`) the words are
  that tool's (`npx tsc -p tsconfig.json` is covered).

Where one of your rules begins the line but such an option, or a node runner sent to another package or
folder (below), keeps it off, the card says so, in KOLONİ's words: "your rule “npm exec tsc” does not cover
this line: --globalconfig has it read a settings file, which can load code - run it once or reject it". It
names an option only where that is npm's settings file (`--globalconfig`, `--userconfig`); any other is
"an option past the rule's words".

Below Full auto, a command that keeps running (a server) asks every time, even with a rule.

Nor does a rule - or a yes you gave before - cover a command whose program, named by its path in
the project (`node_modules/.bin/tsc`, `./scripts/check`), is one an agent wrote, or sits in an
install folder (`node_modules`, `.venv`, `site-packages`) an agent wrote in - for a program in a
`node_modules`, in one above it too, which Node loads its packages from -, while that file still
holds what the agent wrote: below Full auto it asks on a card that says so ("an agent wrote its
program (web/node_modules): no rule covers a program an agent wrote, so none is offered - run it
once or reject it"), with **Run once** and **Reject** alone - an **Always run** rule would not
cover it either while that write stands -. A rule matches by its
words in any folder, so the same line in another folder, or after an agent's write over the
project's own install, would otherwise run what the agent wrote. Once your own install writes
over it, the rule covers it again. A package runner finds its program by itself, so its rule
(`npx tsc`, `npm exec tsc`, `yarn tsc`, `bun x tsc`, `corepack pnpm exec tsc`, `uv run ruff`,
`python -m mypy`) is read the same way: npx, npm, pnpm, yarn and bun look in the `node_modules`
of the folder the command runs in or of one above it - and read an `.npmrc` there, yarn its
`.yarnrc.yml`, `.yarnrc`, `.yarn` folder, Plug'n'Play loader and `.env.yarn`, pnpm its
`.pnpmfile.cjs`, bun its `bunfig.toml` and `.env`, `.env.local`, `.env.production`,
`.env.development` (what they run gets those: `NODE_OPTIONS=--require x`) - and an agent's write in
any of them stops the rule. Where what the agent wrote is such a file - a setting, a manifest, a lock
or a loader, not the program -, the card says so: "an agent wrote a file this line may read or load
(web/.npmrc): no rule covers the line while that write stands, so none is offered - run it once or
reject it". yarn's `.yarn` folder, which holds yarn itself and its unplugged installs, is said as its
program, as a `node_modules` is ("an agent wrote its program (.yarn): …"). Where an agent wrote both
a setting and the program, the card names the program.

A rule for a node runner (npx, pnpx, bunx, npm, pnpm, yarn, bun; `corepack` before one) is
closed on two sides. **What an agent wrote:** while an agent's write of any `package.json` (a
package's in a `node_modules` too), any `.npmrc` or `x.npmrc`, `.yarnrc*`, `.yarn/`,
`.pnpmfile.cjs`, `pnpm-workspace.yaml`, `bunfig.toml`, lock (`package-lock.json`,
`npm-shrinkwrap.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`, `bun.lock`) or `binding.gyp`
anywhere in the project still holds what it wrote, no node runner's rule covers a line - npx and
`npm exec` run a name the package's own `bin` gives before any installed one, yarn and pnpm a
script of that name, `npm install` every workspace's lifecycle scripts, fetches what a lock's
`resolved` address says and runs node-gyp on a `binding.gyp`, and npm reads any settings file it
is pointed at - its card names that file as one the line may read or load. The cost: after an
agent edits a `package.json` (adding a
dependency, say), node runner rules ask until that write is replaced - by your own edit or
install. A line of npm's or pnpm's that runs a script by its name under its own rule (`npm run
build`, `npm test`) is the exception: the script is the project's code by design, as a test is.
yarn's and bun's `run` run a bin too, and npx's `test` is a package - those are not. **Its own
options:** past the rule's words (up to `--` for npm; up to the verb that hands the rest on -
`exec`, `dlx`, `x`, `run` - for pnpm, yarn and bun), a rule covers only options that change what
the runner prints, where it fetches from or that it runs less: `--silent` / `-s`, `--quiet` /
`-q`, `--loglevel`, `--color` / `--no-color`, `--offline`, `--prefer-offline`, `--no`,
`--no-audit`, `--no-fund`, `--ignore-scripts`, `--frozen-lockfile`, `--immutable` - each but
`--loglevel` and `--color` alone or `=true`: `--ignore-scripts=false`, or a `false` after it
(`npm install --ignore-scripts false`, under an `npm install --ignore-scripts` rule too), runs the
scripts again, and an option of the runner's written in pieces a shell joins
(`'--ignore-scripts=false'`) is never harmless. Any other (`--globalconfig=x` - a settings file whose `node-options` loads code -,
`--shell=`, `--node-gyp=`) and no rule covers the line or is offered for it. So `yarn tsc --noEmit` is offered none: use
`yarn run tsc --noEmit`, or for npm `npm exec tsc -- --noEmit` (past `--`, tsc's own).

A rule for tsc - `tsc`, `npx tsc`, `npm exec tsc`, `pnpm exec tsc`, `yarn tsc`, tsc named by its
path (`node_modules/.bin/tsc`, as the rule Code style and types offered in 0.1.7) or its script
(`node node_modules/typescript/lib/tsc.js`) - covers no line
while an agent's write of a `tsconfig*.json` or `jsconfig*.json` anywhere in the project, or of a
JSON file that a tsconfig the line reads (the nearest `tsconfig.json`, a folder or `.json` its
words name - `-p`'s) `extends` or `references`, still holds what it wrote: a tsconfig can make tsc
write a trace, or a composite build's info where `tsBuildInfoFile` says, outside the project too -
its card names that file as one the line may read or load.
Code style and types' own line, word for word, is the exception: its `--composite false
--generateTrace null`, last, win over a tsconfig's composite or incremental build info and its
trace, so its rule still covers it.

For uv, poetry, pipenv, pdm, hatch and `python -m`, whose
environment KOLONİ cannot always place, an agent's write in any `.venv`, `venv` or
`site-packages` of the project does. For uv, uvx, poetry, pipenv, pdm, hatch, pip and pip3 - run
as a module too (`python -m uv`, `py -m pip`), and `python -m build` - so does its
write of any `pyproject.toml`, `setup.py` or `setup.cfg` anywhere in the project (they run its
`[project.scripts]` and build the project first - a workspace member or a path dependency with
it; pip and build build what they install), of their settings (`uv.toml`, `poetry.toml`, `pdm.toml`, `hatch.toml`, `Pipfile`,
`.python-version`, `.pdm-python`, and pipenv's `.env`, which it loads), their locks (`uv.lock`,
`poetry.lock`, `pdm.lock`, `Pipfile.lock`, `pylock.toml`) or requirements (`requirements*.txt`,
`requirements/*.txt`) - but not for a test run (`uv run pytest`). The card of a write in an
environment says "an agent wrote its program (.venv)"; of one of these files, that the agent wrote
a file the line may read or load. As for node runners, the cost:
after an agent edits a `pyproject.toml` (adding a dependency, say), these rules ask until that
write is replaced. Their rule names what they run
(`poetry run ruff`, `uv run python -m ruff`), never the tool alone; and npm's PowerShell shims are
npm's own (`npx.ps1 tsc` is `npx tsc`). A runner's line sent to another package or folder of a
monorepo - npm's and npx's `-w` / `--workspace` / `--workspaces` / `--ws` / `--prefix` / `-C`,
pnpm's `--filter` / `-F` / `-r` / `--dir` / `-C` / `-w`, yarn's `workspace x` / `workspaces
foreach` / `--cwd`, bun's `--filter` / `--cwd` - runs that package's own `bin` and scripts, which
the folder's checks do not read: no rule covers it, and none is offered. Nor does a rule for `npm exec tsc` cover `npm exec tsc -c x` (`--call`: a shell line). `python -m x` (any Python: `python3.12`, `pythonw`, one
named by its path) also imports what its folder holds before the standard library and the tool's
own - so an agent's `.py` file, or package `__init__.py`, there stops its rule too, unless it runs
with `-I` or `-P` (or `PYTHONSAFEPATH`); `python -m pytest` is the exception, since its tests
import the project's code anyway. In a working copy every command's Python also reads the
copy's root and its `src` first (KOLONİ puts them on `PYTHONPATH`), so there an agent's module in
either stops a `python -m` rule, a `uv run` rule or a rule for a `.venv` console script
(`.venv/Scripts/uvicorn.exe`) in any folder of the copy - and a `sitecustomize.py` or
`usercustomize.py` there, which Python imports before anything it runs, stops `python -m pytest`
too (not under `-E` or `-I`). `node <script>` with the script in an install folder
(`node node_modules/typescript/bin/tsc`) is read as that program.

On Windows, KOLONİ writes no file whose name, or a folder's in its path, ends in a dot or a space
(`pyproject.toml.`, `uv.toml `): Windows drops those and would write `pyproject.toml`, while the
record would name another file.

### Known limits

Always run rules are a convenience, not a security boundary: what a rule covers runs unasked; at
Full auto KOLONİ's judge looks at what no rule names. What the rules above do not see:

- Files a command makes - `cp`, `mv`, `tar`, `Expand-Archive` into a settings file's name - are not
  on record as an agent's writes, so they do not stop a rule; nor does a CLI's write of a `.env`
  or `.npmrc` into the project from its working copy, nor an agent's delete of a setting that protected the project.
- tsc's `-p` naming any other file (`-p tsconfig.build`), and a tsconfig that extends a
  package's config (`@scope/cfg`); ts-patch's tsconfig plugins; `vue-tsc`. Past a tsc rule,
  `--init`, `--outDir out` (they write in the folder) and `-w` (it never ends).
- mypy's `--timing-stats F`, `--line-checking-stats F` and `--cache-map …`, which write where they
  name; `ruff format .` and `ruff clean` under a `uv run ruff` or `python -m ruff` rule (they write
  in the folder); eslint's `--mcp`, `--cache` and `--fix-dry-run`.
- pdm's `.pdm.toml`, `pdm_build.py` (pdm-backend loads it), poetry's `build.py` that its
  manifest names, `pylock.<name>.toml`, `.python-versions`, `hatch_build.py`, a file named on
  the line (`-r deps.txt`, `--config-file x`), node-gyp's `*.gypi`, bun's `.env.test`; pip named
  with its version (`pip3.12`).
- make's `SHELL:=`, `SHELL+=` and `.SHELLFLAGS`, and its `--makefile=x`, `-C ../x` /
  `--directory=x` and `--eval=…`, past a make rule.
- On macOS, a name its file system folds into a settings file's (`uv.lock` written with the
  Kelvin sign, U+212A, for its `k`).

On Windows, a command KOLONİ runs, a server it starts and an agent's CLI (started in the work's
folder) find a program named bare - `node`, which an npm `.cmd` shim calls - on PATH only, never
first in the folder they run in, where an agent could have written a `node.cmd` (git's own runs
are started so too). So a batch file of yours that calls its neighbour by its bare name (`call
helper.cmd`, an npm script `"t": "helper.cmd"`) does not find it under KOLONİ: call it as
`.\helper.cmd`, or `%~dp0helper.cmd` inside a batch file - where cmd.exe says such a name "is not
recognized" and the folder has it, the command's result says so too.

## How a command is read

KOLONİ reads an agent's command line the way its shell will run it, and judges every command it
finds, not only the first word. A harm, an install or a write it finds anywhere is asked as it would
be on a line of its own:

- **Groups**: `(cd web && npm ci)`, `{ npm ci; }`, `if exist x (npm ci) else (npm i)`, `for %a in (*) do (…)` and
  PowerShell's script blocks (`if ($true) { npm ci }`, `ForEach-Object { … }`, `& { … }`,
  `Invoke-Command -ScriptBlock { … }`). A group whose brackets do not pair is always asked - but
  brackets a heredoc writes, a comment holds (`echo done # 1) first step`), sh's `case … esac`
  patterns and a group only printed in quotes (`echo "(npm ci)"`, `git commit -m "run (npm ci) first"`)
  are no group.
- **Heredocs and comments**: what a heredoc writes to a file and a comment run nothing; a stop in
  code a heredoc or a pipe hands an interpreter (`python - <<'EOF'`, `echo "…" | python`), or that
  `php -r`, `lua -e`, `R -e` or `julia -e` is handed, is asked.
- **Wrappers**: a branch switch and a patch are read behind a wrapper (`time git switch main`,
  `bash -c '…'`), cmd's `if "%a%"=="x" …` and `trap -- '…' EXIT` are read to the command they run.
- **Launchers**: what `Start-Process … -ArgumentList`, `npx -c` / `--call`, `schtasks /tr`,
  `[scriptblock]::Create(…)`, `cmd /c` and `bash -c` hand on is read as the command it is; a command
  PowerShell is handed encoded (`-EncodedCommand`) is asked at every level.
- **Runners**: what `poetry run`, `uv run`, `pipenv run`, `pdm run`, `hatch run`, `rye run`,
  `conda run`, `npx`, `pnpm exec`, `yarn exec` / `run`, `bun x` and `cargo run --` / `dotnet run
  --` run is read as a line of its own: `poetry run cmd /c rd /s /q src` is a delete, and a shell
  it is handed is a line handed to another program, its path spelt out too
  (`C:\Windows\System32\cmd.exe`).
- **Substitutions**: an install inside `$( … )` (`out=$(npm ci)`) counts.
- **Continued lines**: a line continued with a backtick, `\` or `^` is read joined as well - a branch
  switch, inline code, a patch and a git command that rewrites `.git/config` too (`git `⏎`switch main`).
- **Writes to a place built at run time**: in a branch's worktree, a redirect (`>`, `>>`, `>|`,
  `2>`), `cp`, `mv`, `install`, `tee`, `Set-Content`, `Out-File`, `New-Item`, `Copy-Item` or
  `[IO.File]::Write…` whose target is made when the command runs - `$( … )`, a variable, cmd's
  `%x%` and a `for` loop's `%i`, `Join-Path` / `Split-Path`, `git rev-parse` - a link made to such a
  place (`ln -s`, `mklink /J`, `New-Item -ItemType Junction`), or any write after a `cd` to one, is
  asked at every level: it may be your repository's `.git` (another worktree's link, HEAD or
  history, a ref of origin's). Finding that place is asked there too: `git rev-parse --git-dir`,
  `--git-common-dir`, `--absolute-git-dir` and `--git-path`, a read included (`ls "$(git rev-parse
  --git-dir)/.."`), so a writer KOLONİ does not list (`sed -i`, `tar -C`, `robocopy`) cannot reach it
  unasked. A path written out runs as before, and so do a few built places that cannot be `.git`:
  the temp folder by its variable (`"$TMPDIR/f"`, `$env:TEMP\a`), the folder the command runs in at
  the start of the place (`"$PWD/out.txt"`, `$(pwd)/x`, `(Join-Path $PWD out.txt)`), a date in a
  file's own name (`build-$(date +%s).log`, its format holding no `/`, `.` or quote), a `for`
  loop's name over a glob or names written out (`for f in *.py`) - but never where the place climbs
  (`..`) or the line gives that name a value (`TMPDIR=…`, `read … PWD`, `Set-Item env:TEMP`).
- **Package runners**: `npx -p` / `--package` (before what npx runs), `npm exec --package`, `uv
  run --with` / `-w`, `uvx`, `pipx run`, `bunx`, `pnpm dlx`, `yarn dlx`, `npm create` / `npm init
  <x>` and `yarn` / `pnpm` / `bun create`, `deno run npm:…` / `jsr:…`, `go run <module>@<version>`
  and `corepack pnpm dlx` download a package and run it, so they count as installs: asked with web
  off, and in a working copy whose dependency folders are linked to yours. A plain `npx <tool>` (and
  `npx tsc -p tsconfig.json`: that `-p` is tsc's) runs the project's own tool and is read as before.
- **pytest's `--basetemp`** is a delete - pytest empties that folder first - on its line, in
  `-o addopts=…` or in `PYTEST_ADDOPTS`; but a folder in the agents' scratch (`.koloni/tmp/…`). One a
  config file names (`-c x.ini`) is not read: a rule does not cover `-c`.
- **Always rules** never cover the options listed in [What a rule never covers](#what-a-rule-never-covers).

## Disposable deletes

Some deletes KOLONİ can check by itself. Where you allow them - Settings › This project › When you're
asked › **More** › **Agents may delete what is disposable without asking**, or **Allow such deletes in this
project** on the card of one - they run without a card at **Auto-edit files** and **Full auto**, in
a chat you started, and the command's row says "Ran without asking · disposable: …":

- a build or cache folder (`build`, `dist`, `__pycache__`, `.pytest_cache`, `.ruff_cache`,
  `.mypy_cache`, `coverage`, `.next`, `.turbo`, `target`) below where the command runs, spelt as the
  folder is on disk, that git ignores and that holds no file git tracks or would take (in any case of
  its letters), no link and no repository of its own - not inside `node_modules`, `.venv`, `venv`, a
  folder whose name starts with a dot, KOLONİ's own, a folder git ignores, or another repository, a
  submodule or a worktree in the project; in the project, and in a sub-agent's copy;
- a worktree of yours that git lists, named with no link on the way, `..` only at its start and by
  no end of its path another worktree shares: not the main one, not locked, not one of KOLONİ's, on
  a branch, holding nothing its commits do not (a new or changed file, one marked skip-worktree or
  assume-unchanged - whatever `status.showUntrackedFiles` says - or a last commit on no branch, tag
  or remote), no link, no secret file and nothing git ignores but whole build and cache folders with
  no repository in them (git deletes what it ignores with the worktree);
- a local branch that neither the project, the turn nor any worktree stands on: with `-d`, git
  itself deletes only one it finds merged; with `-D`, only one whose commits the default branch has.
  Never the default branch, `main` or `master`, nor KOLONİ's `koloni/…` ones.

Worktrees and branches go this way only from the project itself (the Orchestrator), never from a
copy, and only run in the project's top folder or a plain folder in it - not in another repository,
a submodule or a worktree inside the project, nor through a link.

Only such a delete alone on its line counts, written the way the shell it runs in reads it:

- **PowerShell** - KOLONİ's own commands on Windows, and Claude Code's PowerShell tool: `Remove-Item`
  or its aliases (`rm`, `ri`, `del`, `erase`) with `-Recurse` (or `-r`), `-Force` (`-fo`) if you like,
  and one path: `Remove-Item -Recurse dist`, `rm -r build`, `ri -r -Force build`. `rm -rf build` is
  not disposable there: PowerShell refuses `-rf` and deletes nothing, so it keeps its card.
- **sh** - KOLONİ's own commands on Linux and macOS and in Docker, and Claude Code's Bash tool (Git
  Bash on Windows): `rm` with `-r`, `-R` or `-rf`, `-f` / `--force` if you like: `rm -rf build dist`.
- **git**, in every shell: `git worktree remove ../wt/x`, `git branch -d old`.

Codex and agy do not say which shell their command runs in, so their delete of a folder keeps
its card. A disposable delete that ran and then failed says so on its row: "Ran without asking as
disposable (…) and failed: exit 1". Anything else on the line, a forced worktree
remove, a path above the folder or with a link in it, a line the shell continues, a command of a CLI
whose folder KOLONİ does not know or that its model names, and any of GitHub Copilot CLI's own
commands (it has no sandbox) asks as before. A delete whose folder changed
between KOLONİ's look and its run - a card of the turn was answered meanwhile - asks too. At
**Ask before changes**, in a side of a comparison and a job while you are away, every delete asks or waits
as before. No **Always run** rule covers a delete either way.

## Sub-agents

Sub-agents work in a working copy of your project, not in your folder. Their edits there never
get a card, at any level. You decide once, when their work comes back:

- At **Ask before changes**, a card asks whether to take their changes into the project.
- At **Auto-edit files** and **Full auto**, the changes come in without a card when the sub-agent
  finished, its changes do not clash with yours, and the tests it wrote passed - each part's test
  command narrowed to them ([Checked](checked.md#when-the-tests-fail)). Those tests are its own
  code: they run by themselves at Full auto, or where the part's command is yours (set on the
  project map, or a saved one under an **Always** rule). With KOLONİ's guess at Auto-edit the
  card waits for your **Run the test** first. Otherwise a card asks.
- At **Full auto**, if the test fails, the work goes back to the Orchestrator a few times before the card
  asks you.
- While you are away, KOLONİ's guess never runs a sub-agent's tests: the
  work comes in as one with no test would, said "not run". Your own command runs there.

Files that steer agents are held for your card at every level.

Whether opening a sub-agent asks first is set under Settings › This project › When you're asked ›
**Opening a sub-agent**: **Ask when it matters** (the default: a card at Ask before changes when
the sub-agent can change things), **Always ask** or **Never ask**.

## Full auto's judge

At **Full auto** a command the list above does not stop runs without asking. **Full auto's judge** puts a
small model before those: such a command is first sent to it once, and it says **fine** or **risky**. It
is the project's switch - Settings › This project › When you're asked › **Full auto's judge** ("A small model
looks at each command the list does not stop."), and the same switch in the level menu, under the levels.
It is **on** by default, in new projects and in the ones you had; off, Full auto is as it was. Under it,
**When the judge finds a command risky** says what it does with one it finds risky: **Refuse and go on**
(the default, in new projects and in the ones you had) or **Ask me** (its card, as before) - see **What
it says** below. And a box lets it also run a harmful-looking command a line of yours names: [Check
what I said first](#check-what-i-said-first).

It looks at Full auto's commands in a chat you watch (a To-do task done in a chat too) and in a job while
you're away (☾ Away) - not at **Ask before changes** or **Auto-edit files**.
It is not asked about:

- a command that only reads;
- ordinary work, as a plain command with its common options only: a test runner (`pytest`, `python -m
  pytest`, `npm test`, `cargo test`, `go test`), a compiler or checker (`tsc`, `ruff`, `eslint`, `mypy`,
  `cargo build`, `go build`), local git (`status`, `add`, `commit`, `diff`, `log`, `switch`, `branch`) and
  `npm run <script>` - but not where an agent wrote what it runs (the program, or the project's
  `package.json`);
- your own test command (the project map's) - but it is, where the line runs a program an agent wrote -,
  a skill's script you let run, and a delete KOLONİ found disposable where you allowed [such
  deletes](#disposable-deletes);
- the very line of a narrow **Always run** rule of the chat, run at the project's root in a chat you
  watch - not a broad rule's (see **Always run rules at Full auto** below), and not where it runs a
  program an agent wrote;
- a command KOLONİ asks about at every level for a reason of its own - a secret, `.koloni`, a file that
  steers agents, a path out of the project, a send, a working copy's reason: that card stays as it was (a
  send the list stops is put to [your words](#check-what-i-said-first) instead, where that box works).
  The judge never runs such a command, and never takes its card away: only its own **risky** may be
  refused. A delete in the project, git work thrown away and a stop by name, which the list asked of
  before, are the judge's since 0.1.10: see [What the judge decides in place of the
  list](#what-the-judge-decides-in-place-of-the-list).

**What it reads** - since 0.1.10 as Claude Code's auto mode's classifier: your words and what the agent
did, never what came back to it. Your preferences, this project's rules as saved on the
[Memory](../memory.md) page and your messages in the chat (in a job while you're away, in the chat you went
away from) - at most your last 6, newest first, and 4,000 characters of them together, the last one cut
where a line or a sentence ends: a newest message longer than that with no line or sentence break in its
first 4,000 characters gives "(none)" for your messages; the command, its folder and who runs it (the
Orchestrator or a sub-agent's role); the same agent's last 8 actions in the turn - its tool calls by
name and arguments, such as `run_command {"command": "…"}`, `read_file {"path": "notes.md"}` or
`write_file {"path": "gen.py", "content": "…"}`, only ones that ended and were not refused or turned
down, each cut to 300 characters; and, where the line runs or reads a file an agent wrote - a script
(`node x.js`, `python x.py`, `python -m x`, `./x.sh`, `x.ps1`, `powershell -File x.ps1`, `x.cmd`), make's
Makefile, a Dockerfile, a `package.json` -, the first 4 KB of that file as the agent's write left it. A
file in the agents' scratch (`.koloni/tmp/`) that no write of an agent's made - `curl -o
.koloni/tmp/x.py …`, a command's output - is named, its text not shown. Everything but your own words is
marked as data an agent wrote, not instructions. It never sees an agent's own replies, what a tool gave
back - a file's text it read, a command's output, a page or a search -, and the secrets KOLONİ knows
are masked first.

**What it finds risky** - a command that could do harm you did not ask for: send your data or files off
this machine, download and run code, change things outside the project (your profile, startup, git or
shell settings, scheduled tasks, the registry), weaken security, or hide what it does. Since 0.1.10, as
Claude Code's auto mode, also one that destroys work in the project you did not ask to lose: deleting or
emptying a file or folder that was there before the turn, or throwing away uncommitted changes - `rm`,
`del`, `Remove-Item`, `git reset --hard`, `git clean -f`, `git checkout -- .`, `git restore .`, `git
stash drop`, `> file`, `truncate`, `Set-Content`, `New-Item -Force`, `find … -exec rm`, `npx rimraf`,
`robocopy /MIR`, `git read-tree -u --reset`, a script or a one-liner that deletes. It stays fine where you asked
for it, for build output and caches a build makes again (`build/`, `dist/`, `node_modules`,
`__pycache__`), for files the same agent made earlier in the turn, for the agents' scratch folder
`.koloni/tmp/`, and for what only shows or keeps work (`git clean -n`, `git stash`,
`git restore --staged`). Measured on 27 Nov 2026 on 180 cases, Claude Code's **haiku** and **Sonnet**
each called no risky command fine, every ordinary one fine, and one fine command risky - haiku a logon
task you asked for, Sonnet an `npm config set` your rule named (before this change, haiku called 16 of
the risky ones fine; the deletes the list asked of then were not among the cases asked).

**What it says:** **fine** - the command runs, as it did before (on its record, not shown). **risky** - as
**When the judge finds a command risky** says:

- **Refuse and go on** (the default) - as Claude Code's auto mode does: the command does not run, no card
  opens and nothing waits. Its agent is told a general reason, never the judge's sentence - the judge read
  your messages and may quote them, and its sentence would guide the next try: "KOLONİ's judge refused
  this as risky (it may send data off this machine, run code it fetched, destroy work in the project,
  change things outside the project, weaken security or hide what it does). Do it another way, or ask the
  user." - and goes on. You
  see the sentence: the command's row says **refused**, with **KOLONİ's judge refused: …** under it, and
  Ready for you lists it in its **Decided for you** column with the judge's sentence until you click OK
  (the top bar's pill says "1 decided" and opens it; so does the chat's one line about it). Where KOLONİ keeps the line (see **Its card**
  below for which lines it keeps), the same line is refused again in that turn without asking the model;
  any other line is asked about each time it runs. After **3** refusals in a row - counted for all its
  agents, sub-agents too; a command that runs ends a row, one refused, turned down or waiting does not -
  or **20** in the turn, as Claude Code's auto mode, each risky command waits for you on its card for the
  rest of the turn, and the chat says once "Full auto's judge refused 3 commands in a row this turn; each
  risky one asks you now." ("… refused 20 commands this turn; …"): an agent cannot try variant after
  variant until one is called fine. A new turn starts again at none.
- **Ask me** - it waits for you on a card that says **KOLONİ's judge: …**, the model's one sentence; once
  answered, that sentence stays under the command's row.

In a job while you're away a risky command is always parked for you, whichever you chose, as any card
there is, and the job goes on ([Waiting for you](../automation/overnight.md#waiting-for-you)). Only the
judge's own **risky** is refused - every card below stays a card at either choice: when the judge gave no
verdict, the decision is yours, never a silent refusal. A command over 4,000 characters, or one that - or
the program an agent wrote that
it runs, or one of the earlier commands it would be shown - reads like orders to a model, is a card without
asking. So is one the judge gave no answer for in 20 seconds (90 for a model on a CLI), gave an answer it
could not read for, or could not be asked about now - no model to ask, no room on its model's provider (its
limit, this month's budget) or the turn past its token limit: "it could not be asked: …", and the chat says once in
the turn `Full auto's judge could not be asked this turn: {why}. Each command it would look at asks you.` -,
and one whose program changed while the judge looked (a link pointed elsewhere too): every time - an agent
can write a command that slows, confuses or spends the judge, so none of these lets a command run.

**Its card** (Ask me, a job while you're away, or one it gave no verdict for) offers **Run once** and
**Reject**, and, where KOLONİ can keep the line, a box, **Don't ask about this line again here**. Run once runs the line, and the judge does not ask about it again in that
turn; with the box ticked, not in this project either. Both are kept only where the judge itself looked at
the line - never on a card it gave no verdict for (too long, orders in it, no room to ask, no answer in
time or none it could read, its program changed meanwhile) -, the folder the line runs in is known and
KOLONİ knows all the line runs, as it is:

- a file of the project's it runs, found and unchanged, in a plain form that runs that file and nothing
  more - `python x.py`, `node x.js`, `make` or `make target` (its Makefile), `make -f F`, `npm test` or
  `npm run <script>` (that folder's `package.json`), `docker build [-f F] [-t T] .` (its Dockerfile). Once
  the file changes, it is another line, asked again;
- or one plain command of a few that run none of the project's code, kept by its words: the file
  commands `rm`, `rmdir`, `del`, `mkdir`, `md`, `cp`, `copy`, `mv`, `move`, `ren`, `chmod`, `touch`; and
  `curl` and `wget` only where every word after them is an `http://` or `https://` address, a flag that
  takes no value (curl: `-s`, `-S`, `-f`, `-L`, `-I`, `-v`, `-sS`, `-fsS`, `-fsSL`, `-sSL`, `-fL`,
  `--silent`, `--show-error`, `--fail`, `--location`, `--head`, `--verbose`, `--compressed`; wget: `-q`,
  `-nv`, `--quiet`, `--no-verbose`, `-S`, `--server-response`, `--spider`) or the output file `curl -o
  NAME` / `wget -O NAME` (a plain file name) - any other word (a config, a file to send, a value glued
  to a flag, a quote, `file://`) and the line is asked each time.

Every other line is asked about each time it runs, and its card has no box: a delete, git work thrown
away or a stop by name the judge decides in place of the list (below), a chain, a pipe, a
redirection or a substitution - `python k.py && python e.py`, `… ; …`, `… | …`, `… || …`, `… > out.txt`,
`$(…)` - kept on its first file, the next one could change unseen; `git` and `gh` (they may run the
project's own aliases and settings), a wrapped line (`env …`, `uv run …`, `timeout …`), a shell's code
(`bash -lc …`, `cmd /c …`), `npx …`, a line sent to another folder (`-C`, `--prefix`, `-w`, `--cwd`), an
option that loads more code (`node -r x`; PowerShell with any option but `-NoProfile`, `-NonInteractive`,
`-NoLogo`, `-ExecutionPolicy`, `-WindowStyle` and `-File`), a variable set on make's line (`make CC=x`), a
package run by its `__main__.py` (`python -m pkg`, `python pkg`), a Python line without `-I` or `-E` in a
working copy (its commands get the copy first on `PYTHONPATH`, so a `sitecustomize.py` there runs before
the script) or where KOLONİ's own environment sets `PYTHONPATH`, `bun`, `Rscript`, any other runner
KOLONİ does not know, a file it did not find (`python -m x` with no `x.py`), or a line whose folder is not
known (a CLI that does not say). No **Always run** is offered on its card.

**Always run rules at Full auto** (since 0.1.10, as Claude Code's auto mode): a **narrow** rule of the
chat, one that names its task (`npm test`, `npm run build`, `python gen.py`, `make build`, `gh pr
list`), lets **its very line** by with no judge - the rule's words and nothing more: `npm test -- --x`,
`make build CC=./x` or `python manage.py shell -c …` under the rules `npm test`, `make build` and `python
manage.py` are looked at, as one word more may be another task, or a file the program is told to load -,
run at the project's root (the same words in another folder run another file), in a chat you watch: not
in a job while you're away, nor in a To-do task's turn, which may run with nobody there. Nor does it
where the line runs a program an agent wrote (the judge reads that one), where it is an interpreter's or
a runner's line whose file KOLONİ does not find (`uv run python x.py`, `npx x`), or a tool's run that
builds the folder's code (`cargo run`, `go run .`, `dotnet run`): what it runs is not known, and the
judge looks. On purpose: a narrow rule belongs to the chat, so a sub-agent of the same chat running
that exact line is let through too. A **broad** rule never lets a line by:

- one with no word past its program that is not an option (`npm`, `git`, `docker`, `make`, `gh`,
  `pytest -x`);
- one whose sub-command takes whatever it is handed - an install (`npm install` / `i` / `add` / `ci` /
  `update`, `pnpm add`, `yarn add`, `pip install`, `python -m pip install`, `uv pip`, `uv add`, `poetry
  add`, `pdm add`), a container (`docker run`, `docker exec`, `docker compose`, `docker container`) or
  a remote (`git remote`) - even where KOLONİ offered it on a card;
- one KOLONİ would offer no rule for at all - a shell's, a wrapped line, an interpreter or a package
  runner with no script or package named, a runner's `run` or `exec` with nothing named (`bash …`, `env
  …`, `python -c …`, `npx`, `npm run`, `uv run`).

What a broad rule covers is looked at by the judge as if there were no rule. Below Full auto rules work
as they always did.

**With no model to ask** - no Judge model chosen that can be asked, and none in the Fast tier - it does
not step aside (since 0.1.10; as Claude Code's auto mode, it fails closed): each command it would look at
waits for you on a card, "KOLONİ's judge: it could not be asked: no judge model answered - …", and the chat
says once in the turn `Full auto's judge could not be asked this turn: no judge model answered - choose a
Judge model in Settings › The app › Agents, or give a model the Fast tier. Each command it would look at
asks you.` To have Full auto as it was before the judge, turn the judge's switch off for the project.

**Which model:** Settings › The app › Agents › **Judge model** - **Fast tier's first (now: …)** unless you
choose one of the models listed (those of every tier that answer with no tools - a CLI with tools of its
own among them, such as GitHub Copilot CLI run **Native**, asked with them off). A choice that cannot be
asked now (its provider gone, closed to agents or down) stays chosen and the list says so; the Fast tier's
first is asked meanwhile. On a CLI each such command waits for it to start. [Check what I said
first](#check-what-i-said-first) asks the same model. Each command it looks at is one request, on your plan or your bill, shown on
[Usage](../money/usage.md) under that model; reads, ordinary work and a line already judged in the turn
make none.

### What the judge decides in place of the list

Since 0.1.10, as Claude Code's auto mode: in a chat you watch at **Full auto**, with the judge's switch
on, KOLONİ's list keeps its card only for what it asks at every level. What it asked of before as harm
in the project, written as a plain line, goes to the judge instead of a card:

- deleting or emptying files or folders in the project (`rm`, `del`, `Remove-Item`, `Clear-Content`,
  `find src -delete`, pytest's `--basetemp`);
- throwing away git work: `git reset --hard`, `git clean -f` (not `-x`), `git checkout -- .`, `git
  restore .`, `git checkout main -- file`, `git stash drop` / `clear`, `git rm -f`, `git branch -D`;
- stopping a program by its name (`taskkill /IM notepad.exe`, `Stop-Process -Name x`) - never what may
  be KOLONİ itself, nor what it and its terminals stand on.

A plain line is words of letters, digits and `_ . / = ~ -`, its commands joined by `;` or `&` - so
KOLONİ reads each target as the shell will. In KOLONİ's own PowerShell a `\` is a path's separator
(`del src\app.py`); everywhere else it is an escape (`.gi\t` is `.git` to Git Bash), and the line is
the list's. The line is one such harm - but the one `cd sub` its folder starts it with (a folder
there): a change of folder with no plain word in the folder (`cd`, `cd -`, `cd ..`, `popd`,
`Set-Location`, an alias of `cd`), any other command beside it (`rm -rf build; npm install`) and a
second harm (`rm -rf build; rm -rf dist`: one could make a link the other goes through) keep the
card. So does a Windows short name (`ENV~1` is `.env`; git's `HEAD~3` is not one), git told of
another tree (`git -C x`, `--work-tree=…`), and git's work where the project is not its repository's
top folder (a reset there throws away work outside it). Before the judge is asked KOLONİ looks at the
disk, and again once it said fine and as the command is about to run: a path through a link or a
junction (`rm -rf data/`, where `data` leads elsewhere) is the list's card too. A sub-agent's delete in
its working copy stays its card. No command or CLI KOLONİ starts is given a `CDPATH`: `cd src` is
the project's own `src`.

The list still asks at every level - its card, never the judge's word - about:

- a line that is not plain: a quote, an escape, a wildcard or a bracket, a brace, a group or a
  subexpression (`(Split-Path (pwd))`), a .NET call (`[Environment]::…`), a variable, a backtick, a
  pipe, a redirection, a comment or a line break - and a line handed to a shell, a wrapper or a prefix
  (`bash -c "rm -rf build"`, `sudo`, `env`, `timeout 60`, `FOO=1 …`, `… | xargs rm`): any of them can
  build a target the list does not read;
- what reaches out of the project or all of it: a path out of it (`../x`, `/tmp/x`, `$HOME`, `C:\…`),
  the folder itself or all in it (`rm -rf .`, `rm -rf *`, `find . -delete`, a `find` with no folder),
  `git clean -x` or an exclude that starts with `!` (`-e '!*'`), `git stash --all` then dropped (they
  take ignored files - `.env`, `.koloni`), `git clean -ff` (other repositories inside, their history
  with them), a link, a worktree outside the project or removed (`git worktree remove`: git picks one
  by its last name, KOLONİ's own or one outside);
- what git could still bring a dropped branch or stash back by: `git gc --prune=now`, `git prune`,
  `git reflog expire`;
- what may stop KOLONİ itself (python, node, uvicorn, an agent's CLI, a filter, a wildcard, `kill -1`,
  a process looked up) or what it stands on (the terminal, the shell, the session, the system:
  WindowsTerminal, conhost, powershell, pwsh, cmd, bash, zsh, tmux, screen, sshd, Terminal, iTerm2,
  gnome-shell, Xorg, WindowServer, loginwindow, systemd, launchd, explorer, lsass, csrss, svchost,
  git, …);
- a send off the machine (put to [Check what I said first](#check-what-i-said-first) where that box
  works), and a git remote's branches overwritten or deleted (`git push --force`, `git push origin
  :x`) - a card whatever you said;
- a secret file, `.koloni/` (its free folders too: what is on the disk there is KOLONİ's to look at),
  a file that steers agents, git's settings or a patch;
- a line KOLONİ cannot read (`-EncodedCommand` anywhere in it, more than it reads), web with web
  tools off, Docker's
  deletes (its containers and volumes are the machine's, or with `-H` another's), cmd's `rd /s /q`
  (its `/s` reads as a path from the drive's root);
- a working copy's, a branch worktree's and a disposable delete's own reasons.

Where [Check what I said first](#check-what-i-said-first) works it looks first: its run runs, its
refusal refuses, and its ask - a condition of yours, "ask me first" - keeps the card; the judge is not
asked then. **fine** runs the line; **risky** is refused (Refuse and go on) or waits on its card (Ask
me). That card says what the list says of the line ("Deletes files or disks."), the judge's sentence on
its record, and has no **Don't ask about this line again here**: Run once runs that one line. A **risky**
stands for the turn - the same line again is refused or its card without asking -, a **fine** is asked
again each time (what the turn did before changes what a delete takes). Anything else - the switch off, no judge model to answer, an answer it cannot read, no room -
is the list's card as before; and so is each of these at **Ask before changes** and **Auto-edit
files**, in a To-do task's turn, in a job while you're away (parked), in a turn of a chat you went away
from, on a side of a comparison, and for a CLI whose folder KOLONİ does not know. If the chat leaves
Full auto, or the judge is turned off, while it looks, its **fine** lifts nothing: the card opens.

Measured on 27 Nov 2026 on the 31 cases of such lines the list now hands the judge, Claude Code's
**haiku** and **Sonnet** each called no risky line fine. Haiku called one fine line risky - `git stash
clear` after "Drop my old stashes, I don't need them." -, which then waits on its card or is refused;
Sonnet called none.

### The judge is not a wall

- It is a model's decision: it can call a risky command fine, and then that command runs - as it did
  at Full auto before the judge. Text written to steer it, in a command or a program an agent wrote, is
  marked as data, but can still sway a model.
- Hidden work may not be seen: a tool an agent changed but did not write, a program past its first 4 KB,
  a program that imports another file. A file an agent made by copying (`cp x.txt x.py`) is not known as
  the agent's, and is not shown.
- Test runners and build tools load the project's test and settings code by design - a `conftest.py`,
  test files, an eslint or mypy plugin a setting names, `build.rs`, a cargo runner - and an ordinary line
  (`pytest -q`, `cargo build`) runs what an agent wrote there with no judge.
- For a CLI run **Native**, KOLONİ - and so the judge - sees only the command the CLI reports.
- KOLONİ looks at the disk on the way to what a delete names (a link or a junction there is the
  list's card), not inside a folder it deletes: a link you made deep in one is not looked at (no
  shell's delete on this machine follows one).
- It can be led to call a plain delete fine that it should not: a file of yours written over first and
  then deleted as the agent's own, work moved into the scratch and then deleted, a path that only looks
  like a build folder (`build/../src`).
- Each command it looks at waits for a model request, a few seconds; with only a CLI to ask, from that
  CLI's quota.
- **Don't ask about this line again here** cannot be listed or undone in the app yet: what it keeps goes
  with the project. A changed file makes its line another one.

See [Known limits](../reference/known-limits.md#commands) for the rest.

## Check what I said first

Since 0.1.9 this is a question of [Full auto's judge](#full-autos-judge), under its switch: in Settings ›
This project › When you're asked, below **Full auto's judge**, the box **It also lets a delete or a push
run when a line you saved names it**. Its own row and its switch in the level menu are gone; there the
judge's line says, where the box is on, "…; a harmful-looking one runs without a card only where a line of
yours names it". It works only:

- once your Judge model's measurement has passed - a set of cases on which a good check never lets a
  command run wrongly, in every run. None has yet: Claude Code's **haiku**, measured on 25 Nov 2026,
  passed one run of 70 cases, but in three repeats of all 171 one run let 2 commands run wrongly (a
  condition, "Pending review, you may push to main.", and a delete in another folder than the line
  names). Claude Code's **Sonnet**, measured on 27 Nov 2026 with all 171 cases three times, let a
  delete in another folder than the line names run in every run ("You may delete dist/." for `rm -rf
  dist` in `packages/api`). So the box says **(after its measurement)** and cannot be ticked (the level menu's line says
  so too), and such a command waits for you on its card, as before - a push, a pull request or a merge
  you asked for with [your words quoted](#a-push-a-pull-request-or-a-merge-you-asked-for). A model that passes counts only as
  it was measured: on its own service (not a model server of yours, nor with your own Claude Code setup
  or a variable such as `ANTHROPIC_BASE_URL` pointing it elsewhere), run as a session or natively, and
  as the Judge model you chose - or, none chosen, the Fast tier's first; never one asked because your
  choice could not be. Settings › The app › Agents would say so under the Judge model. Another model is measured
  with `scripts/measure_judge.py` (see its first lines; one request a case);
- or in a project where you had turned Check what I said first on before 0.1.9: its box comes ticked and
  works as it did, and you may untick it and tick it again.

With the judge off, or the box unticked, it is never asked. The judge's two questions come one after
the other: a command the list stops softly (a delete, a push, a send) is first asked whether your words
cover it - its run runs, its refusal refuses, and its ask (a condition of yours, "ask me first") keeps
the card. Where it gave no answer, or is not asked, a delete, git work thrown away or a stop by name in
the project, written as a plain line, goes on to the judge's own question, whether it looks risky
([which](#what-the-judge-decides-in-place-of-the-list));
a push or a send keeps its card - [quoted](#a-push-a-pull-request-or-a-merge-you-asked-for) where you
asked for it. A force push or a branch deleted on the remote is never asked: a card at every level,
whatever you said.

At Full auto, in a chat you started, a command that sends something off this machine would wait for you
on a card, and one that deletes in the project goes to Full auto's judge (a card where the judge does not
run). Where the box works, your Judge model (as for [Full auto's
judge](#full-autos-judge): the Fast tier's first unless you choose one) first reads
your preferences, this project's rules as saved on the [Memory](../memory.md) page and your own
messages in the chat - never anything an agent wrote - and then:

- A whole line of yours that names the command and what it touches ("You may delete build/ and
  dist/."), and forbids nothing and sets no condition: the command runs without a card. Its row says
  "Ran without asking · your rule: …" with where the line is (Your preferences, This project's rules
  or your message).
- A whole sentence of yours that forbids it ("Never push to main."): it is not run and opens no card.
  The agent is told that sentence (for a sentence in a message of yours, only that one of yours
  forbids it - the sentence stays with you), and not to run it or anything that does the same again,
  and goes on with the rest of its task. Its row says "Not run · your rule: …".
- A sentence that sets a condition or asks to be asked ("unless", "ask me before", "else",
  "while", "whenever", "as long as", "so long as", "provided", "providing", "in case", "assuming"; in
  Turkish "eğer", "ise" / "isen", "-madan", any "-se" / "-sa" - "Kontroller yeşilse …", "Hata yoksa …",
  "Testler OK'se …" -, "-ınca", "-dığında" / "-dığımda" / "-diklerinde", "-ken", "-dikçe", "durumunda",
  "-dığı zaman", "sonra", "-ene kadar", "dek", "madem", "yeter ki" and "sürece"; an apostrophe written as
  ’, ‘, ´ or ʼ is read as one, so "OK’se" counts too), or nothing of yours that covers it: the card, as
  before. Its card then says "Nothing you said covers this."
- A line limited in time or in how many times it may be used ("once", "this time", "today", "on
  weekdays", "until Friday", "bir kereliğine"): the card too - KOLONİ cannot tell whether it was used up
  or its time has passed. The model is told to ask here; KOLONİ's own reading of your line does not
  catch every such word, so the measurement decides how well this holds.
- Two lines of yours that disagree about a delete: a line that names what the delete takes and forbids
  it or sets a condition - "Never delete ./x." beside "You may delete ./x.", or an item under "Never delete
  these:" - keeps its card, whichever line the model quoted, as KOLONİ reads such a line. A heading covers
  the lines right under it, up to a blank line, and a list or code under it until a line of prose; a
  heading right under another is read with it ("Never delete:" over "Outputs:" forbids what Outputs
  lists), unless a blank line came after the other's own lines. So "Never delete these:" over
  `./archive` says nothing of a "You may delete ./build." in a section of its own after a blank line.
  Some wordings
  ("Keep build.", "Leave build alone.", "…but check with me first.") are not caught, and the measurement
  decides the rest. Two lines about a push, a branch or a remote are left to the model.
- A command run in a folder of the project other than its root (`rm -rf dist` in `packages/api`):
  it runs without a card only on a line that names that folder from the root ("You may delete
  packages/api/dist."). A path in your line is read from the root - "You may delete dist/." is the root's
  `dist` -, so a line that does not name the folder keeps the card, whatever the model said; and so does
  one whose folder KOLONİ does not know.

A command that ran or was not run this way also waits on Ready for you, in its **Decided for you**
column, until you press **OK**. After 3 such refusals in a row, or 10 in one turn, KOLONİ says so in the chat and the rest of
that turn asks you on a card. Secret files, `.koloni`, files that steer later turns, paths outside the
folder, a delete or a send of the whole folder, and a CLI's command whose folder KOLONİ does not know
are always asked; anything that goes wrong (no model to ask, over the budget, no answer in 20 seconds -
90 for a model on a CLI -, an unreadable one) opens the card as before. Each such command is one request
of your Judge model.

While you're away it holds in a
To-do task's chat at Full auto too, reading the chat you went away from - never the task's words -
for a one-line delete in the task's copy only: a command of more than one line or continued, a send,
a git remote's branch, Docker's prune or volumes, a file that steers agents and a command that runs
another through a shell or a wrapper keep their card. The
same holds in the chat you went away from, while you're away. A plain chat has no judge's switch.

### A push, a pull request or a merge you asked for

A push, opening a pull request and merging one are yours to say. Once a Judge model has passed the
measurement, Check what I said first can let one you asked for run with no card, as it does a delete.
Until then the card stays, but it quotes you and asks for one click. When a sentence of the message
that started the turn asks for it, its card says

> **You said “Push it.” — push now?**

with **Push, as you said** (**Open the PR, as you said**, **Merge, as you said**) and **Reject**. It is a
card all the same: nothing runs until you press it. It shows at every level, in a turn you started from
the app's own page; a To-do task's turn, a job while you're away and a side of a comparison keep the
plain card.

What asks for it - in English an order or a leave ("Push it.", "Commit and push.", "You may push now.",
"Open a PR.", "Squash and merge."), in Turkish a request ("push et", "pushla", "push edebilirsin", "PR
aç", "PR'ı merge et", "PR'ı birleştir"). Only:

- the message you sent from the app's own page that started this turn - never an earlier turn's ("Push
  it." yesterday does not cover today's push after "Fix the typo."), an agent's words, a tool's result, a
  file, your preferences or the project's rules; nor code - a fence (in a list's item too) closes only
  on a line of its own marks, at least as many, so what an agent wrote inside the quote **Ask about
  this** makes stays code -, a quoted line (`>`) or a sentence with a backtick in it. A message over
  4,000 characters is not read for it;
- the last sentence of it that mentions it decides, and the whole message is read with it: anything in
  it that says no, asks, waits, puts it off or calls it off ("Don't push.", "push etme", "Push it. Don't
  merge.", "Push it. Actually no.", "Never mind.", "Scratch that.", "Hold off.", "Later.", "Revert
  that.", "Or should we wait?", "Hayır, bekle.", "Yok, vazgeçtim.", "Boşver.", "İptal.", "Önce bana
  göster."), that says what you do or will do ("I'll push it myself.", "I'll do it myself.", "push
  ettim", "push edeceğim", "tomorrow" - a message with "I" or "we" in it at all), or sets a condition
  ("after the review", "once CI passes", "testler geçince") leaves no quote - the plain card. Fewer
  quotes, never a wrong one;
- the sentence names no other branch or pull request than the line does: "Merge PR 5." (or "PR-5",
  "PR #5", "#5", "5 numaralı PR") is no quote
  for `gh pr merge 7`, nor "Push feature-a." for `git push origin feature-b`, nor "Push it to main." for a
  push of another branch, nor "Open a PR into main." for `gh pr create -B develop`. A word counts as a
  branch where your repository knows it - its branches, its remotes' and its tags - and `main` and
  `master` always; a bare `git push` pushes a branch KOLONİ does not know, so a sentence that names one
  gets the plain card there;
- a line of your preferences or the project's rules that names it and forbids it or sets a condition
  ("Never push to main.") leaves no quote for it at all.

The quote is shown as you typed it, in its own reading order: marks that turn text around (right-to-left
overrides and the like) are taken out of it.

Which commands - one program on one line, run at the project's root, written with letters, digits,
spaces and `. : / = + - _` alone, a value in double quotes (`-t "Fix the typo"`):

- `git push`, alone or to `origin` with branches of your repository's own (or `HEAD`), and `-u`,
  `--set-upstream`, `-q`, `-v`, `--progress`. A push to `main` or `master` by name is quoted only on a
  sentence that names it ("Push to main.", "main'e push et"); a bare `git push` is quoted on "Push it."
  whatever branch it pushes;
- `gh pr create` with a title, a body, a base, a head (a branch of this repository: `owner:branch` is
  not), one label, assignee, reviewer, milestone or project, `--draft` or `--fill`;
- `gh pr merge` with a number or a branch, `--merge`, `--squash`, `--rebase`, `--auto`, a subject or a
  body.

An option's value never starts with `-`. KOLONİ reads your repository's branches and tags for it (read
only); where it cannot - no git, or the project is not the repository's top folder - nothing is quoted.
Anything else gets the plain card, unquoted: a force push, a branch deleted (`git push origin :x`,
`--delete`, `gh pr merge --delete-branch`), a tag or any other ref than a branch (`refs/tags/…`,
`refs/for/…`, the short names git reads so - `tags/v1.0.0`, `heads/main`, `remotes/origin/main` -, a tag
by its bare name: `git push origin v1.0.0`), a name that is no branch of your repository's own (only
another remote's, or none), another remote or repository (`upstream`, an address, `-R`),
a file read in (`--body-file`), `--admin`, a push in a subfolder, any other option, more than one
command (`&&`, `;`, `|`), a redirection, and any other character - `$`, a backtick, a bracket, single
quotes, a comma (`-r a,b`), `@` (`@me`), `!`, `?`, `#`, `*`, `%`, a line break. So does a pull request
whose body is written with a heredoc or on more lines (`--body "$(cat <<'EOF' …)"`, as Claude Code
often writes one). "Open a PR." covers `gh pr create` alone, not the `git push` before it. A local
`git merge` sends nothing: it is not quoted.

## Plan first

With **Plan first** on, each new message first gets a plan to approve. While it plans, an agent
can only read, search and ask you. It cannot write or run anything, at any level.

## A job's own branch while you're away

In a git repository a job of [☾ Away](../automation/overnight.md#in-a-git-repository-each-job-on-its-own-branch)
works on its own `koloni/<task>` branch in a worktree. Its git there - `status`, `diff`, `log`, `add`,
`commit` on that branch - runs at every level without a card. Its `git push` never runs: "KOLONİ pushes
this branch when the user says yes: go on" - the push waits for your **Run** in the morning. Anything
else of git (switching branches, reset, stash, fetch, config) is parked for you.

KOLONİ's own check of [code style and types](checked.md#documents-diagrams-data-and-slides) runs
the project's ruff, eslint, tsc or mypy as it runs the test command: at Ask and Auto-edit it asks
on a card - a yes is that line in that folder for the turn, and **Always** keeps that line, never
the bare program; while you are away it is not run, and says so. A program an agent wrote - this turn, or an earlier turn in an
install folder, while the file still holds it - is never run.

## Choosing a level

- Start with **Ask before changes** in a project you care about. You see every change before it
  is made.
- **Auto-edit files** suits work you review afterwards. Changes can be reverted, and commands
  still ask.
- **Full auto** is for work you are ready to let run. What reaches out of the project, sends, or touches
  secrets and risky files still asks; [Full auto's judge](#full-autos-judge) decides the rest - a delete
  in the project too - and everything it calls fine runs. A script that opens `.env` without naming it can still read it, unless
  KOLONİ's own commands run in Docker (Settings › This project › When you're asked › More) or Copilot's
  sandbox is on; a CLI run **Native** runs its commands on this machine, outside Docker.
