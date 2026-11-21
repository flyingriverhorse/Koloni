import type { Provider } from '../api/types'
import type { ListedModel } from './ModelsPage'

export type Routing = NonNullable<Provider['models'][number]['routing']>

/** Copilot's routings of its own auto and fusion (its 1.0.114 package: `AutoTier`, `FusionTier`), as shown. */
export const ROUTINGS: Record<'auto' | 'fusion', [Routing, string][]> = {
  auto: [
    ['efficiency', 'Efficiency'],
    ['balance', 'Balance'],
    ['intelligence', 'Intelligence'],
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

/** The routings a model takes: Copilot's auto or fusion on your GitHub account; null for any other. */
export function routingOf(provider: Provider | null | undefined, model: string | null | undefined): 'auto' | 'fusion' | null {
  return provider?.kind === 'copilot_cli' && !provider.base_url && (model === 'auto' || model === 'fusion') ? model : null
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
