# Copilot on your GitHub account

GitHub Copilot CLI on your GitHub account runs only what your Copilot plan offers, and what it offers
changes with the plan. On 24 Nov 2026 an account whose premium requests were used up listed no model by
name, only `auto` at **Standard** and **Fast**. The day before, the same account listed about 14 models.
So KOLONİ asks Copilot itself what your account offers, and offers only that.
(Set up the provider first: [Set up a CLI](setup-cli.md#github-copilot-cli).)

## What KOLONİ asks, and when

KOLONİ asks Copilot two things in one start, with no model turn: which models and Auto tiers your account
offers (`models.list`), and what is left of your plan (`account.getQuota`). It starts Copilot the way the
plan meter does, in an empty home of KOLONİ's own, signed in with your `gh` login or the provider's token.

It asks:

- as the provider is added (the top bar reads it within seconds),
- by the top bar's plan meter, at most once in 10 minutes, and on **Read now** on its card in **Models**,
- when you fill its tiers (**Fill from the catalogue**, **Fill tiers**),
- at once after Copilot refuses a model or a routing.

Opening the **Models** page or the chat's model panel asks nothing: they show what your account offered when it
was last asked.

A Copilot on a model server of your own is never asked: its models are the server's.

## Models

| What your account says | What KOLONİ does |
| --- | --- |
| It lists the model | The model stays on. |
| It does not list the model | KOLONİ switches the model off on the provider's list and says why: "not on your Copilot plan now". |
| It has no premium requests left | The models it no longer lists go off with "your Copilot plan has no premium requests now". |
| One of its Auto tiers is on | `auto` stays on. |
| No Fusion tier is on | `fusion` goes off, in Copilot's own words: "This tier is not available for the user's Copilot plan." |
| It lists a model it did not list before | KOLONİ switches the model back on. |

A model you switched off yourself stays off: KOLONİ switches back on only what it switched off. So does
a model Copilot refused while your account listed it, whatever the list says later; its row says so.
Switch it on yourself once you think it works.

- **Fill from the catalogue** proposes only what your account offers. When it lists no model by name,
  the fill says so. A Copilot not added yet is not filled: add it first, and KOLONİ then asks your
  account. **Fill tiers** asks it too; a Copilot whose account does not answer is left as it is.
- The model names the chat's model panel offers are your account's too.
- An agent picked by tier never gets a model that is switched off. A model Copilot refuses at its first
  turn is switched off the same way, and your account is asked again at once.

## Routing

`auto` and `fusion` take a routing, on the model's row of the **Models** tab and in the chat's model panel.

- Once your account was asked, `auto` offers only its Auto tiers, by Copilot's own names. On 24 Nov 2026
  those were **Standard** (Copilot's `balance`) and **Fast**. Fast is on in the account, though Copilot's
  own picker does not show it. KOLONİ offers it and sends it as you chose it.
- A tier your account has off is dimmed, "not on your plan", with Copilot's own words in its tooltip.
  A routing a row already had that the account no longer lists stays on the row, dimmed, until you pick
  another.
- `fusion` offers its Fusion tiers the same way: on 24 Nov 2026 **High** and **Max**, both off. Where no
  Fusion tier is on, `fusion` itself is switched off.
- Before your account was asked (a new provider, or Copilot not answering), the routing offers every tier
  Copilot's package knows: Efficiency, Balance, Intelligence and Fast; Standard, High and Max.

## Plan limits

The provider's card, the top bar and **Plan limits** on the Usage page show Copilot's **chat requests**
and **premium requests** apart, for example "0% of chat requests used (200 of 200 left) · premium
requests: none on your plan". A plan with no premium requests says "none", never "100% used".

Before a turn, KOLONİ checks whether the account has room:

- A named model is held back when either counter is used up.
- `auto` runs while chat requests are left, even with premium requests used up: on 24 Nov 2026 `auto`
  ran with premium at 0 and chat requests left. It is held back when every counter is used up, and on a
  plan with unlimited chat requests (no chat counter) once premium requests are used up - which counter
  `auto` spends there is not measured.
- A plan with no premium requests at all (0 of 0) holds nothing back by itself: the models your account
  no longer lists are switched off instead (above).

## Not measured yet

- Whether Copilot takes `fast` from KOLONİ as Fast, not as its own default. A run with it went well, but
  the tier it ran at was not read back.
- Which of the two counters `auto` spends.
- What a listed model carries: KOLONİ reads only its name.
