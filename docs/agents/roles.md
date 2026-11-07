# Roles

A role is what an agent is for: a description, instructions, the tools it may use and, if you like,
its own model. Open **Agents** on the left rail ("Who does the work, in which teams, by which
recipes"). The page has three tabs: **Teams & roles**, **Recipes** and **History**.

## The roles

The Orchestrator is the agent you talk to. It opens other roles as sub-agents when a part of the work
needs them. KOLONİ comes with these roles:

Orchestrator, Planner, Coder, Tester, Reviewer, Researcher, Debugger, Architect, Security reviewer,
Docs writer, Refactorer, UI designer, Data analyst, DevOps, Spec writer, Performance engineer,
Database engineer, Dependency keeper, Translator, Summarizer, Product owner, Assistant product owner,
Observer, Data engineer, ML engineer, Data scientist, Model evaluator, MLOps engineer, Designer,
SEO specialist, Copywriter, Accessibility reviewer.

The **Roles** list on the **Teams & roles** tab shows them all. **Filter roles…** searches it, and the
buttons **All**, **In no team** and **Off** narrow it. Each role has an on / off switch. The
Orchestrator, the Planner and the Observer are always on.

## A role's panel

Click a role to open its panel. It has four tabs:

- **Overview**: its category, the teams it is in, what it may do, and its **Model** as four answers:
  **Which model**, **How hard it thinks**, **How much it reads** and **Who may move it** (and **Runs as**
  where a role can run inside the CLI). Click an answer, or **Edit**, to change it.
- **Instructions**: what the role is told.
- **Tools**: the tools it may use, grouped (Files, Commands, Web, Browser, Team, To-do, Memory). A
  click switches a tool on or off and saves at once. A role needs at least one tool. Tools marked
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
  keeps its own session and does that itself. Where the window is unknown there is no fullness meter and
  nothing is summarized early. **Set by hand** takes a window of your own.

  **Who may move it**: **Any provider in the team guide**, **Only these**, or **No one**. An agent that
  moves a sub-agent to another provider must say why.

  **Run inside the CLI**: only when the agent that opens it runs in Claude Code. Cheaper, and counts toward
  no turn or role limit; it is not its own agent on the canvas, stops with the agent that opened it, and
  is never used while you're away or for a trigger. Not for the Orchestrator, the Observer or a team's lead.
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
