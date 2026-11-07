# Troubleshooting and FAQ

The messages below are the ones KOLONİ shows, word for word. Text in `{braces}` is filled in by
KOLONİ.

## Starting and opening

**"Open KOLONİ from the link in its window"** ("Each start of KOLONİ makes a new link.")
: You opened an old tab or a bookmark after KOLONİ restarted. Each start makes a new page key. Copy
  the link KOLONİ printed in its window (`KOLONİ is open at http://127.0.0.1:8790/#key=…`) and
  paste it there.

**"KOLONİ cannot reach its server"**
: The page cannot reach KOLONİ. Check that KOLONİ still runs in its window, then press
  **Try again**.

**"This page could not be shown"**
: "Often the page and the server are different versions: restart KOLONİ, then reload. The other
  pages still work." This often happens right after an update. Restart KOLONİ, then press
  **Reload**.

**"KOLONİ serves your keys and files with no TLS: bind to this machine (KOLONI_HOST=… is not), or run the image."**
: KOLONİ stopped because `KOLONI_HOST` names an address other than this machine. Use `127.0.0.1`
  (the default), `::1` or `localhost`, or run the Docker image.

**The port is already in use**
: KOLONİ has no message of its own for this; the error comes from the system. Another KOLONİ (or
  another program) uses port 8790. Start KOLONİ on another port with `KOLONI_PORT`, and give it its
  own `KOLONI_RUNTIME_ROOT`. See [Install](getting-started/install.md#another-port).

## Updating

The update script stops at the first problem and prints `update: {why} - stopped, nothing after it
ran.` The reasons:

| `{why}` | What to do |
|---|---|
| `tracked files have uncommitted changes: commit or stash them first` | Commit or stash your own changes to KOLONİ's files, then run it again. |
| `something answers on 127.0.0.1:{port} - stop KOLONİ first (Ctrl+C in its window)` | Stop KOLONİ, then run it again. |
| `this folder is not a git checkout; update it with git first (git clone)` | KOLONİ's folder must be a git checkout. |
| `this is a linked working copy; run the update in the main checkout` | Run the script in the main KOLONİ folder. |
| `{step} failed` | That step's own output says why. |

When it works, it says `Updated to {commit}. Restart KOLONİ; the database is migrated when it starts`,
and where the backup is.

## Models

**"{Provider} isn't answering at {address}."**
: The bar at the top. The model server does not answer. Start it (for a server on this machine,
  Models → the provider → **Server**), or press **Pick another model**. The bar speaks only of the
  providers the open chat would run on: the one chosen for the chat, and where its Orchestrator and
  roles would run. With several down it names them all ("2 providers aren't answering: …");
  **Details** lists each. **✕** hides it for this session until something else goes wrong.

**"{Role} can't run: {why}"**
: The bar at the top. A role this chat would use (the Orchestrator, too) cannot run where it would
  now: its model is not one its provider may run, or the provider cannot be opened here. Pick
  another model for the role on the Agents page, or change the provider's list on the Models page.

**"{Provider} has no model it may run with by default."**
: The provider's default model is not one it may run. Open the provider on the Models page and
  check its **Default model**.

**"{model} does not support tool calls; chat works, file tools are off."**
: This model can talk but cannot use KOLONİ's tools. Pick a model that supports tool calls. For
  llama.cpp, start `llama-server` with `--jinja`.

**"The {command} command was not found on this machine. Install it in your own terminal (KOLONİ does not), then press Check on the Models tab"**
: The CLI is not installed, or not on your `PATH`. Install it with the command shown, or set
  **Path to the command** on the provider's **Connection** tab. The card says "not installed".

**"{command} is not signed in. Sign in in your own terminal (KOLONİ does not), then press Check on the Models tab"**
: Sign in to the CLI in your own terminal with the command shown, then press **Check**. The card
  says "not signed in".

**"The {command} command was found. It was not run, so sign-in is not checked."**
: This is what **Test** says for a CLI. To check sign-in too, press **Try a real run**. It counts
  against your plan.

**"Qoder: in the model's queue for {time} (waits up to {time})"**
: In the agent's window; its box on the canvas says "queued {time}". Qoder holds a free model's
  request in a queue while the model is busy. In tests the wait was about 1 to 3 minutes. Wait, or pick
  another model for the chat or the role. A sub-agent whose model KOLONİ picked by tier is moved to the
  tier's next model after 90 seconds, if the tier has another. See
  [Qoder's free models](models/setup-cli.md#qoders-free-models).

**"Copilot can't use {model} on your account: pick another model"**
: Or, when Copilot runs as a session: "GitHub Copilot CLI exited with code 1: Error: Model "{model}" from
  --model flag is not available." KOLONİ's list offers a model that your Copilot account or CLI does
  not. Pick another model. So that agents do not pick it by its tier, switch the model's **On** off on the
  Copilot provider's **Models** tab.

**"{CLI} {version} could not be asked before it acts ({why}); run it as a session instead"**
: Seen with Qoder run **Native**, with the reason "it did not apply KOLONİ's hook". KOLONİ runs a CLI
  with its own tools only when the CLI asks KOLONİ before each tool, and this one did not, so nothing
  ran. Open the provider and set **How it runs** to **One session per agent, with KOLONİ's tools**. See
  [Set up a CLI](models/setup-cli.md#how-it-runs).

**Tokens show as "–" or "unknown" for a CLI**
: GitHub Copilot CLI run as a session reports no token counts, and KOLONİ estimates none. The Usage page
  shows "–" and the agent's window "unknown". Run **Native**, it reports its tokens and AI credits (or
  premium requests). A CLI on a plan never has a cost either. To see how much of your plan is
  used, look at the provider's plan meter, which Copilot has on your GitHub account (not on a model
  server of your own). See [Usage and budgets](money/usage.md#plan-meters).

## When a turn fails

A failed turn shows **"Run failed: {Provider}: {reason}."** with a next step under it:

| Reason | Next step shown |
|---|---|
| limit reached, resets {time} | "Wait until it resets, or pick another model." |
| out of credits | "Add credits to that account, or pick another model." |
| not signed in, or its key was refused | "Sign in to it again, or pick another model." |
| the CLI stopped without finishing | "Send the message again." |
| it ended without an answer | "Send the message again." |
| model server unreachable | "Check that the model server is running, or pick another model." |
| no model provider is set up | "Add one on the Models page." |

**"the CLI stopped without finishing"**
: The CLI closed in the middle of its turn. The turn ends within a few seconds, even if a command the
  CLI started was still running. The programs it started end with it, as they do when you press
  **Stop**, so none keeps running or spending your plan.

**"model server did not start answering within {seconds} seconds"**
: The model took too long to start. A large local model can be slow to load. Raise
  `KOLONI_MODEL_FIRST_TOKEN_SECONDS` (default 900) before you start KOLONİ.

**"model server sent nothing for {seconds} seconds"**
: The model stopped in the middle of an answer. Raise `KOLONI_MODEL_STALL_SECONDS` (default 120)
  if your model pauses for long.

**"Interrupted by a server restart. Send a message to continue."**
: KOLONİ stopped while the turn ran. Nothing is run again by itself. Send a message to go on.

**"Stopped at its step limit."**
: The Orchestrator used all its steps for this message. Its limit is Settings › The app ›
  Agents › **Steps an agent may take**, with more for its teams and recipes. Send a message to go on, or split big work into smaller
  messages. See [Step limits](agents/step-limits.md).

**"{name} came to its limit of {taken} steps before its work was done."**
: A sub-agent with nothing kept reached the app's step limit, and its card asks: **Continue (+{n}
  steps)** or **Stop here**. At Full auto the Orchestrator answers it once for each agent in a turn. See
  [Step limits](agents/step-limits.md#a-sub-agent-with-nothing-kept).

**"stopped at its role's limit of {limit} steps"**
: A sub-agent reached the step limit set on its role. While the turn still runs, its kept work's card
  offers **Continue (+{n} steps)**; {n} is Settings › This project › Limits and money › **Continue gives this many more
  steps**. Without kept work there is no card. Only you give more past a role's limit: the
  Orchestrator's go on is refused there, at **Full auto** and while you're away too. The role's limit counts the agent's earlier steps, in
  later turns too: after the turn, raise **At most this many steps** under **Safety stops for one
  agent** in the role's form (Agents page), then ask the Orchestrator to go on. A CLI working with its
  own tools takes no steps KOLONİ can count, so this limit does not hold it.

**"Stopped after the {n} steps it was given"**
: An agent reached the end of the steps it was given by a Continue, or by the Orchestrator's call at
  Full auto. {n} is the job's whole count, the steps it had taken plus those given: after a Continue of
  25 at 25 steps it reads 50. No
  Continue / Stop here card comes for it again in this turn. If it changed files, its kept work's card
  has **Continue** while the turn runs; otherwise ask for more in your next message. See
  [Step limits](agents/step-limits.md#going-on-by-message).

**"could not work: Codex kept trying its own tools, which are off in step mode. Try running Codex as One session per agent (Models › Codex › How it runs)."**
: Or "could not review: …" for a reviewer. Run as **One run per model step**, Codex sometimes tries its
  own tools, which KOLONİ switches off there. KOLONİ tells it to use KOLONİ's tools and tries the step
  again. A step that asks for any of KOLONİ's tools starts the count anew. The third such step in a row
  (one that tried Codex's own tools and asked for none of KOLONİ's) ends the agent. Each step tried
  again counts toward its step limit. Open the Codex provider and set **How it runs** to **One session
  per agent**, Codex's default for a provider added since 7 Nov 2026 (on a model server of your own it
  starts as One run per model step: its session there is not yet measured, so try it there knowing
  that): it keeps working with KOLONİ's tools, triggers included. To let Codex use its own tools instead, set it to **Native**. Triggers never start a Native CLI, so a trigger then no longer runs
  its turns on Codex (see [FAQ](#faq)). See [Set up a CLI](models/setup-cli.md#how-it-runs).

**"budget: stopped after {steps} model steps, the most this trigger gives a turn"**
: A trigger's run used its budget. Raise **Model steps a run** on the trigger. See
  [Triggers](automation/triggers.md).

## Money

**"Over this month's budget. Send it anyway?"**
: The project's monthly budget is used up. Press **Go on anyway** to send it, or **Cancel**. A
  provider's own limit shows the same way, starting "Over {provider}'s limit of …". Change the budget
  under Settings › This project › **Limits and money**, and a provider's limits on its **Limits** tab.

## Triggers

**"It would have asked you:"**
: A trigger's turn met something it was not allowed to do. "Each was refused, and nothing was done in
  its place." Press **Allow this in the trigger** to open the trigger's form with it ticked; it is
  yours to save.

**"this project is over this month's budget: nothing was started"** and **"the provider its Orchestrator runs on is over its limit: nothing was started"**
: A trigger did not start because of a budget or a limit.

## Commands and Docker

**"Docker is not running: a container cannot be chosen."**
: Settings › This project › Commands and secrets. Start Docker, then open the page again.

**"the image {image} is not on this machine; run: docker pull {image}"**
: KOLONİ never pulls an image for you. Run the command shown in your own terminal.

**"Permission denied" on files in the project, with commands in Docker on Linux**
: Commands in Docker run as your user now. Files an older version of KOLONİ made in the project, such
  as `dist/`, `node_modules/` or `.coverage`, may still belong to root. Give them back to yourself in
  your own terminal, in the project's folder: `sudo chown -R "$(id -u):$(id -g)" .`

**You rejected a command, and the same change comes back as a file change**
: You rejected a command that writes a file or applies a patch. The agent is told "If the change is
  still needed, make it with edit_file / write_file", so it makes the same change as a file change:

    - at **Ask before changes**, it waits on a file-change card with its diff;
    - at **Auto-edit files**, it is written at once, and **Revert** takes it back;
    - from a sub-agent, it comes back with its working copy's card (**Take in** or **Discard**).

  If you do not want the change at all, tell the agent so. See
  [Permission levels](use/permissions.md#the-cards).

## Taking work in

**"Changed on both sides, and git does not put them together: {files}"**
: You and an agent changed the same lines. Press **Let an agent resolve the conflicts**, or resolve
  them yourself.

**"Your uncommitted changes are in the way (commit, stash or unstage them first): {files}"**
: Commit, stash or unstage your own changes to those files, then try again.

## Folders

**"{path} cannot be opened as a folder: {why}"**
: Some places are never opened as a project: a drive's root, a folder that holds your home folder's
  secrets (such as `.ssh` or a CLI's settings), KOLONİ's own folder, and network paths. In the folder
  browser they are tagged "always blocked". Pick a folder inside your projects instead.

## Restore

**"not restored: {why}"**
: The file could not be restored. For example, "it is not a KOLONİ export: it has no manifest.json",
  or "it was made by a newer KOLONİ (…): update KOLONİ first". Restore only a file you exported
  yourself.

**"A restore could not be applied at the last start: it is kept in {path}, and KOLONİ's log says why."**
: Your data was not replaced. KOLONİ's log, in `runtime/logs/koloni.log`, says why.

## This guide

**"The guide is not built yet"**
: At `/guide/`, or after a **Learn more →** link. KOLONİ serves this guide only once it is built. Run
  the commands that page shows in KOLONİ's folder, then reload. See
  [This guide inside KOLONİ](getting-started/install.md#this-guide-inside-koloni).

**On GitHub, the guide is not published**
: Only in your own copy of KOLONİ on GitHub. The Guide workflow builds this guide and pushes it to the
  `gh-pages` branch; it publishes by itself only once the repository variable `PAGES_ENABLED` is
  `true` (a run by hand always publishes). The site shows only after Settings → Pages → **Deploy from a
  branch**, `gh-pages`, `/ (root)`. A broken link or anchor fails the build, and nothing is published.

## FAQ

**Is anything on screen simulated?**
No. The canvas, the agents and the usage come from what was recorded. A value KOLONİ does not know is
shown as unknown.

**Does KOLONİ send anything about me?**
No telemetry. What leaves your machine is the requests to the providers you add, and the web searches,
requests and tools you allow. See [Data and privacy](security/privacy.md).

**Can I give a running command some input?**
No. Commands cannot be given input while they run.

**Why did my trigger not start on a CLI?**
Triggers do not start a turn on a CLI that works with its own tools (Native, or agy).

**Why can an agent still read `.env` at Full auto?**
A script that opens `.env` without naming it (it builds the name, say) is not caught. A command that
names it, or searches the whole folder, is asked about at every level, but when it runs **Native**, Codex
runs the reads its own rules count as safe without asking KOLONİ, and agy reading with its own tools reads
it without asking at any level. Only Docker and Copilot's sandbox hide secret files from commands. See
[Known limits](reference/known-limits.md#secrets) and [Permission levels](use/permissions.md).

**Are canvas positions saved?**
No. The canvas is drawn from the record each time.

**Which systems are tested?**
Windows the most. Linux and the Docker image less, macOS not yet. See
[Install](getting-started/install.md#how-well-each-system-is-tested).
