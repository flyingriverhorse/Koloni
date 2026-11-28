# Answering for you

When you are away, questions can wait for you, or the Orchestrator can answer the safe ones itself.

## Switching it on

Settings › This project › When you're asked › **When you're away**:

- **Everything waits for you**;
- **The Orchestrator answers what it safely can**, after a number of minutes (0 to 1440).

A new project has the second, after 5 minutes; a project from before 0.1.5 keeps what it had - turn it
on here. In a chat with no folder everything waits for you. With it, once you have not answered a card for that many minutes, "the Orchestrator picks,
says why, and you see it under "Decided for you"". In the chat you went away from ([☾ Away](overnight.md))
and its tasks' chats it decides at once, whatever this setting says - also the cards that waited when
you pressed Go away. While you type an answer to a question, it waits (2 minutes after your last key);
once you are back, a card held so waits this setting's minutes again.

"An Orchestrator on a CLI uses one request of your plan for each answer." When it answers, it also
reads your preferences and this project's rules as saved on the [Memory](../memory.md) page.

## What it may decide

Only:

- an agent's question to you;
- a recipe's "Ask me";
- opening a sub-agent on its role's own model, while that provider has room;
- going on or stopping at a sub-agent's [step limit](../agents/step-limits.md), where that card comes.

## What always waits for you

Commands, file changes, the web, installing, secrets, folders, new roles or skills, deleting, Take in,
Discard, Commit, a different model that may cost money, and Stop. It also does not answer when the turn
is over its token limit, the project is over its monthly budget, or the provider is over its limit.

The same rule holds in To-do task chats and while you're away. Your Orchestrator's own questions to
you wait for you - but in a job while you're away (☾ Away), where it decides them itself: "The user is
away. Decide yourself and say what you assumed in one sentence. Only if the answer is something only
the user can know (a password, an account, a personal fact), answer `park`." Its answer and reason are
under **Decided for you**. What it answers `park` is parked for you under **Waiting for you**, and so is
a question it could not answer (no answer it could read, a CLI past its most or with tools of its own);
the job goes on. A sub-agent's question there is asked with the second sentence alone. `park` decides
nothing by itself - an option spelled "Park" is parked, not picked. See [Work while you're
away](overnight.md#questions-and-approvals).

## Decided for you

What it answered shows under **Decided for you** on the [Ready for you](../use/ready.md) page, the
project's whole list: who decided, what the Orchestrator chose, and why. Press **OK** to keep it, or
**Change →** to give another answer while the agent that asked still works. If the answer cannot be
undone any more, the row says why. The chat says it in one line at its top, "3 things were decided
for you in this project and 2 wait for you here.", with **Open in Ready for you**. See
[Decisions](../use/decisions.md). A chat with no folder keeps its own **Decided for you while you were
away** box, with the same **OK** and **Change →**.

At **Full auto** the Orchestrator also answers questions in a chat you watch, at once, and some of
KOLONİ's own cards, such as an agent's Continue / Stop here card at its
[step limit](../agents/step-limits.md#who-answers-the-card); those answers are in the same list.
So does a command that [Check what I said first](../use/permissions.md#check-what-i-said-first) ran
without a card, or did not run, on a line of yours: "Coder ran … without asking" or "KOLONİ did not run
… for Coder", with that line, until you press **OK**.
Full auto alone does not let it open a sub-agent for you; of KOLONİ's own cards only the step limit's
is decided while you're away. An Orchestrator on a CLI answers at Full auto only where **When you're away** is set
to **The Orchestrator answers what it safely can**.

A decision the Orchestrator took without a card - a library, an approach - it can note for you with
`note_decision` (0.1.11): it is in the same list, "Orchestrator · Decided: …" with its reason, until
your **OK**; **Change** takes your own words. See
[Talking while agents work](../use/talk-while-agents-work.md#what-the-orchestrator-has-while-its-agents-work).

## The same question again

If the same agent asks the same question again in the turn, with the same words and choices, it gets
the Orchestrator's earlier answer at once, with no new request. Its line under **Decided for you** says
it is "its answer when this was asked before". If you changed that answer, your answer is the one given.
