import type { Agent, Conversation, Provider, Role } from '../api/types'
import { ranOn } from '../shell/modelName'
import type { ConvState } from '../state/applyEvent'
import { chainOf } from '../topics/topics'

/**
 * An agent that goes on from an earlier turn on the provider · model it ran on then,
 * while its role would get another today: where it stays (`on`), and what its role would
 * now run on (`role`; null when that cannot be told from what is known here).
 */
export interface Stays {
  on: string
  role: string | null
}

/**
 * What an agent of a role would run on if it were opened clean today, as the server works
 * it out (`app/providers.py`, `resolve`): the role's own choice, else the conversation's,
 * else the first provider - a choice whose provider is gone counts as no choice, and a
 * choice with no model takes its provider's own. Null when the role is not known here, or
 * there is no provider to name.
 */
function roleRunsOn(roleName: string, conversation: Conversation, roles: Role[], providers: Provider[]): string | null {
  const role = roles.find(r => r.name === roleName)
  if (!role || providers.length === 0) return null
  for (const [providerId, modelId] of [[role.provider_id, role.model_id], [conversation.provider_id, conversation.model_id]]) {
    const provider = providerId ? providers.find(p => p.id === providerId) : undefined
    if (provider) return ranOn(provider.name, modelId || provider.default_model)
  }
  return ranOn(providers[0].name, providers[0].default_model)
}

const same = (a: string | null, b: string | null) => (a ?? '').toLowerCase() === (b ?? '').toLowerCase()

/**
 * Whether a sub-agent that goes on from an earlier turn stays where it ran before, though
 * its role would run elsewhere today - for the card that asks before it is opened. Null
 * when there is nothing to say: it started clean, it was put on its role's choice of
 * today, or that choice is where it runs anyway.
 */
export function staysOn(state: ConvState, agent: Agent, roles: Role[], providers: Provider[]): Stays | null {
  const chain = chainOf(state, agent.id)
  const before = chain.length > 1 && agent.depth > 0 ? chain[chain.length - 2].agent : null
  // (Known by its provider's name, which is all that is on record of where the earlier one ran.)
  if (!before || !agent.provider_name || !same(agent.provider_name, before.provider_name)) return null
  const on = ranOn(agent.provider_name, agent.model_id, agent.model_from)
  const role = roleRunsOn(agent.role_name, state.conversation, roles, providers)
  return same(on, role) ? null : { on, role }
}
