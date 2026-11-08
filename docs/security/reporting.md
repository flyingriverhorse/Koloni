# Reporting a problem

## A security problem

Do not open a public issue: until it is fixed, anyone could use it. Report it privately on GitHub:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Say what you found, how to reproduce it, and what an attacker could do with it.

Only the maintainers see it. The fix is prepared there in private; once a release carries it, the
advisory is published and you are credited unless you ask not to be.

What to report: an agent writing, running or reaching the network where your
[permission level](../use/permissions.md) says it must ask; another site driving KOLONİ; KOLONİ's
own data, keys or CLI sign-ins reachable from a project; a provider key shown in the page, a log or an
export. The limits the [Security model](model.md) names are known; a way around a check it says holds
is a vulnerability.

## A bug

Open an issue on the repository. Say what you did, what you expected, and what happened instead. Say which
release or commit you run (`git log -1` in KOLONİ's folder); the backend's log is `runtime/logs/koloni.log`. Look through a log before you
attach it: it can hold file paths and parts of your chats.
