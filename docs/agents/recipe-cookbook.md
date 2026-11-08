# Recipe cookbook

The ready recipes KOLONİ comes with. Ready recipes cannot be changed; press **Copy it** on the Recipes tab
to make your own from one. "Review" means the step is done only when it has no findings. An **in** end
takes the work into the project (on the **Teams' work is ready** card); a **report** end tells you what was
found.

| Recipe | Steps | Loops back | Ends |
|---|---|---|---|
| **Feature** | Write the spec (Spec writer, asks you to approve) → Build it (Coder) → at once: Code review (Reviewer), Security review (Security reviewer), UI review (UI designer), Test it (Tester), all reviews | reviews → Build it, 2 rounds | in |
| **Bugfix** | Reproduce it (Debugger) → Fix it (Coder) → Test it (Tester, review) → Review it (Reviewer, review) | review → Fix it, 2 rounds | in |
| **Review only** | at once: Reviewer, Security reviewer, UI designer, all reviews | — | report |
| **Integration** | Learn (the team's experts) → Plan (Planner) → Experts check the plan (review) → Build (Coder) → Test (Tester, review) | check → Plan, 2 rounds | in |
| **Quality check** | Run the tests (Tester, review) → Find and fix the cause (Debugger, only if a problem was found) → at once: Code review (Reviewer), Security review (Security reviewer) | fix → tests, 2 rounds | report |
| **Model change** | Plan the experiment (Data scientist) → Experts review the plan (review) → Build it (ML engineer) → at once: Run the tests (Tester), Compare the metrics (Model evaluator) → Review it (Reviewer, review) | experts → plan, 1 round; checks → build, 2 rounds | in |
| **Pipeline change** | Change the pipeline (Data engineer) → at once: Run the tests (Tester), Check the data quality (Data analyst) → Review it (Reviewer, review) | checks → change, 2 rounds | in |
| **Infra change** | Change the infrastructure (DevOps) → at once: Security review (Security reviewer), Performance review (Performance engineer) → Review it (Reviewer, review) | reviews → change, 2 rounds | in |
| **Docs** | Write the docs (Docs writer) → Review it (Reviewer, review) | review → write, 2 rounds | in |
| **Research** | Find it out (Researcher) → Sum it up (Summarizer) | — | report |
| **Spec** | Break it into tasks (Product owner) → Write the spec (Spec writer) | — | report |
| **Analysis** | Analyse the data (Data analyst) → Review the analysis (Reviewer, review) | — | report |
| **Upkeep** | Update the dependencies (Dependency keeper) → Run the tests (Tester, review) → Find and fix the cause (Debugger, only if a problem was found) | fix → tests, 2 rounds | in |
| **Evolve** | Try it three ways (3 Coders as candidates, target score 80) | try again, 3 rounds | in |

## Which team runs which

Each ready team has a ready recipe as its default: Web app runs **Feature**, Backend / API **Bugfix**,
Quality **Quality check**, Product **Spec**, Data **Analysis**, Maintenance **Upkeep**, ML **Model
change**, DataOps **Pipeline change**, DevOps **Infra change**, and Docs and Research the recipes of their
names. You can change a team's **Default recipe** on the Agents page.

If you renamed or removed a ready recipe or team, yours may differ.

See [Recipes and candidates](recipes.md).
