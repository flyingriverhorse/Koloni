import type { Run } from '../api/types'

/** Who wrote a plan (slice 49), as the card, the canvas and the inspector say it. */
export function plannedBy(plan: NonNullable<Run['plan']>): string {
  return `Planned by ${plan.model_id ?? 'a model not on record'} · ${plan.strongest ? 'the team’s strongest model' : 'this conversation’s model'}`
}
