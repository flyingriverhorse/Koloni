import { type ReactNode, useCallback, useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { MemoryRecord, MemorySearch, ProjectMemory } from '../api/types'
import type { ConvState } from '../state/applyEvent'
import { useApp } from '../state/store'
import { Cell } from '../shell/Cell'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { Find, type Place } from './Find'
import { type NewFact, WriteBox } from './forms'
import { MemoryParts, Ways } from './MemoryParts'
import {
  byTopic,
  decisionId,
  decisionOf,
  FACT_CELL,
  lastAutoText,
  meter,
  moment,
  partId,
  subject,
  wouldReplace,
  writerOf,
} from './memoryText'
import { CoreFact, JournalNote, PastRecord, Proposal } from './records'
import { YourWords } from './YourWords'

interface Props {
  /** The open project's memory; null until it has been read. */
  memory: ProjectMemory | null
  /** Why it could not be read, if it could not. */
  error?: string | null
  /** Each of these throws ApiError with the server's reason; the memory is read again after. */
  onApprove: (id: string, text?: string) => Promise<void>
  onReject: (id: string) => Promise<void>
  onRestore: (id: string) => Promise<void>
  /** Of a source that moved: these are the same lines. */
  onConfirm: (id: string) => Promise<void>
  onCorrect: (id: string, changes: { text: string; about: string | null }) => Promise<void>
  onWrite: (fact: NewFact) => Promise<void>
  onSaveRules: (rules: string) => Promise<void>
  /** 0.1.10: the Project notes, the rules' second box - what you kept at turns' ends. */
  onSaveProjectNotes: (text: string) => Promise<void>
  /** Your own preferences (22b), one text for every project; and a suggested line into them. */
  onSavePreferences: (text: string) => Promise<void>
  onAddPreference: (id: string) => Promise<void>
  onReload: () => Promise<void>
  /** What an agent's `recall` would find for these words; left out, there is no search deeper. */
  onSearch?: (query: string) => Promise<MemorySearch>
  /** Saves the core as a Markdown file; left out when there is no project. */
  onExport?: () => Promise<void>
  /** Come from "Search in messages" (Ctrl+K), each time with a new count: the search box takes the focus, and searches the words deeper. */
  searchFor?: { words: string; n: number }
  /** 0.1.10: the page's second part, its sources (`KnowledgePage`); left out, the page is its first part alone. */
  sourcesPart?: ReactNode
  /** Whether the sources are the part shown; and the way to the other part. */
  sources?: boolean
  onPart?: (sources: boolean) => void
  /** How many sources may be old, on their part's tab; null while they are read. */
  old?: number | null
  /** The other projects Search deeper and Recall also look in, by name; and the way to change them. */
  linked?: string[]
  onLinked?: () => void
}

function Section({
  title,
  hint,
  more,
  children,
}: {
  title: string
  hint?: string
  more?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="memory-section" aria-label={title}>
      <h3>{title}</h3>
      {(hint || more) && (
        <div className="muted memory-hint">
          {hint} {more && <Hint doc={GUIDE.memoryKinds}>{more}</Hint>}
        </div>
      )}
      {children}
    </section>
  )
}

/** An area's one line of what it holds, its "?", and its own controls at the right. */
function AreaHead({ line, more, children }: { line: string; more: ReactNode; children?: ReactNode }) {
  return (
    <div className="memory-tab-head">
      <span className="muted memory-hint">
        {line} <Hint doc={GUIDE.memoryKinds}>{more}</Hint>
      </span>
      {children}
    </div>
  )
}

/** A filter of an area by subject: '' for all, otherwise '=' and the subject as compared. */
function TopicFilter({
  records,
  value,
  onChange,
}: {
  records: MemoryRecord[]
  value: string
  onChange: (value: string) => void
}) {
  return (
    <select className="input memory-filter" aria-label="Topic" value={value} onChange={e => onChange(e.target.value)}>
      <option value="">All topics</option>
      {byTopic(records).map(topic => (
        <option key={topic.about ?? ''} value={`=${subject(topic.about)}`}>
          {topic.about ?? 'no subject'}
        </option>
      ))}
    </select>
  )
}

const ofTopic = (records: MemoryRecord[], topic: string) =>
  topic ? records.filter(record => `=${subject(record.about)}` === topic) : records

/** The core's room: ten cells, filled as its facts take room, with the count beside them (a full core refuses more). */
function Room({ chars, limit }: { chars: number; limit: number }) {
  const said = meter(chars, limit)
  const used = Math.min(10, Math.round((10 * chars) / Math.max(limit, 1)))
  return (
    <span className="memory-room">
      {Array.from({ length: 10 }, (_, at) => (
        <Cell key={at} tone={at < used ? 'honey' : 'plain'} fill={at < used ? 'full' : 'none'} label={said} hidden />
      ))}
      <span className="mono muted memory-count">{said}</span>
    </span>
  )
}

/** What a fact's cell says, each in words. */
function FactLegend() {
  return (
    <p className="cell-legend">
      {Object.values(FACT_CELL).map(one => (
        <span key={one.word}>
          <Cell tone={one.tone} fill={one.fill} label={one.word} hidden />
          {one.word}
        </span>
      ))}
    </p>
  )
}

/**
 * Which turn the last notes made by themselves were of: one of the open conversation's, when it
 * is there; only that it is another conversation's otherwise.
 */
function lastTurnOf(memory: ProjectMemory | null, conv: ConvState | null) {
  const ofAuto = memory?.last_auto ? conv?.runs.find(run => run.id === memory.last_auto?.run_id) : undefined
  return ofAuto && conv
    ? `the work on the ${moment(ofAuto.created_at)} message in “${conv.conversation.title}”`
    : 'a message of a conversation not open here'
}

const FACTS_MORE =
  'What agents are given: what you approved or wrote, each with its source. A fact is given to an agent whose work names its subject; any agent can look the rest up. Each rests on file lines: a fact whose source changed, or moved within its file, is given to no agent until you look at it again. “Source unchanged since noted” only means the file lines a record rests on read as they did when it was written. It does not mean the record is right.'

/** The core saved as MEMORY.md (`download`: the key in no address the browser keeps), and a refusal said beside it. */
function ExportButton({ onExport }: { onExport: () => Promise<void> }) {
  const [failed, setFailed] = useState<string | null>(null)
  const save = () => {
    setFailed(null)
    onExport().catch((err: unknown) => setFailed(errorText(err)))
  }
  return (
    <>
      <button
        type="button"
        className="btn btn-small"
        onClick={save}
        title="The core as a Markdown file to read. A copy: editing it does not change the memory."
      >
        Export
      </button>
      {failed && (
        <span role="alert" className="alert">
          {failed}
        </span>
      )}
    </>
  )
}

/**
 * What this project remembers (0.1.10, as cells): one search and the three ways memory reaches an agent on top, then the
 * page's two parts. What the project knows: what waits for your word in one honey box; the core's facts, each with a
 * cell for how it stands, and the journal's notes at the left, History folded under them; your own words at the right.
 * Its sources are the second part. Nothing is shown as surer than its record: a source is unchanged, changed, or not
 * there.
 */
export function MemoryPage({
  memory,
  error,
  onReload,
  onSearch,
  onExport,
  searchFor,
  sourcesPart,
  sources = false,
  onPart,
  old = null,
  linked,
  onLinked,
  ...on
}: Props) {
  const [factTopic, setFactTopic] = useState('')
  const [noteTopic, setNoteTopic] = useState('')
  const [writer, setWriter] = useState('')
  const [adding, setAdding] = useState(false)
  // A note made a fact: the box opens with its words (keyed, so it starts again each time).
  const [draft, setDraft] = useState<{ text: string; about: string; n: number } | undefined>(undefined)
  // A row to go to once it is shown: a search hit, or the fact box.
  const [goTo, setGoTo] = useState<{ id: string; n: number } | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  useEffect(() => {
    if (!goTo) return
    const row = document.getElementById(goTo.id)
    row?.scrollIntoView?.({ block: 'center' })
    // (Not from a question that took the focus: "Replace what you typed?")
    if (!document.activeElement?.closest('[role="alertdialog"]')) row?.focus()
  }, [goTo])
  // (Once, as it is shown: the page is drawn again while it stands - a source learning on the other part.)
  const focusOnce = useCallback((said: HTMLElement | null) => said?.focus(), [])
  const conv = useApp(s => s.conv)
  const lastTurn = lastTurnOf(memory, conv)
  // Once something waited, its box stays while the page is open: deciding the last note does not take the place you were in.
  const [waited, setWaited] = useState(false)
  if (!waited && memory && memory.proposals.length > 0) setWaited(true)

  // A hit, or the fact box: History unfolded for one of its rows, and this part shown.
  const go = (to: Place, id: string) => {
    if (to === 'history') setHistoryOpen(true)
    if (sources) onPart?.(false)
    setGoTo(was => ({ id, n: (was?.n ?? 0) + 1 }))
  }
  // A hit is shown whatever the filters said.
  const open = (to: Place, id: string) => {
    setFactTopic('')
    setNoteTopic('')
    setWriter('')
    go(to, id)
  }
  const makeFact = (record: MemoryRecord) => {
    setDraft(was => ({ text: record.text, about: record.about ?? '', n: (was?.n ?? 0) + 1 }))
    setAdding(true)
    go('facts', 'new-fact')
  }
  const panelOf = (part: boolean) =>
    onPart
      ? {
          id: `${partId(part)}-panel`,
          role: 'tabpanel',
          'aria-labelledby': partId(part),
          hidden: part !== sources,
          className: 'memory-part',
        }
      : { className: 'memory-part' }
  /** The page: its head, the search, the three ways and the two parts' tabs, then the part shown. */
  const page = (knows: ReactNode) => (
    <div className="memory-page">
      <div className="memory-top">
        <h2>Memory</h2>
        <span className="muted memory-hint">
          What the project carries from chat to chat; a job’s own notes are in its notebook.
        </span>
      </div>
      {memory && (
        <Find key={searchFor?.n} memory={memory} onOpen={open} onSearch={onSearch} searchFor={searchFor?.words} />
      )}
      <Ways />
      {onPart && (
        <MemoryParts sources={sources} onPart={onPart} waiting={memory ? memory.proposals.length : null} old={old} />
      )}
      <div {...panelOf(false)}>
        {error && (
          <div role="alert" className="alert">
            {error}
          </div>
        )}
        {knows}
      </div>
      {sourcesPart && <div {...panelOf(true)}>{sourcesPart}</div>}
    </div>
  )
  if (!memory) return page(!error && <p className="muted">Reading the project’s memory…</p>)

  // A filter whose topic or writer is gone since (removed, corrected) shows all again.
  const factsOf = ofTopic(memory.core, factTopic).length ? factTopic : ''
  const notesOf = ofTopic(memory.journal, noteTopic).length ? noteTopic : ''
  const writers = [...new Set(memory.journal.map(writerOf))]
  const by = writers.includes(writer) ? writer : ''
  const facts = ofTopic(memory.core, factsOf)
  const notes = ofTopic(memory.journal, notesOf).filter(record => !by || writerOf(record) === by)
  const lastAuto = lastAutoText(memory.last_auto, lastTurn)
  const waiting = memory.proposals.length

  /** What waits for your word: the one honey box, on top, each note beside the fact it would replace. */
  const waits = () =>
    (waiting > 0 || waited) && (
      <section id="memory-waits" className="memory-waits" aria-label="Waits for you">
        {waiting > 0 ? (
          <>
            <h3>
              <Cell tone="honey" fill="soft" label="waits for your word" hidden />
              {waiting} {waiting === 1 ? 'fact waits' : 'facts wait'} for your word
            </h3>
            <p className="muted memory-hint">
              Notes agents put forward for the core. Nothing enters the core unless you approve it.
            </p>
          </>
        ) : (
          // (Shown as the last note is decided: the focus goes here, not to the page.)
          <p className="muted" tabIndex={-1} ref={focusOnce}>
            Nothing waits for you.
          </p>
        )}
        {memory.proposals.map(record => (
          <Proposal
            key={record.id}
            record={record}
            replaces={wouldReplace(memory, record)}
            onApprove={on.onApprove}
            onReject={on.onReject}
            onConfirm={on.onConfirm}
          />
        ))}
      </section>
    )

  /** Facts: the core, a cell for how each stands, filtered by subject, and the box to add one. */
  const factsArea = () => (
    <section className="memory-area" aria-label="Facts">
      <div className="memory-area-head">
        <h3>
          Facts <span className="muted memory-hint">the core</span>
        </h3>
        <Room chars={memory.core_chars} limit={memory.core_limit} />
      </div>
      <AreaHead line="Given to an agent when its work names the subject." more={FACTS_MORE}>
        <TopicFilter records={memory.core} value={factsOf} onChange={setFactTopic} />
        <button type="button" className="btn btn-small" onClick={() => void onReload()}>
          Look at the sources again
        </button>
        {onExport && <ExportButton onExport={onExport} />}
      </AreaHead>
      {memory.core.length > 0 && <FactLegend />}
      <div className="memory-rows">
        {memory.core.length === 0 && (
          <p className="muted">Nothing is in the core yet. Agents are given only what you approve or write here.</p>
        )}
        {facts.map(record => (
          <CoreFact
            key={record.id}
            record={record}
            onCorrect={on.onCorrect}
            onReject={on.onReject}
            onConfirm={on.onConfirm}
          />
        ))}
        <div className="memory-addrow">
          <span className="muted memory-hint">A fact on a file’s lines is checked again each time it is read.</span>
          <button
            type="button"
            className="btn btn-small btn-primary"
            aria-expanded={adding}
            onClick={() => {
              setAdding(!adding)
              setDraft(undefined)
            }}
          >
            ＋ Add a fact
          </button>
        </div>
      </div>
      {adding && (
        <Section
          title="Add a fact"
          hint="It goes into the core at once, replacing the fact on the same subject. Without a subject, it is found only when looked up."
        >
          <WriteBox from={draft} onWrite={on.onWrite} />
        </Section>
      )}
    </section>
  )

  /** Notes: the journal, filtered by subject and by who wrote it, and how noting by itself last went. */
  const notesArea = () => (
    <section className="memory-area" aria-label="Notes">
      <h3>
        Notes <span className="muted memory-hint">the journal</span>
      </h3>
      <AreaHead
        line="Found only when an agent looks."
        more="What agents noted, and, if the project’s settings say so, what a fast model noted of finished work, signed as its own. No agent is given these: an agent finds them only when it looks."
      >
        <TopicFilter records={memory.journal} value={notesOf} onChange={setNoteTopic} />
        <select
          className="input memory-filter"
          aria-label="Written by"
          value={by}
          onChange={e => setWriter(e.target.value)}
        >
          <option value="">Anyone</option>
          {writers.map(name => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </AreaHead>
      {lastAuto && <p className="muted memory-hint">{lastAuto}</p>}
      {memory.journal.length === 0 ? (
        <p className="muted hive-empty">Agents have noted nothing yet.</p>
      ) : (
        notes.length === 0 && <p className="muted">No note matches.</p>
      )}
      {notes.length > 0 && (
        <div className="memory-rows">
          {notes.map(record => (
            <JournalNote key={record.id} record={record} onReject={on.onReject} onMakeFact={makeFact} />
          ))}
        </div>
      )}
    </section>
  )

  /** History, folded: the last decisions, and what was removed or replaced. */
  const historyArea = () => (
    <details
      className="memory-area memory-history"
      open={historyOpen}
      onToggle={e => setHistoryOpen(e.currentTarget.open)}
    >
      <summary>
        History <span className="mono muted">{memory.decisions.length + memory.past.length}</span>
      </summary>
      <section className="memory-panel" aria-label="History">
        <AreaHead
          line="Decisions and what was removed. Nothing is deleted."
          more="The last decision on each record and the last change to your rules, newest first. KOLONİ only knows each came from this page’s address, not who made it. If one of them was not yours, look into it."
        />
        <Section title="Recent decisions">
          {memory.decisions.length === 0 ? (
            <p className="muted">Nothing has been decided yet.</p>
          ) : (
            <ul className="memory-list">
              {memory.decisions.map(decision => (
                <li key={decisionId(decision)} id={decisionId(decision)} tabIndex={-1} className="memory-decision">
                  <span>{decisionOf(decision)}</span>
                  {decision.text !== null && <span> · {decision.text}</span>}
                  <span className="mono muted"> · {moment(decision.at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Removed / replaced" hint="Any of these can be taken back.">
          {memory.past.length === 0 && <p className="muted">Nothing has been removed or replaced.</p>}
          {memory.past.map(record => (
            <PastRecord key={record.id} record={record} onRestore={on.onRestore} />
          ))}
        </Section>
      </section>
    </details>
  )

  return page(
    <>
      {waits()}
      <div className="memory-grid">
        <div className="memory-col">
          {factsArea()}
          {notesArea()}
          {historyArea()}
        </div>
        <YourWords
          memory={memory}
          onSavePreferences={on.onSavePreferences}
          onAddPreference={on.onAddPreference}
          onReject={on.onReject}
          onSaveRules={on.onSaveRules}
          onSaveProjectNotes={on.onSaveProjectNotes}
          linked={linked}
          onLinked={onLinked}
        />
      </div>
    </>,
  )
}
