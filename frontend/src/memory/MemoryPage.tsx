import { type KeyboardEvent, type ReactNode, useEffect, useState } from 'react'
import { errorText } from '../api/client'
import type { MemoryRecord, MemorySearch, ProjectMemory } from '../api/types'
import { useApp } from '../state/store'
import type { ProjectSettingsValues } from '../shell/ProjectSettings'
import { Find } from './Find'
import { type NewFact, RulesBox, WriteBox } from './forms'
import { byTopic, decisionId, decisionOf, lastAutoText, linesOf, meter, moment, subject, type Tab, TABS, wouldReplace, writerOf } from './memoryText'
import { CoreFact, JournalNote, PastRecord, Proposal, Suggestion } from './records'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { KEPT_IN_FOLDER } from '../shell/ProjectSettings'

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
  /** Your own preferences (22b), one text for every project; and a suggested line into them. */
  onSavePreferences: (text: string) => Promise<void>
  onAddPreference: (id: string) => Promise<void>
  onReload: () => Promise<void>
  /** What an agent's `recall` would find for these words; left out, there is no search deeper. */
  onSearch?: (query: string) => Promise<MemorySearch>
  /** 22c: saves which provider the search by meaning embeds with, and the model's name; left out, there is no picker. */
  onMeaning?: (values: Pick<ProjectSettingsValues, 'embedding_provider_id' | 'embedding_model'>) => Promise<void>
  /** Saves the core as a Markdown file; left out when there is no project. */
  onExport?: () => Promise<void>
  /** Come from "Search in messages" (Ctrl+K), each time with a new count: the search box takes the focus, and searches the words deeper. */
  searchFor?: { words: string; n: number }
}

