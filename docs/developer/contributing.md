# Contributing (DCO)

- **Sign off every commit** (Developer Certificate of Origin): `git commit -s`.
- **CLA**: a pull request agrees to the short-form `CLA.md` in the repository, which lets the
  project relicense the contribution. KOLONİ is AGPL-3.0-or-later.
- Keep a change small and focused, and deliver a behaviour end to end: backend and page together.
- `scripts/verify.ps1` must pass. See [Tests and verify](verify.md).
- Review the staged diff before you commit. Never add secrets, caches or `runtime/` output.
- Check the licence of any source code or asset before you take it.
- No fake agents, progress or usage: a value KOLONİ does not know stays unknown.

## The changelog

`CHANGELOG.md` is in English and every release looks the same:

- One heading per version: `## [X.Y.Z] - YYYY-MM-DD`. Unreleased work goes under `## [Unreleased]`.
  Versions follow Semantic Versioning.
- Inside a version, only these sections, in this order, and only those with entries: Added, Changed,
  Fixed, Security, Removed, Deprecated.
- One line per entry: `- **Area**: what the user can now do or will notice, in plain words.` The area is a
  page or part the user knows (Canvas, Chat, Ready, To-do, Agents, Models, Tools, Memory, Knowledge,
  Triggers, Usage, Settings, CLIs, Install, Docs).
- Say what changed for the user, not how it was built. No commit hashes or internal names. A breaking
  change starts with **Breaking:**.
- A migration that changes saved data says so.
- Link to the docs where a feature is explained.
