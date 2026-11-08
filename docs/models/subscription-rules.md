# Subscription rules

When you use a CLI through KOLONİ, you use your own subscription with that vendor. Each vendor has its
own terms for that. This page says what each vendor's official page says, as read on 5 November 2026.
It is not legal advice: read the terms yourself, and decide.

## What KOLONİ does

KOLONİ starts the CLI that you installed and signed in to yourself, unchanged, and sends it prompts. It
does not read the CLI's sign-in token, and it does not talk to the vendor's service for the CLI. For
Claude Code, you can have KOLONİ keep a separate sign-in folder; you still sign in through Anthropic's
own sign-in.

## What each vendor's page says

| Vendor | Its page | What it says |
|---|---|---|
| Anthropic (Claude Code) | [Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance) | Third-party developers may not offer a Claude.ai sign-in in their own apps, or collect, store or route users' credentials or session tokens. The exception is an end user signing in to the unchanged Claude Code program with their own subscription. The page does not speak of another app starting the CLI. |
| OpenAI (Codex) | [Authentication](https://developers.openai.com/codex/auth) | The page could not be read in full. For apps, the official way is "Sign in with ChatGPT" ([preview](https://developers.openai.com/siwc)). No text was found that allows or forbids another program using Codex's own ChatGPT sign-in. |
| GitHub (Copilot CLI) | [Use Copilot CLI](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli) | It documents running the CLI from scripts and with `-p`. It says nothing against another tool running it. Requests count as premium requests ([Copilot requests](https://docs.github.com/en/copilot/concepts/billing/copilot-requests)). Copilot's own terms were not read. |
| Google (Antigravity, `agy`) | [Terms](https://antigravity.google/terms), section 6 | "Using third party software, tools, or services to access the Service (e.g. using OpenClaw with Antigravity OAuth) is a breach of this Agreement." It warns that Antigravity and Gemini CLI accounts can be suspended. |
| Qoder | [Terms of Service](https://qoder.com/product-service) (29 April 2026), [Run in scripts](https://docs.qoder.com/cli/run-in-scripts) | The docs endorse headless use (`-p`) in "Shell scripts, automation workflows, and CI/CD Pipelines". The terms forbid sharing your account or letting a third party use it (2.3), and scraping outputs with scripts (3.2.10). Nothing forbids a local tool starting the CLI under your own sign-in. No page states limits for the free models. |

## Open questions

!!! warning "agy: switched off"
    Whether KOLONİ starting `agy` counts as "third party software … to access the Service" is not
    settled, but it is close to the example Google gives. So KOLONİ adds agy switched off, and its card on the Models page says why.
    Switching it on is your choice, and your risk with your Google account.

- Codex: no rule either way was found.
- Qoder: allowed for your own use as far as the pages say; your sign-in or access token is never given to anyone else.

What a CLI's use costs you is set by your plan; see [Usage and budgets](../money/usage.md).
