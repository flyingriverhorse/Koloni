import { FilePdf, FilmStrip, Image, SpeakerHigh } from '@phosphor-icons/react'
import { INPUTS, type ModelFacts, type ModelInput } from '../api/types'

const ICON = { image: Image, video: FilmStrip, audio: SpeakerHigh, pdf: FilePdf }
const WORD: Record<ModelInput, string> = { image: 'images', video: 'video', audio: 'audio', pdf: 'PDFs' }

type Said = ModelFacts['inputs'][number]

/** One kind a model takes or does not, and who said it: "images ✓ (seen)", "takes video, said by models.dev". */
export function inputText(said: Said): string {
  const word = WORD[said.kind]
  if (said.source === 'tried') return said.takes ? `${word} ✓ (seen)` : `doesn’t take ${word} (tried)`
  return `${said.takes ? 'takes' : 'doesn’t take'} ${word}, ${said.source === 'you' ? 'set by you' : 'said by models.dev'}`
}

const FROM = { tried: 'tried', you: 'set by you', 'models.dev': 'models.dev' } as const

/** All a model takes in one line, each source said once: "images, video, PDFs; not audio (models.dev)". */
export function inputsLine(inputs: Said[] | null | undefined): string | null {
  if (!inputs?.length) return null
  return (Object.keys(FROM) as Said['source'][])
    .map(source => {
      const of = inputs.filter(said => said.source === source)
      if (!of.length) return ''
      const takes = of.filter(said => said.takes).map(said => WORD[said.kind])
      const not = of.filter(said => !said.takes).map(said => WORD[said.kind])
      return `${[takes.join(', '), not.length ? `not ${not.join(', ')}` : ''].filter(Boolean).join('; ')} (${FROM[source]})`
    })
    .filter(Boolean)
    .join(' · ')
}

/** The facts with the user's marks as the row has them now - saved or not yet read back; what was tried still wins. */
export function withMarks(facts: ModelFacts | null | undefined, marked: ModelInput[] | null | undefined): ModelFacts | null | undefined {
  if (!facts || marked == null) return facts
  const tried = (facts.inputs ?? []).filter(said => said.source === 'tried')
  const mine = INPUTS.filter(kind => !tried.some(said => said.kind === kind)).map(kind => ({ kind, takes: marked.includes(kind), source: 'you' as const }))
  return { ...facts, inputs: [...mine, ...tried] }
}

/** Small icons for what a model takes besides text (slice 85b); none where nothing says it takes any. */
export function InputIcons({ facts }: { facts: ModelFacts | null | undefined }) {
  // (Facts from before slice 85b have no inputs.)
  const taken = facts?.inputs?.filter(said => said.takes) ?? []
  if (!taken.length) return null
  return (
    <span className="model-inputs">
      {taken.map(said => {
        const Icon = ICON[said.kind]
        return (
          <span key={said.kind} role="img" aria-label={inputText(said)} title={inputText(said)}>
            <Icon size={13} />
          </span>
        )
      })}
    </span>
  )
}

/** The kinds the user marks a model to take by hand (null: not marked). Unmarked, the boxes show what is known
 * (what was tried, else the catalogue); a click starts the user's own marks from there. */
export function MarkInputs({ name, marked, known, onChange }: {
  name: string
  marked: ModelInput[] | null | undefined
  known?: Said[] | null
  onChange: (inputs: ModelInput[]) => void
}) {
  const now = marked ?? INPUTS.filter(kind => {
    const said = known?.filter(one => one.kind === kind) ?? []
    return (said.find(one => one.source === 'tried') ?? said[0])?.takes ?? false
  })
  return (
    <span className="model-mark-inputs">
      {INPUTS.map(kind => (
        <label key={kind}>
          <input
            type="checkbox"
            aria-label={`${name} takes ${WORD[kind]}`}
            checked={now.includes(kind)}
            onChange={e => onChange(e.target.checked ? [...now, kind] : now.filter(k => k !== kind))}
          />
          {WORD[kind]}
        </label>
      ))}
    </span>
  )
}
