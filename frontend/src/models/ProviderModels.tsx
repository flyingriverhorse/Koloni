import { Plus } from '@phosphor-icons/react'
import { errorText } from '../api/client'
import type { Availability, CatalogueFill, Provider, Usage } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { type GuideRow, ModelRow } from './ModelRow'
import type { ListedModel, Props as PageProps } from './ModelsPage'

export const MAX_MODELS = 30

interface Props extends Pick<PageProps, 'onFacts' | 'onSave'> {
  provider: Provider | null
  rows: GuideRow[]
  setRows: (rows: GuideRow[]) => void
  savedRows: () => GuideRow[]
  listed: ListedModel[]
  usual: boolean
  avail?: Availability | null
  used?: Usage['by_model'] | null
  onCheck?: () => Promise<void>
  persist: (next: GuideRow[], said: string) => Promise<void>
  adding: string | null
  setAdding: (adding: string | null) => void
  add: () => void
  listId: string
  propose: (() => Promise<CatalogueFill>) | null
  busy: boolean
  run: (action: () => Promise<void>) => Promise<void>
  draft: string
  noCatalogue: string | null
  setNoCatalogue: (draft: string | null) => void
  leftOut: number | null
  setLeftOut: (leftOut: number | null) => void
  modelsError: string | null
  setModelsError: (error: string | null) => void
  toast: string | null
  setToast: (toast: string | null) => void
}

