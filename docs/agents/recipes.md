# Recipes and candidates

A recipe is the drawn steps of a piece of work: who does each step, what runs at once, where it loops
back and how it ends. "A chat's team runs by the recipe picked for it, else by its team's default."
Recipes are on the Agents page, tab **Recipes**.

[![Teams, recipes and discussions: a team's stages, a lane between teams, and a recipe's steps, loops, candidates and Evolve](../diagrams/teams.svg)](../diagrams/teams.svg)

*Teams, recipes and discussions in one picture.*

## Making a recipe

- **+ Draw a new recipe** starts an empty one.
- Pick a ready recipe and press **Copy it**. Ready recipes cannot be changed: "A ready recipe: copy it
  to change it."
- **Or write it**: describe the recipe in a sentence and press **Make it a recipe**. The note
  under it says which model it asks first ("Asks Balanced: Local · qwen3"). It asks, each once
  and in turn: the balanced tier's models, then the fast and the strongest tier's, then the
  Orchestrator's model in the chat you are in (the one its model picker chose), then the model
  your newest chat ran on - passing over one whose server is not running, and never a CLI that
  keeps its tools. If one does not answer, the next is asked. Where none answers, it names every
  model it tried, each with why, and how to fix it ("No model answered: Local · qwen3 (not
  running). Start Local on the Models page, give a model a tier there, or pick a model in the
  chat."). The model draws the recipe on the board; nothing is saved until you save it.

The ready recipes include Feature, Bugfix, Review only, Integration, Quality check, Model change,
Pipeline change, Infra change, Docs, Research, Spec, Analysis, Upkeep and Evolve.

Each recipe in the list, and in the chat's recipe picker, says how many agents a run of it opens,
counted from its drawing: "Feature · 6–16 agents" - the fewest where no review finds a problem (a
step that runs only on a problem left out), the most where every loop goes back all its rounds. A
team's experts or stages count as one agent there, and the helpers a step's agents open are not
counted. The number is the recipe's alone: the Orchestrator, each team's lead and what KOLONİ's
own checks at the end of the turn open (a reviewer, the agent of a fix round) come on top of it - a
one-step recipe says "1 agent", and a turn of it may open several more.

## The parts of a recipe

The toolbar adds parts to the drawing: **+ Step**, **+ All at once**, **+ Loop back** and **+ Ask me**. **Tidy up** lays the drawing out again.

**A step** says who does it:

- **The Orchestrator picks**;
- **The team's experts**;
- **A role**, with **At most** 1 to 5 agents;
- **Candidates (the best one goes on)** (see below);
- **A team's stages**.

A step can also have **Done when**, **Only if the step before found a problem**, **If it fails**
(ask me or stop), and **Ask me to approve its work before it goes on**. That last one gives a card with
**Go on**, **Ask for changes** and **Stop**.

