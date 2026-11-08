import { useEffect, useState } from 'react'
import { EFFORTS, type Effort, type ModelFacts } from '../api/types'

/** The reasoning levels a model takes ([]: none, or not said - nothing is sent); undefined while looked up, null where that failed. */
export type Takes = Effort[] | null | undefined

/** What is known of a model on a provider. Throws ApiError. */
export type LoadFacts = (providerId: string, model: string) => Promise<ModelFacts>

/**
 * What is known of the model being picked: undefined while it is looked up, null where that failed.
 * Looked up a moment after the name stops changing - a server on this machine is asked - and an
 * answer for a name typed over since is dropped.
 */
export function useModelFacts(load: LoadFacts | undefined, providerId: string | null, model: string, again = 0) {
  const [facts, setFacts] = useState<ModelFacts | null>()
  useEffect(() => {
    setFacts(undefined)
    if (!load || !providerId) return
    let current = true
    const timer = setTimeout(() => {
      load(providerId, model).then(
        told => current && setFacts(told),
        () => current && setFacts(null),
      )
    }, 300)
    return () => {
      current = false
      clearTimeout(timer)
    }
    // (`again`: looked up once more - what was tried taken away, slice 85b.)
  }, [load, providerId, model, again])
  return facts
}

/** A model's levels as its facts say them; "Could not look up" only where asking really failed. */
export function takesOf(facts: ModelFacts | null | undefined): Takes {
  if (facts === undefined) return undefined
  if (facts === null || (facts.failed && facts.efforts === null)) return null
  return facts.efforts ?? []
}

const FROM: Record<string, string> = {
  you: 'set by you',
  catalog: 'from the catalogue',
  server: 'from the server',
  anthropic: 'from Anthropic',
  docs: 'from OpenAI’s docs',
}

/** The day a catalogue was read, and the time where an update gave one. A bare day ("2026-10-21") is that day
 *  here: `new Date` would read it as midnight UTC, the day before west of Greenwich. */
export function dayOf(when: string, time = when.length > 10): string {
  const [y, m, d] = when.slice(0, 10).split('-').map(Number)
  const at = when.length > 10 ? new Date(when) : new Date(y, m - 1, d)
  return at.toLocaleString('en-GB', { day: 'numeric', month: 'short', ...(time ? { hour: '2-digit', minute: '2-digit' } : {}) })
}

/** Where a fact came from, in words: models.dev's with the day its copy was read - "models.dev (deepseek)" where
 *  another service has the model its own does not. */
export function sourceOf(facts: ModelFacts, fact: string): string {
  const source = facts.sources[fact]
  const day = facts.catalogue_date && dayOf(facts.catalogue_date, false)
  return source?.startsWith('models.dev') ? `from ${source}${day ? `, ${day}` : ''}` : (FROM[source] ?? source)
}

/** The rest of what is known of a model, in a line: its window, the most it writes, its price, its tier, and whether it is being retired. */
export function factsText(facts: ModelFacts | null | undefined): string {
  if (facts === undefined) return 'Looking up the model…'
  if (facts === null) return 'Could not look up the model.'
  const said = [
    facts.context_window && `reads ${facts.context_window.toLocaleString('en-US')} tokens at most, ${sourceOf(facts, 'context_window')}`,
    facts.max_output && `writes ${facts.max_output.toLocaleString('en-US')} at most`,
    facts.price && `${facts.price.input} / ${facts.price.output} ${facts.price.currency} a million tokens in / out, ${sourceOf(facts, 'price')}`,
    facts.tier && `${facts.tier}, ${sourceOf(facts, 'tier')}`,
    facts.deprecated && 'being retired: it still runs, and is no longer offered',
  ]
    .filter(Boolean)
    .join(' · ')
  if (!said) return facts.failed ? 'Could not look up the model.' : 'Nothing more is known of this model.'
  return `${said[0].toUpperCase()}${said.slice(1)}.`
}

/** Why a model takes no level, where the server says (`catalog.facts`): its name sets it (B-404), or it is Copilot's auto, which picks it. */
export type Named = false | 'name' | 'auto'
const NAMED: Record<string, Named> = { 'its name says its level': 'name', 'Copilot picks it (auto)': 'auto' }
export const namedLevel = (facts: ModelFacts | null | undefined): Named => NAMED[facts?.sources.efforts ?? ''] ?? false
/** The same of a role's model as the roles' list says it (`level_named`): only Copilot's takes the name auto. */
export const namedOf = (levelNamed: boolean | undefined, model: string | null | undefined): Named => levelNamed ? (model === 'auto' ? 'auto' : 'name') : false
/** Why none is sent, in a line's words. */
export const NAMED_WHY: Record<'name' | 'auto', string> = { name: 'its name sets its level', auto: 'Copilot picks the model and its level' }

/** What is known of a model's levels, for the note under a level's select. `named`: why it takes none. */
export function levelsKnown(takes: Takes, named: Named = false): string {
  if (takes === undefined) return 'Looking up the model’s levels…'
  if (takes === null) return 'Could not look up the model’s levels.'
  if (takes.length) return `Its model takes: ${takes.map(level => EFFORTS[level]).join(', ')}.`
  const why = named ? NAMED_WHY[named] : 'the model’s levels are not known'
  return `${why[0].toUpperCase()}${why.slice(1)}: nothing is sent.`
}

/** A level's select may be changed where its model takes some, or to take a saved one back to Default. */
export const levelsDisabled = (takes: Takes, value: Effort | null) => !takes?.length && value === null

/** A saved level its model does not take: none goes where it takes none, else the nearest lower one it takes (if any). */
const untaken = (takes: Effort[]) => (takes.length ? ' (not taken: the nearest lower level it takes is sent, if any)' : ' (not sent to this model)')

/** Default, the levels the model takes, and a saved level it is known not to take, said as such. */
export function LevelOptions({ takes, value }: { takes: Takes; value: Effort | null }) {
  return (
    <>
      <option value="">Default</option>
      {(Object.keys(EFFORTS) as Effort[])
        .filter(level => takes?.includes(level) || level === value)
        .map(level => (
          <option key={level} value={level}>
            {EFFORTS[level]}
            {Array.isArray(takes) && !takes.includes(level) ? untaken(takes) : ''}
          </option>
        ))}
    </>
  )
}
