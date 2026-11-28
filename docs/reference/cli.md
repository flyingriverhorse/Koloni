# CLIs

What KOLONİ supports for each CLI. How to set one up is in [Set up a CLI](../models/setup-cli.md).

| CLI | Command | How it runs (default first) | Native asks KOLONİ before | Plan read | Versions measured with KOLONİ |
|---|---|---|---|---|---|
| Claude Code | `claude` | session, step, native | every tool it uses | yes (one short request) | 2.1.310, 2.1.311, 2.1.312 |
| Codex | `codex` | session, native | each command and patch, but not those its own allow rules cover | yes | 0.163.0, 0.164.0 |
| GitHub Copilot CLI | `copilot` | session, native | every tool it uses, through KOLONİ's own hook (1.0.114 on); on the older protocol, each command, write and read | yes | 1.0.91, 1.0.103, 1.0.105, 1.0.114 |
| agy ([experimental](../models/setup-cli.md#experimental-clis)) | `agy` | reads, native | every tool it uses | yes | 1.3.3, 1.4.7, 1.4.8 |

Qoder is no longer run since 0.1.8: see [Qoder is no longer supported](../models/setup-cli.md#qoder-is-no-longer-supported).

## A version that was not measured

KOLONİ records the versions of each CLI that its use of the CLI's protocol was measured with: the
last column of the table. A newer version is never refused. KOLONİ
tries it once; if it answers as expected it runs, with a note that this version was not measured with
KOLONİ. If not, it runs the old way: with KOLONİ's tools, and the CLI's own tools off.

Single behaviours were measured on newer versions too, which does not make them measured versions:
Codex 0.172.0 (what it asks KOLONİ before, its own sub-agents switched off, **Send now**), Claude Code
2.1.332 (**Send now**) and agy 1.5.18 (a word sent waits for its turn's end). Each is told in [Known
limits](known-limits.md), under Secrets and CLIs.

GitHub Copilot CLI is asked its version and protocol as KOLONİ starts it: on the newer protocol
(1.0.114 on) any version runs **Native**, with that note when it was not measured; on the older one only
a measured version does. A Copilot that does not say its version, or speaks a protocol KOLONİ does not
know, runs the old way, and the provider's card on the Models page says why. See
[Set up a CLI](../models/setup-cli.md#github-copilot-cli).

## What every CLI has in common

- You install it and sign in yourself, in your own terminal.
- Its use counts against your plan with that vendor; KOLONİ shows no money for it.
- When a CLI runs **Native**, its model reads its commands' raw output; KOLONİ masks keys only in what it
  records and shows.

See [Subscription rules](../models/subscription-rules.md) and [Known limits](known-limits.md).
