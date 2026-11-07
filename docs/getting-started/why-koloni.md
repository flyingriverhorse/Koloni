# Why KOLONİ

An agent CLI on its own works in one terminal, one session at a time. KOLONİ puts the agents you already
use, and the models you choose, in one place on your own machine, and shows you what they really did.

## What it adds

- **Many agents, one chat.** The Orchestrator hands parts of a job to other roles (Coder, Reviewer, Tester
  and more), each in its own working copy, so your folder changes only when you take the work in.
- **Any model you have.** Claude Code, Codex, GitHub Copilot CLI, Qoder and agy on your own plans, an API
  key, or a model server on your own machine, side by side. Each agent shows the provider and model it
  really ran on.
- **Evidence, not a story.** The canvas draws every turn from the record: the agents, their tools,
  commands and the files they changed, with real diffs. A value KOLONİ does not know is shown as unknown.
- **You decide.** Before anything risky, an agent asks you on a card. The permission level sets how much
  runs without asking.
- **Memory with sources.** Facts rest on lines of files and are checked again each time; a fact whose
  source changed is not used until you look.
- **Work that goes on.** Teams follow recipes, triggers start work by themselves, and jobs run in copies
  while you are away.
- **Local.** KOLONİ listens on `127.0.0.1` only, keeps its data in a folder on your machine, and sends no
  telemetry.

## What it is not

- Not finished: 0.1.0 is the first release, an alpha, so expect rough edges. See [Known limits](../reference/known-limits.md).
- Not a sandbox by itself. Below Full auto your cards are the wall; for more, run commands in Docker. See
  [Security model](../security/model.md).
