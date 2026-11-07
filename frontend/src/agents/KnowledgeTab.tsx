import { type CSSProperties, useState } from 'react'
import { errorText } from '../api/client'
import type { Knowledge, KnowledgeItem, KnowsMode, Provider, Role } from '../api/types'
import { type Sent, Sources } from '../knowledge/KnowledgeParts'
import type { RoleValues } from './AgentsPage'
import { EXPERT_MAY } from './roleTools'

export interface KnowledgeActions {
  /** K-bilgi: an expert made at once in the open project (its knowledge kept on its Knowledge page), and that knowledge saved. */
  createExpert?(role: RoleValues, knowledge: Knowledge): Promise<Role>
  /** A role uses a knowledge in full, as a map, or (null) no more. Throws ApiError with the server's reason. */
  useKnowledge?(knowledgeId: string, roleId: string, mode: KnowsMode | null): Promise<void>
}

/** Agents → New role → Expert: only what it knows and where it reads it. */
export function ExpertForm({ providers, onCreate, onCancel }: { providers: Provider[]; onCreate: (name: string, knowledge: Knowledge) => Promise<void>; onCancel: () => void }) {
  const [topic, setTopic] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = (sent: Sent) => {
    setBusy(true)
    setError(null)
    onCreate(`${topic.trim()} expert`, { ...sent, topic: topic.trim() })
      .catch(err => setError(errorText(err)))
      .finally(() => setBusy(false))
  }
  return (
    <div className="role-tab">
      <div className="field role-editor">
        <label htmlFor="expert-topic">Knows</label>
        <input id="expert-topic" className="input" value={topic} maxLength={40} placeholder="Stripe" aria-describedby="expert-topic-note" onChange={e => setTopic(e.target.value)} />
        <span id="expert-topic-note" className="muted">
          It reads its sources once, writes a short guide in the project, and answers from it: it advises and reads only.
        </span>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <Sources knowledge={null} providers={providers} busy={busy || !topic.trim()} button="Create expert" onSave={save} />
      <button type="button" className="btn btn-small" onClick={onCancel}>
        Cancel
      </button>
    </div>
  )
}

const ONLY_OWN = 'only a role of your own can be an expert'

/** Why a role cannot use a knowledge in full (the server's words, `knowledge_page.use`); null: it can. */
function cannotFull(role: Role, teamLead: boolean) {
  if (role.builtin || teamLead) return ONLY_OWN
  const beyond = role.tools.filter(tool => !EXPERT_MAY.includes(tool))
  return beyond.length > 0 ? `an expert advises and reads only: it has no ${beyond.join(', ')}` : null
}

/** K-bilgi (sample E): a role's Knowledge tab - the project's knowledge, each on or off and, when on, Full or Map, as the Tools tab's tiles. What a knowledge is and how it learns is the Knowledge page's. */
export function KnowledgeTab({ role, teamLead, projectId, items, onUse, onOpenKnowledge }: { role: Role; teamLead: boolean; projectId: string | null; items?: KnowledgeItem[]; onUse?: KnowledgeActions['useKnowledge']; onOpenKnowledge?: () => void }) {
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<{ text: string; error: boolean } | null>(null)
  const modeOf = (item: KnowledgeItem) => (role.knows ?? []).find(one => one.knowledge_id === item.id)?.mode ?? null
  const full = items?.find(item => modeOf(item) === 'full')
  const cannot = cannotFull(role, teamLead)
  const use = (item: KnowledgeItem, mode: KnowsMode | null) => {
    if (!onUse) return
    setBusy(true)
    setSaid(null)
    onUse(item.id, role.id, mode)
      .then(
        () => setSaid({ text: `${item.knowledge.topic}: ${mode === 'full' ? 'Full' : mode === 'map' ? 'Map' : 'off'}, saved.`, error: false }),
        err => setSaid({ text: errorText(err), error: true }),
      )
      .finally(() => setBusy(false))
  }
  if (!projectId) return <p className="muted">Open a folder: knowledge is a project’s, added on its Knowledge page.</p>
  if (!items) return <p className="muted">Reading the project’s knowledge…</p>
  return (
    <>
      {full && (
        <p className="muted">
          <span className="chip-knows">knows: {full.knowledge.topic}</span> advises · reads only
        </p>
      )}
      {said?.error && (
        <p role="alert" className="alert">
          {said.text}
        </p>
      )}
      {items.length === 0 ? (
        <p className="muted">This project has no knowledge yet.</p>
      ) : (
        <div className="tool-block" style={{ '--c': 'var(--tool-memory)' } as CSSProperties}>
          <div className="tool-tiles">
            {items.map(item => {
              const mode = modeOf(item)
              const topic = item.knowledge.topic
              const learned = item.state.learned
              return (
                <div key={item.id} className={`tool-tile skill-tile${mode ? ' tool-tile-on' : ''}`}>
                  <span className="tool-tile-name">
                    {topic}
                    <input type="checkbox" role="switch" className="switch" aria-label={`Knowledge ${topic}`} aria-describedby={`knows-${item.id}-line`} checked={!!mode} disabled={busy} onChange={e => use(item, e.target.checked ? 'map' : null)} />
                  </span>
                  <span id={`knows-${item.id}-line`} className="tool-tile-line">
                    {learned ? `${learned.pages.filter(one => one.read).length} pages read` : 'not learned'}
                    {item.project_id === null && ' · every project'}
                    {mode && <> · {mode === 'full' ? 'Full: its whole guide at each step' : 'Map: its guide, read when its work touches it'}</>}
                  </span>
                  {mode && (
                    <div className="files-modes" role="group" aria-label={`${topic}: how`}>
                      <button type="button" className="view-run" aria-pressed={mode === 'full'} disabled={busy || (!!cannot && mode !== 'full')} title={cannot ?? 'An expert in it: it advises and reads only'} onClick={() => mode !== 'full' && use(item, 'full')}>
                        Full
                      </button>
                      <button type="button" className="view-run" aria-pressed={mode === 'map'} disabled={busy} onClick={() => mode !== 'map' && use(item, 'map')}>
                        Map
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
      {onOpenKnowledge && (
        <button type="button" className="link-btn" onClick={onOpenKnowledge}>
          on Knowledge →
        </button>
      )}
      <span role="status" className="muted provider-note">
        {said && !said.error && said.text}
      </span>
    </>
  )
}
