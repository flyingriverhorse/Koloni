import { type FormEvent, useEffect, useRef, useState } from 'react'
import { errorText } from '../api/client'
import type { MemorySearch, ProjectMemory } from '../api/types'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import {
  decisionId,
  decisionOf,
  hasWords,
  linesOf,
  matches,
  rowId,
  saidWhere,
  type Tab,
  TABS,
  waitId,
} from './memoryText'
import { RecordCard } from './RecordCard'

/** Where a hit is: what waits for your word (above the tabs), or one of the tabs. */
type Place = Tab | 'waiting'
const PLACES = [['waiting', 'Waiting for your word'], ...TABS] as const

/** What a record of a linked project says of itself (22c): the server's words for an agent, in short. */
const NOT_CHECKED_HERE = 'its files are not in this project: it could not be checked here'

interface Hit {
  id: string
  text: string
}

/** What on this page has every word typed, by the tab it is under; the id is the row (or the box) it is on. */
function pageHits(memory: ProjectMemory, query: string): Record<Place, Hit[]> {
  const rows = (records: ProjectMemory['core'], at = rowId) =>
    records.filter(record => matches(record, query)).map(record => ({ id: at(record.id), text: record.text }))
  const lines = (text: string | null | undefined, id: string) =>
    linesOf(text)
      .filter(line => hasWords(line, query))
      .map(line => ({ id, text: line.trim() }))
  return {
    waiting: rows(memory.proposals, waitId),
    told: [
      ...lines(memory.preferences, 'memory-preferences'),
      ...rows(memory.suggestions ?? []),
      ...lines(memory.rules, 'memory-rules'),
    ],
    facts: rows(memory.core),
    notes: rows(memory.journal),
    history: [
      ...memory.decisions
        .filter(decision => hasWords(`${decisionOf(decision)} ${decision.text ?? ''}`, query))
        .map(decision => ({
          id: decisionId(decision),
          text: [decisionOf(decision), decision.text].filter(Boolean).join(' · '),
        })),
      ...rows(memory.past),
    ],
  }
}

interface Props {
  memory: ProjectMemory
  /** Opens a tab at a row: a hit was clicked. */
  onOpen: (place: Place, id: string) => void
  /** What an agent's `recall` would find; left out, there is no search deeper. */
  onSearch?: (query: string) => Promise<MemorySearch>
  /** Come from Ctrl+K: these words, searched deeper at once. */
  searchFor?: string
}

/**
 * One search over the whole page, two layers deep. As you type, what is on the page is sifted, by
 * tab; Enter searches deeper, as an agent's `recall` does: the memory, what was said in the
 * project's earlier messages, and the linked projects - each as it was said, with whose words.
 */
