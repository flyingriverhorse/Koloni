# Chats

**Chats** on the left rail opens the list of your chats: each chat with how it stands, and on the
right **Now**, what is at work and what waits for your word in every folder.

![The Chats page: under the project folder, three chats - "Run the tests" with a honey-rimmed cell and "Waits for your word · Command", "Review the greeting" with a green cell and "Done · 2 agents · Local · fake-qwen · 312 tokens", "Ideas for the logo" with an empty cell and "No turn yet"; on the right Now, its cells, "Nothing at work; 1 thing waits for your word. Today 8 done.", Go to Ready, and what the cells mean](../images/chats.png)

## The list

Chats are grouped by folder, the open chat's folder first; chats with no folder are under **No
folder**. Each folder says how many chats it holds; click its name to fold it. Inside a folder, chats
sit under **Today**, **Last 7 days** and **Older**, or are listed by name. A chat that waits for your
word comes first in its group. Archived chats are listed last, under **Archived**.

- **Search by name** finds chats by their title.
- **Show** keeps **All states**, **Failed or stopped**, or **Done**.
- **Sort by**: **Last activity** or **Name**.
- A chat that came from the To-do list has a mark, and its task's state beside it when the chat's
  own line does not say it already; one with kept work says "changes kept".

**Refresh conversations** (the round arrow beside the heading) reads the list again. The list also refreshes by itself
when you come back to the page or the window, and every 30 seconds while the page is in view.

## How each chat stands

Each row starts with a [cell](ready.md#the-cells) - the same hexagon as on Ready for you, with the
same meanings - and has one line under the chat's name:

| Cell | The line says |
|---|---|
| Honey rim, lightly filled | **Waits for your word**, and what: a command, a question, a file change, a plan… |
| Honey, full | who is at work and how ("Orchestrator working, Coder waiting for a file"), and the branch they work on |
| Red-orange, full | **Stuck**: its last turn failed or was interrupted, or its To-do task is blocked |
| Green, full | **Done**, and what its last turn ran with: its agents, model and tokens |
| Empty | **Stopped**, or **No turn yet** |

What waits for your word in a chat is what [Ready for you](ready.md) lists for it, and **Show** goes by
the same. A chat Ready for you has not read yet - or could not read - says what KOLONİ's list of the project's
chats says, **Waits for your word** with nothing after it, until it is read or that chat's state changes. A chat whose
state is not read at all has no cell and no line: the page says nothing it does not know.

## Now

**Now** stands beside the list, over every folder:

- a cell for each chat at work (one that waits for your word too, while another of its agents works),
  each thing that waits for your word, and each chat whose last turn ended today stuck or done; hover a
  cell, or let a screen reader say it, for its chat and its state;
- one sentence that counts them - "2 chats at work; 2 things wait for your word. Today 1 stuck." The
  number that waits is the top bar's pill's;
- **Go to Ready**, where what waits is answered;
- what the cells mean.

On a narrow window Now goes under the list.

## Starting a chat

- **New chat** starts a chat in the open chat's folder.
- **From a GitHub issue…** starts a chat from an issue, with the issue attached. See
  [Starting from a GitHub issue](workspace.md#starting-from-a-github-issue).

## Archiving and deleting

**Archive** puts a chat away; **Unarchive** brings it back. Tick chats, or **Select all**, then
**Archive selected**. Only archived chats can be deleted: **Delete selected** asks first, and "This
cannot be undone in KOLONİ."
