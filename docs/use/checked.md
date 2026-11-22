# Checked

A turn that changed code does not end on the model's word. Before the Orchestrator's answer
ends the turn, KOLONİ runs the project's tests once on the work as it now stands. Under the
answer a **Checked** section says what ran, how it went, and what was not checked. KOLONİ
writes it from its own records, not from the model's words, and no model is asked for it.

It works the same for every model and CLI.

## When it runs

- After a turn in a project folder that changed a file. A turn that changed nothing, a plain
  chat, a plan, and a side of a comparison get no Checked section.
- Where the work now is: in the project, or in the Orchestrator's own working copy (a team's
  branch, or a job while you're away). Work that waits in **Ready for you** is not part of it.
- Once, after the turn's work is in: the agents run only the tests near their change while
  they work, and KOLONİ runs the whole test command at the end, like a pull request's CI - in a
  turn you watch, the tests related to the change first and the whole suite after, in the
  background (see [How long it waits](#how-long-it-waits)).
- KOLONİ runs one such test run at a time across the app, unless Settings say more (see
  [How many run at once](#how-many-run-at-once)). A second turn that ends meanwhile waits for
  the first. A run whose card waits for your yes holds up no other: it takes its turn once you
  answer.

**Settings › This project › Checks and git › After a change** turns it on or off for the
project:

- **Test and review** (the default) runs the tests, and has a big or security-touching change
  looked over by a read-only Reviewer (see [The review](#the-review)).
- **Tests only** runs the tests and nothing more.
- **Nothing** runs nothing and sends nothing back. The Checked section still says that nothing
  was checked, and names the last test run an agent made in the turn.

The line under the choice says what it does in this project now, from its real state - for
example "Runs python -m pytest -q in ./ (found by KOLONİ), related tests first, the whole suite in
the background; a change over 80 lines or 3 files, or one touching sign-in, secrets or commands,
is read by a Reviewer (one more model request). Failing work goes back up to 2 times." It names
your check command; else each test command you set for a part on the project map ("npm test in
web/"), then what KOLONİ saved for any other folder - and changes as you save one there. Before a
test command is known it says KOLONİ finds one and asks you once. Its ⓘ leads here.

### For one chat

**Test and review changes**, in the permission level's menu beside **Plan first**, turns it on
or off for this chat only. Its line says what this chat's changes get: "As the project: runs
python -m pytest -q after each change, then a Reviewer reads big or security changes. Failing work
goes back to be fixed, up to 2 times.", "Off for this chat: nothing is tested or reviewed; each
answer says “Not checked”.", or "On for this chat · the project's is Nothing: runs …" (on in a
project at Nothing is Test and review for this chat). Its ⓘ leads here. Off, the level's button
says "· no checks", no Checks node is drawn for its turns, the Checked section says "Not checked:
off for this chat" and the Orchestrator's box "not checked · off for this chat". Other chats go
on with the project's setting.

It is free at every level. At **Full auto** with it off, the menu says so under it: "Full auto
with no checks: nothing checks this chat's changes". A turn that runs a team's recipe follows
the recipe, not this switch: today the project's setting.

A project that had turned off the old **Finish only when the tests pass** switch is on
**Nothing**, and Settings says so under the setting.

## Which tests

1. The project's own **Test before adding** command, if it has one - and then only it: nothing is
   guessed, found or saved beside it.
2. Otherwise each part's test command from the project map (yours, or the map's guess), run in
   that part's folder. A part you set to no test is never guessed.
3. Otherwise the test command KOLONİ saved before (below).
4. Otherwise a command KOLONİ guesses from each part's files, in any language: `python -m pytest
   -q` (a `pyproject.toml`, `pytest.ini` or `tests/`), `npm test` (a test script in
   `package.json`), `go test ./...` (`go.mod`), `cargo test` (`Cargo.toml`), `mvn test`
   (`pom.xml`), `./gradlew test` or `gradle test` (`build.gradle`), `dotnet test` (a `.sln` or
   `.csproj`), `bundle exec rspec` (a `Gemfile` and `spec/`), `composer test` or
   `vendor/bin/phpunit` (`composer.json`), `mix test` (`mix.exs`), `swift test`
   (`Package.swift`), `ctest --test-dir build` (`CMakeLists.txt`), `make test` (a `test:` target
   in the `Makefile`).
5. Otherwise a test command an agent ran in this turn that really ran tests, in a turn you are
   there for (not while you're away, not a trigger's).
6. Otherwise KOLONİ asks the project's **Fast** tier's model once, in a turn you are there for,
   where its tests are. KOLONİ shows it the project's parts and languages, its test files and the
   start of its README, CONTRIBUTING and Makefile (never a secret file, nor one reached through a
   link), with no tool. It answers with command lines, which are read as data. The request shows
   in Usage. It is asked again only when the project's parts change; until then the commands it
   named are tried again. With no Fast-tier model the section says so.

A line an agent ran (5) or the model named (6) is tried only if it is one of the commands in 4,
or `pytest`, `npx vitest run`, `npx jest`, `yarn test`, `pnpm test`, `bun test`, `tox`, `nox` or
`ctest` - with at most `-q` or `-v` after it, in a folder of the project. Any other line (more options, a wrapper, a chain) is never run: the look's row says
how many it named that were not tried.

A guessed command is tagged **guessed**. If nothing can be found, the section says "No test
command: nothing was run"; after the look found no tests at all, "No tests in this project".

### From your CI

Where the project has GitHub Actions workflows (`.github/workflows/*.yml`), KOLONİ reads their
lint, typecheck and test lines - `ruff`, `eslint`, `mypy`, `ty check`, `tsc`, `pytest`, `vitest` and
the like, each in its step's `working-directory` (or the job's or workflow's `defaults.run`). Each
line must be one plain command of at most 500 characters: a line that chains, pipes, redirects
or substitutes (`pytest; curl …`, `npm test && …`, `cd web && npm test`, `pytest $(…)`) is not
taken. It never takes an e2e step, nor a step with a `${{ … }}` expression, a secret or an install
in it, one whose `shell:` is another language, or one whose folder is outside the project. The
workflow files are read with limits - at most 50 files, 256 KB each and 1 MB in all, no links, no
YAML aliases; a file past them is not read. What was left out is said beside the lines it offers
or runs ("e2e not run: …", "CI step Tests: not run: not a plain command", "CI file not read: …");
where no line is taken, nothing of the CI is said.

It asks once a project: the section lists them - "CI commands found: ruff check app, python -m
pytest -q - not run until you approve them once (Run these)" - and **Run these** approves exactly
the lines that row shows. If the workflow files changed since, or another turn offered other lines,
nothing is approved and they are offered again after the next change. From the next change on they are the turn's test run, one line each, said "(from
CI)". Until you approve them they are not run - at **Full auto** and while you're away too. A
change to a workflow file asks again; a workflow changed in the turn itself is not used ("CI
commands not used: a workflow changed in this turn"). Your own **Test before adding** command wins
over them. Each still goes through KOLONİ's reading of commands: a harmful one is asked as your
level says. An approved line runs as your own command does: `make test`, `npm test` or `tox` run
the project's own Makefile, package scripts or tox file, whatever they hold. A trigger's turn runs
one only with the trigger's own leave for that line.

### Saved by KOLONİ

The first time a guessed command really runs tests (its runner counted some that passed or
failed), KOLONİ saves it as this project's test command for that folder, with no question. The
section says "Saved as this project's test command - change it in Settings". A guess that ran no
test, or no test tool, is never saved, and a command of yours is never replaced.

Settings › This project › Checks and git shows each saved command under **Found by KOLONİ** as
soon as it is saved, where it came from and when. **Forget it** clears them; they are found again
at the next change. A saved command runs as the project's for this check only, and below **Full
auto** on a card until you say **Always** on it (see [Asking](#asking)). It is not your **Test before adding**:
it does not check a sub-agent's work before it is taken in, and agents and triggers do not get to
run it unasked. To make it yours, set it there.

Where KOLONİ reads a count from the runner's summary (pytest, jest, vitest, go, cargo, dotnet,
Maven, Gradle, RSpec, PHPUnit), the line gives it. Any other runner is judged by its exit code
alone, and the line says so: "Tests passed (by exit code, no count)".

A turn whose changes are all documents, slides, diagrams or data runs no tests and says so.
A change to a configuration file (`requirements.txt`, `package.json`, a CI workflow, a
`Makefile`) counts as code: the tests run.

## Asking

KOLONİ's test run is asked about as the Orchestrator's own command would be:

- Your own command (the check command, or a part's test command you set) runs without a card.
- A guessed command at **Ask before changes** or **Auto-edit files** waits on one command card.
  Your yes holds for the rest of the turn, for that command in that folder only: the same command
  in another part of the project is asked again. At **Full auto**, or under an **Always run**
  rule, it runs by itself.
- A command KOLONİ saved (see [Saved by KOLONİ](#saved-by-koloni)) is not a
  leave of yours: at **Ask before changes** and **Auto-edit files** it waits on a card like a
  guess. **Always** on that card (or on the guess's card before it was saved) keeps it as yours
  for that very line in this project: from then on it runs without a card, in every chat, and
  while you're away. An **Always run** rule you gave another command's card (`python -m pytest`)
  lets it run without a card in that chat only. **Forget it** forgets that too. At **Full auto**
  it runs by itself.
- While you're away (a job of **Away**, or a To-do task's turn while Away runs) a guessed
  command is not run: the section says "Tests not run: a guessed command, you were away", and the
  job finishes. Nor is a saved command you have not said **Always** to: "Tests not run: a saved
  command no Always rule covers, you were away". Your own command still runs. A To-do task you
  run from the screen asks as any turn does.
- In a trigger's turn it runs only where the trigger allows that very command. Otherwise the
  section says "Tests not run" with the trigger's words.

The run shows in the turn like any command, as KOLONİ's own. The Orchestrator does not see it
in its history: it is told the result when the tests fail.

## When the tests fail

The Orchestrator is told that the tests failed, with the end of their output, and goes on to fix
what fails, by itself or with an agent that writes code. It is told never to delete or skip a
test to make it pass. Then KOLONİ runs the tests again.

It is sent back at most **Fix rounds** times a turn (**Settings › This project › Checks and git ›
Fix rounds**, 1 to 5, 2 unless you change it) - one count with the Reviewer's findings. After that
the turn ends, and the section says "Still failing after 2 fix rounds: you decide (Fix it)". **Fix it**, on the newest turn, sends a
new message that asks for the fix. Nothing starts until you click it.

Rounds never stack: where a recipe of the turn has already run its own test-and-fix rounds to
the end (Bugfix's **Test it** back to **Fix it**), KOLONİ does not send the Orchestrator round
again on top of them. A recipe's review loop that ran out leaves KOLONİ's own rounds. The section says "Still failing
after the recipe's fix rounds: you decide (Fix it)".

The check before a sub-agent's work is taken in (**Test before adding**) is a separate check with
its own two rounds. A turn can have both.

## A test for the change

A turn that changed source code (a script of a language: `.py`, `.ts`, `.go`, ...) and no test
is asked, once, for a test: "Not the end yet: `a.py` changed and no test did." The Orchestrator
has one written - by an agent that writes code, or itself; for a bug fix, first a test that fails
without the fix - and KOLONİ runs the tests again on it. Where no test fits (documents, settings, a
one-off script), it says so in one line instead, and that line is quoted under the answer. The ask
comes last, after the tests and the review, spends no fix round, and is made under **Test and
review** and **Tests only**, never under **Nothing** or where checks are off for the chat. A
turn of a recipe whose steps wrote a test (Bugfix's **Reproduce it**) is not asked. It works the
same while you're away and at Full auto: the Orchestrator writes the test or gives its reason.

A test is known by its name or folder: `test_a.py`, `a_test.go`, `a.test.ts`, `a.spec.js`, a file
under `tests/` or `__tests__/`. A test file the turn deleted is said under the answer as "Test
removed", failed, and under **Test and review** the Reviewer looks at it whatever the change's
size: one removed to make the tests pass is a blocking finding.

While they work, agents that write and run code are told to run only the tests near their change;
KOLONİ runs the project's whole test command once, at the end. The Orchestrator is told so too.

## The review

Under **Test and review**, once the tests pass, a change of more than **80 lines** or **3 files** of code,
config or screens - or one that touches security - is looked over by the **Reviewer**, an agent
KOLONİ opens itself. A security touch is a path with a word like auth, login, session, token,
secret, password, permission, crypto, cookie or cors as a whole word of a name in it (`auth.py`,
`oauth2/`, `tokens.ts` - not `author.py` or `tokenizer.py`), a `.env`, `.pem` or `.key` file, a
Dockerfile or a CI workflow, or an added line that runs a command (`subprocess`, `shell=True`,
`os.system`, `child_process`), runs or loads code (`eval(`, `exec(`, `pickle.load`, `yaml.load(`),
reaches the network (`fetch(`, `requests.`, `httpx.`, `socket.`), puts HTML in a page
(`dangerouslySetInnerHTML`, `.innerHTML =`), or loosens a check or a file's rights
(`verify=False`, `chmod`, `setuid`). Then the **Security reviewer** looks too, told to try to
refute that the change is safe. Both may look at once. The whole change is read for these,
also what does not fit in the diff the Reviewer is shown.

- They read: the user's request, the turn's change as a diff (cut at 12 000 characters, the files
  left out named; a secret file is named, never shown), KOLONİ's own test lines, and any file of
  the project they open. They get read tools only and no MCP server, whatever their role is
  given: they change nothing. They may run two kinds of command, never asked about: one that only
  reads (`git diff`, `cat a.py`, `ls src`), and the project's approved test command exactly as it
  is set, in its folder - your check command or a part's test command, a saved one an **Always**
  rule covers, or a CI line you approved with **Run these**. Any other (`rm`, `pip install`, the
  test command with an option added) is refused, and they are told which test commands they may
  run; no card is ever opened for a Reviewer's command. One whose model is a CLI that works with
  tools of its own is not opened ("Review not run: …"), as KOLONİ could not hold it to reading.
- For a change a user sees (a screen's file, a command's option) in a project with `docs/`, a
  README or a CHANGELOG, they also check the docs: "Docs not updated for: …" is a suggestion,
  blocking only where the project's own rules say docs must change with it.
- Each ends with **MERGE** (it may stand) or **HOLD** (it must change first) and its findings,
  each blocking or a suggestion. Blocking findings go back to the Orchestrator as a fix round,
  as failing tests do; KOLONİ runs the tests again, and the Reviewer looks again at the new
  change - until MERGE with the tests passing, or the **Fix rounds** are spent. Then the section
  lists the findings and says "Still on hold after 2 fix rounds: you decide (Fix it)"; **Fix it**
  sends a new message asking for them to be fixed, and the Orchestrator is handed the findings
  as data, never as your words.
- Each look is an agent's work on its model: on the canvas, in its window and in Usage.
- In a chat with teams the look is KOLONİ's, not a team's: no team's lead or door holds it, and
  it gets no team's tools (their shared folder, a request for another team's work).
- The Orchestrator may answer the findings without changing anything: the turn ends there, and
  the section says "Still on hold after round 1: not settled by the last look - you decide (Fix
  it)" ("nothing changed" where KOLONİ checked again and found no change).
- A HOLD is a hold: one that marks no finding blocking, or writes its findings as prose, goes
  back with its own words as the finding. The verdict is a line `Verdict: MERGE` or `Verdict:
  HOLD` of its own (not one quoted or in a code block); any HOLD wins.
- **Stop this check** ends a look that runs now too: "Review stopped by you - not checked".
- No look: a small change, **Tests only**, tests that still fail (they are fixed first), a turn
  over its token limit, or a recipe whose own Review step looked already - rounds never stack.
  A recipe without a Review step gets this review at its end.

## How long it waits

A long test suite does not hold up the answer. In a turn you watch, whose work is in the project
itself, the end works like a pull request's CI:

1. **Related tests first.** KOLONİ runs only the tests related to the files the turn changed,
   and the answer waits for those. A failure goes back to the Orchestrator as above. They are
   read from the test command itself, where its runner can name them:

    | Runner | Related tests |
    |---|---|
    | pytest | the changed test files, and the test files named for a changed module (`test_greet.py` or `greet_test.py` for `greet.py`) |
    | vitest | `vitest related --run` with the changed files |
    | jest | `--findRelatedTests` with the changed files |
    | go | `go test` of the changed packages, where the command is `go test ./...` |
    | cargo | `cargo test -p` each changed crate of a workspace |
    | dotnet | `dotnet test` of the one test project of the change |

    The runner must be the command's first word or follow its launcher (`python -m`,
    `uv run`, `npx`, ...): `tox -e pytest` or `make pytest` gets no related step. Where none can
    be named (another runner, a change to a configuration file or to `conftest.py`, a command
    that names its own tests), there is no related step. A guessed command, or a saved one
    you have not said **Always** to, that would need its card has no related step either: one card
    per command.

    A test file named on the command line would get past what you left out of your tests, so
    where you left tests out there is no related step, only the whole suite: for pytest, an
    `--ignore`, `--ignore-glob` or `--deselect` (in the command or in `addopts`), a
    `norecursedirs`, or a `conftest.py` with `collect_ignore` or `pytest_ignore_collect`, and a
    command that picks or overrides pytest's config (`-c`, `--config-file`, `-o`, `--rootdir`,
    `-p`) or a `PYTEST_ADDOPTS` in the environment; for jest, a `testPathIgnorePatterns`. Test
    files under pytest's default `norecursedirs` (`build`, `dist`, `venv`, `node_modules`, a dot
    folder) are never named. pytest's `testpaths` are kept: only test files under them
    are named. vitest's `related` keeps the config's `exclude` itself. An `npm test` with a
    `pretest` script gets no vitest related step (it would skip the `pretest`).

2. **Then the whole suite.** After related tests it goes on in the background at once. Without
   them the answer waits up to **1 minute** for it: one that ends by then is said, and a
   failure goes back as above. One that runs on goes on after the answer. The section says
   "Full tests running: `command` (2:14)", and the line over the message box says
   "Full tests running… (2:14)". When it ends, its line is written again with the result.
   A failure then offers **Fix it**: nothing starts by itself.

    If the related tests fail on the last round, the whole suite is not run: "Full tests not
    run: the related tests fail".

The whole suite's own limit is the commands' 10 minutes. Past it the section says "Tests timed
out after 10 min".

**Stop this check**, under a suite running after the answer, stops it: what finished stays, and
the line says "Full tests stopped by you at 1:02 - not checked" (counted from when it started),
or "before they started" if it was still waiting for the machine. It works at every permission
level. The canvas's Checks node has it too, in its **⋯** menu, also while the answer waits for
the related tests (see [On the canvas](#on-the-canvas)).

- A newer turn that changes the same project and runs the same suite stops one still running in
  the background, as a new push stops a pull request's old CI run: "Tests not finished: the
  project changed, and a newer run took their place". A result that comes after the project
  changed beneath it adds "- the project changed while they ran", and a pass then is not shown
  as passed: a change on record (written, taken in or undone) or a command of any turn that may
  have changed files.
- What the suite writes of the files that steer later work (`.vscode/`, `.claude/`, an
  instruction file, `.koloni/`) is taken back when it ends, as for any command; after its turn,
  with no card. What another turn wrote there meanwhile stays. Where its card asks you ("KOLONİ's
  test run wrote `AGENTS.md` without naming it — taken back. Keep it?"), the section says "Full
  tests waiting for your answer on a file the tests wrote: `command`" until you answer, with
  no clock.
- **Stop everything** and putting the chat away stop it too. If KOLONİ closes while it runs,
  the next start says "Tests not finished: KOLONİ restarted".
- A job while you're away, a To-do task's turn and a trigger's turn have nobody waiting for
  the answer, and their fix rounds need the result: they wait for the whole suite, up to the
  commands' 10 minutes, with no related step.
- A turn whose work is in its own working copy (a team's branch) cannot leave its tests running
  after it: the copy is taken in or set aside when the turn ends. There KOLONİ waits at most
  **2 minutes** for the tests, all of the turn's test commands together and another turn's run
  before them. A longer run is stopped, and the section says "Tests not waited for: still
  running at 2:00"; one that never got to start says "Tests not run" and why. Until the run
  takes less than that again (for example, when an agent's run of the same command does), later
  such turns say "Tests not run" and why, instead of waiting again.
- **Stop** during the turn ends the turn as Stopped. The section says "Tests not finished:
  stopped".

### How many run at once

KOLONİ's own test runs queue: **Settings › The app › KOLONİ's test runs at once** (1 unless you
change it, up to 4) go at the same time, and the rest wait. A whole suite waiting its turn says
"Full tests waiting for another test run to end". **Test processes per run** (2 unless you change
it, up to 16) is given to each of KOLONİ's runs where its runner reads it: pytest-xdist's
`-n auto`. The agents' own commands are not limited by either.

## On the canvas

A checked turn has a **Checks** node under its Orchestrator. While KOLONİ's test run works, it
shows the tool and how long it has run; once the turn is over, each line of the Checked section,
with the runner's counts ("pytest · 214 ✓ · 2 ✗"), the related step's ("related tests · 12
passed"), and a whole suite running after the answer with its clock from its own start ("full
tests · 2:14 …"), or "full tests · waiting for another test run to end", then its result or
"full tests · stopped by you at 1:02 - not checked". Each fix round is a line back to the
Orchestrator, "round 1 of 2: tests fail" - or, for the Reviewer's, "round 1 of 2: 1 blocking
finding". The Reviewer and Security reviewer KOLONİ opened are agent nodes after it. The
Orchestrator's own box gets one line: "● checking…"
while a run goes on, "✓ checked · 1 round", "✓ checked · related only" (the whole suite stopped or
not run), "✗ still failing" or "not checked". In a recipe's turn the node says "end of the recipe".

Its **⋯** menu has **Stop this check** while one of its runs goes on - the same as under the
answer, at every permission level: what ran stays, the rest says "not checked" -, **Off for this
chat** (the level menu's **Test and review changes**, for the chat open now) and **Open its log**,
the Orchestrator's window, whose record holds the runs.

## What each line means

| Line | Means |
|---|---|
| ✓ Tests passed: `command` - `summary` | The command ended with exit code 0 and its output counted no failure. |
| ✓ Tests passed (by exit code, no count): `command` | Exit code 0 from a runner whose output KOLONİ reads no count from (an `npm test` that prints none). |
| ✓ Tests passed: `command` - run by `who` after the last change | The Orchestrator ran the same command after the turn's last change, or a recipe's Tester did on the work that was then taken in, it passed, and no command that may change files (a formatter, a generator) ran after it. KOLONİ did not run it again. |
| – Tests gave no verdict: `command` masks its exit | The test line hides its exit code (piped into `tail`, or followed by `; true`) and its output counts no failure. This is not a pass. |
| ✗ Tests failed: `command` - `summary` | Any other exit code, or an exit code of 0 with a failure counted in its output. |
| – Tests ran none: `command` collected no test | The runner found no test: pytest's or unittest's exit code 5, "Ran 0 tests", jest's "No tests found", vitest's "No test files found". This is not a pass. |
| – Tests skipped only: `command` - `summary` | Every test it found was skipped. This is not a pass. |
| – Tests could not start: `why` | The program was not found, the command could not start, or KOLONİ's check itself broke. Nothing is sent back. |
| – Tests not run: `why` | It was declined on its card, a trigger does not allow it, the web is off and it reaches the internet, or the turn ended first. |
| – Tests timed out / not waited for | It did not end in time. This is neither a pass nor a failure. |
| ✓ Related tests passed: `command` `files` - `summary` | The tests related to the changed files passed. The whole suite runs after them. |
| … Full tests running: `command` (2:14) | The whole suite goes on after the answer. Its line is written again when it ends. |
| … Full tests waiting for another test run to end: `command` | It waits its turn: see How many run at once. |
| – Full tests not run: the related tests fail | The related tests still failed on the last round. |
| – Full tests stopped by you at `m:ss` - not checked | You stopped it. Nothing it had run is counted. |
| – Tests not finished: `why` | Stopped, a newer run took its place, or KOLONİ restarted while it ran. |
| – `…` - the project changed while they ran | The project changed under the run. Its result stands for no state of the work, and a pass is not shown as passed. |
| – Tests not run on the last change: `why` | A file changed after the last run, and the turn ended before KOLONİ could run the tests again. The lines above it are of the earlier run. |
| – No test command | There was nothing to run. |
| – Sent back to fix: 1 of 2 rounds | How many times the Orchestrator was sent back this turn, of the project's Fix rounds; "(tests fail; 1 blocking finding)" after it where a review sent one back. |
| ✓ Review: Reviewer (`provider · model`) - MERGE, no findings | The Reviewer looked over the whole change and let it stand ("after 1 round" where it held it first). |
| ✗ Review: Reviewer (`provider · model`) - HOLD, 2 findings, 1 blocking | It held the change; each finding follows as "Blocking: …" or "Suggestion: …". |
| – Review: … in the part it saw (3000 of 15000 characters; not shown: …) | The diff was cut: what it said is of that part only, never a pass. |
| – Review gave no findings section: not counted | Its report had no findings section: nothing was sent back. |
| – Review not run: `why` | It could not look: it failed, it was refused, or the turn's token limit was reached. |
| – No review: a small change (12 lines, 1 files) | Not big, and no security touch. |
| – No review: After a change is Tests only / the tests still fail / the recipe's own Review step looked it over | Why no Reviewer looked. |
| ✗ Still on hold after 2 fix rounds: you decide (Fix it) | The Fix rounds were spent with blocking findings left. |
| – New tests: `files` | The test files the turn added or changed. |
| – No new test: the Orchestrator said “`line`” | It was asked for a test and gave this reason instead (its first line). |
| ✗ Test removed: `path` | The turn deleted a test file that was there before it. |
| – Not in this run: `name`'s work waits in Ready for you | That work was not tested. It is still in its working copy. |
| – Not checked: After a change is set to Nothing | The project's setting. |
| – Not checked: off for this chat | This chat's **Test and review changes** is off. |
| – CI commands found: `lines` - not run until you approve them once (Run these) | The project's CI lint, typecheck and test lines, offered. **Run these** approves exactly these. |
| – CI step `name`: not run: `why` / e2e not run: `name` / CI file not read: `file` - `why` | What of the CI is left out beside the lines it offers or runs: an e2e step, a line not plain, an install, a secret, another shell, a folder outside, a file past the limits. |
| – CI commands not used: a workflow changed in this turn | A workflow file changed in the turn: its lines wait for the next one. |
