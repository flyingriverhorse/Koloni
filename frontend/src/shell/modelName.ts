import { EFFORTS, type Effort, type Provider, type Tier } from '../api/types'

/**
 * A short display name for a model id. llama.cpp reports the full path of the
 * weights file as the id; show the file name without its extension. Nothing is made
 * up: where a CLI did not say which model it used, that is what is shown.
 */
export function modelName(id: string | null): string {
  if (!id) return 'model unknown'
  // A CLI run without a model name uses its own default and does not always say which.
  if (/^(claude|codex|qodercli|copilot) default$/.test(id)) return 'CLI default (model not reported)'
  if (!/\.gguf$/i.test(id)) return id
  const file = id.split(/[\\/]/).pop() ?? id
  return file.replace(/\.gguf$/i, '')
}

/** The model a lead's "how hard is this message" went to; null when nobody was asked, or it is not on record. */
type Asked = { provider_name: string; model_id: string } | null | undefined

const who = (asked: NonNullable<Asked>) => `${asked.provider_name} · ${modelName(asked.model_id)}`

/**
 * Said before a lead's reason where its model followed the message ("Lead model: automatic"):
 * nobody picked it, and how hard the message is was a model's guess - shown as that, and as
 * whose (a lead from before that was kept: "a fast model").
 */
export const autoModel = (asked: Asked) => `automatic, by ${asked ? who(asked) : 'a fast model'}’s guess`

/**
 * KOLONİ's own sentence for a lead whose model was to follow the message, when somebody was asked
 * and it did not. Fixed, and true of each way that happens: the question failed or was stopped,
 * its answer cannot be read, or the answer names a tier no model can be used from now.
 */
export const autoNothing = (asked: NonNullable<Asked>) =>
  `automatic: ${who(asked)} was asked, and nothing came of it (no answer to go by, or no model of the tier it said) - the Orchestrator’s model is what it would be without the question`

/** Before a model Copilot's auto picked for an agent asked for auto (`model_from` "auto"); nothing before any other. */
export const autoPicked = (modelFrom?: string | null) => (modelFrom === 'auto' ? 'auto → ' : '')

/**
 * Where an agent runs: its provider, its model, the tier of that model and the reasoning level its steps were
 * sent ("Claude Code · Opus 4.8 · strongest · high"). A model nobody knows is left out, and so is a tier it has
 * not and a level none was sent; a name read from the CLI's own settings, rather than reported by it, says so, and
 * one Copilot's auto picked says that ("auto → gpt-6-luna").
 */
export function ranOn(provider: string | null, modelId: string | null, modelFrom?: string | null, effort?: Effort | null, tier?: Tier | null): string {
  const model = modelId ? autoPicked(modelFrom) + modelName(modelId) + (modelFrom === 'settings' ? " (from Codex's settings)" : '') : null
  return [provider, model, tier, effort && EFFORTS[effort]].filter(Boolean).join(' · ')
}

/** The models something may be learned with: each provider's default and those it lists ("<provider id> <model>").
 *  One switched off (or on a provider switched off) is `off`: shown, so a choice saved on it reads as it is, not picked. */
export const modelChoices = (providers: Provider[]) =>
  providers.flatMap(p =>
    [...new Set([p.default_model, ...p.models.map(m => m.name)].filter((m): m is string => !!m))].map(model => {
      const off = p.enabled === false || p.models.some(m => m.name === model && m.enabled === false)
      return { value: `${p.id} ${model}`, label: `${p.name} · ${modelName(model)}${off ? ' — off' : ''}`, off }
    }),
  )
