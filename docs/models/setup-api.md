# Set up an API provider

An API provider is a service you pay per token, with a key: the Anthropic API, or any service that
speaks the OpenAI API.

## Anthropic API

1. Models → **Add a provider**. **Kind**: **Anthropic API**.
2. **API key**: your Anthropic key. "Keys are kept in plain text in KOLONİ's local database on this
   machine." Once saved, the key "is never shown again".
3. **Address**: leave it empty for `https://api.anthropic.com`.
4. **Default model**: needed, for example `claude-sonnet-5-5`.
5. **Workspace ID**: "Only needed for a key that is not scoped to a workspace. Copy it from the
   Anthropic console."
6. Press **Add provider**, then **Test**. For the Anthropic API, Test reads the model's details and
   spends nothing.

## A service that speaks the OpenAI API

1. Models → **Add a provider**. **Kind**: **OpenAI-compatible server**.
2. **Address**: the service's API address, starting with `http://` or `https://`. The field suggests
   the services KOLONİ knows from its model catalogue; an address that only names a known service is
   completed to its full API address.
3. **API key**: the service's key. The field says what the service calls its key.
4. **Default model**: if you leave it empty, KOLONİ uses the first model the server lists.
5. Press **Add provider**, then **Test**. Test sends one small request to see whether the model can use
   tools, which costs a few tokens on a paid service. It then says "Reachable" and the model, and adds
   "this model does not take tools" if it cannot use them.

A model that does not take tools can chat, but agents cannot use KOLONİ's tools with it.

## After adding

- **At most this many agents at once**: 8 by default for a service.
- On the **Models** tab, give the models a **Tier**, and set **Agents may use**. See
  [Tiers and Agents may use](tiers.md).
- On the **Limits** tab, set dollars a day or a month, or mark the key as a plan. See
  [Limits](limits.md).
- Prices come from the catalogue unless you set your own. See [Usage and budgets](../money/usage.md).
