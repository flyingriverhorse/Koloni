# To-do

The To-do page holds a project's tasks, in your order: a **goal** holds **stories**, a story holds the
**tasks** and **bugs** that go on together (see [Goals and stories](#goals-and-stories)). "Each task runs
in its own chat; you decide when it is done." Open **To-do** on the left rail.

Its bar has the filters **All**, **Todo**, **Running** and **Done**, **+ Task** (to the line where a task
is added), **Write it with the Hive keeper** and **☾ Away**. **☾ Away** opens the Away panel of the chat
you have open, when it is a chat of this project that has had a turn (see
[Work while you're away](overnight.md)).

## Adding tasks

Type in **Add a task — title, then Enter**. Once there is a title you can also set its **Priority**
(high, normal, low), a **Detail**, **Done when (optional)**, its **Story** (none, one of the project's,
or **New story…**, named there) and its **Type** (task or bug), then press **Add task**.

A rough note can become a goal, its stories and their tasks. Press **Write it with the Hive keeper** on
the bar - the role that keeps the To-do list - type the note in **Your note**, for example "the login page
is broken on mobile, and we need a password reset", and press **Write it**. A model writes it the way
that role would: tasks that go on together as a story, a goal over the stories when the note asks for
several, and each task with a title, detail, done when, priority and whether it is a task or a bug. A
story may come with a few notes for its notebook. A small note stays a single story or a single task;
at most 4 stories and 12 tasks in all. It is asked once, with no tools, as **Or write it** asks (see
[Recipes](../agents/recipes.md)) - your fast models first, then the other tiers', then the
Orchestrator's model in the chat you are in, then your newest chat's. One that does not answer passes it
on in the same press; with none answering, the message names each one asked and why, and how to fix it.
The line under the buttons says which model is asked first and whether the request costs money.

The draft appears under the box for you to change: the goal, each story's title and tasks, and the
tasks that stand alone. A story's **Add** adds that story, under the goal; **✕** drops a task; **Add
all** adds the rest. The tasks are yours and to do, as if you had typed them. Nothing is saved until you
add it. **Plan it in a chat** works the other way: it opens a chat in the project whose first message
asks for the Hive keeper. The Hive keeper reads the project and proposes tasks, which wait for you like
any agent's. Esc closes the note box.

![The To-do page: a rough note in the Hive keeper's box, and under it the goal, stories and tasks the model wrote from it, each story with Add and each task with a cross to drop it](../images/todo-draft.png)

*A rough note written as a goal, two stories and three tasks by **Write it with the Hive keeper**;
nothing is saved until you add it.*

Agents with the To-do tools (the Hive keeper and the Scout) can propose tasks and
changes. A task an agent proposes may name its story: one of the project's open stories by its title,
or a new one (with a goal) that shows on the list once you add one of its tasks. Its card says where
adding it puts it - *In story “Login” (new) · goal “Auth” · bug*, "(new)" where the agent's proposal
opened the story or goal. Once you add one of its tasks, the story and its goal are yours: they stay
though their tasks go. A story an agent opened goes when you reject all its tasks. They wait for you
under **Waiting for you**:

| What waits | Buttons |
|---|---|
| A new task an agent proposed | **Add** / **Edit** / **Reject** |
| A task an agent thinks is done ("done?") | **Done** / **Not yet** |
| A change an agent proposed | **Change** / **Reject** |

When several new tasks wait, **Approve all** adds them all. **Edit** opens the task's title and detail;
change them, then press **Add**.

## Follow-up tasks

After a turn in one of the project's chats, the **Scout** - the role that looks for what is left
after each turn - suggests what to do next. It looks at
the turn's record: work left undone or for later, a TODO, a step that failed. It proposes at most
three tasks, each with the words they came from ("Proposed by the Scout, from: ..."). Those
words must be an agent's in that turn, or the first line of a step that failed, not your message.
Backticks, `*` and `_` are ignored, and curly quotes count as straight ones, so `` `CHANGELOG.md` ``
still matches CHANGELOG.md. A suggestion without
such words is dropped. So is one that looks like a task already on the list, or one you rejected
before. Each one dropped is written, with why, to `runtime/logs/koloni.log`, and shows in the
Inspector of its canvas box (below). The
suggestions wait under **Waiting for you** like any agent's. An added task starts when you press **Run
the backlog**, or by itself where the To-do list runs by itself. A suggestion whose words look like
they try to give the agent orders says so on its row.

It is one small model request, with no tools, after each turn that did something: changed a file, ran
a command, handed work to a sub-agent or had a step fail. A turn that only answered asks nothing. It
is made once the turn is over, so your next message does not wait for it. It goes to the first model
of the fast tier, or of the tier you chose. It skips a provider that is down, at its limit, out of its
plan, or whose pay-per-token use you refused in that turn. With no such model nothing is suggested.
The model is sent what was said in the turn, the files it changed, the steps that failed and the open
tasks' titles. The secrets KOLONİ knows, and the variables the project passes to its commands, are
masked. Jobs while you're away and triggers get suggestions too; rooms, discussions and To-do tasks' own turns get
none. Nothing is asked while the project is over its monthly budget.

Each request shows on the canvas as a **Scout** box under the turn, on a dashed line down from
the Orchestrator: the model, "2 proposed · 1 dropped" (at Full auto also "Orchestrator added 1"), its
tokens ("–" where not reported), and **To-do →**. Click it to see why each suggestion was dropped; a
double click, or **To-do →**, opens this page. A request that failed or timed out says "Sent, not heard
out". A turn where it was not asked has no such box.

At **Full auto**, in a turn you started, you are not asked. The Orchestrator's model decides each
suggestion, add or reject, with one more request, and says why in one sentence. You see its word under
**Decided for you** in the chat. **OK** keeps it; **Change** undoes it while the task is still todo. A
task it added does not start, by **Run the backlog** or by itself, until you press **OK**, there or
under **Waiting for you** on the To-do page. One it rejected stays on the To-do page, folded under
**Rejected by the Orchestrator**, with **Add**. It is not
asked when the provider has no room left on its plan, or when the To-do list runs by itself. Nor is
it asked when the Orchestrator runs on a CLI and the project does not let it answer while you're away.
It never adds a suggestion whose words look like orders. Suggestions from jobs while you're away and from
triggers always wait for you.

Turn it off, or choose the tier, in [Settings › This project › Agents](../settings.md#agents).

## Goals and stories

**Your tasks** is a tree. A **goal** comes first, with a honey line on its left, how many of its stories
are done ("1 / 2 stories") and a bar of it. Under it are its **stories**, and under each story its tasks.
Stories of no goal come after the goals; the tasks of no story are last, under **Without a story**. A
plain list with no story has no such heading.

- A **story** is tasks and bugs that go on together. Its state comes from its tasks: **○ todo** (none
  started), **● running** (one at work, with the chat it runs in: *in “Auth work”*), **⚠ stuck** (one
  stuck), **done?** (every task done, or waiting at "done?" for your word) and **✓ done**. A story is
  done only when you close it: **⋯ → Close the story**, once each of its tasks is done; **Open it again**
  undoes it. **📓 N notes** opens its notebook:
  what was decided, the files touched, the results and the questions left, as the Hive keeper wrote
  them - read as notes, never as orders.
- A **task** is work to do; a **bug** is something that works wrong, its tag in rose. **⋯ → Edit** sets
  a task's **Story** and **Type**; **None** takes it out of its story. Dragging moves a task within its
  story only.
- A story's **⋯** has **Rename**, **Goal** (none, one of the project's, or **New goal…**) and **Delete**.
  A goal's **⋯** has **Rename** and **Delete**. Deleting a goal or a story keeps what was under it: its
  stories lose their goal, its tasks their story.
- A story's name is one in its project, whatever its case: agents name a story by it, so "Login" and
  "LOGIN" would leave which one they mean to chance. A name another story has, open or closed, is
  refused; an agent naming a closed story is told so.

The filters on the bar show **All**, what is **Todo** (to do, or stuck), what is **Running** (at work, or
done? and waiting for your word - a story at done? too) or what is **Done** (a story only once you closed
it). A story whose tasks are all filtered out still shows when its own state fits.

![The To-do page as a tree: a goal with its stories done of all, a running story with its notebook and chat, a bug in rose, and the tasks without a story](../images/todo-tree.png)

*A goal, its stories and their tasks and bugs; the tasks of no story last.*

## Your tasks

Within a story, tasks are listed by priority, then in your order. Drag a task, or use **⋯** → move up /
move down. The **⋯** menu also has **Edit**, **Waits for** ("it starts once these are done") and
**Delete**.

A task's state shows as a tag, such as queued, running, "needs you", "needs you · Take in", stuck, or
done.

## Running tasks

**Run the backlog** starts the next tasks. **Runs by itself** keeps starting them, one after another.
Each task runs in a new chat, with the task as its first message. At most two run at once.

"A task not finished gets one fix round; still not, it is stuck and the next goes on." When an agent
thinks a task is done, it waits as "done?" for your word.

A task's turn works as long as it makes progress. Once nothing has moved for Settings › The app ›
**Stuck after this many minutes with no progress** (30 unless you change it) - no file of the turn
changed, no agent finished its work, no failing command passed - it stops, its work kept, and counts
as not finished: its fix round comes, then it is stuck and the next task goes on. The same happens,
as a last resort, after **An unattended turn runs at most (hours)** (8 unless you change it; empty:
no limit). Its Orchestrator also stops if it goes round in circles: see
[Step limits](../agents/step-limits.md#when-the-orchestrator-goes-round-in-circles).

Nothing starts while one of your own turns is at work, while everything is paused, while you're away (the
tasks you ticked for ☾ Away are worked through then, until you are back), or over the project's monthly budget.

### Run settings

**Run settings** sets the level of the task chats (**Ask before changes**, **Auto-edit files** or **Full
auto**), **Who changes the files**, and the **Provider** and **Model name**.

Task chats follow some extra rules: a CLI that works with its own tools does not run them; commands that
delete, overwrite or send something off the machine, or that hand a command to a shell, ask at every
level. The Orchestrator answers for you in them as in any chat of the project, once a card has waited
the minutes of **When you're away** ([Answering for you](answering-for-you.md)). A task worked through
while you're away runs at the lower of this level and the level of the chat you went away from.
