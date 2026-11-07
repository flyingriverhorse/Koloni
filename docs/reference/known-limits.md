# Known limits

What KOLONİ does not do yet, or does only in part.

## First release (alpha)

Version 0.1.0 is the first release, an alpha: expect rough edges. Several paths were built against
stand-ins only, including the **Server** tab for llama.cpp, Copilot with a GitHub token, and some limit
and credit messages.

## Secrets

- A command that names a secret file, or searches the whole folder when the folder holds one (`grep -r`,
  `rg`, `gci | gc`), is asked about at every level, Full auto too. A script that opens a secret file
  without naming it (it builds the name, say) is not caught. Only Docker and Copilot's sandbox hide secret
  files from commands; KOLONİ's own commands on this machine, Claude Code, Codex, Qoder and agy do not.
- When it runs **Native**, Codex runs the commands its own rules count as safe (a read of `.env`, or of a
  file outside the project) without asking KOLONİ, at every level; KOLONİ records them after they ran, so
  no card stands in their way. agy reading with its own tools has no hook: its reads, of a secret file
  too, are not asked about at any level. That Qoder asks before every tool is not yet measured.
- A command you approve can still print, encode or send a secret it was given.
- An agent's request for a key on a hidden card is not available to CLIs working with their own tools.
- A branch deleted because it held a secret you gave still has its commits in git's reflog until git
  prunes them.

## Outside content

- Text from the web, MCP tools, Knowledge and GitHub issues is framed as data, but the frame only tells
  the model; a model can still follow what it says.
- Only KOLONİ's own tools frame what they bring in. A CLI's own web fetch, MCP servers or file reads
  are not framed.
- A forged end of the frame is not caught when it is written with look-alike letters from other scripts,
  with full-width or mathematical letters, with words joined by marks (`end-of-the`, `end_of_the`), or
  with markdown or HTML inside it. See [Security model](../security/model.md#outside-content).

## CLIs

- When a CLI runs **Native**, it runs its commands itself, so its model reads their raw output; KOLONİ
  masks keys only in what it records and shows. Measured once on Copilot (Native) with a made-up GitHub
  token (`ghp_…`) in a command's output: it was `***` in the model's answer and absent from Copilot's raw
  stream, so Copilot hid that kind of key itself; other kinds of key were not tried. Claude Code, Codex,
  Qoder and agy run Native were not measured. With KOLONİ's tools (as a session, or one run per step),
  the keys KOLONİ knows and values shaped or named like keys are masked before the model reads the
  output.
- Copilot does not report which paths its PowerShell commands touch, so at Full auto a command that
  writes a protected file without naming it (a script, a path it builds) runs without a card. The same
  goes for KOLONİ's own commands at Full auto: one that names the file (`echo … > .claude/settings.json`)
  is asked about, but a script that writes `~/.claude/settings.json` is not. Such a file in the project
  is put back, and you are asked whether to keep it; one outside the project is not.
- Claude Code, Qoder and agy run **Native** (and Copilot where it cannot sandbox its commands) have no
  sandbox of KOLONİ's: it can stop what they do only at their hook. A write with their own file tools
  outside the project and the folders it also works in (or that you allowed) is asked about on a card at
  every level, Full auto too, and refused in a turn nobody watches (in a working copy, refused: it may
  write only in the copy); one into a CLI's own folder (`.claude`, `.gemini`, `.codex` or `.copilot` in
  your home folder) or another place KOLONİ never opens (`.ssh`, browser profiles) is refused. Their
  commands are judged by what they name: a command that writes outside the project, for example to the
  Startup folder or a PowerShell profile, runs without a card at Full auto, and at any level where an
  allow rule covers it, unless it names a CLI's settings folder such as `.claude` or `.gemini`, or a
  secret file, or it deletes or sends data off the machine.
- Claude Code and Qoder run **Native** do not say where their commands run, so KOLONİ judges each one as
  run in the project folder. If the CLI keeps a `cd` from an earlier command, later relative paths are
  judged at the wrong place: after you approve `cd ..`, reading a file there by its name is taken for a
  read in the project and is not asked about below Full auto. Whether Claude Code keeps a `cd` that
  leaves the project is not measured.
- A sub-agent on Claude Code or Qoder run **Native** works in a working copy, but its commands are not
  sandboxed: at Full auto, one that writes into your project by a path it does not spell out (`..\..`, a
  script) changes the project directly. KOLONİ finds such a change at the end of the turn and records it
  as made in the project by an unknown maker.
- Triggers do not start a turn on a CLI that works with its own tools (Native, or agy).
- GitHub Copilot CLI's tokens and AI credits run as a session are counted from its usage checkpoint, as
  in **Native**; measured with `copilot -p` (CLI 1.0.103), not yet seen in a live session.
- Copilot's thinking levels on a model server of your own are not measured.
- An agy model whose name ends in its level takes no other level. Only a name ending in `-low` was seen
  to refuse one; the other endings are read the same way, not measured.

## GitHub

- Reading a GitHub issue with a real `gh` is not measured yet: the fields KOLONİ asks gh for are taken
  from gh's manual.

## Models

- Other OpenAI-compatible servers, such as Ollama, should work but are not tested. The local server
  that is measured is llama.cpp's `llama-server`.

## Commands

- Some harmful commands are not on the list yet: `kubectl delete`, `terraform destroy`,
  `rsync --delete`, `robocopy /MIR`, `mail`, `ssh host 'command'`.
- At Full auto, the harm check sees honest commands only; a command written to hide what it does is not
  seen. See [Security model](../security/model.md).
- Commands cannot be given input while they run.
- In Docker on Linux and macOS, commands run as your user, not as root. A command that needs root in
  the container, such as `apt-get install`, fails. On Linux, files an older version of KOLONİ made as
  root in the project may no longer be writable; see
  [Troubleshooting](../troubleshooting.md#commands-and-docker). Under rootless Docker, the files a
  command makes belong to another user id on the host.

## Recipes

- Recipes do not run in triggers' turns.
- A chat cannot open a room while a recipe runs.
- A team as a step's "Who" runs its stages as slots of one step, not one after another.

## The page

- Canvas positions are worked out from the record each time and are not saved.
- At phone width, the top bar wraps to two lines.
- Desktop notifications are on Windows only.

## Systems

macOS, Linux and the Docker image have been tested less than Windows. See
[Install](../getting-started/install.md#how-well-each-system-is-tested).
