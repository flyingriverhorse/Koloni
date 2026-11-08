# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for a security problem: until it is fixed, anyone could use it.

Report it privately on GitHub instead:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Say what you found, how to reproduce it, and what an attacker could do with it.

Only the maintainers see the report. The fix is discussed and prepared there in private; once a release
carries it, the advisory is published and you are credited unless you ask not to be.

## Supported versions

| Version | Fixes |
|---|---|
| 0.1.x | Yes |

## What counts

KOLONİ runs on your own machine and starts agents that read, write and run commands in your
projects. Examples of what to report:

- an agent writing, running or reaching the network where your permission level says it must ask;
- a page or a request from another site driving KOLONİ (approving a card, reading a chat);
- KOLONİ's own data, keys or CLI sign-ins reachable from inside a project;
- a provider key shown in the page, a log or an export.

What KOLONİ does and does not protect against is in the guide's
[Security model](docs/security/model.md). A limit written there (for example, Full auto's harm
check is a courtesy for honest commands, not a wall) is known, not a vulnerability, but a way around a
check that the page says holds is.

Ordinary bugs go to the public issues.
