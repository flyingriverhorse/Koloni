# Quick start

From install to your first approved change, in five steps.

## 1. Install and start

Follow [Install](install.md) for your system. When KOLONİ starts, its window prints one line:

```
KOLONİ is open at http://127.0.0.1:8790/#key=…
```

Started from a terminal, KOLONİ also opens this page in your browser. If it does not, open the link
from the window. Keep the window open while you use KOLONİ; Ctrl+C in it stops KOLONİ.

On first open, the canvas shows **First steps**: a provider, a folder, and your first message.
The step you are on has a button that takes you where you do it.

## 2. Add a model

Press **Add a provider** (in First steps, or on the **Models** page). Fill in:

- **Name**: any name you like.
- **Kind**: **OpenAI-compatible server**, **Anthropic API**, or a CLI: **Claude Code (CLI)**,
  **Codex (CLI)** or **GitHub Copilot CLI** (**agy (CLI)** under Experimental, once you [show it](../models/setup-cli.md#experimental-clis)).
- For a server: its **Address** (a llama.cpp server is usually `http://127.0.0.1:8080/v1`) and an
  **API key** if it needs one.
- For the Anthropic API: your **API key** and a **Default model**.
- For a CLI: nothing more, as long as the CLI is installed and you signed in to it in your own
  terminal. KOLONİ never signs in for you. If the CLI is missing or not signed in, its card shows the
  command to install it or sign in.

Press **Save**, then **Test** to check that it answers.

The first provider on the Models page is the default: new chats run on it. KOLONİ makes one called
"Local" at the first start, for a model server on this machine. If you do not run one, First steps
says that Local isn't answering. If the Models page holds another provider that is switched on,
First steps offers **Use … for new chats** with its name: press it to make that provider the
default. Or open the provider on the Models page and press **Make default**. KOLONİ never changes
the default by itself, and the step is done once the default answers.

If a CLI was installed when KOLONİ first started, you may find it on the Models page already.

## 3. Choose a folder

Press the folder button at the top left and choose **Open a folder…**. Pick the project your agents
should work in. To only talk, without files or commands, choose **No folder · a plain chat**.

## 4. Write your first message

Next to the message box, check the permission level. Keep **Ask before changes** for now:
commands that do more than read wait for you, and no change reaches your folder before you say so.
See [Permission levels](../use/permissions.md).

Write what you want done, for example "Add a README that explains how to run this project", and
send it.

The chat shows the Orchestrator's answer and a row for each agent it opened. The canvas draws the
turn: each agent as a box with its tools, commands and files.

## 5. Answer the cards

In a new project the Orchestrator plans, asks and checks, and hands every change to files to a
sub-agent (for code, a Coder). The sub-agent usually works in its own copy of the project, not in your
folder. So the first turn asks you on cards in the chat:

**Open this sub-agent?** shows the role, the model it runs on, its task and its tools. Press
**Open agent** to let it start, or **Reject**.

**Run this command?** comes when an agent wants to run a command:

- **Run once** runs it this time.
- **Always run …** runs it, and keeps a rule so the same kind of command runs without a card in
  this chat.
- **Reject** turns it down.

**Take in …'s work?** (with the sub-agent's name) comes when the sub-agent has finished. It lists
the files it changed; click a file to see its diff. Nothing is in your folder yet. Press **Take in**
to bring the changes into your project, or **Discard** to throw the copy away. See
[Working copies and Take in](../use/workspace.md).

If you let the Orchestrator change the files itself (Settings › This project › How agents work › **Who
changes the files**), or no copy can be made (a very large project), each change comes on a card
with its diff and **Approve** or **Reject** instead, and after it is written you can still
**Revert** it.

While something waits for you, the project's tab above the canvas turns orange, and **Ready** on the
rail counts it, so you can do something else meanwhile.

## Next

- [Permission levels](../use/permissions.md): what asks and what runs at each level.
- [Memory](../memory.md): what KOLONİ remembers between chats.
- [Settings](../settings.md): the app's and the project's settings.
