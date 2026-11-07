# Answering for you

When you are away, questions can wait for you, or the Orchestrator can answer the safe ones itself.

## Switching it on

Settings › This project › Asking and away › **When you're away**:

- **Everything waits for you** (the default);
- **The Orchestrator answers what it safely can**, after a number of minutes (0 to 1440; 10 unless you
  change it).

With the second, once you have not answered for that many minutes, or the away card is on, "the
Orchestrator picks, says why, and you see it under "Decided for you"". During work while you're away it
answers at once.

"An Orchestrator on a CLI uses one request of your plan for each answer."

## What it may decide

Only:

- an agent's question to you;
- a recipe's "Ask me";
- opening a sub-agent on its role's own model, while that provider has room.

## What always waits for you

Commands, file changes, the web, installing, secrets, folders, new roles or skills, deleting, Take in,
Discard, Commit, a different model that may cost money, and Stop. It also does not answer when the turn
is over its token limit, the project is over its monthly budget, or the provider is over its limit.

In To-do task chats it never answers for you.

## Decided for you

What it answered shows under **Decided for you while you were away**: who asked, what the Orchestrator
chose, and why. Press **OK** to keep it, or **Change →** to give another answer. If the answer cannot be
undone any more, it says so.

At **Full auto** the Orchestrator also answers questions in a chat you watch, at once, and some of
KOLONİ's own cards, such as an agent's Continue / Stop here card at its
[step limit](../agents/step-limits.md#who-answers-the-card); those answers show under the same heading.
Full auto alone does not let it open a sub-agent for you, and it does not answer those cards during
work while you're away. An Orchestrator on a CLI answers at Full auto only where **When you're away** is set
to **The Orchestrator answers what it safely can**.

## The same question again

If the same agent asks the same question again in the turn, with the same words and choices, it gets
the Orchestrator's earlier answer at once, with no new request. Its line under **Decided for you** says
it is "its answer when this was asked before". If you changed that answer, your answer is the one given.
