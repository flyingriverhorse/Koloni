# Step limits

An agent works in steps. A sub-agent stops after a set number of them, so that no agent runs on
without end. The Orchestrator counts no steps of its own: it stops when its work is done, when it
goes round in circles, or at a limit you set. This page says where the limits are set, what happens
when an agent reaches one, who may give it more, and what happens when nobody is there to ask.

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
| Settings › The app › Agents › **Steps an agent may take** | The most steps one sub-agent takes on a job: its task, or one later message it works on. 25 unless you change it, a whole number from 5 to 200. It holds in every project. It does not hold the Orchestrator. |
| The role's form (Agents page) → **Safety stops for one agent** → **At most this many steps** | A limit of the role's own. Where it is lower than the app's, it holds. It counts the steps an agent of the role takes on its work in the turn, and in the earlier turns it goes on from. Empty: only the app's limit. On the **Lead** role it is the Orchestrator's step limit; empty, it has none. |
| Settings › This project › Limits and money › **Continue gives this many more steps** | How many more steps **Continue** gives. 25 unless you change it, 1 to 200. |

### More steps for coordinators

A team's coordinator needs steps to open its recipe's agents, wait, and read what comes back. It gets
4 more for each step of its recipe. Each **Ask for changes** that sends the recipe back gives that
much again, for up to three rounds. With the app's 25, a coordinator whose recipe has six steps takes
up to 49 steps. A role's own lower limit still holds over these.

### The Orchestrator: no step count

The Orchestrator runs the whole turn: it opens the teams, passes messages on and
writes the answer. A fixed count of its steps ran out on honest work, after the work was already in
the project, so it has none. What stops it:

- its work is done;
- it goes round in circles (below);
- a limit you set: the **Lead** role's **At most this many steps**;
- in a To-do task's turn, and in a job while you're away: nothing has moved
  for Settings › The app › **Stuck after this many minutes with no progress** (30 unless you change
  it) - no file of the turn changed, no agent finished its work, no failing command passed. Each of
  those starts the minutes again, so honest work runs as long as it needs. They do not run out while
  a card waits for you, a command or a model step of the turn is under way, or an agent below the
  Orchestrator is at work;
- a last resort: a To-do task's turn and a job while you're away end after **An unattended turn runs
  at most (hours)** (8 unless you change it; empty: no limit), however they go. A night's stop time
  holds as before;
- either way the turn fails with the reason, its work kept - never cancelled: a To-do task gets its
  fix round, then is stuck, and its chat's queue goes on; a night tries the job once more, then goes on;
- money and tokens, where you set them: the project's token limit for a message, its monthly
  budget, a night's money;
- **Stop**.

A turn you started has no clock that ends it: you are there to press **Stop**, and the cards below
ask you.

### When the Orchestrator goes round in circles

KOLONİ watches the Orchestrator's tool calls. It stops it when:

- the same call fails the same way 5 times, with no change of the turn and no command succeeding in
  between;
- 10 calls in a row each repeat a call it had made, with the same result, since something last
  moved.

Something moves when a file of the turn changes, it opens an agent, or it sends a message to one it
had not written to among its last three. A command that succeeds is judged by what it said, like any
call. A call with other arguments, or one that gets a new result (a team's report), is new; the same
call made several times in one step counts once. From the third repeat on, the Orchestrator is told what is repeating.

In a turn you started, the first time it is told, in its next step, to try a different approach or
to report what it did and end. Its counts start again and it goes on; you see nothing. If it goes
round in circles again, a card under the call asks you:

> The Orchestrator has no step limit, and it seems to go round in circles: its last 10 calls each
> repeated one it had made, with the same result, with no change of this turn on record and no
> command of its own succeeding in between. Go on lets it carry on; Stop here ends it, with what it
> did so far. With no answer in 10 minutes its turn ends, its work kept.

- **Go on**: it carries on, and the counts start again.
- **Stop here**: the turn ends with that reason.
- **No answer in 10 minutes**: the turn ends by itself. What is in the project stays, and work in
  agents' copies stays behind its cards, as at **Stop**. KOLONİ's line in the chat says how many
  agents it had opened, how many files it had changed in the project, and which call it repeated.
  A message you sent meanwhile, the chat's To-do queue or the night then goes on.

Either way the turn ends there: nothing more is waited for, and no other card comes. Where this
turn's work is already in the project, it ends **completed**, not red, with KOLONİ's line saying why
it ended; otherwise it fails with the reason.

The card waits for you at every level, **Full auto** too. As it goes up, KOLONİ tells you on the
desktop, where you switched that on (Settings › This project › Notifications):
"The Orchestrator seems stuck: it repeated list_dir with the same result…".

In a job while you're away there is no card: the Orchestrator
fails with the reason on record, also where it had written something, and a night goes on with the
next job. A To-do task's turn is its chat's, so the card comes there too; where the turn fails, the
task gets its fix round, then is stuck with why, and the chat's queue goes on with the next task.

### When the Orchestrator's model is slow to answer

In a turn you started, when the Orchestrator's model has said nothing for 5 minutes while it was
asked - no words, no call - a card under the turn asks you:

> Codex · gpt-6-astra has not answered for 5 min. Keep waiting, or stop this turn and pick another
> model?

Time on a tool (a sub-agent, a command) or on another card that waits for you does not count.

While it waits, the card counts as waiting for you outside its chat too: on the Ready page, as a
mark on the chat in the Chats list, and in a note in the corner ("Orchestrator waits for you").

- **Keep waiting**: the turn waits on; the next card comes only after another 5 minutes with no word.
- **Stop and pick another model**: the turn ends as at **Stop**, what it did kept, and KOLONİ's line
  says to pick another model for the Orchestrator and send your message again: in the chat's model
  picker, or on the Agents page where the Orchestrator role has a model of its own (see
  [A role's model](../models/tiers.md#a-roles-model)).
- No answer: it keeps waiting. The card closes by itself once the model answers.

A sub-agent has no such card (one whose provider fails is moved to the next model of its tier), and
a turn nobody watches is as above.

## At the limit

What happens depends on who stopped, which limit it reached, and whether it changed files.

### The Orchestrator

The Orchestrator reaches a step limit only where you set one: its role's own. It gets
no Continue card there. If its teams are still at work it waits for them, then the turn ends. Send a
message to go on.

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

- the Orchestrator itself, at a limit you set (its loop guard asks: see above);
- a job of [work while you're away](../automation/overnight.md#step-limits-while-away);
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
- for work that is always big, raise **Steps an agent may take**: it holds every sub-agent.

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

**While you're away.** In a To-do task's job no card comes: the Reviewer stops at 25, and the job's
Orchestrator is told its part is not done. (In the chat you went away from, the card comes and the
Orchestrator decides it at once, as at Full auto.) It may tell the Reviewer once to go on: the Reviewer gets 25 new steps and ends at about 35.
Had it needed more than 50, it would stop again, and the job's report would say what is left undone.
The job can still count as done when you're back: open its chat to read what was left.
