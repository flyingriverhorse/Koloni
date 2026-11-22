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
  they work, and KOLONİ runs the whole test command at the end, like a pull request's CI.
- KOLONİ runs one such test run at a time, across the app. A second turn that ends meanwhile
  waits for the first. A run whose card waits for your yes holds up no other: it takes its turn
  once you answer.

**Settings › This project › Checks and git › After a change** turns it on or off for the
project:

- **Check it** (the default) and **Tests only** both run the tests.
- **Nothing** runs nothing and sends nothing back. The Checked section still says that nothing
  was checked, and names the last test run an agent made in the turn.

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

### Saved by KOLONİ

The first time a guessed command really runs tests (its runner counted some that passed or
failed), KOLONİ saves it as this project's test command for that folder, with no question. The
section says "Saved as this project's test command - change it in Settings". A guess that ran no
test, or no test tool, is never saved, and a command of yours is never replaced.

Settings › This project › Checks and git shows each saved command under **Found by KOLONİ**, where
it came from and when. **Forget it** clears them; they are found again at the next change. A
saved command runs as the project's for this check only. It is not your **Test before adding**:
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

- In a turn you watch, KOLONİ waits at most **2 minutes** for the tests: all of the turn's test
  commands together, and another turn's run before them. A longer run is stopped, and the
  section says "Tests not waited for: still running at 2:00"; one that never got to start says
  "Tests not run" and why. Until the run
  takes less than that again (for example, when an agent's run of the same command does), later
  turns you watch say "Tests not run" and why, instead of waiting again.
- A job while you're away, a To-do task's turn and a trigger's turn wait up to the commands'
  limit of 10 minutes. Past it the section says "Tests timed out after 10 min".
- **Stop** during the run ends the turn as Stopped. The section says "Tests not finished:
  stopped".

## On the canvas

A checked turn has a **Checks** node under its Orchestrator. While KOLONİ's test run works, it
shows the tool and how long it has run; once the turn is over, each line of the Checked section,
with the runner's counts ("pytest · 214 ✓ · 2 ✗"). Each fix round is a line back to the
Orchestrator, "round 1 of 2: tests fail". The Orchestrator's own box gets one line: "✓ checked ·
1 round", "✗ still failing" or "not checked". The node's window button opens the Orchestrator's
window, whose record holds the runs. In a recipe's turn the node says "end of the recipe".

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
| – Tests not run on the last change: `why` | A file changed after the last run, and the turn ended before KOLONİ could run the tests again. The lines above it are of the earlier run. |
| – No test command | There was nothing to run. |
| – Sent back to fix: 1 of 2 rounds | How many times the Orchestrator was sent back this turn. |
| – Not in this run: `name`'s work waits in Ready for you | That work was not tested. It is still in its working copy. |
| – Not checked: After a change is set to Nothing | The project's setting. |
