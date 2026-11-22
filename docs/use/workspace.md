# Working copies and Take in

## The Workspace

The **Workspace** button, the first under the message box, opens "the project's files, what agents changed,
wrote or showed, and what waits for you". Its number is what waits for you in this chat, a copy kept for **Take in** too (in
**Changes** that copy is under **Kept**).

- **Files**: the project's files. Open files show as tabs.
- **Changes**: what changed, sorted by what you have to do: **Waits for you**, **At work**, **Kept**,
  **In the project**, **Not by an agent**, **Needs a look**, and **Closed** (shut at first).
  Inside a group, each change sits under its agent and your message. Each file says in words what
  happened ("changed", "new", "deleted", "you said no"). With git, the tab shows this chat's work and
  what git sees changed since the last commit. Without git (or when git does not answer in time), it shows
  this chat's record and says so. The tab's count is git's (as in the top bar), or without git what is not
  closed.
  **Show folders as a tree** puts the files in their folders. When changes wait for you, it says how many
  and offers **Next waiting ▸**. A file that waits opens on its diff with **Approve** and **Reject**; one
  in the project offers **Revert**. An agent's copy opens on what it holds, with **Take in…** (or
  **Look**) to its card.
- **Previews**: dev servers agents started.
- **Working copies**: each sub-agent's copy ("*name*'s copy").

## Working copies

Each sub-agent changes files in its own copy of the project, outside your folder. Your folder does not
change until its work is taken in.

- `.git` and caches are not copied. `node_modules`, `.venv` and `venv` are linked, not copied.
- A project over 20,000 files or 500 MB gets no copy: the agent works in the project itself.
- When you and an agent changed the same file, KOLONİ merges line by line (for files up to 1 MiB).
- On Linux and macOS a copy keeps whether each file is runnable, so a script such as `./gradlew` still
  runs, and Take in carries that back to your project. A new file written with **Write files** gets your
  usual mode (`0644` with the common umask).
- Work goes into your folder one way at a time: a Take in waits while a branch is merged, and the other
  way round. What went in reaches the other agents' copies where they did not change those files, and a
  copy made at that moment gets all of it.

Agents at work beside each other are told that each works in a copy of its own: change only what
their task needs, write nothing outside their copy, stop no program by its name, start a server on a
free port, and install nothing into the linked `node_modules`, `.venv` or `venv`. A command an agent
runs in its copy is asked at every level, Full auto too, when it:

- names another agent's copy, a worktree of your project, or a place above its copy (`../..`) - also
  past a `cd` KOLONİ cannot follow, where any `..` counts;
- writes in the linked `node_modules`, `.venv` or `venv`, which are your project's own, or installs
  into them (in a turn you watch; a trigger's turn runs only the commands its trigger allows, as
  before);
- stops programs by their name (`taskkill /IM`, `pkill`, `killall`, `Stop-Process -Name`), or looks a
  process up and stops it (`lsof -ti:8000 | xargs kill`, `fuser -k`). By its id (`taskkill /PID`,
  `kill 1234`, `Stop-Process -Id 1234`), or one the line itself started (`kill $!`), is fine. In
  your project, at Full auto, **Check what I said
  first** may let a stop by name run on a line of yours, but never one that may stop KOLONİ itself
  or another agent's CLI (python, node, uvicorn, claude, codex, copilot, qodercli, agy, a
  filter, a wildcard, `kill -1` or `kill 0`, or a process looked up).

KOLONİ reads the command as written: a path built in a script is not seen.

