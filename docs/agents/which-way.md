# Which way to work

KOLONİ offers several ways to get work done, from one message to a list of jobs while you are away. Start with the
smallest that fits: every extra agent is more model calls, so more tokens, money or plan use.

## At a glance

| You want… | Use… | Because… | What it costs |
|---|---|---|---|
| a small, clear job done | **just ask**, in a chat | the Orchestrator does small jobs itself, or opens one sub-agent | the fewest calls |
| to see the plan before anything changes | **Plan first** | each message first gets a plan to approve | one planning pass more |
| a bigger piece of work, built, reviewed and tested | **a team** with a **recipe** | the recipe runs the steps in order, loops back on findings, and asks you where the recipe says (Feature: the spec, and the work at the end) | one agent per step, more for each loop |
| two or more agents to build one thing at the same time | **a room** | its members share the work out, each file has one holder, and they read each other's posts | each member's calls, up to the room's budget |
| agents to think a question through, with nothing changed | **a discussion** | agents talk in rounds and nobody writes anything | each speaker's whole work so far is sent again at each step, so tokens grow faster than the talk |
| the best of several attempts | **Evolve**, or another recipe with **Candidates** | 2 to 5 agents try the same job, each is scored by your measure command, and the best goes on | each candidate in each round, plus the measure runs |
| two models' answers side by side | **Compare** | one message goes to two models, and you keep one's work | two runs of the message |
| several jobs done while you are away | **work while you're away** | each job runs in its own copy, and you decide when you're back what comes in | each job, within the card's money limit |
| the same job by the clock, or when files change | **a trigger** | it starts a turn by itself, with only the permissions you ticked | each run, within the trigger's budget |
| a list of tasks worked through in order | **To-do** | each task runs in a chat of its own, one after another | each task's turn |

## Examples

**"Fix the failing date test."**
Just ask. One bug in one place is a job for the Orchestrator, or one Coder it opens. With
**Teams for this chat** → **No teams**, it never brings in a team.

**"Add a password reset page, with review and tests."**
A team with the **Feature** recipe: in **Teams for this chat** choose **Manual**, then the **Web app**
team, whose default recipe is Feature. A Spec writer writes the spec for you to approve, a Coder builds
it, then a Reviewer, a Security reviewer, a UI designer and a Tester check it at once; findings go back
to the Coder, at most twice. You take the work in on the **Teams' work is ready** card. See
[A web app with a team](../examples/team-web-app.md).

**"Fix this crash, and make sure it stays fixed."**
The **Bugfix** recipe: in **Teams for this chat** choose **Manual**, then the **Backend / API** team,
whose default recipe is Bugfix. A Debugger reproduces the crash, a Coder fixes it, a Tester and a
Reviewer check it. Cheaper than Feature: four steps, no spec and fewer reviews.

**"The backend and frontend teams must agree the API first."**
A room. Open one with **Work together…** under **More**, or ask the Orchestrator to bring the teams'
leads together in a room before the teams start. They agree the shape in the room, then each team
builds its side. See [Rooms](rooms.md).

**"Should we keep SQLite or move to Postgres?"**
A discussion. Ask the Orchestrator to have the Architect and a Database engineer discuss it. Nobody
changes anything; you can join in and end it. Set a token limit under Settings › This project ›
Limits and money › **A discussion's tokens, at most**. See [Discussions](discussions.md).

**"Make this function faster, and keep the fastest version."**
**Evolve**. First set a **Measure command** (Settings › This project › Checks and git) whose last line is a score
from 0 to 100. Evolve has three Coders try the job, each their own way, and tries again while the
best score is under 80, for at most four rounds. That is up to twelve Coders: the most expensive way on
this page. See [Picking the best of several candidates](../examples/candidates.md).

**"Run the tests every night and tell me what failed."**
A trigger: **By the clock**, **At a time of day**, with the message "Run the tests and say what
failed". It may only do what you tick. A recipe does not run in a trigger's turn, and a trigger never
starts a CLI that works with its own tools. See [Triggers](../automation/triggers.md).

**"While I'm away tonight: update the dependencies, tidy the docs, and add tests to the parser."**
Work while you're away. Ask the Orchestrator to plan the jobs; it proposes the jobs on a **While you're away**
card, with a money limit and, if you want one, a stop time. Leave KOLONİ running: closing it ends
the jobs. See [A job while you're away](../examples/overnight-job.md).

## The ready recipes

KOLONİ comes with these recipes: **Feature**, **Bugfix**, **Review only**, **Integration**,
**Quality check**, **Model change**, **Pipeline change**, **Infra change**, **Docs**, **Research**,
**Spec**, **Analysis**, **Upkeep** and **Evolve**. The [Recipe cookbook](recipe-cookbook.md) lists each
one's steps and which team runs it by default.

## Keeping the cost down

- Start small. A single agent that is not enough can still hand work on; a team that was too much has
  already spent.
- **Review only** and **Research** report what they found and change nothing.
- A discussion and a room have budgets: set them before you start.
- Give roles a tier, so easy jobs go to a fast model. See [Tiers and Agents may use](../models/tiers.md)
  and [Keeping costs down](../money/cost.md).
