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

- **Check it** (the default) and **Tests only** both run the tests.
- **Nothing** runs nothing and sends nothing back. The Checked section still says that nothing
  was checked, and names the last test run an agent made in the turn.

A project that had turned off the old **Finish only when the tests pass** switch is on
**Nothing**, and Settings says so under the setting.

## Which tests

1. The project's own **Test before adding** command, if it has one.
2. Otherwise each part's test command from the project map (yours, or the map's guess), run in
   that part's folder.
3. Otherwise a command KOLONİ guesses from the folder's files: `python -m pytest -q` for a
   Python project, `npm test` for one whose `package.json` has a test script.

A guessed command is tagged **guessed**. If nothing can be guessed, the section says
"No test command: nothing was run".

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
- While you're away (a job of **Away**, or a To-do task's turn while Away runs) a guessed
  command is not run: the section says "Tests not run: a guessed command, you were away", and the
  job finishes. Your own command still runs. A To-do task you run from the screen asks as any
  turn does.
- In a trigger's turn it runs only where the trigger allows that very command. Otherwise the
  section says "Tests not run" with the trigger's words.

The run shows in the turn like any command, as KOLONİ's own. The Orchestrator does not see it
in its history: it is told the result when the tests fail.

## When the tests fail

The Orchestrator is told that the tests failed, with the end of their output, and goes on to fix
what fails, by itself or with an agent that writes code. It is told never to delete or skip a
test to make it pass. Then KOLONİ runs the tests again.

It is sent back at most **two** times a turn. After that the turn ends, and the section says
"Still failing after 2 fix rounds: you decide (Fix it)". **Fix it**, on the newest turn, sends a
new message that asks for the fix. Nothing starts until you click it.

Rounds never stack: where a recipe of the turn has already run its own test-and-fix rounds to
the end (Bugfix's **Test it** back to **Fix it**), KOLONİ does not send the Orchestrator round
again on top of them. A recipe's review loop that ran out leaves KOLONİ's own rounds. The section says "Still failing
after the recipe's fix rounds: you decide (Fix it)".

The check before a sub-agent's work is taken in (**Test before adding**) is a separate check with
its own two rounds. A turn can have both.

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
    that names its own tests), there is no related step. A guessed command that would need its
    card has no related step either: one card per command.

    A test file named on the command line would get past what you left out of your tests, so
    where you left tests out there is no related step, only the whole suite: for pytest, an
    `--ignore`, `--ignore-glob` or `--deselect` (in the command or in `addopts`), a
    `norecursedirs`, or a `conftest.py` with `collect_ignore` or `pytest_ignore_collect`; for
    jest, a `testPathIgnorePatterns`. pytest's `testpaths` are kept: only test files under them
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
level. A button to stop the related tests while the answer waits for them comes with the
canvas's Checks node; until then **Stop** ends the turn.

- A newer turn that changes the same project and runs the same suite stops one still running in
  the background, as a new push stops a pull request's old CI run: "Tests not finished: the
  project changed, and a newer run took their place". A result that comes after the project
  changed beneath it adds "- the project changed while they ran", and a pass then is not shown
  as passed: a change on record (written, taken in or undone) or a command of any turn that may
  have changed files.
- What the suite writes of the files that steer later work (`.vscode/`, `.claude/`, an
  instruction file, `.koloni/`) is taken back when it ends, as for any command; after its turn,
  with no card. What another turn wrote there meanwhile stays.
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
| – Sent back to fix: 1 of 2 rounds | How many times the Orchestrator was sent back this turn. |
| – Not in this run: `name`'s work waits in Ready for you | That work was not tested. It is still in its working copy. |
| – Not checked: After a change is set to Nothing | The project's setting. |
