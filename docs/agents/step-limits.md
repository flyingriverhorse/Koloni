# Step limits

An agent works in steps, and KOLONİ stops it after a set number of them, so that no agent runs on
without end. This page says where the limits are set, what happens when an agent reaches one, who
may give it more, and what happens when nobody is there to ask.

## What a step is

A step is one request to the agent's model. The model answers, and may call tools: read a file, run
a command, open a sub-agent. The tools run, and the next step reads what they gave back.

- A CLI run **One session per agent** counts one step for each message it writes.
- A CLI working with its own tools (**Native**) takes no steps KOLONİ can count: no step limit holds
  it. See [Set up a CLI](../models/setup-cli.md#how-it-runs).

When an agent has two steps left, KOLONİ tells it to start nothing new, finish what it is on, and
write its report: what it did and what is left.

## Where the limits are set

| Where | What it sets |
|---|---|
| Settings › The app › Agents › **Steps an agent may take** | The most steps one agent takes on a job: its task, or one later message it works on. 25 unless you change it, a whole number from 5 to 200. It holds in every project. |
| The role's form (Agents page) → **Safety stops for one agent** → **At most this many steps** | A limit of the role's own. Where it is lower than the app's, it holds. It counts the steps an agent of the role takes on its work in the turn, and in the earlier turns it goes on from. Empty: only the app's limit. |
| Settings › This project › Limits and money › **Continue gives this many more steps** | How many more steps **Continue** gives. 25 unless you change it, 1 to 200. |
| A trigger's **Model steps a run** | The steps of a whole turn a trigger starts, all its agents together. See [Triggers](../automation/triggers.md#budget-and-end). |

### More steps for coordinators and the Orchestrator

Agents that run other agents need steps to open them, wait, and read what comes back. They get more:

- A team's coordinator: 4 more for each step of its recipe. Each **Ask for changes** that sends the
  recipe back gives that much again, for up to three rounds.
- The Orchestrator: 8 more for each team of the chat that has a coordinator, and 4 more for each step
  of a recipe it runs itself (a team with no coordinator), again for each **Ask for changes**, up to
  three rounds.

With the app's 25, a coordinator whose recipe has six steps takes up to 49 steps, and an Orchestrator
with two coordinated teams takes up to 41. A role's own lower limit still holds over these.

## At the limit

What happens depends on who stopped, which limit it reached, and whether it changed files.

### The Orchestrator

The Orchestrator gets no card. If its teams are still at work it waits for them, then the turn ends
with "Stopped at its step limit." Send a message to go on.

### A sub-agent with changed files

A sub-agent that works in its own copy and has changed something stops at once. Its work is kept on a
card in the chat ("*Coder* did not finish its work: this is what it had changed"), and nobody waits
for it. While the turn runs, that card has **Continue (+25 steps)**, with the project's Continue
amount:

- **Continue** gives it that many more steps, and it goes on in its kept copy. It gets the whole
  amount, also when it stopped at its role's own limit.
- The card's other buttons decide the kept work, as on any card of changes.

If it stops again with changes, its card comes back with Continue. After the turn the card has no
Continue: ask the Orchestrator in a new message to go on with it.

### A sub-agent with nothing kept

A sub-agent with no changes of its own, such as a team's coordinator or a reviewer, waits at the app's
limit on a card under the call that opened it:

> *Reviewer* came to its limit of 25 steps before its work was done. Continue gives it 25 more to go
> on where it is; Stop here ends it, with what it did so far.

- **Continue (+25 steps)**: it goes on where it is, with that many more steps. If its role has fewer
  steps left, the card offers only those.
- **Stop here**: it ends with what it did so far. Its opener is told that you chose Stop here, and does
  not tell it to go on.

The card comes once for a job. After Continue the agent stops at the end of the steps it was given,
with no new card.

There is no card when the agent stopped at its role's own limit, when its role has no steps left, or
in the cases under [When there is no card](#when-there-is-no-card).

### Who answers the card

| Level | Who answers |
|---|---|
| **Ask before changes**, **Auto-edit files** | You. The turn waits for your answer. **When you're away** does not answer this card. |
| **Full auto** | The Orchestrator, at once: Continue or Stop here, with why. You see it under **Decided for you**. It answers once for each agent in a turn. The next time that agent reaches its limit in the turn, it gets no card and ends. |

At Full auto the card still waits for you when:

- the project is over its monthly budget;
- the Orchestrator's provider is over its limit;
- the turn is over the project's token limit;
- the Orchestrator runs on a CLI and **When you're away** is **Everything waits for you**: each answer
  would use a request of your plan.

## Going on by message

The Orchestrator, or a team's coordinator, may tell an agent that stopped at a step limit to go on,
with a message. This works at every level, once for each agent in a turn. The agent gets a new app
step limit, not the Continue amount. Its role's own limit still holds: it stops there.

It is refused when:

- you chose **Stop here** on the agent's card;
- the agent already had more steps in this turn: Continue on its Continue / Stop here card, or an
  earlier go on;
- the agent has no steps left under its role's own limit. A role's limit is your safety stop: only
  you give more past it, at every level, **Full auto** and work while you're away too. Press Continue on its kept
  work's card, or raise the role's limit. The Orchestrator is told "*Coder* is at its role's limit of
  12 steps; more steps are the user's to give". While you're away nothing is given, and the job's report says
  the part is left undone.

## When there is no card

These get no Continue / Stop here card. The agent stops, and the agent that opened it is told what
is left:

- the Orchestrator itself;
- a job of [work while you're away](../automation/overnight.md#step-limits-while-away);
- a turn a trigger started: the trigger's **Model steps a run** holds for the whole turn, and it ends
  with "budget: stopped after {steps} model steps, the most this trigger gives a turn";
- a To-do task's chat;
- a room's members, and a room's sharing step (which has one step of its own);
- an agent answering another agent's question, or working on another agent's message, a go on
  included: the sender waits for its reply;
- an agent whose work is kept on a card with Continue;
- an agent of a team you stopped.

## Afterwards

When a sub-agent stops at a step limit, its opener is told that its part is not done. It hands what is
left to another agent, tells it to go on where it may, or says in its answer what is left undone.

On the canvas the agent's box says "Stopped at its step limit". Where
it had more, it says "Stopped after the {n} steps it was given": {n} is the job's whole count, so after
a Continue of 25 at 25 steps it reads 50.

To give it more:

- while the turn runs, **Continue** on its kept work's card;
- after the turn, ask the Orchestrator in your next message to go on with it. That is a new turn, so
  the once-a-turn go on is there again for an agent that stopped at the app's limit or at the end of
  the steps it was given;
- an agent that stopped at its role's own limit counts the steps it took before, in later turns too:
  raise the role's **At most this many steps** first, then ask the Orchestrator to go on. A raised
  limit holds from its next job;
- for work that is always big, raise **Steps an agent may take**.

## One job, three ways

A Reviewer has to read a large change. It needs about 35 steps. The app's limit is 25, Continue gives
25, and the Reviewer role has no limit of its own.

**In the day, at Ask before changes.** At 23 steps the Reviewer is told it has two left. At 25 it
stops, and the card asks you. **Continue** gives it 25 more; it goes on where it is and ends at about
35. **Stop here** ends it with what it found so far, and the Orchestrator's answer says what was not
reviewed.

**In the day, at Full auto.** The same card comes, and the Orchestrator answers it at once, say with
Continue. Its answer and why show under **Decided for you**. The Reviewer ends at about 35. Had it
needed more than 50, it would stop at 50 with no new card, and the Orchestrator would say what is left;
more steps are then yours to give in your next message.

**While you're away.** No card. The Reviewer stops at 25, and the job's Orchestrator is told its part is not
done. It may tell the Reviewer once to go on: the Reviewer gets 25 new steps and ends at about 35.
Had it needed more than 50, it would stop again, and the job's report would say what is left undone.
The job can still count as done when you're back: open its chat to read what was left.
