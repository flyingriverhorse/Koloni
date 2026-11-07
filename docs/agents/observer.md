# Observer

The Observer is a built-in role that never works on its own. When you switch it on, its model reads
each sub-agent's report and says what the record shows of it.

## Switching it on

Settings › This project › Agents › **Have a model look over each sub-agent's report**.

That is one more model request after every sub-agent's report, on your plan or your bill. The
Observer's model is sent the task, the report, the diffs of the changed files and the test's output,
with the secrets KOLONİ knows masked. Choose its model on the Agents page, in the Observer role's
panel.

## What it does

It answers one question about a report, with no tools: what of the report the record shows, in a few
sentences. No agent is opened.

## How you see it

In the agent's window, under its report, the Observer's words are tagged "opinion". If it could not
answer, it says "no observation" and why.

The Orchestrator takes the Observer's words as an opinion, not a fact.