[![A working copy's life: the copy is made, the agent works in it, a card in Ready for you, Run the test, then Take in, Merge or Open pull request, or Discard; clashes, commits, and what is removed or kept; and a lane for an agent on a branch: a locked worktree made from your folder as it is, its work committed when it stops, go on on the same branch or in a copy, a merge that waits for your commit, a pull request that never sends your unpushed commits, and a branch holding a secret never kept](../diagrams/working-copy.svg)](../diagrams/working-copy.svg)

*A working copy's life, from the copy to your project; the "On a branch" lane is [Branches](#branches) below. ([full size](../diagrams/working-copy.svg))*

## Taking work in

When a sub-agent finishes, its changes come back on a card: **Take in …'s work?**, with
**Take in** and **Discard**. At **Auto-edit files** and **Full auto** they come in without a card when the
agent finished, nothing clashes and the project's test passed. See [Permission levels](permissions.md).

- **Changed on both sides**: files you and the agent both changed. "Nothing is chosen for you"; pick a
  side for each, or press **Let an agent resolve the conflicts**.
- **Run the test** runs the project's test on the copy (Settings › This project › Checks and git › **Test before
  adding**).

A team's recipe keeps its work in one copy until you press **Take in** on the **Teams' work is ready** card. See
[Ready and approval cards](ready.md).

<video src="../videos/take-in.webm" poster="../../videos/take-in.jpg" controls muted loop playsinline preload="none" style="width: 100%; height: auto" aria-label="Video: the Ready for you node opens the list, Take in brings the team's work in, and the node says In the project"></video>

*Take in: the team's work comes into the project only now.*

![The Ready for you panel under Ready to take in: KOLONİ asks whether to take the Web app team's work into the project, with Take in and Ask for changes](../images/take-in.png)

*A team's work waits under **Ready to take in** until you press **Take in**.*

## Branches

The Orchestrator can give a team's work a git branch of its own. Then the card offers **Merge** or **Open
pull request**, as you chose under Settings › This project › Checks and git › **How a team's finished branch reaches
yours**. Until you choose, the first finished branch on a GitHub project asks. A pull request lets KOLONİ
push the branch; it never merges one. **Keep this branch after merging** keeps the branch.

Opening a pull request needs **gh** (GitHub's CLI) installed and signed in (`gh auth login`), and the
project's `origin` must be the GitHub repository gh sees. Until then the card says why it cannot open one.
A branch that holds commits of yours that origin does not have - your branch or another merged into it,
fast-forwarded to, rebased onto or cherry-picked - is not pushed until you push them, also after you
amended, rebased or dropped them; the card names them. What counts as the agent's own is what its branch's
history says was committed on it: where that history is gone (`git reflog expire`, or git's cleanup of an
old branch), the card says KOLONİ cannot attribute those commits, and they are not pushed either. Nor is a
file that holds exactly what a commit of yours not pushed yet put there (an agent's squash, pick or amend
of it, or a copy of a stashed file, of a commit on a detached HEAD - in this folder or in another worktree
of yours -, or of a file you had not committed when the branch began). And while you have any commit or
stash not on GitHub - on a branch, in a stash, on a detached HEAD, in any worktree of yours - or the
branch began from your uncommitted work, a pull request waits for your click at every level, Full auto
too: the card says why ("you have 2 commits not on GitHub yet", "you have a stash not on GitHub yet"), so
you can check its files are the agent's work.

The Inspector and **Where the work is** label such an agent "works on branch koloni/*name*" (an agent
in a plain copy: "works in its own copy").

The branch starts from your folder as it is, not only from your last commit: your edits, staged files
and new files that git does not ignore are in the agent's worktree. KOLONİ makes that one commit
("KOLONİ: your folder as koloni/*name* began") from an index of its own, so your files, your index,
your branch and HEAD are not touched; it is the branch's first commit and shows in `git log
koloni/*name*`. Left out, whether you staged them or not: what git ignores (`.env`, build output),
files named as secrets (`.env.local`, a key file, `credentials.json`, `token.json`), `node_modules`,
`.venv` and `venv` (linked in instead), a git repository inside your folder, KOLONİ's own `.koloni`
folder, and every link or junction with what it leads to. Code named like a secret (`credentials.py`,
`.env.example`) is taken as any file. The card says in one line which of your files were left out as a
secret or a link: "Not in its branch: 2 of your files (.env, token.json) - a secret by its name, or
through a link".

The card, the merge and a pull request carry the agent's work alone, measured from that commit - never
your uncommitted files. A merge waits for your commit:

- If the agent changed a file you have uncommitted changes in, the card lists it under what is in the
  way; commit yours, then **Merge**.
- If it changed the very lines you had not committed when it began (or a new file of yours), the card
  says so - nothing is merged or sent as a pull request over them, and no agent puts them together.
  Commit yours, then **Merge**.
- If what is in the way is another agent's work you took in and did not commit yet, the card names that
  agent's Take in: commit it (on its card, where a commit is offered), then **Merge**.

Where the agent's work changes a file you had not committed when it began, the card says so and waits
for your **Merge**, at Full auto too.

If your folder had more new or changed files than a copy takes, your git is older than 2.40, or git
could not take your folder as it is (a file another program holds open, a path too long for git, a
folder it may not read, or longer than three minutes), the branch starts from your last commit as
before, and its card says so in one line under its heading: your uncommitted changes were not in it.

Its worktree, in KOLONİ's copies folder, is locked while the agent works (`git worktree list -v` says
"KOLONİ: an agent works here; KOLONİ removes it"), so your own `git worktree prune`, `remove` or `move`
leaves it alone. KOLONİ unlocks it before it removes it. When KOLONİ starts, it removes git's records of
its own worktrees whose folder is gone (after a crash, say), and nothing else: never your worktrees,
never a branch. The Orchestrator is told that `koloni/…` branches and these worktrees are not its to
delete, rename or switch to.

In its copy, git works for the agent on its own branch, and it is told so: status, diff, history and
its commits there, with a few plain options, run as its other commands do. Any other option, and git
that reaches your own repository - switching branches, stashing, reset, merge, push, config - is asked
at every level, Full auto too. In a project that runs in Docker the agent is told that git does not
work in its copy: the worktree points to a folder on this machine, not in the container.

Your repository's git hooks (pre-commit, commit-msg, post-commit, also those of a `core.hooksPath` such
as husky's) do not run for an agent's own git commands in its copy - a commit on its branch included -
nor for an MCP server's it starts there; nor does your `core.fsmonitor`, and its commits are not
signed. On a branch, a command that clears or sets git's own environment (`unset GIT_…`, `env -i`,
`$env:GIT_… =`) would bring them back: it is asked at every level, Full auto too.

Those settings reach whatever the agent runs in its copy, your project's tests too: a test that needs
your git hooks or signed commits does not get them there.

A secret you gave in this turn (see [Security model](../security/model.md#secrets)) never leaves on a
branch:

- If a file on a finished branch holds it, the card does not merge it or open a pull request, at any
  level, even on your click. Take the secret off the branch, or press **Discard**, which deletes the
  branch.
- If the agent stopped first, or nobody watched the turn, a branch that holds it is deleted whole and
  the Orchestrator is told (on a **Stop**, the chat says so too). For a branch opened again from an
  earlier turn, the work of those turns goes with it.
- **Keep this branch after merging** is refused when any of its commits holds it.

### When an agent stops

An agent on a branch that stops before it finishes leaves its work committed on the branch. That holds
also when you press **Stop** or **Stop everything** while it works; the chat says so. A **Stop** while
KOLONİ merges a finished branch by itself (at Full auto) waits for git to finish: the merge is on its
card, and the branch's worktree goes.

Told to go on (by the Orchestrator, in this turn or a later one you watch), it goes on on the same
branch: its earlier commits are there, and new work goes on top. Its merge is still held to where the
branch was first made from: if the project is on another branch now, or that commit is gone from it, the
merge waits for you, at Full auto too. Its work is still measured from your folder as the branch began.

A branch copy kept over a restart comes back as a kept card, like a plain copy's: a file you changed too
is merged line by line, from what the branch was made of. **Discard** deletes its branch and git's
record of its worktree; so does a **Take in** that took all of it, unless the agent may still go on
on that branch.

Sometimes it cannot go on on its branch. Then it works in a fresh copy of the project instead:

- The branch was merged or sent as a pull request already: it and the Orchestrator are told why.
- Git refuses the branch (it was deleted, another branch has its name now, or it is checked out
  somewhere else): they are told why too.
- You pressed **Discard**, which deleted the branch: no message.
- The branch was made by an older KOLONİ that did not record where it started: no message.

An agent in a plain working copy that stops unfinished keeps what it changed: by itself (it failed, or
hit its [step limit](../agents/step-limits.md)), and on **Stop** or **Stop everything** too, also when
its Take in card was already waiting for you. A card under
**Ready to take in** offers **Take in** or **Discard**; nothing of it reaches your folder before that,
at Full auto too. An agent told to go on gets that copy back. A copy with no changes is removed. A
team's recipe and a job while you're away keep their copy on a Stop as well.

The git button in the top bar ("⑂ main · 4 changed") opens **Where the work is**. It reads git and changes
nothing but the branch you switch to. It has three parts, each saying in words how a piece of work stands:

- **Your branch**: what is not saved in git yet (**See changes**), the last commit, and **+ New branch**.
  While a turn works or files are not committed, it says why you can't switch.
- **Agents' copies · this chat**: "working" (**See changes**), "finished, waits for you" (**Take in…**),
  or "kept" (**Look**).
- **Other branches**: "not joined" or "joined ✓", how many commits ahead and behind, with **Look** and
  **Switch to**. What an agent said it made, but git does not show, is listed last.

While a branch is open in the Workspace (**Look**), it shows read only, against your branch, with **Back
to the project**.

### Starting from a GitHub issue

On the [Chats](chats.md) page, **From a GitHub issue…** (beside **New chat**) starts a chat in the open
chat's folder from an issue. Paste the issue's address, or its `#number` in the project's repository, or
pick one of the repository's open issues from the list. KOLONİ opens a new chat, attaches the issue's
title, text and comments as a file (`github-issue-12.md`), and writes a short first message. Nothing
runs until you press **Send**. Long issues are cut at about 20,000 characters.

Anyone can write an issue, so KOLONİ marks its text as data for the agents, never as your instructions.
See [Outside content](../security/model.md#outside-content) for what that does and does not stop.

KOLONİ reads GitHub with your own **gh** (GitHub's CLI) and never stores or sees a token. Install gh
from <https://cli.github.com> and sign in once with `gh auth login`. Until you do, the dialog says why
no issues are listed. The project folder must be a git repository. Listing issues, or picking one by
`#number`, also needs its git remote to be on GitHub; an issue's address works without that.

## Committing

With **Save each sub-agent's work as a git commit** on (Settings › This project › Checks and git), the card offers a
commit once the changes are in: one commit per piece of work, only where the folder is the top of a git
repository. It is always your click, and nothing is pushed.
