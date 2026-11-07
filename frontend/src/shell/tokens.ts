import type { Run } from '../api/types'
import type { ConvState } from '../state/applyEvent'

/** Tokens of the whole turn: every agent that started; unknown if any did not report. */
export function turnTokens(conv: ConvState, run: Run): Pick<Run, 'input_tokens' | 'output_tokens'> {
  const agents = conv.agents.filter(a => a.run_id === run.id && a.started_at)
  if (agents.length === 0) return run
  const sum = (values: (number | null)[]) =>
    values.some(v => v === null) ? null : values.reduce<number>((total, v) => total + (v ?? 0), 0)
  return {
    input_tokens: sum(agents.map(a => a.input_tokens)),
    output_tokens: sum(agents.map(a => a.output_tokens)),
  }
}

/**
 * K-r152: a turn where some agents said their tokens and some did not - "≥ 277k tokens · 3 unknown", what was said and
 * how many did not say. Null where all said, or none did: `tokens(turnTokens(…))` says those.
 */
export function partTokens(conv: ConvState, run: Run): string | null {
  const agents = conv.agents.filter(a => a.run_id === run.id && a.started_at)
  const unknown = agents.filter(a => a.input_tokens === null || a.output_tokens === null).length
  const known = agents.reduce((sum, a) => sum + (a.input_tokens ?? 0) + (a.output_tokens ?? 0), 0)
  if (unknown === 0 || agents.every(a => a.input_tokens === null && a.output_tokens === null)) return null
  return `≥ ${known >= 1000 ? `${Math.round(known / 1000)}k` : known} tokens · ${unknown} unknown`
}

/** A token count the model reported, or "unknown" — never a made-up zero. */
export function tokens(run: Pick<Run, 'input_tokens' | 'output_tokens'>): string {
  if (run.input_tokens === null && run.output_tokens === null) return 'tokens unknown'
  const show = (n: number | null) => (n === null ? 'unknown' : n.toLocaleString('en-US'))
  return `in ${show(run.input_tokens)} · out ${show(run.output_tokens)}`
}

/**
 * What of the tokens sent the provider says it read again from its cache and wrote to it:
 * each part only where it said so, and null where it said neither - never a made-up zero.
 */
export function cached({ cache_read_tokens: read, cache_write_tokens: written }: { cache_read_tokens: number | null; cache_write_tokens: number | null }): string | null {
  const show = (n: number) => n.toLocaleString('en-US')
  if (read === null) return written === null ? null : `${show(written)} written to the cache`
  return `${show(read)} read again from the cache${written === null ? '' : ` · ${show(written)} written to it`}`
}

/**
 * What Copilot says an agent spent in its own unit: AI credits where it said them (given in billionths), else
 * premium requests, its older unit; null where it said neither - never a made-up zero.
 */
export function spent({ nano_aiu: nano, premium_requests: premium }: { nano_aiu: number | null; premium_requests: number | null }): string | null {
  const show = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })
  if (nano !== null) return `${nano > 0 && nano < 1e7 ? '< 0.01' : show(nano / 1e9)} AI credits`
  if (premium === null) return null
  return `${show(premium)} premium request${premium === 1 ? '' : 's'}`
}

/** What its last step sent, as a % of its model's window; null where either is not known. */
export function percentFull(sent: number | null, window: number | null): string | null {
  return sent === null || !window ? null : `${Math.round((sent / window) * 100)}%`
}

/** How full an agent's context is: what its last step sent, of its model's window; null where either is not known. */
export function contextFull(sent: number | null, window: number | null): string | null {
  const full = percentFull(sent, window)
  return full && `context ${full}`
}