export function Find({ memory, onOpen, onSearch, searchFor }: Props) {
  const [query, setQuery] = useState(searchFor ?? '')
  const [deeper, setFound] = useState<{ query: string; result: MemorySearch } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Only the latest search counts: an older one's answer that comes later is not shown.
  const searches = useRef(0)
  const form = useRef<HTMLFormElement>(null)
  useEffect(() => {
    if (searchFor === undefined) return
    // Come from Ctrl+K: the box and what it finds are in sight (no smooth scroll).
    form.current?.scrollIntoView?.({ block: 'start' })
    if (searchFor.trim()) form.current?.requestSubmit()
  }, [searchFor])

  async function submit(event: FormEvent) {
    event.preventDefault()
    const asked = query.trim()
    if (!asked || !onSearch) return
    const mine = ++searches.current
    setBusy(true)
    setError(null)
    try {
      const result = await onSearch(asked)
      if (mine === searches.current) setFound({ query: asked, result })
    } catch (err) {
      if (mine === searches.current) setError(errorText(err))
    } finally {
      if (mine === searches.current) setBusy(false)
    }
  }

  const typed = query.trim()
  const hits = typed ? pageHits(memory, typed) : null
  // An emptied box clears what was found deeper too.
  const found = typed ? deeper : null
  /** How many on this page have the words typed, and that Enter searches deeper; empty while nothing is typed. */
  const status = () => {
    const count = hits ? Object.values(hits).reduce((n, list) => n + list.length, 0) : 0
    return (
      <div role="status" className="muted memory-hint">
        {hits &&
          (count === 0
            ? `Nothing on this page has “${typed}”.`
            : `${count} on this page ${count === 1 ? 'has' : 'have'} “${typed}”.`)}
        {hits && onSearch && ' Enter searches deeper.'}
      </div>
    )
  }
  return (
    <section className="memory-find-box" aria-label="Search">
      <div className="memory-find">
        <form ref={form} role="search" className="memory-find-form" onSubmit={submit}>
          <input
            autoFocus={searchFor !== undefined}
            className="input"
            aria-label="Search everything this project remembers"
            placeholder="Search everything this project remembers"
            maxLength={300}
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          {onSearch && (
            <button type="submit" className="btn btn-small" disabled={busy || !typed}>
              Search deeper
            </button>
          )}
        </form>
        <Hint doc={GUIDE.memorySearch}>
          As you type, what is on this page is sifted. Search deeper (Enter) is the same search an agent’s recall makes:
          it looks in the memory, in what was said in this project’s earlier messages - yours, the Orchestrator’s
          answers and agents’ reports, never what a tool returned - and in the linked projects.
        </Hint>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {/* (On the page from the start, so the first count is announced too.) */}
      {status()}
      {hits && (
        <div className="memory-hits">
          {PLACES.map(
            ([tab, label]) =>
              hits[tab].length > 0 && (
                <div key={tab} role="group" aria-label={tab === 'waiting' ? label : `In ${label}`}>
                  <h4 className="memory-found-head">{tab === 'waiting' ? label : `In ${label}`}</h4>
                  <ul className="memory-list">
                    {hits[tab].map((hit, i) => (
                      <li key={`${hit.id}:${i}`}>
                        <button type="button" className="memory-hit" onClick={() => onOpen(tab, hit.id)}>
                          {hit.text}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ),
          )}
        </div>
      )}
      <div aria-live="polite">{found && deeperFound(found)}</div>
    </section>
  )
}

/** What a search deeper found, as an agent's `recall` would: in the memory, in earlier messages, and in the linked projects. */
function deeperFound(found: { query: string; result: MemorySearch }) {
  const own = found.result.memory.filter(record => !record.from_project)
  const linked = found.result.memory.filter(record => record.from_project)
  const saidHere = found.result.turns.filter(said => !said.project)
  const saidLinked = found.result.turns.filter(said => said.project)
  return (
    <>
      <h4 className="memory-found-head">Searched deeper for “{found.query}”</h4>
      {own.length === 0 ? (
        <p className="muted">Nothing on record speaks to “{found.query}”.</p>
      ) : (
        <ul className="memory-list" aria-label="What an agent would find in the memory">
          {own.map(record => (
            <li key={record.id}>
              <RecordCard record={record} />
            </li>
          ))}
        </ul>
      )}
      <h4 className="memory-found-head">In earlier messages</h4>
      {saidHere.length === 0 ? (
        <p className="muted">Nothing said in earlier messages speaks to “{found.query}”.</p>
      ) : (
        <ul className="memory-list" aria-label="In earlier messages">
          {saidHere.map(said => (
            <Said key={`${said.run_id}:${said.who}:${said.at}`} said={said} />
          ))}
        </ul>
      )}
      {(linked.length > 0 || saidLinked.length > 0) && (
        <>
          <h4 className="memory-found-head">In linked projects</h4>
          <ul className="memory-list" aria-label="In linked projects">
            {linked.map(record => (
              <li key={record.id}>
                <div className="memory-meta mono">
                  <span className="tag">from project {record.from_project}</span>
                  <span className="muted">{NOT_CHECKED_HERE}</span>
                </div>
                <RecordCard record={record} />
              </li>
            ))}
            {saidLinked.map(said => (
              <Said key={`${said.run_id}:${said.who}:${said.at}`} said={said} />
            ))}
          </ul>
        </>
      )}
    </>
  )
}

function Said({ said }: { said: MemorySearch['turns'][number] }) {
  return (
    <li className="memory-record">
      <div className="memory-said-text">“{said.excerpt}”</div>
      <div className="memory-meta mono muted">
        {saidWhere(said)}
        {said.project && <span className="tag">from project {said.project}</span>}
      </div>
    </li>
  )
}
