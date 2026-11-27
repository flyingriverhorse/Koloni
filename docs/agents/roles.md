# Roles

A role is what an agent is for: a description, instructions, the tools it may use and, if you like,
its own model. Open **Agents** on the left rail ("Who does the work, in which teams, by which
recipes"). The page has three tabs: **Teams & roles**, **Recipes** and **History**.

## The roles

The Orchestrator is the agent you talk to. It opens other roles as sub-agents when a part of the work
needs them. KOLONİ comes with these roles:

Orchestrator, Planner, Coder, Tester, Reviewer, Researcher, Debugger, Architect, Security reviewer,
Docs writer, Refactorer, UI designer, Data analyst, DevOps, Spec writer, Performance engineer,
Database engineer, Dependency keeper, Translator, Summarizer, Hive keeper, Scout, Data engineer,
ML engineer, Data scientist, Model evaluator, MLOps engineer, Designer, SEO specialist, Copywriter,
Accessibility reviewer.

Two are named for KOLONİ's hive. The **Hive keeper** keeps the To-do list: it turns a goal into
tasks, each with what makes it done, and puts them in order. The **Scout** keeps watch on the To-do
list: it splits vague tasks, asks what is missing, flags duplicates, stale and blocked tasks, and
checks finished tasks against what makes them done. After each turn KOLONİ also asks a model, in
the Scout's name, for follow-up tasks (see [To-do](../automation/todo.md#follow-up-tasks)). A role
of your own that already had one of these names keeps it; the built-in one is then "Hive keeper
(built-in)" or "Scout (built-in)". A slash command of yours named `scout` would hide behind the
role's chip in the message box: it is renamed `scout-command`.

Before 0.1.7 they were the Product owner and the Assistant product owner. Your recipes and saved
slash commands that named the old roles were changed to name the new ones, and an agent that asks
for an old name is told the new one ("Product owner is now the Hive keeper"). Past conversations
keep the names they had. A recipe kept in a folder's `.koloni/recipes` is a file of yours, not
changed: one that names an old role is renamed there, by hand.

The **Roles** list on the **Teams & roles** tab shows them all. **Filter roles…** searches it, and the
buttons **All**, **In no team** and **Off** narrow it. Each role has an on / off switch. The
Orchestrator and the Planner are always on. So are the Coder, Tester, Reviewer, Debugger and Security
reviewer: KOLONİ's checks and recipes use them, so they have no switch (a chat's teams still decide
whether they are opened there).

In a window narrower than 1280 px the list folds to a **Roles ▸ N** button over the teams, which opens it
as a drawer; it stays at the top of the page however far you scroll.

## A role's panel

Click a role to open its panel. It has four tabs:

- **Overview**: its category, the teams it is in, what it may do, and its **Model** as four answers:
  **Which model**, **How hard it thinks**, **How much it reads** and **Who may move it** (and **Runs as**
  where a role can run inside the CLI). Click an answer, or **Edit**, to change it.
- **Instructions**: what the role is told.
- **Tools**: the tools it may use, grouped (Files, Commands, Web, Browser, Team, To-do, Memory). A
  click switches a tool on or off and saves at once. A role needs at least one tool. The Coder, Tester,
  Reviewer, Debugger and Security reviewer keep the tools their job needs: reading files for all five,
  writing files for the Coder and the Debugger, **Run commands** for the Coder, the Tester and the
  Debugger. Those tiles stay on, greyed: "Kept: KOLONİ's checks and recipes need it". Their other tools
  are yours to change, and **Reset to default** still works. A sub-agent never has a tool its opener
  may not hand on: an Orchestrator without **Run commands** gives no Tester one. Tools marked
  "asks" wait for your yes, as the chat's permission level says. Below, the MCP servers and skills the
  role has; you change those on the Tools page.
