import type { Provider } from '../api/types'
import type { ListedModel } from './ModelsPage'

export type Routing = NonNullable<Provider['models'][number]['routing']>

/** Copilot's routings of its own auto and fusion (its 1.0.114 package: `AutoTier`, `FusionTier`), as shown. */
export const ROUTINGS: Record<'auto' | 'fusion', [Routing, string][]> = {
  auto: [
    ['efficiency', 'Efficiency'],
    ['balance', 'Balance'],
    ['intelligence', 'Intelligence'],
    ['fast', 'Fast'],
  ],
  fusion: [
    ['standard', 'Standard'],
    ['high', 'High'],
    ['max', 'Max'],
  ],
}

/** What a routing does, for its select's title. */
export const ROUTING_WHY: Record<'auto' | 'fusion', string> = {
  auto: 'How Copilot’s auto picks the model for each request. Default: Copilot’s own.',
  fusion: 'Fusion High and Max run each turn on several models and keep one: they cost more than auto.',
}

/** A routing as its select offers it; `off`: why the account does not offer it now (null: it does). */
export interface RoutingChoice {
  value: Routing
  label: string
  off: string | null
}

/** What an option the account does not offer says after its name; the account's own words are its title. */
export const NOT_ON_PLAN = 'not on your plan'

/**
 * The routings a row's select offers. Once Copilot's account was asked (`provider.offers`): only its own tiers, by
 * its own names (Standard is balance), one it has off dimmed with its why, and the row's own one that it does not list
 * kept, dimmed - Fusion's from its Fusion tiers alone, as the server reads them (`copilot_offers.offered`). Before it
 * was asked: every routing the package knows.
 */
export function routingChoices(
  provider: Provider | null | undefined,
  routed: 'auto' | 'fusion',
  current?: Routing | null,
): RoutingChoice[] {
  const known = new Map(ROUTINGS[routed])
  const tiers = provider?.offers?.tiers ?? []
  if (tiers.length === 0) return ROUTINGS[routed].map(([value, label]) => ({ value, label, off: null }))
  // Auto's by their ids; Fusion's by the routing each of its own tiers takes (its `fusion`).
  const choices = tiers.flatMap(t => {
    const value = (t.type === routed && (routed === 'auto' ? t.id : t.fusion)) as Routing | false | null | undefined
    return value && known.has(value) ? [{ value, label: t.name, off: t.enabled ? null : (t.why ?? NOT_ON_PLAN) }] : []
  })
  if (current && !choices.some(c => c.value === current))
    choices.push({ value: current, label: known.get(current) ?? current, off: NOT_ON_PLAN })
  return choices
}

/** The routings a model takes: Copilot's auto or fusion on your GitHub account; null for any other. */
export function routingOf(
  provider: Provider | null | undefined,
  model: string | null | undefined,
): 'auto' | 'fusion' | null {
  return provider?.kind === 'copilot_cli' && !provider.base_url && (model === 'auto' || model === 'fusion')
    ? model
    : null
}

/** A provider's list as its Models tab saves it, with one model's routing changed (null: Copilot's default). */
export function withRouting(provider: Provider, model: string, routing: Routing | null): ListedModel[] {
  return provider.models.map(m => ({
    name: m.name,
    note: m.note ?? null,
    tier: m.tier ?? null,
    agents: provider.for_agents && m.agents !== false,
    ...(m.name === model && { routing }),
  }))
}
