# Work while you're away (☾ Away)

Before you leave - for an hour, an afternoon or the night - press **☾ Away** on a chat's status
line, or tell the Orchestrator you are going. The chat finishes its turn, then the
[To-do](todo.md) tasks you tick are worked through, one at a time, each in its own copy of the
project: your project does not change while you are gone. When you are back you decide what comes
in.

[![Work while you're away and triggers: the To-do tasks Away works through one at a time in their own copies, and the report](../diagrams/night.svg)](../diagrams/night.svg)

*Work while you're away (below) and triggers (above): work that runs while nobody watches.*

## Going away

**☾ Away** is on the line over the message box of a chat with a folder (not in a plain chat; in a
chat with no turn yet it waits: "Write to the Orchestrator first: Away finishes this chat's turn").
It opens the Away panel:

- "The Orchestrator finishes this chat, then works through To-do in order."
- **Then from To-do, in this order**: the project's open tasks (proposed or to do). The tasks
  proposed in this chat are ticked already ("new · from this chat"); older ones are not ("on To-do
  since Mon"). Tick up to 10; **Move up** and **Move down** change the order, which is saved to
  To-do. A ticked proposed task counts as your OK.
- **Decides for you** and **Always waits for you**: see [Questions and approvals](#questions-and-approvals).
- **Until**, **spend at most** and **kept out**: none unless you set one. If the project has a
  monthly budget, the work spends at most what is left of it. Name a file or folder of the project
  to keep out (up to 20): a pattern such as `src/*` or a place outside the project is refused.
- **Go away**, or **Cancel**. **How it works** says the rest.

Go away is refused while **Stop everything** holds (press **Resume** first), while a To-do task is
at work, and from a chat with no turn.

### From the chat

Tell the Orchestrator you are going away (to sleep, out, in any language) and what it should work on
meanwhile. It does none of that work itself: it puts each piece on To-do and offers one line under
its answer - "☾ Go away now? Until 08:00 · at most 2.00 USD" with **Go away** and **Change** (the
panel, there). The limits are only those it heard from you. Nothing starts before your Go away. Only
the Orchestrator offers this, in a turn you started in a chat with a folder - not in a **Plan first**
turn, nor while the project is away. A newer offer takes the place of one not answered yet.

### While you're away

The status line says where it stands: "Away · To-do 1 of 2: Add a bye line · 3 decided for you · 1
waits", then "To-do 2 of 2 looked at". The chip becomes **I'm back**, and the message box says
"Write to come back…". Away lasts until you are back: press **I'm back**, or write a message in any
chat of the project. Once every task was looked at, you get one notification if you set them up.

## How the jobs run

Tasks run one at a time, in the panel's order, once the chat you went away from has finished its
turn (a turn that waits for your word does not hold them back). A task added meanwhile does not join.
Each starts in a new chat named after it, its first message the task and what makes it done, and
works in a copy of the project of its own.

- **Level and model:** the job's chat has the model of the chat you went away from, and the lower of
  that chat's permission level and the To-do page's (the Away panel says which). Its other settings are the project's, as in any chat:
  who changes the files, opening sub-agents, and the rest.
- **Team and recipe:** where you picked the teams in that chat (**Manual**), the job's chat has
  them, with their recipes.
- **The copy** leaves out `.git/`, `build/`, `dist/` and caches, and shares `node_modules/`, `.venv/`
  and `venv/` with the project. A job that needs what is not in the copy changes nothing and waits for
  you, its report ending "Needs the project itself: …".
- **A job that fails** is tried once more in its chat. Failed twice, it could not be done, and the next
  one goes on.
- **A job that waits for your word** waits, and the next one goes on.

The top bar shows "☾ Away · To-do 2 of 4" with **I'm back** and **Stop all**, and "· until 07:00"
after it when you set a stop time. The To-do page shows the jobs too: since when, what they spent against the limit,
and each job as it stands, with what its agents are doing right now. A job's chat says at the top when
its jobs started, with a link back to their report.

### Stricter rules while you're away

- **Commands** follow the job chat's level. Below **Full auto**, a command no rule covers waits for you,
  and the job with it. At every level these wait too: a command that deletes, overwrites or sends
  something off the machine; one that hands a command to a shell or another program; and one that
  installs into the project's shared dependency folders.
- **Ordinary file changes** in the job's copy never ask: they are kept for your Take in. Files that
  steer agents, secret files and places outside the project wait for you as in a watched turn, and the
  job with them.
- **Kept-out places:** a write to one, or a command that names one, is refused, and the try is on the
  report.
- **No MCP server tools** are used.
- **CLIs:** a CLI working with its own tools that is not started in the job's copy, or not held to
  it (Copilot working Native, agy when it may write), cannot work on a job: "… cannot work on a job
  while you're away".
- At **Full auto**, with **Check what I said first** on, a command that deletes is first checked
  against your own words - your preferences, the project's saved rules and your messages in the chat
  you went away from, never the task's words - and runs in the job's copy without a card where a line
  of yours names it. Only a delete: a line that also sends work off the machine or touches a git
  remote, and a delete of a file that steers agents (`AGENTS.md`, `CLAUDE.md`), keep their card. See
  [Permissions](../use/permissions.md).

## Questions and approvals

What needs your word waits for you, and the job waits with it. The next job goes on meanwhile.

While you're away the Orchestrator decides at once, in the chat you went away from and in the
tasks' chats, what it may decide for you (another chat of the project keeps its own minutes): an agent's question, a recipe's "Ask me", opening a sub-agent on its role's own model,
and going on or stopping at a step limit. The cards already waiting when you press Go away are decided
then. Its own questions to you wait for your return. It does not answer once the project is over its
monthly budget or a provider is over its limit. Everything else always waits: commands and changes
that ask, the web, secrets, folders, another model that may cost money, new roles and skills, Take in,
Discard, Commit. See [Answering for you](answering-for-you.md).

A job that waits is shown under **Waits for your word**, on the report and in **Ready for you**.

## Step limits while away

Nobody is there to answer a Continue / Stop here card in a job, so none comes (in the chat you went
away from, the Orchestrator decides that card at once):

- A sub-agent that reaches its step limit stops. The job's Orchestrator is told its part is not done,
  and may tell it once to go on, with a new step limit.
- One that stopped at its role's own limit, or stops again, ends. The job's Orchestrator hands what is
  left to another agent, or says in its report what is left undone. The job can still count as done:
  read its chat.
- The job's Orchestrator counts no steps. If it goes round in circles (the same call failing the same
  way 5 times, or 10 calls in a row bringing nothing new), the job fails with that reason, is tried once
  more in its chat, and the night goes on with the next job.

See [Step limits](../agents/step-limits.md).

## What stops the jobs

Away ends when:

- you are back: **I'm back**, or a message of yours (the job at work finishes; its cards then wait for
  you);
- the stop time comes, if you set one ("Stopped at 07:00, the time you set.");
- it has spent its money - what the tasks' chats and the chat you went away from spent since Go away
  ("Stopped at 5.02 of 5.00 USD, the spend limit."); the chat's turn at work is stopped too;
- the project is over its monthly budget, or the Orchestrator's provider is over its limit, when the
  next job is about to start;
- you press **Stop all** ("Stopped by you.");
- KOLONİ is closed ("Stopped: KOLONİ was closed while you were away.");
- the next job cannot start.

The time and the money are checked before each model step. A clock also watches the stop time and
each job's hours at most, so a long command is cut at them too. Its minutes with nothing moving
do not run out while a command or a model step of it is under way, an agent below the Orchestrator
is at work, or it waits for your word: those have limits of their own. When the jobs stop, the job at work stops, its
work kept in its copy, and is shown as **Stopped**. A job that waits for your word goes on waiting -
but **Stop all** stops it too.
When KOLONİ is closed, the jobs at work and those that wait count as could not be done: answer what
waits before you close KOLONİ.

**Stop everything** in the top bar holds the jobs instead of ending them: the job at work and a job
that waits for your word are stopped, the next job waits for **Resume**, and the time and money you
set still end them.

A trigger's budget plays no part here: these jobs are not trigger turns.

If you set up [notifications](../settings.md#notifications), you get one when every task was looked
at, and one when a limit or Stop all ends Away - none when you come back yourself.

## When you're back

The chat you went away from has one summary: "While you were away (23:10 – 07:42): 2 of 2 To-do
done · 3 decided for you · 1 waits · 0.84 USD", what was done (waiting in Ready to take in), what was
decided for you, what waits (with **Allow and go on** / **Refuse**), **Review and take in** and **On the
canvas**. KOLONİ opens on the report on the canvas until you have seen it.

The report shows when the jobs ran, what they spent and why they ended; nothing of it is in your
project before you take it in. Its sections are **Done**, **Waits for your word**, **Could not be
done**, **Stopped**, **Not started**, **Decided for you**, **Proposed while you were away, not started**
(with **Add to To-do** or **Dismiss**) and **Kept out, as you asked** (what tried to change those
places, refused).

Each job row says what its reviews found, and warns where its copy changed a place you kept out, or a
file another job changed too. A job that changed nothing is "Done, nothing changed". For each job:

- **Allow and go on** or **Refuse**, when it waits for a command, a change, a web request or an agent
  to open. A question, a folder or a secret is answered in its chat: **Open its chat**. The job then
  goes on in its copy.
- **Take in** brings its work into the project; **Take in all** takes in every done job's work. Where
  two jobs changed one file, the two are joined line by line where their lines do not clash. A
  clashing line is not taken: the card of the job's kept copy, in its chat, decides it.
- **Try again**, for a job that could not be done or was stopped, once you are back. It runs in
  the job's chat as an ordinary turn, not in a copy: its changes go into the project as that chat's
  level says.
- **See the changes** or **Open its chat**.

The To-do page shows the same jobs, open by itself while a job needs a decision of yours.

See [A job while you're away](../examples/overnight-job.md) for the steps from going away to taking
the work in.