- **Knowledge**: a switch for each Knowledge topic. On, choose **Full** ("its whole guide at each
  step") or **Map** ("its guide, read when its work touches it").

## Editing a role

**Edit** opens the role's form:

- **Name**, and **What it does**: "The Orchestrator reads it to pick the role."
- **Category** and **Instructions**.
- **Model**: a card for each question. Each says one line; **Learn more** holds the rest.

  **Which model** asks **Who picks it?**, then only what that choice needs:

| Choice | What it needs | What it means |
|---|---|---|
| **Orchestrator** | **From** and **to** | "It picks a tier for each job, inside this range, and says why." |
| **As the chat** | nothing | "Whatever the chat's model picker says." |
| **One tier** | **Fast**, **Balanced** or **Strongest** | "Always this tier. The Orchestrator can't change it." |
| **One model** | a **Provider** and a **Model name** | "Always this model, whatever the job." |

  The Orchestrator itself has no **Orchestrator** choice. **Try first** lists up to 5 models from the
  team guide, tried in order before the choice above; **+ Add a model** adds one. See
  [Tiers](../models/tiers.md).

  **How hard it thinks** (Thinking) is **Auto** or **One fixed level**, and one ladder of the levels Off
  to Max:

  - **Auto**: the agent that opens a sub-agent picks a level for each task: Low for reading or
    summarizing, Medium for normal code, High for hard bugs or design. The levels it may pick are shaded,
    from Low up to the one marked **most** (High unless you move it, or the nearest lower level a model
    without High takes); click a level to move it. Its pick, and its reason, show under **Details** in the
    agent's window. Auto never picks Off. If it picks nothing, KOLONİ sends Medium (or the most, where that
    is lower), and the agent's window says "Thinking Medium, KOLONİ's default for Auto (the opener gave no
    level)".
  - **One fixed level**: every task gets the level you click, any level its model takes; the
    Orchestrator doesn't change it.

  An agy model whose name ends in its level, such as `gemini-3.8-flash-low`, takes no other: it is sent
  none, and the agent's window says so. Under **How hard it thinks**, the role's Model
  card says "The model's own" and "its name sets its level: none is sent".

  A role from before may still have a most next to a fixed level, or a most of Off under Auto. A line
  under the ladder says so ("The Orchestrator may also go up to High (set earlier)"), and **Remove** takes
  it away.

  Struck levels are ones the role's model does not take, named under the ladder. A model without a level
  gets the nearest lower level it takes, never down to Off; one whose levels are not known gets none.
  Back to Auto, a most of Off, or one the model is known not to take, is taken away.

  Nobody opens the Orchestrator, so it has no **most**: a click sets its level, and with **Auto** no level
  of its own is sent, and the chat's level, or the model's own, applies.

  **How much it reads** (the context window) says the window found for its model, and where from. Past the
  % set in **Settings › The app** ("Summarise a long context at (%)") KOLONİ summarizes the older part, unless its CLI
  keeps its own session: Claude Code compacts its own; Copilot's and Codex's start anew past that % of
  their bound ([Going on from the last turn](../models/setup-cli.md#going-on-from-the-last-turn)). Where the window is unknown there is no fullness meter and
  nothing is summarized early - but a CLI lead that starts each turn anew, which is summarized after its turn
  against the catalogue's window for its model where there is one, which only a very long chat reaches
  ([Set up a CLI](../models/setup-cli.md#going-on-from-the-last-turn)). **Set by hand** takes a window of your own.

  **Who may move it**: **Any provider in the team guide**, **Only these**, or **No one**. An agent that
  moves a sub-agent to another provider must say why.

  **Run inside the CLI**: only when the agent that opens it runs in Claude Code or GitHub Copilot CLI run
  **Native** ([experimental](../models/setup-cli.md#experimental-clis)) - Copilot on its newer protocol
  (1.0.114 on), where its provider is in the team guide. Cheaper, and counts toward
  no turn or role limit; it is not its own agent on the canvas, stops with the agent that opened it, and
  is never used while you're away. Not for the Orchestrator or a team's lead. The agent's window and the
  canvas show it as an **own sub-agent**, "Checker (inside GitHub Copilot CLI)", with what it did inside
  it. It has its role's own tools only, each asked about as its agent's are (a card where your level
  says so): none of KOLONİ's tools, which are its agent's, and no sub-agent of its own. In Copilot it
  runs on the agent's own model; Copilot is given only these roles, none of its built-in sub-agents, and
  opens one only while it waits for it - one it asks to open in the background, or by another name, is
  refused.
- **It may**: **Read and search**, **Write code**, **Run commands**, **Use the web**, or
  **Pick tools one by one**.
- **This role will** sums up what the role will do, as you change the form.

Press **Save**. A built-in role has **Reset to default**; your own has **Delete role**.

## A new role

**New role** (on the **Teams & roles** tab) opens a form. "Agents in this role are opened by the
Orchestrator or a team lead." Start from:

- **Blank**;
- **An expert**: it reads only; an expert changes nothing;
- **A copy** of another role: it gets that role's servers, skills and knowledge, but not its teams.

Press **Create role**. An agent can also propose a role while it works; you decide on the
**Create this role?** card.

## History

The **History** tab shows what the roles, teams and recipes did in the **Last 30 days** or **Last 7
days**: how many agents were opened and ended done, and the team and recipe runs. Filter by role, team
or recipe, or tick **Failed only**. Each row shows when, the role, the chat, the model and how it
ended; click the chat to open it.
