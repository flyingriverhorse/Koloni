# Tiers and Agents may use

## Tiers

A tier is how strong you say a model is: **fast**, **balanced** or **strongest**. You set it in the
**Tier** column of a provider's **Models** tab. **Fill tiers** fills them from the catalogue.

Tiers let KOLONİ pick a model for a job instead of one fixed name:

- a role can ask for a tier instead of one model;
- an agent can call a job easy or hard, to go one tier down or up;
- a chat's Orchestrator can follow how hard your message is.

**A model with no tier is only ever picked by name.**

### The tier lists

Below the provider cards, the Models page shows three lists: **Strongest**, **Balanced** and
**Fast**. Each lists its models, numbered in the order they are tried. Drag a model, or use its move
up and move down buttons, to change the order; each move saves at once. A model that agents may not
use is marked "off for agents". With no tiers at all, the page says "No model has a tier yet".

A model greyed with its provider's state ("not answering") shows how that provider looked when the
page read it. A provider that is not installed, not signed in or without a key is passed over until
KOLONİ sees it again: the page reads it, or you press its **Check**. A model server is passed over
after not answering for two minutes. Where every model of a tier looks so, the first is still tried.

## Agents may use

Each model has an **Agents may use** switch. On, agents may pick the model by themselves, for
example by its tier. Off, only you pick it: in a chat's model picker, or as a role's own model.

A provider with no list of models has one switch for the whole provider: **Agents may use this
provider**. **Never run a model that is not on this list** keeps agents to the listed models.

**What it is good for** (for a provider) and **Its note for agents** (for a model) are short notes that
agents read when they choose.

## A role's model

On the Agents page each role chooses who picks its model: **Orchestrator**, **As the chat**, **One tier**
(Fast, Balanced or Strongest) or **One model**. See [Roles](../agents/roles.md).

## Orchestrator model: automatic

In the chat's model picker, **Orchestrator model: automatic** sends each message to a fast model,
which judges it easy, normal or hard. The Orchestrator then runs on a fast, balanced or strongest
model. That is one more request for each message you send. It overrides the Orchestrator role's own
model and tier. A trigger's message does not use it.
