# Talking while agents work

A turn stays open while the Orchestrator's agents work, and you can talk to the Orchestrator in it:
ask how things stand, add a wish, have it open, message or stop an agent - without waiting for the
turn to end.

## Send now and After this turn

While a turn runs, the message box has two ways to send:

- **Send now** (Enter): *the Orchestrator reads it in this turn.* Your message goes into the turn at
  work. If the Orchestrator is waiting for its agents, it wakes and answers you; if it is in the
  middle of a step, it reads your message at its next step. The turn does not end before it has
  read it.
- **After this turn**: *it waits in the queue and starts its own turn*, as a message did before.

The box says what it does: "Write to the Orchestrator - it reads it in this turn…". With no turn at
work there is only **Send**.

Some turns take no message while they run. Then Send now puts your message in the queue and the box
says why under it - **Queued:** and one of:

| Why | When |
|---|---|
| the turn was ending | the Orchestrator had given its last answer |
| this turn takes no message now (a plan turn) | the turn writes a plan ([Plan first](plan-first.md)) |
| this turn takes no message now (a comparison) | the turn is one side of a [comparison](compare.md) |
| this turn takes no message now (a To-do task's turn) | the turn works on a To-do task |
| this turn takes no message now (a job while you were away) | a ☾ Away job's turn |
| this turn takes no message now (not one you started) | the turn was not started from your own page |
| it is for another topic | you wrote into another topic, or started a new one |

A message is in exactly one place: in the turn at work, or in a turn of its own. If the turn ends
before the Orchestrator read it - you pressed Stop, or the turn failed - your message goes on in a
turn of its own, queued, so it is never lost.

When it answers your message, the Orchestrator changes nothing itself: its steps until that answer
are refused Write files, Edit files, Diagram pictures, Run commands, a skill's script, Web requests and
any MCP server's tool. It hands new work to an agent (opens one, messages one, stops one) or says it in
its answer; it may still read, look things up, **Remember** and propose To-do tasks, which wait for your
OK as ever. A CLI Orchestrator's own tools are only told so. Its own work goes on as before once it has
answered. While it answers it waits for no place among the agents at work: its agents keep theirs, and
it answers you at once (Settings › This project › Limits and money › More limits).

Only you can send now: the message must come from KOLONİ's own page. What you write is your own
word, as any message of yours is - Full auto's judge reads it as yours.

### With a CLI as the Orchestrator

| CLI | Send now |
|---|---|
| Claude Code, Codex, Copilot run **Native** | goes into its turn at once (measured 27 Nov 2026: Claude Code 2.1.332, Codex 0.172, Copilot 1.0.114) |
| agy, and any CLI run **One session per agent** | read when its current run ends, in one more run of the same turn |

A word to the Orchestrator about an agy agent (its window's box) wakes the Orchestrator as your own
word does, while it waits for its agents.

## Agents in the background

The Orchestrator of an API model can open an agent **in the background**: it starts it and goes on at
once - talks to you, opens others, messages or stops it. When the agent ends, its report comes to the
Orchestrator as a note and it takes one step to read it. Until then it says the agent is still at
work, never what it found. A CLI's Orchestrator always went on like this; it reads its agents'
reports once all of them are back.

Background agents are held to the chat's limits as any agent: how many work at once, how many a turn
opens, how deep ([Step limits](../agents/step-limits.md)). Their cards come to you as usual, and Full
auto's judge looks at their commands as at any. Each wake is a step of the Orchestrator's, counted to
its role's limit. Stop on the turn stops them all.

The Orchestrator can also run a command in the background (`run_command` with `background`): it goes
on, reads the command's output with `command_output`, stops it with `stop_command`, and is told when it
ends. At most as many run at once as the chat lets agents work at once. The turn's end stops them.

## Stop and Message on one agent

An agent at work that the Orchestrator (or one of its agents) opened has **Stop** and **Message** on
its node on the canvas and in its window's head:

- **Stop** stops that agent alone. The chat says *"You stopped Coder. Its work so far is kept for
  your Take in; nothing of it is in the project."* The Orchestrator is told, as KOLONİ's word, not to
  open it again unless you ask; the rest of the turn goes on. The Orchestrator has its own
  `stop_agent` for one it opened.
- **Message** opens the agent's window at its Tell box.

KOLONİ's own checks (Stop this check) and the agents of a team's recipe (the team's Stop) are stopped
their own way, so they have no Stop of their own here.

An agy agent cannot hear messages while it works: its box says so - "Coder can't hear messages while
it works (agy). Tell the Orchestrator instead - it can stop it and start it again." - and sends your
words to the Orchestrator. A Claude Code, Codex or Copilot agent hears them in its running turn.

## When an agent ends and nobody is looking

When a background agent ends while its chat is not open anywhere, KOLONİ shows a desktop notice -
"Reviewer finished: 2 findings", "Coder stopped", "Tester failed" - where the project has
**Desktop notifications** on (Settings › This project › Notifications). The notice holds only the
agent's name and how it ended, never its words.
