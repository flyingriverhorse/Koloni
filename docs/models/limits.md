# Limits

Each provider's window has a **Limits** tab. What it offers depends on how the provider is paid.

## A CLI on a subscription

**Step down a tier at [ ] % of the plan**: once this much of the plan is used, agents picked by tier
move one tier down. A whole number from 50 to 100, or empty for never. "A role that always runs on
one tier, or on one model, is never stepped down: your own rule wins."

## An API key

- **This key is a plan: count no money**: its runs show no cost on Usage and count nothing in a
  project's budget.
- Otherwise, **At most $ … a day** and **At most $ … a month**, spent at your prices, in every
  project. Empty means no limit. Past the limit, a new message whose Orchestrator runs on this
  provider asks you first, a model picked by tier moves to the next one of its tier, and no sub-agent
  or room member is opened here.

Press **Save limits** to keep them.

## A model server on this machine

"A model server on this machine spends no money and has no plan: there is nothing to limit."

## When a message would go over a limit

When a provider's limit or the project's monthly budget is reached, a new message asks first. It
says which limit and how much was spent, then "Send it anyway?". Press **Go on anyway** to send it,
or **Cancel**.

## When an agent would move to a paid provider

If KOLONİ would open a sub-agent on a provider that is paid per token, while the chat runs on one that
is not, it asks on the **Open this sub-agent?** card. The card's reason says that the new provider is
paid per token and the other is not. Press **Open agent** or **Reject**. Your answer counts for that
provider for the rest of the turn. In a turn nobody watches, such an agent is not opened.

See also [Usage and budgets](../money/usage.md).
