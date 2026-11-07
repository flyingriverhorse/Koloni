# The guide's diagrams

Each picture in the guide is a draw.io file here, `name.drawio`, with the SVG the pages show beside it,
`name.svg`. The `.drawio` is the source: change it, then draw the SVG again. Each diagram's footer names
the code it was drawn from and the day it was checked against it.

| File | Shown in |
|---|---|
| `system-map.drawio` | [Architecture](../developer/architecture.md) |
| `concept-map.drawio` | [Home](../index.md), [KOLONİ in 5 minutes](../getting-started/concepts.md) |
| `turn.drawio` | [Chat and canvas](../use/chat-and-canvas.md) |
| `permissions.drawio` | [Permission levels](../use/permissions.md) |
| `memory.drawio` | [Memory](../memory.md) |
| `models.drawio` | [Providers](../models/providers.md) |
| `teams.drawio` | [Recipes and candidates](../agents/recipes.md) |
| `night.drawio` | [Triggers](../automation/triggers.md), [Work while you're away](../automation/overnight.md) |
| `security.drawio` | [Security model](../security/model.md) |
| `message-flow.drawio` | [Architecture](../developer/architecture.md) |
| `data-model.drawio` | [Architecture](../developer/architecture.md) |
| `runner.drawio` | [Architecture](../developer/architecture.md) |
| `cli-modes.drawio` | [Set up a CLI](../models/setup-cli.md) |
| `working-copy.drawio` | [Working copies and Take in](../use/workspace.md) |
| `recipe-engine.drawio` | [Recipes and candidates](../agents/recipes.md) |
| `install-update.drawio` | [Backup and update](../backup-and-update.md) |

## Opening and editing

- **In KOLONİ**: open this folder as a project and click a `.drawio` file in the Workspace. KOLONİ's own
  draw.io viewer draws it; it shows the diagram, it does not edit it.
- **To edit**: draw.io desktop, or app.diagrams.net (File → Open from → Device).

Keep the files easy to diff and the SVGs plain:

- Save uncompressed (draw.io: File → Properties, untick **Compressed**). The files are plain XML, one
  shape per line.
- Keep labels plain text: no **Formatted Text** (`html=1`) and no word wrap (`whiteSpace=wrap`); break
  lines yourself. Plain labels become plain SVG text, which every viewer shows the same way.
- Give every shape a place. A shape without one is placed by KOLONİ's viewer, not where you meant.
- When the code a diagram rests on changes, change the diagram and its footer's date.

## Drawing the SVG again

Draw the SVG with KOLONİ's own viewer, so every picture is drawn the same way:

- In the Workspace, open the diagram and press **Save as SVG**. The picture is written beside it, over
  the old one: `docs/diagrams/memory.drawio` gives `docs/diagrams/memory.svg`.
- Or ask an agent with the **Diagram pictures** tool for it ("draw docs/diagrams/memory.drawio as an
  SVG").

Both run the vendored viewer (`frontend/public/drawio/`) in a browser that loads nothing from the network.
draw.io's own File → Export as → SVG also works, but its SVG differs from KOLONİ's; don't mix the two.
