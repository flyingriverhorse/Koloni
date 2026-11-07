# Plan first

With **Plan first** on (the switch next to the message box, or `/plan`), each new message first gets a
plan to approve, before anything changes.

## While it plans

"Writing a plan: this message's work only reads, and nothing changes before you approve it." A plan turn
can only list, read and search files, look at images, ask you questions, read notes and recall memory, at
any permission level.

When **Who changes the files** is **Orchestrator delegates the work** (Settings › This project ›
Agents), the plan is asked to say that the Orchestrator changes no files in the work turn, and to name
the sub-agent or role that makes each change.

## The plan card

**Approve this plan?**

- **Approve** starts the work at once, following the plan.
- **Edit** lets you change the plan, then **Approve edited plan**.
- **Reject**, then **Reject plan**, with "Why not, in a sentence (optional)".

"Approve here — a new message plans again." If a later message started meanwhile, the card says "This
plan was not decided": reject it, or ask again.

If the project is over its monthly budget, approving asks "Start the work anyway?" with **Go on anyway**
and **Cancel**.

## On the canvas

A plan turn shows a small **Plan** node, which says how the plan stands: "being written", "proposed" or
"approved" (or "rejected"). In the work turn of an approved plan, a small **Plan** node stands over the
Orchestrator, on a dashed line down to it; the legend calls it "From an approved plan down to the
Orchestrator that carries it out". Click a Plan node to read the plan in the Inspector.

## When there is no plan

Plan first applies to your own messages in a chat with a folder. A plain chat (no folder), a trigger's
turn and a room never plan first.
