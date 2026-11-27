# Memory

Memory is what a project remembers between chats: your preferences, the project's rules and its
Project notes, facts you approved, and notes agents wrote while they worked. Open it with **Memory**
on the left rail. Each project has its own memory.

The Memory page has two parts, as two tabs near its top: **What the project knows** - this page - and
**Sources to look things up in**, the documents, files and repositories agents read
([Sources to look things up in](knowledge.md); until 0.1.10 the Knowledge page). Each tab says what waits
in it: "1 waits for your word" (a fact an agent put forward), "2 may be old" (a source whose guide may be
out of date).

Memory is one of the two places KOLONİ keeps notes. The other is a job's
[notebook](automation/todo.md#the-storys-notebook): what a To-do story's or task's turns, or a night's
job, note for the turns after them, for as long as the job runs. Memory is what stays true of the
project.

KOLONİ never shows a memory as surer than it is. A fact rests on lines of a file, and KOLONİ
checks those lines again each time it reads the fact.

[![Memory flow: notes, proposals, approved facts anchored on lines and checked again, and the three ways memory reaches an agent](diagrams/memory.svg)](diagrams/memory.svg)

*From a note to an approved fact, and how agents get it.*

## The page

![The Memory page: the search and the three ways on top, the two parts' tabs, a fact waiting for your word in the honey box beside the fact it would replace, the core's facts each with its cell and the journal's notes at the left, and your preferences, the project's rules and the Project notes at the right](images/memory.png)

*What the project knows: what waits for your word on top, what agents were told at the left, your own words at the right.*

From the top:

- **The search**: "Search everything this project remembers" ([Searching memory](#searching-memory)).
- **Three ways memory reaches an agent**, one line each: **Given at the start**, **Found when asked**
  and **Sources given to a role** ([below](#the-three-ways-memory-reaches-an-agent)).
- **The two parts' tabs**, each with what waits in it.
- **What waits for your word**: a honey box, only while an agent's proposal waits for you
  ([Who writes what](#who-writes-what)).
- At the left, **Facts** (the core) and **Notes** (the journal), and under them **History**, folded.
- At the right, **Your words**: your preferences, this project's rules and its Project notes, set apart
  from what agents wrote. Only you write them. Under them, which other projects' memory **Search deeper**
  and **Recall** also look in, with **Change** (Settings › This project › Memory and web).

### The cells

Each fact has a small hexagon, a cell, that says how it stands for agents. A word always says it too:
its name for a screen reader, the line above the facts and the words under the fact. A cell never says
a fact is right.

| Cell | What it means |
|---|---|
| Green, filled | Given when the work names its subject. |
| Red-orange, filled | Given to no agent until you look again: its source changed or moved. |
| Empty | Only found by looking it up: it has no subject, or one too general to match. |

Ten smaller cells beside **Facts** fill in honey as facts take the core's room, with the count beside
them ("1 240 / 4 000 characters").

## The kinds of memory

| Kind | Who writes it | Where you see it |
|---|---|---|
| **Your preferences** | You. One text, used in every project. | **Your words**, at the right |
| **This project's rules** | You. Kept in the folder's `.koloni/rules.md`, so they go into git with the project. | **Your words** |
| **Project notes** | You, ticking lines on the **Add to Project notes?** card at the end of a turn. | **Your words**, under the rules |
| **Facts** (the core) | You, or an agent's proposal that you approved. | **Facts**, at the left |
| **Notes** (the journal) | Agents, while they work, and KOLONİ's own note-taker if you switch it on. | **Notes**, under the facts |

A fact has a subject (a few words, such as `test command`) and usually a source: a file and a
range of lines. The core holds at most 4 000 characters of facts; **Facts** shows how much is used.

The rules you save here are also written to the folder's `.koloni/rules.md`. When that file says
something else (a `git pull` or a script changed it), **Your words** say so - "The folder's
rules.md differs from what you saved here; Full auto's check goes by what you saved." - and shows the
folder's text, with **Use the folder's rules here** to take it into the box. Full auto's
[Check what I said first](use/permissions.md#check-what-i-said-first) reads the rules saved here.

KOLONİ may also suggest a preference. It shows under **Your preferences** with a "suggested" tag
and the buttons **Add** and **Reject**.

### Project notes

At the end of a turn, KOLONİ may ask **Add to Project notes?** It lists findings that were fixed and
changes to the project's `docs/`, at most 8, in the words of the agent or the file. Tick the ones to keep
and press **Add**, or **Not now**. The card never holds the turn: answer it whenever you like.

Each line you add goes into the **Project notes** box under **This project's rules**, in **Your words**,
as `- <line>`. The Orchestrator is given them every turn, each line in quotes, as notes written from the
agents' work: they are not your instructions. They are not written to `.koloni/rules.md`, and Full auto's
check of your words does not read them. Correct a line or take it out in the box, then press **Save
Project notes**. They hold at most 4 000 characters; past that, **Add** asks you to take some lines out
first, and the card waits.

Before 0.1.10 the Project notes were a topic of [Knowledge](knowledge.md). At the upgrade their lines
were copied here ([Upgrade notes](reference/upgrade-notes.md#0110)).

## The three ways memory reaches an agent

The strip at the top of the page says them, one line each:

1. **Given at the start**: your preferences and rules, to every agent; the Project notes, to the
   Orchestrator; a fact, when the work names its subject.
   - **Your words** are "Said to every agent, always": your preferences and the project's rules are put
     in every agent's briefing. The Orchestrator is also given the [Project notes](#project-notes), every
     turn.
   - **Facts** are "Given to an agent when its work names the subject." When every word of a fact's
     subject appears in the agent's task, the fact is given to it. The agent is also told how many other
     facts exist, so it can look them up. A fact whose subject is too general to match is only found by
     looking it up: its cell is empty.
2. **Found when asked**: an agent's **Recall** tool ("look in memory") finds notes and facts, earlier
   messages and linked projects' memory. **Notes** are "Found only when an agent looks": they are never
   given by themselves.
3. **Sources given to a role**: only a role you give a source looks in it - docs, repositories, folders
   ([Sources to look things up in](knowledge.md)).

**History**, folded under the notes, shows decisions and what was removed.

While an agent works, KOLONİ keeps checking what it was given. If a fact it was given changes or
is removed during its work, the agent is told.

In an agent's window, under **Details** › **Every step as recorded**, you can see what that agent got:
**Given from memory** and **Looked up in memory**.

## Sources and evidence

Most facts and notes point to a file and its lines. KOLONİ keeps a fingerprint of those lines and
compares it each time memory is read. Next to each one you see what it found:

| What you see | What it means |
|---|---|
| **source unchanged since noted** | The lines read exactly as they did when the record was written. |
| **source moved since noted: check again** | The same lines are now somewhere else in the file. |
| **source changed since noted: check again** | The lines are different now, or gone. |
| **no source** | The record does not point to a file. |

"Source unchanged" only means the file lines read as they did. It does not mean the record is
right.

**A fact whose source changed or moved is given to no agent until you look at it again.** Open
it with **Look again**. You see the lines as they read now, and you can choose:

- **These are the same lines** (only when they moved): the fact now points to the new place.
- **Correct**: rewrite the fact.
- **Remove**: take it out of the core.

**Look at the sources again**, beside **Facts**, checks every source again.

A record written in a turn nobody watched (a trigger's turn, before 0.1.10) is tagged "written with nobody
watching".

## Who writes what

**Agents write notes.** An agent with the **Remember** tool ("note what it found") adds a note to
the journal. A few rules apply:

- A note about a file must name the lines, and the agent must have read those lines in this turn.
- Text that reads like an instruction is refused.
- A newer note on the same subject replaces the older one.

**KOLONİ notes a flaky test.** A test that failed in a full run and passed alone once is noted in
the journal as KOLONİ's, under "flaky test: `test`", with how many times it was seen so
([Not this turn's](use/checked.md#not-this-turns-flaky-tests-and-failures-from-before)).

**Agents propose facts; you approve them.** An agent can put a note forward for the core. Nothing
enters the core unless you approve it. Waiting proposals show at once in a honey box at the top of
the part, headed such as "1 fact waits for your word"; the part's tab says so too. For each one you
can choose **Approve**, **Edit and approve** (then **Approve as edited**) or **Reject**. If it would
replace a fact on the same subject, you see both side by side: **Would replace** and **Put forward**.
Once you decided the last one, the box says "Nothing waits for you." until you leave the page.

A proposal can be approved only while its source is unchanged, and not if the file was changed
in the same turn the note was written. A note on a subject the core already has a fact on waits
for you too; until you decide, no agent is given it and **Recall** does not find it.

**You write facts yourself.** Under the facts, **＋ Add a fact** asks for the fact, its
subject and, if you like, a file with its first and last line. **Add to the core** saves it. It
replaces any fact on the same subject. A fact's **⋯** menu has **Correct** and **Remove**. A note
has **Make it a fact** in sight, which opens **Add a fact** with its words and subject, and **Remove**
in its **⋯** menu.

**Your words on a card become a fact.** When you ask for changes on a card and say why, that text
is kept as a fact, shown as "said by you at a card, asking for changes".

**Preferences and rules are yours alone.** No agent writes them.

**Automatic notes** are off by default. Switch them on under Settings › This project › Memory and web ›
**Note what the work found, by itself**. After each message's work, a fast model writes at most
three notes of what it found. That is one more model request after every message, on your plan or
your bill. These notes go into the journal, signed as that model's. They never go into the core
by themselves and never replace an agent's note or a fact.

## Searching memory

One search box sits at the top of the page: "Search everything this project remembers".

- **Typing** filters what is on the page, grouped by where it is: **Waiting for your word**, **In Your
  words**, **In Facts**, **In Notes** and **In History**. Every word must match. A hit goes to its row,
  whatever the filters say, and unfolds **History** for one of its rows.
- **Search deeper** (or Enter) runs the same search an agent's **Recall** does in memory (an
  agent's also looks in its role's [sources](knowledge.md#how-agents-look-things-up)). It looks in the
  project's memory, in earlier messages, and in the memory of linked projects. Results are grouped
  under "In earlier messages" and "In linked projects".

![The Memory page after Search deeper for zeppelin: two earlier messages found, one by the Orchestrator and one by you](images/memory-search.png)

***Search deeper** finds the word in earlier messages, with who said it and when.*

Earlier messages means your messages, the Orchestrator's last answers, sub-agents' reports and
closed To-do tasks. Tool output is not searched.

You can also start a deep search from Ctrl+K with **Search in messages**.

**Memory of other projects.** Under Settings › This project › Memory and web › **Also look in the memory of**,
tick other projects. Their records are found by **Search deeper** and **Recall**, but never given
to an agent at its start.

## Topics

Memory is what a project keeps from one chat to the next. Inside a chat, what an agent remembers of
the turns before is its **topic**: the turns that go on with one piece of work.

- A chat's first message starts its first topic, named after the message's first line. Each message
  after it goes on with the topic you were last in. Rename a topic from **Recent** (top bar): the list
  names the topic on screen, with a pencil.
- **New topic**, under the message box, makes your next message start a new one; press it again to go
  on instead. Its tooltip says which topic the next message goes on with. In the chat a line marks
  where the topic changes: "New topic: …", or "Continuing: …" back in one seen before.
- A trigger's turns (triggers were removed in 0.1.10) are a topic of their own. A message you send while one of them is on screen still
  goes on with your own topic; **Write into … instead** sends it into the trigger's.

What each agent is given:

- **The Orchestrator** is sent its own topic's turns - your messages and the Orchestrators' answers -
  and of the chat's other topics only their names (the last 20), with the words "what was said and
  done in them is not shown to you".
- **A sub-agent** sees only its own work. Within a topic the Orchestrator can go on with an agent of
  an earlier turn - one it opened that finished by itself, or one stopped with its work kept on a
  branch of its own: an agent of the same name is opened again, and what the earlier ones did and said
  is its history. Never one of another topic.
- **Claude Code** run **Native** with **Sign-in: Its own for KOLONİ** goes on in its own CLI session
  from the topic's previous turn: it is sent only what is new, and compacts the session itself. A new
  topic starts a new session, and so does a turn run with another model, folder, permission level or
  setup.
- **GitHub Copilot CLI** run **Native** does the same: it goes on in its own session from the topic's
  previous turn, sent only what is new, and compacts the session itself, with a line on the agent's
  record when it does. Past a size, about 75,000 tokens by default, it is not gone on in, so that it
  stays below Copilot's dearer price step: the next turn starts anew from the history KOLONİ keeps.
  Its session is kept in a folder of its own under KOLONİ's runtime, removed when you start a new
  topic or go back to another one, when a turn starts a new session, and when its chat is deleted ([Data and privacy](security/privacy.md#where-your-data-is)). Where Copilot cannot go on in
  it, it starts a new session sent the whole topic, and its record says so once.
- **Codex** run **Native** with **Sign-in: Its own for KOLONİ** does the same with its own thread, kept
  in its provider's sign-in folder (never your `~/.codex`). Past about 124,500 tokens by default (75%
  of 166,000) it is not gone on in, so that KOLONİ's own summary comes before Codex's, which KOLONİ
  cannot read; when Codex compacted its thread itself, a line on the agent's record says so and the
  next turn starts anew too. On your own
  sign-in, the default, each Codex turn starts anew, as before. Going on in its thread is not yet tried
  with a real Codex ([Codex](models/setup-cli.md#codex)).
- On any other model the Orchestrator is sent the topic's history each turn, and KOLONİ summarises its older part
  past **Summarise a long context at (%)** of the window (75 by default; see
  [Going on from the last turn](models/setup-cli.md#going-on-from-the-last-turn)).
- **A To-do story** goes on in a topic of its own, so in one session; its next task starts a new topic of
  the story after a task of it ended badly, or a day later - told the story so far - never for a session's size.
  Every turn of the story is given its [notebook](automation/todo.md#the-storys-notebook), as data ([A story's session](automation/todo.md#a-storys-session)).
  The other topics' names come with how a story's or a To-do task's stands: (done), (done?) or (stuck).

[![Who remembers what: one chat's two topics with the line New topic draws between them, and where the turns before are kept - an API model sent the topic's history by KOLONİ, which compacts it; every other CLI started anew and sent it again; Claude Code, Native on its own sign-in, and Copilot, Native, resuming their session from the topic's last turn; Codex, Native on its own sign-in, does too; and a To-do story's tasks going on in a topic of its own, a new topic of the story after a task that ended badly or a day later, its notebook given at every turn](diagrams/topics.svg)](diagrams/topics.svg)

*Who remembers what, by topic and by kind of model - and a To-do story in its own topic.*

**When to press New topic**: when the next message is about other work. The Orchestrator then starts
with a short history - cheaper, and nothing of the other work leads it astray - and Claude Code,
Copilot or Codex with a new session. Keep going in the topic when the message builds on what was just done: the Orchestrator
sees that work, and can go on with the agents that did it.

## Sources to look things up in

The page's second part, its second tab, holds the knowledge: expert topics learned from web pages, project files,
a repository or a folder. Roles use them while they work, and an agent's **Recall** looks in a
role's own ([Sources to look things up in](knowledge.md)). What the project knows is short facts and
notes, each checked against its source; a source is longer material an expert reads.

## History and Export

**History**, folded under the notes with how many it holds beside it, says "Decisions and what was
removed. Nothing is deleted."

- **Recent decisions** lists the latest decisions, such as "Approved into the core", "Corrected",
  "Rejected" or "Removed".
- **Removed / replaced** lists what was removed or replaced. Any of these can be brought back with
  **Take back**.

Correcting a fact keeps the old one as replaced. Removing or rejecting never deletes a record.

**Export**, beside **Facts**, downloads the core as `MEMORY.md`: each fact with its subject,
who wrote it and when, and its source with its status now. Only facts are exported, not notes. The
file is a copy to read; editing it does not change the memory.

To take everything KOLONİ keeps, memory included, use **Export everything** under
Settings › The app › Your data. See [Settings](settings.md).

## FAQ

**Why didn't an agent use a fact I approved?**
A fact is given only when the agent's task names every word of its subject, and only while its
source is unchanged. Check the fact's cell and its line under **Facts**. The agent can still find it
with **Recall**.

**A fact says "source changed". Is it wrong now?**
Not necessarily. Its lines changed, so KOLONİ stopped giving it to agents until you look. Open
**Look again** and correct, confirm or remove it.

**Can an agent change the core without me?**
No. Agents write notes and proposals. Only your approval, or your own words, put a fact in the
core.

**How do I make agents always follow something?**
Write it in **This project's rules** (for this project) or **Your preferences** (for every
project). Both are told to every agent.

**Does memory leave my machine?**
Memory is given to the models your agents run on, as part of their work. Searching it sends nothing:
it matches words on this machine.

**Can I delete a memory for good?**
Not from the page. Removing hides it from agents and keeps it in History, where you can take it
back.