function Section({ title, hint, more, children }: { title: string; hint?: string; more?: ReactNode; children: ReactNode }) {
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

/** A tab's one line of what it holds, its "?", and its own controls at the right. */
function TabHead({ line, more, children }: { line: string; more: ReactNode; children?: ReactNode }) {
  return (
    <div className="memory-tab-head">
      <span className="muted memory-hint">
        {line} <Hint doc={GUIDE.memoryKinds}>{more}</Hint>
      </span>
      {children}
    </div>
  )
}

/** A filter of a tab by subject: '' for all, otherwise '=' and the subject as compared. */
function TopicFilter({ records, value, onChange }: { records: MemoryRecord[]; value: string; onChange: (value: string) => void }) {
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

const ofTopic = (records: MemoryRecord[], topic: string) => (topic ? records.filter(record => `=${subject(record.about)}` === topic) : records)

const FACTS_MORE =
  'What agents are given: what you approved or wrote, each with its source. A fact is given to an agent whose work names its subject; any agent can look the rest up. Each rests on file lines: a fact whose source changed, or moved within its file, is given to no agent until you look at it again. “Source unchanged since noted” only means the file lines a record rests on read as they did when it was written. It does not mean the record is right.'

/**
 * What this project remembers, in four tabs by how it reaches an agent: told to every agent
 * (your preferences, the project's rules), given when the work names its subject (the core's
 * facts), found only when looked for (the journal's notes), and what was decided and removed.
 * One search over all of it on top, and what waits for your word above the tabs. Nothing here is
 * shown as surer than its record: a source is unchanged, changed, or not there.
 */
/** The core saved as MEMORY.md (`download`: the key in no address the browser keeps), and a refusal said beside it. */
function ExportButton({ onExport }: { onExport: () => Promise<void> }) {
  const [failed, setFailed] = useState<string | null>(null)
  const save = () => {
    setFailed(null)
    onExport().catch((err: unknown) => setFailed(errorText(err)))
  }
  return (
    <>
      <button type="button" className="btn btn-small" onClick={save} title="The core as a Markdown file to read. A copy: editing it does not change the memory.">
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

export function MemoryPage({ memory, error, onReload, onSearch, onMeaning, onExport, searchFor, ...on }: Props) {
  const [tab, setTab] = useState<Tab>('facts')
  const [factTopic, setFactTopic] = useState('')
  const [noteTopic, setNoteTopic] = useState('')
  const [writer, setWriter] = useState('')
  const [adding, setAdding] = useState(false)
  // A note made a fact: the box opens with its words (keyed, so it starts again each time).
  const [draft, setDraft] = useState<{ text: string; about: string; n: number } | undefined>(undefined)
  // A row to go to once its tab is shown: a search hit, or the fact box.
  const [goTo, setGoTo] = useState<{ id: string; n: number } | null>(null)
  const [waitOpen, setWaitOpen] = useState(false)
  useEffect(() => {
    if (!goTo) return
    const row = document.getElementById(goTo.id)
    row?.scrollIntoView?.({ block: 'center' })
    // (Not from a question that took the focus: "Replace what you typed?")
    if (!document.activeElement?.closest('[role="alertdialog"]')) row?.focus()
  }, [goTo])
  // Which turn the last notes made by themselves were of: one of the open conversation's,
  // when it is there; only that it is another conversation's otherwise.
  const conv = useApp(s => s.conv)
  const ofAuto = memory?.last_auto ? conv?.runs.find(run => run.id === memory.last_auto?.run_id) : undefined
  const lastTurn = ofAuto && conv ? `the work on the ${moment(ofAuto.created_at)} message in “${conv.conversation.title}”` : 'a message of a conversation not open here'
  // Once something waited, its line stays while the page is open: deciding the last note does not take the place you were in.
  const [waited, setWaited] = useState(false)
  if (!waited && memory && memory.proposals.length > 0) setWaited(true)
  // Whether .koloni/rules.md was there before the last save of the rules: the save that put it there says so, once.
  const [keptBefore, setKeptBefore] = useState(true)
  if (!memory) {
    return (
      <div className="memory-page">
        {error ? (
          <div role="alert" className="alert">
            {error}
          </div>
        ) : (
          <p className="muted">Reading the project’s memory…</p>
        )}
      </div>
    )
  }

  const go = (to: Tab | 'waiting', id: string) => {
    if (to === 'waiting') setWaitOpen(true)
    else setTab(to)
    setGoTo(was => ({ id, n: (was?.n ?? 0) + 1 }))
  }
  // A hit is shown whatever the filters said.
  const open = (to: Tab | 'waiting', id: string) => {
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
  function onTabKey(event: KeyboardEvent<HTMLDivElement>) {
    const at = TABS.findIndex(([id]) => id === tab)
    const to = ({ ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: TABS.length - 1 } as Record<string, number>)[event.key]
    if (to === undefined) return
    event.preventDefault()
    const next = TABS[(to + TABS.length) % TABS.length][0]
    setTab(next)
    event.currentTarget.querySelector<HTMLElement>(`#memory-tab-${next}`)?.focus()
  }

  // A filter whose topic or writer is gone since (removed, corrected) shows all again.
  const factsOf = ofTopic(memory.core, factTopic).length ? factTopic : ''
  const notesOf = ofTopic(memory.journal, noteTopic).length ? noteTopic : ''
  const writers = [...new Set(memory.journal.map(writerOf))]
  const by = writers.includes(writer) ? writer : ''
  const facts = ofTopic(memory.core, factsOf)
  const notes = ofTopic(memory.journal, notesOf).filter(record => !by || writerOf(record) === by)
  const lastAuto = lastAutoText(memory.last_auto, lastTurn)
  const waiting = memory.proposals.length
  const counts: Record<Tab, number> = {
    told: linesOf(memory.preferences).length + linesOf(memory.rules).length,
    facts: memory.core.length,
    notes: memory.journal.length,
    history: memory.decisions.length + memory.past.length,
  }
  return (
    <div className="memory-page">
      <div className="conv-head">
        <h2>Memory</h2>
        <div className="memory-actions">
          <button type="button" className="btn btn-small" onClick={() => void onReload()}>
            Look at the sources again
          </button>
          {onExport && <ExportButton onExport={onExport} />}
        </div>
      </div>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}

      <Find key={searchFor?.n} memory={memory} onOpen={open} onSearch={onSearch} onMeaning={onMeaning} searchFor={searchFor?.words} />

      {(waiting > 0 || waited) && (
        <div className="memory-waiting">
          <button type="button" className="memory-waiting-line" aria-expanded={waitOpen} aria-controls="memory-waits" onClick={() => setWaitOpen(!waitOpen)}>
            {waiting > 0 ? `● ${waiting} ${waiting === 1 ? 'fact waits' : 'facts wait'} for your word` : 'Nothing waits for your word'}
          </button>
          {/* shortcut: no "Open in Ready →" beside it - the Ready page is not on main yet; add the link when it is. */}
          {waitOpen && (
            <section id="memory-waits" className="memory-section" aria-label="Waits for you">
              <p className="muted memory-hint">Notes agents put forward for the core. Nothing enters the core unless you approve it.</p>
              {/* (Shown as the last note is decided: the focus goes here, not to the page.) */}
              {waiting === 0 && (
                <p className="muted" tabIndex={-1} ref={said => said?.focus()}>
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
          )}
        </div>
      )}

      <div className="tabs memory-tabs" role="tablist" aria-label="Memory" onKeyDown={onTabKey}>
        {TABS.map(([id, label]) => (
          <button
            key={id}
            id={`memory-tab-${id}`}
            type="button"
            role="tab"
            className="tab"
            aria-selected={tab === id}
            aria-controls={`memory-panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
          >
            {label} <span className="mono muted">{counts[id]}</span>
          </button>
        ))}
      </div>

      {/* Each is kept while another is open: what was typed in one is still there when you come back. */}
      <div id="memory-panel-told" role="tabpanel" aria-labelledby="memory-tab-told" className="memory-panel" hidden={tab !== 'told'}>
        <TabHead
          line="Said to every agent, always."
          more="Your preferences are yours in every project: every agent is told them as your instructions, before the project’s rules - language, tone, commit rules, whatever holds wherever you work. This project’s rules are like an AGENTS.md or CLAUDE.md file: every agent working in this project is given them each turn. Only you write either."
        />
        <Section title="Your preferences">
          {/* Keyed by what is saved, so the text follows a save made here or elsewhere. */}
          <RulesBox key={memory.preferences ?? ''} rules={memory.preferences ?? null} what="preferences" onSave={on.onSavePreferences} />
          {(memory.suggestions ?? []).length > 0 && (
            <div role="group" aria-label="Suggested for your preferences" className="memory-section">
              <div className="muted memory-hint">
                {/* (What Add does is read before it is clicked: in sight, the rest behind the "?".) */}
                <span className="tag">suggested</span> Added, it is told to every agent in every project as your instruction.{' '}
                <Hint doc={GUIDE.memoryKinds}>What KOLONİ’s summariser took for a preference of yours from a finished message. Nothing enters your preferences unless you add it.</Hint>
              </div>
              {(memory.suggestions ?? []).map(record => (
                <Suggestion key={record.id} record={record} onAdd={on.onAddPreference} onReject={on.onReject} />
              ))}
            </div>
          )}
        </Section>
        <Section title="This project’s rules">
          {/* Keyed by what is saved, so the text follows a save made here or elsewhere. */}
          <RulesBox
            key={memory.rules ?? ''}
            rules={memory.rules}
            onSave={rules => {
              setKeptBefore(memory.rules_kept ?? true)
              return on.onSaveRules(rules)
            }}
          />
          {!keptBefore && memory.rules_kept && (
            <p role="status" className="muted">
              {KEPT_IN_FOLDER}
            </p>
          )}
          {memory.rules_not_read && <p className="alert">{memory.rules_not_read}</p>}
        </Section>
      </div>

      <div id="memory-panel-facts" role="tabpanel" aria-labelledby="memory-tab-facts" className="memory-panel" hidden={tab !== 'facts'}>
        <TabHead line="Given to an agent when its work names the subject." more={FACTS_MORE}>
          <span className="mono muted memory-count">{meter(memory.core_chars, memory.core_limit)}</span>
          <TopicFilter records={memory.core} value={factsOf} onChange={setFactTopic} />
          <button type="button" className="btn btn-small btn-primary" aria-expanded={adding} onClick={() => { setAdding(!adding); setDraft(undefined) }}>
            ＋ Add a fact
          </button>
        </TabHead>
        {adding && (
          <Section title="Add a fact" hint="It goes into the core at once, replacing the fact on the same subject. Without a subject, it is found only when looked up.">
            <WriteBox from={draft} onWrite={on.onWrite} />
          </Section>
        )}
        {memory.core.length === 0 && <p className="muted">Nothing is in the core yet. Agents are given only what you approve or write here.</p>}
        {facts.map(record => (
          <CoreFact key={record.id} record={record} onCorrect={on.onCorrect} onReject={on.onReject} onConfirm={on.onConfirm} />
        ))}
      </div>

      <div id="memory-panel-notes" role="tabpanel" aria-labelledby="memory-tab-notes" className="memory-panel" hidden={tab !== 'notes'}>
        <TabHead
          line="Found only when an agent looks."
          more="What agents noted, and, if the project’s settings say so, what a fast model noted of finished work, signed as its own. No agent is given these: an agent finds them only when it looks."
        >
          <TopicFilter records={memory.journal} value={notesOf} onChange={setNoteTopic} />
          <select className="input memory-filter" aria-label="Written by" value={by} onChange={e => setWriter(e.target.value)}>
            <option value="">Anyone</option>
            {writers.map(name => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </TabHead>
        {lastAuto && <p className="muted memory-hint">{lastAuto}</p>}
        {memory.journal.length === 0 ? <p className="muted hive-empty">Agents have noted nothing yet.</p> : notes.length === 0 && <p className="muted">No note matches.</p>}
        {notes.map(record => (
          <JournalNote key={record.id} record={record} onReject={on.onReject} onMakeFact={makeFact} />
        ))}
      </div>

      <div id="memory-panel-history" role="tabpanel" aria-labelledby="memory-tab-history" className="memory-panel" hidden={tab !== 'history'}>
        <TabHead
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
      </div>
    </div>
  )
}
