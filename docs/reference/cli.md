# CLIs

What KOLONİ supports for each CLI. How to set one up is in [Set up a CLI](../models/setup-cli.md).

| CLI | Command | How it runs (default first) | Native asks KOLONİ before | Plan read | Versions measured with KOLONİ |
|---|---|---|---|---|---|
| Claude Code | `claude` | session, step, native | every tool it uses | yes (one short request) | 2.1.310, 2.1.311, 2.1.312 |
| Codex | `codex` | session, step, native (step first on a model server of your own) | each command and patch, but not those its own rules count as safe | yes | 0.163.0, 0.164.0 |
| GitHub Copilot CLI | `copilot` | session, native | each command, write and read | yes | 1.0.91, 1.0.103 |
| Qoder | `qodercli` | session, native | every tool it uses (not yet measured) | no | — |
| agy | `agy` | reads, native | every tool it uses | yes | 1.3.3, 1.4.7, 1.4.8 |

## A version that was not measured

KOLONİ records which versions of each CLI it was measured with. A newer version is never refused. KOLONİ
tries it once; if it answers as expected it runs, with a note that this version was not measured with
KOLONİ. If not, it runs the old way: with KOLONİ's tools, and the CLI's own tools off.

## What every CLI has in common

- You install it and sign in yourself, in your own terminal.
- Its use counts against your plan with that vendor; KOLONİ shows no money for it.
- Triggers do not start a CLI that works with its own tools.
- When a CLI runs **Native**, its model reads its commands' raw output; KOLONİ masks keys only in what it
  records and shows.

See [Subscription rules](../models/subscription-rules.md) and [Known limits](known-limits.md).