/** The models agents and you can pick here, and how strong each is: read first, each change saved at once. */
export function ProviderModels({ provider, rows, setRows, savedRows, listed, usual, avail, used, onFacts, onSave, onCheck, persist, adding, setAdding, add, listId, propose, busy, run, draft, noCatalogue, setNoCatalogue, leftOut, setLeftOut, modelsError, setModelsError, toast, setToast }: Props) {
  const marks = new Map(avail?.models.map(m => [m.name, m]) ?? [])
  const setRow = (index: number, change: Partial<GuideRow>) => rows.map((row, at) => (at === index ? { ...row, ...change } : row))
  // What 30 days of the record say of a model of this provider; null where that is not known.
  // shortcut: K-model-puan's taken in / turned down / cost are on the Agents page's per-role table
  // only (its table is per role, not per model); add a per-model line here when the page loads /record.
  const usedOf = (model: string) => {
    if (!used || !provider) return null
    const one = used.find(row => row.provider_id === provider.id && row.model_id === model)
    if (!one) return 'not used'
    const turns = `${one.runs} message${one.runs === 1 ? '' : 's'}`
    if (one.input_tokens === null && one.output_tokens === null) return turns
    return `${turns}, ${((one.input_tokens ?? 0) + (one.output_tokens ?? 0)).toLocaleString('en-US')} tokens`
  }
  // Models with a tier first; those without one last (and faded). Each row keeps its place in the list.
  const shownRows = rows.map((row, index) => ({ row, index })).sort((a, b) => Number(!a.row.tier) - Number(!b.row.tier))
  return (
    <div className="provider-models">
      {rows.length > 0 && (
        // A narrow window scrolls the table, not the page.
        <div className="tools-table">
          <table className="usage-table model-table" aria-label="Models agents and you can pick">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Tier</th>
                <th scope="col">Context</th>
                <th scope="col">Max output</th>
                <th scope="col">Thinking</th>
                <th scope="col">Price in / out (1M)</th>
                <th scope="col" aria-label="Agents may use">
                  Agents may use <Hint doc={GUIDE.providerModels}>On: agents may pick this model by themselves (tiers, Auto). Off: only you pick it in a chat.</Hint>
                </th>
                <th scope="col" aria-label="On">
                  On{' '}
                  <Hint doc={GUIDE.providerModels}>
                    Off: nobody uses this model, not you, not agents, not the tiers. KOLONİ switches a model off itself when Copilot
                    says it can’t use it on your account (the reason shows beside it). The provider’s own switch turns all its models
                    off.
                  </Hint>
                </th>
                <th scope="col">
                  <span className="visually-hidden">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shownRows.map(({ row, index }) => (
                <ModelRow
                  key={row.name}
                  row={row}
                  provider={provider}
                  avail={avail ? (marks.get(row.name) ?? null) : undefined}
                  used={usedOf(row.name)}
                  onFacts={onFacts}
                  onTier={tier => void persist(setRow(index, { tier }), `${row.name}: ${tier ?? 'no tier'}.`)}
                  onAgents={on =>
                    void persist(setRow(index, { agents: on }), `Agents ${on ? 'may' : 'may not'} use ${row.name} now.`)
                  }
                  onEnabled={on =>
                    void persist(setRow(index, { enabled: on }), `${row.name} is switched ${on ? 'on' : 'off'}.`)
                  }
                  onInputs={inputs => void persist(setRow(index, { inputs }), `What ${row.name} takes is saved.`)}
                  onContext={context =>
                    void persist(setRow(index, { context }), `${row.name}: ${context === 'long_context' ? 'long' : 'default'} context.`)
                  }
                  onNote={text => setRows(setRow(index, { note: text }))}
                  onNoteDone={() =>
                    row.note.trim() !== (provider?.models.find(m => m.name === row.name)?.note ?? '') &&
                    void persist(rows, `The note of ${row.name} is saved.`)
                  }
                  onRemove={() => void persist(rows.filter((_, at) => at !== index), `${row.name} removed.`)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {adding !== null && (
        <div className="model-add">
          <input
            className="input mono"
            list={listId}
            aria-label="New model’s name"
            value={adding}
            maxLength={200}
            placeholder="As the provider knows it"
            autoFocus
            onChange={e => setAdding(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault()
                add()
              } else if (e.key === 'Escape') {
                e.preventDefault() // (the window stays open)
                setAdding(null)
              }
            }}
          />
          <button type="button" className="btn btn-small btn-primary" onClick={add}>
            Add
          </button>
          <button type="button" className="btn btn-small" onClick={() => setAdding(null)}>
            Cancel
          </button>
        </div>
      )}
      <div className="role-actions">
        {adding === null && (
          <button type="button" className="btn btn-small" disabled={rows.length >= MAX_MODELS} onClick={() => setAdding('')}>
            <Plus size={13} />
            Add a model
          </button>
        )}
        {propose && (
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            title="Proposes the known models; nothing is saved until you save them"
            onClick={() =>
              void run(async () => {
                const offer = await propose()
                // Nothing beyond what was typed: there is no catalogue for it.
                // shortcut: a list that already holds every catalogued model reads as none
                // too; let the answer say whether there is a catalogue if that ever matters.
                const none = !provider && offer.models.length === listed.length && offer.left_out === 0
                setNoCatalogue(none ? draft : null)
                // A model already listed keeps whether agents may use it; one more joins the provider's way.
                const had = new Map(rows.map(row => [row.name, row.agents]))
                setRows(offer.models.map(m => ({ name: m.name, note: m.note ?? '', tier: m.tier ?? null, agents: had.get(m.name) ?? usual, ...(m.context && { context: m.context }) })))
                setLeftOut(none ? null : offer.left_out)
              })
            }
          >
            Fill from the catalogue
          </button>
        )}
        {provider && onCheck && (
          <button
            type="button"
            className="btn btn-small"
            disabled={busy}
            title="Looks again whether each model can be used now; no model is run"
            onClick={() => void run(onCheck)}
          >
            Check
          </button>
        )}
        <Hint doc={GUIDE.providerModels}>
          Your own list, kept with this provider and offered wherever a model is picked; an agent can choose only these
          here, besides the default model. A model with no tier is only ever picked by name.
        </Hint>
      </div>
      {noCatalogue === draft && (
        <span className="muted provider-note">No catalogue for this address; the models will be listed once it is added.</span>
      )}
      {rows.some(row => marks.get(row.name)?.retired) && (
        <span className="muted provider-note">
          Being retired: models.dev says so. Such a model still runs, and is no longer offered for new picks.
        </span>
      )}
      {leftOut !== null && (
        <div role="status" className="muted provider-note">
          Proposed from the catalogue and the provider’s own list, not saved yet: look it over, then save it.
          {leftOut > 0 && ` ${leftOut} left out: models that cannot chat, or past the ${MAX_MODELS} the list holds (the strongest are kept).`}
          {provider && (
            <span className="role-actions">
              <button
                type="button"
                className="btn btn-small btn-primary"
                onClick={() => {
                  setLeftOut(null)
                  void (async () => {
                    setModelsError(null)
                    try {
                      await onSave(provider.id, { models: listed })
                      setToast('The proposed models are saved.')
                    } catch (err) {
                      setModelsError(errorText(err))
                    }
                  })()
                }}
              >
                Save these models
              </button>
              <button
                type="button"
                className="btn btn-small"
                onClick={() => {
                  setLeftOut(null)
                  setRows(savedRows())
                }}
              >
                Cancel
              </button>
            </span>
          )}
        </div>
      )}
      {modelsError && (
        <div role="alert" className="alert">
          {modelsError}
        </div>
      )}
      {/* A change saved at once is said for a moment; there is nothing to undo but the change itself. */}
      <span role="status" className="muted provider-note">
        {toast}
      </span>
    </div>
  )
}
