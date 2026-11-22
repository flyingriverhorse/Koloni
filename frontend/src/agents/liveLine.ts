import type { Agent, Tier } from '../api/types'
import { took } from '../canvas/timeline'
import { modelName } from '../shell/modelName'

/** A tier as it is named on the screen. */
export const TIER_NAMES: Record<Tier, string> = { strongest: 'Strongest', balanced: 'Balanced', fast: 'Fast' }

const COMPACT = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

/**
 * What is known of work under way, piece by piece, as Claude Code says it: "12s", "↓ 1.2k tokens", "Fast" - how long
 * since `since`, the tokens written, the tier or model. What is not known is left out, never guessed; nothing known, [].
 */
export function liveFactList(now: number, since: string | null, wrote: number | null, kind: string | null): string[] {
  // (This browser's clock a little behind the server's: no time has passed, not an unknown one.)
  const pieces = [since && took(Math.max(0, now - Date.parse(since))), wrote !== null && `↓ ${COMPACT.format(wrote).toLowerCase()} tokens`, kind]
  return pieces.filter((piece): piece is string => Boolean(piece))
}

/** An agent's tier by its name, else its model's (`runModel`: its turn's, for a lead from before models were per agent); null: neither known. */
export function liveKind(agent: Pick<Agent, 'tier' | 'model_id'>, runModel: string | null = null): string | null {
  if (agent.tier) return TIER_NAMES[agent.tier]
  const id = agent.model_id ?? runModel
  // (A CLI's own default model is not a name: not said.)
  return id && !modelName(id).startsWith('CLI default') ? modelName(id) : null
}
