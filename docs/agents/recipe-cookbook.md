# Recipe cookbook

The ready recipes KOLONİ comes with. Ready recipes cannot be changed; press **Copy it** on the Recipes tab
to make your own from one. "Review" means the step is done only when it has no findings. An **in** end
takes the work into the project (on the **Teams' work is ready** card); a **report** end tells you what was
found. **Agents** is how many agents a run opens, as the Recipes tab counts them: the fewest where no
review finds a problem, the most where every loop goes back all its rounds. The Orchestrator and what
KOLONİ's own checks open at the end (a reviewer, the agents of a fix round) come on top
([Recipes and candidates](recipes.md)).

| Recipe | Steps | Loops back | Ends | Agents |
|---|---|---|---|---|
| **Feature** | Write the spec (Spec writer, asks you to approve) → Build it (Coder) → UI review (UI designer, review) → Checks (tests and a review) | UI review → Build it, 2 rounds | in | 3–7 |
| **Bugfix** | Reproduce it with a failing test (Debugger) → Fix it (Coder) → Checks (tests and a review) | — (KOLONİ's fix rounds go back to Fix it) | in | 2–2 |
| **Review only** | at once: Reviewer, Security reviewer, UI designer, all reviews | — | report | 3–3 |
| **Integration** | Learn (the team's experts) → Plan (Planner) → Experts check the plan (review) → Build (Coder) → Test (Tester, review) | check → Plan, 2 rounds | in | 5–9 |
| **Quality check** | Run the tests (Tester, review) → Find and fix the cause (Debugger, only if a problem was found) → at once: Code review (Reviewer), Security review (Security reviewer) | fix → tests, 2 rounds | report | 3–8 |
| **Model change** | Plan the experiment (Data scientist) → Experts review the plan (review) → Build it (ML engineer) → Compare the metrics (Model evaluator, review) → Checks (tests and a review) | experts → plan, 1 round; metrics → build, 2 rounds | in | 4–10 |
| **Pipeline change** | Change the pipeline (Data engineer) → Check the data quality (Data analyst, review) → Checks (tests and a review) | quality → change, 2 rounds | in | 2–6 |
| **Infra change** | Change the infrastructure (DevOps) → at once: Security review (Security reviewer), Performance review (Performance engineer) → Review it (Reviewer, review) | reviews → change, 2 rounds | in | 4–10 |
| **Docs** | Write the docs (Docs writer) → Review it (Reviewer, review) | review → write, 2 rounds | in | 2–6 |
| **Research** | Find it out (Researcher) → Sum it up (Summarizer) | — | report | 2–2 |
| **Spec** | Break it into tasks (Hive keeper) → Write the spec (Spec writer) | — | report | 2–2 |
| **Analysis** | Analyse the data (Data analyst) → Review the analysis (Reviewer, review) | — | report | 2–2 |
| **Upkeep** | Update the dependencies (Dependency keeper) → Run the tests (Tester, review) → Find and fix the cause (Debugger, only if a problem was found) | fix → tests, 2 rounds | in | 2–7 |
| **Evolve** | Try it three ways (3 Coders as candidates, target score 80) | try again, 3 rounds | in | 3–12 |

## Which team runs which

Each ready team has a ready recipe as its default: Web app runs **Feature**, Quality **Quality check**
and Docs **Docs**. The other ready recipes are no ready team's default since 0.1.10: pick one for a
team in **Teams for this chat** (**Manual**), or make it a team's **Default recipe** on the Agents
page - **Bugfix** for a team with a Debugger, a Coder and a Tester, **Spec** for one with the Hive
keeper and a Spec writer, and so on.

In Bugfix the Debugger only shows the bug: it writes a test that fails because of it, runs it and
reports the failing output, and fixes nothing; the Coder's fix must make that test pass. Its Checks
step then runs the tests, and has a Reviewer look at a big or security-touching change - the rule of
every turn ([What KOLONİ checked](../use/checked.md)); a small change gets no agent review. A failing
test or a blocking finding goes back to Fix it, not to Reproduce it: the failing test it showed stays.
**Ask for changes** goes back to Fix it too. Before 0.1.7 Bugfix had its own Test it and Review it
steps; a copy of it you changed keeps its steps - to have every change reviewed, copy Bugfix and add a
Review it step.

Feature, Model change and Pipeline change lean on their Checks step the same way (since 0.1.10). Feature's
one review is the UI designer's - a judgement of the screens KOLONİ's checks do not make; Model change
keeps its experts' review of the plan and the Model evaluator's metrics, Pipeline change the Data
analyst's look at the data. Their tests are KOLONİ's to run, and a big or security-touching change gets
KOLONİ's Reviewer and Security reviewer; a small one gets no review of KOLONİ's. Before 0.1.10 Feature had a
Code review, a Security review and a Test it beside its UI review (6 to 16 agents), and Model change and
Pipeline change a Tester and a closing Reviewer; a copy you made keeps them.

If you renamed or removed a ready recipe or team, yours may differ.

See [Recipes and candidates](recipes.md).
