# Answering for you

When you are away, questions can wait for you, or the Orchestrator can answer the safe ones itself.

## Switching it on

Settings › This project › Asking and away › **When you're away**:

- **Everything waits for you**;
- **The Orchestrator answers what it safely can**, after a number of minutes (0 to 1440).

A new project has the second, after 5 minutes; a project from before 0.1.5 keeps what it had - turn it
on here. In a chat with no folder everything waits for you. With it, once you have not answered a card for that many minutes, "the Orchestrator picks,
says why, and you see it under "Decided for you"". In the chat you went away from ([☾ Away](overnight.md))
and its tasks' chats it decides at once, whatever this setting says - also the cards that waited when
you pressed Go away. While you type an answer to a question, it waits (2 minutes after your last key);
once you are back, a card held so waits this setting's minutes again.

"An Orchestrator on a CLI uses one request of your plan for each answer."

## What it may decide

Only:

- an agent's question to you;
- a recipe's "Ask me";
- opening a sub-agent on its role's own model, while that provider has room;
- going on or stopping at a sub-agent's [step limit](../agents/step-limits.md), where that card comes
  (not in a To-do task's turn).

## What always waits for you

Commands, file changes, the web, installing, secrets, folders, new roles or skills, deleting, Take in,
Discard, Commit, a different model that may cost money, and Stop. It also does not answer when the turn
is over its token limit, the project is over its monthly budget, or the provider is over its limit.

The same rule holds in To-do task chats and while you're away. Your Orchestrator's own questions to
you always wait for you.

## Decided for you

What it answered shows under **Decided for you while you were away**: who asked, what the Orchestrator
chose, and why. Press **OK** to keep it, or **Change →** to give another answer. If the answer cannot be
undone any more, it says so.

At **Full auto** the Orchestrator also answers questions in a chat you watch, at once, and some of
KOLONİ's own cards, such as an agent's Continue / Stop here card at its
[step limit](../agents/step-limits.md#who-answers-the-card); those answers show under the same heading.
Full auto alone does not let it open a sub-agent for you; of KOLONİ's own cards only the step limit's
is decided while you're away. An Orchestrator on a CLI answers at Full auto only where **When you're away** is set
to **The Orchestrator answers what it safely can**.

## The same question again

If the same agent asks the same question again in the turn, with the same words and choices, it gets
the Orchestrator's earlier answer at once, with no new request. Its line under **Decided for you** says
it is "its answer when this was asked before". If you changed that answer, your answer is the one given.