Before a step that runs only if a problem was found, a test run that failed is a problem, whatever
the agent's report says. At any other review step it is one too where the report says nothing is wrong,
unless its **Already failing before** lines name every test that run says failed - with its file or
suite where the run gives them (a bare name only where no other failing test has it), and never one
the run's reproduce step showed failing: that is the bug. A later pass clears a failed run only where it
is the same command in the same folder, or a run of the same test tool in that folder that picks none of
its tests (`pytest` and `python -m pytest` are one tool): a narrower pass - a test name, `-k`, `::`, `-t`,
`--grep`, `-run`, `--filter`, tests left out (`--ignore`, `--deselect`), options of its own (`-c`,
`-o`, `--rootdir`, `PYTEST_ADDOPTS`) - clears no wider failure. A pass of files or folders clears it only
where it counted tests and every test the failed run names as failing is in one of them. A run that
never started its tests (the tool not found), one that runs none (`-h`, `--help`, `--version`,
`--collect-only`, a list of the tests, no tests found, or a summary that counts 0 passed and 0 failed)
and one whose exit is hidden (`; true`, `|| true`, a pipe after it) gives no verdict either way. In a step
with the id `reproduce` (Bugfix's first) the failing test is the work: the agent's report says it "fails
as it should". It is told to write and run that test itself and to open no other agent. In a recipe with no loop,
**Ask for changes** - and a fix round of KOLONİ's checks - goes back to the step after such a step
once it is done: the failing test it showed stays, and the fix goes again. Any other recipe with no
loop goes back to its first step.

A Tester at a review step, or any agent of a step with the id `test` or `tests`, passes only on a command
it ran that checks something. Where the project has a test command (yours, one KOLONİ saved, or one its
files name) and the recipe changed code, that is a test run that really ran tests - its runner counted
some, or your own test command ran. Elsewhere a mere read (`ls`, `cat`, `git status`) checks nothing, nor
does `echo`, `true`, `cd .`, `sleep`, `python -c "pass"`, a `--version` or `--help`, or a test run that
ran none. Its task says so, and one that ran none does not pass - "it is a check that ran no test on
record". Where you declined its command,
the recipe stops at **Teams' work is ready**, "Not checked: you declined …", rather than sending the work
back. A reviewer that only reads (a Data analyst, a Performance engineer) passes on its report. (Where an
agent's CLI keeps its own commands off KOLONİ's record, its report is taken as it is.)

**All at once** runs steps side by side. It waits for **all branches** or for **the first one done**.

**Loop back** goes back to an earlier step, **at most** 1 to 5 rounds.

A **Room** step of a recipe drawn before 0.1.10 (rooms are gone) opens as an **All at once** group in
its place, with a step for each of its roles: they run side by side, as sub-agents, in the recipe's
copy. Its arrows and loops are kept. A Room step that reviewed (**no finding is left**) becomes a review
by each of its roles but one that does the recipe's work at a step of its own: that one works in the
group (a role does not check its own work). A Room step that ran only if the step before found a
problem now always runs: a group runs on no condition.

**Ask me** is an end: **Ask me, then in**, or **Tell me what was found**. Every recipe needs an end.

### The Checks step

Every recipe ends in a **Checks** step 🔒: what KOLONİ checks before the recipe's work is done
([What KOLONİ checked](../use/checked.md)). It stands between the step(s) that lead to the end and
the end itself ("Ask me, then in", "Take in", "Tell me"): the arrows go last step → Checks → end,
one Checks step before all of the ends, and it moves with them when you add or move a step. It cannot be
removed or dragged. KOLONİ runs its checks first, on the work in the recipe's copy, and only then asks
**Ready for you**: a fix round sends the recipe back to work, and work whose tests still fail after
the rounds is never offered nor taken in.

![The ready Bugfix in the editor - Reproduce it with a failing test, then Fix it - its locked Checks step between its last step and the end, and its panel set for the recipe with Tests, Review and Config ticked of Tests, Review, Docs, Diagrams, Data, Slides, Pages and Config (Scripts and Code style and types are further down the panel)](../images/recipe-checks-step.png)

Click it to choose:

- **Follow the project** (the default): the project's **After a change** - Test and review, Tests
  only or Nothing - with its **Check by kind of work** and **Fix rounds**.
- **Set for this recipe**: **Tests**, **Review**, **Docs**, **Diagrams**, **Data**, **Slides**,
  **Pages** (a changed page in KOLONİ's own browser at phone, tablet and desktop widths),
  **Config** (JSON, YAML and TOML files parse), **Scripts** (shell and PowerShell scripts parse -
  read, never run) and **Code style and types** (the project's own ruff, eslint, tsc and mypy, asked
  before one runs unasked, as in [Checked](../use/checked.md#documents-diagrams-data-and-slides)),
  each on or off (Config, Scripts and Code style and types start on), and
  **Fix rounds** - the project's, until it passes, 1 to 10, or **0 - check only** (a problem is said,
  nothing goes back to be fixed). With **Review** on, a big change of screens is also tried by the
  Tester ([the live try](../use/checked.md#the-live-try)).

A recipe that makes no code - a report, the docs - turns **Tests** off and its kind of work on: its
turn runs no tests and checks the documents it wrote; a fixable problem (a broken link) goes back
as a fix round, as a failing test does. With every check off, the answer says "Not checked: this
recipe's Checks step checks nothing". The choice is kept with the recipe - in a folder's
`.koloni/recipes/*.json` too, as its graph's `checks`.

The ready recipes come set: **Bugfix** and **Feature** check their tests and a review, **Docs** its
documents and a review, **Evolve** its tests; the others follow the project. A recipe set for itself
checks so even in a project at **Nothing** - set its Checks step to **Follow the project** to leave it
to the project. Only a recipe you picked (**Teams for this chat**: Manual) can check less than the
project does; one the Orchestrator picked (Orchestrator decides) only adds to the project's checks
and takes the larger Fix rounds - it never turns them off. A recipe's turn follows its Checks step,
never the chat's **Test and review changes** switch. Rounds never stack: where the recipe's own
loop of test and fix ran out, the Checks step sends nothing back on top.

## Where a recipe is kept

Choose **Kept in KOLONİ, for every folder**, or **Kept in this folder's .koloni/recipes (in git)**. A
recipe kept in the folder travels with the project, but only recipes kept in KOLONİ can be picked under
**Teams for this chat** or as a team's default.

## How a recipe runs and ends

The team works in one working copy, step by step, following the drawing. When the work reaches its
end, the **Teams' work is ready** card asks whether to take it into the project: **Take in**,
**Fix the findings** or **Ask for changes**. See [Ready and approval cards](../use/ready.md).

At **Full auto**, the work is taken in without the card, unless a team failed or a check was skipped.

[![The recipe engine: steps, all at once, a review and a fixer, loop back for up to 5 rounds; blocking findings and suggestions; candidates and Evolve; Ask me cards; an end and the Ready for you card with Take in, Fix the findings and Ask for changes](../diagrams/recipe-engine.svg)](../diagrams/recipe-engine.svg)

*How a recipe runs, loops and ends. ([full size](../diagrams/recipe-engine.svg))*

## Candidates

A step whose **Who** is **Candidates (the best one goes on)** gives the same job to 2 to 5 agents.
Each works in its own working copy. For their models choose **Auto, the Lead picks**, **Same model** or
**I pick each**.

Each candidate's work is scored by the project's **Measure command** (Settings › This project › Checks and git):
a command whose last line of output is a number from 0 to 100. A card then lists the scores and asks
which candidate's work goes on. At Full auto the best score goes on by itself.

With a **Target** (0 to 100) and a loop, the step is tried again while the best score is below the
target, and a new result replaces the kept one only if it scores higher. The ready recipe **Evolve**
works this way: three Coders try the job, each their own way. With no measure command there is no
score to compare, so the step runs one round only, and its card says so.
