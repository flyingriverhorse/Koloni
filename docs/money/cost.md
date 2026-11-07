# Keeping costs down

## What spends extra requests

Some settings make one more model request each time. Each says so where you switch it on.

| What | When it spends |
|---|---|
| **Note what the work found, by itself** (Settings › This project › Memory and web) | One request after every message. |
| **Have a model look over each sub-agent's report** (Settings › This project › Agents) | One request after every sub-agent's report. |
| **Orchestrator model: automatic** (the chat's model picker) | One request for each message you send. |
| **The Orchestrator answers what it safely can** (Settings › This project › Asking and away › When you're away), on a CLI | One request of your plan for each answer. |
| **Try a real run** (Models page, a CLI) | One short run, on your plan. |
| **Read now** for Claude Code (a provider's card) | One short request. |
| Search by meaning (Memory page) | One embeddings request for each search. |
| Learning a knowledge topic (Knowledge page) | Model requests, up to the limit you set. |
| Candidates in a recipe | Each candidate is its own agent. |
| Agents on a CLI working at the same time | They spend your subscription at the same time. |

## Ways to keep a job cheap

- Give models tiers, and let roles ask for a tier, so easy jobs go to a fast model. See
  [Tiers](../models/tiers.md).
- Turn off **Agents may use** for an expensive model you want to pick only by hand.
- Set a **Monthly budget** and a token limit per message (Settings › This project › Limits and money), and dollar limits
  on API keys (a provider's **Limits** tab).
- Keep **Agents at the same time** and **Sub-agents per request** low (Settings › This project › Limits and money).
- Give an MCP server only to the roles that need it, and switch off tools you do not use: every tool's
  description is sent at every model step.
- Use a model server on your own machine for work that does not need a large model: it spends no money.
- On GitHub Copilot CLI, give the provider a model. Copilot's `auto` picks one for each request; with no
  model and Medium thinking, Copilot's default spent 7.12 AI credits for the same short answer that `auto`
  answered for 0.18 (measured once, 7 Nov 2026, Copilot CLI 1.0.105). See
  [GitHub Copilot CLI](../models/setup-cli.md#github-copilot-cli).

See [Usage and budgets](usage.md).
