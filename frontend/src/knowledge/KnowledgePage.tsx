import { type FormEvent, type KeyboardEvent, useEffect, useId, useState } from 'react'
import { errorText } from '../api/client'
import type { Knowledge, KnowledgeIn, KnowledgeItem, KnowledgeState, Project, ProjectFile, Provider } from '../api/types'
import { Markdown } from '../chat/Markdown'
import { useConfirm } from '../shell/Confirm'
import { GUIDE } from '../shell/guide'
import { Hint } from '../shell/Hint'
import { CopyGuide, Guide, Pages, type Sent, Sources } from './KnowledgeParts'

interface Props {
  /** The project's knowledge and every project's; null while it is read. */
  items: KnowledgeItem[] | null
  error: string | null
  projectName: string
  providers: Provider[]
  /** The user's other projects: a guide is copied into one of them. */
  otherProjects: Project[]
  onReload(): Promise<void>
  onAdd(body: KnowledgeIn): Promise<KnowledgeItem>
  /** Each of these throws ApiError with the server's reason. */
  onSave(knowledgeId: string, body: Knowledge): Promise<void>
  onDelete(knowledgeId: string): Promise<void>
  onLearn(knowledgeId: string): Promise<void>
  onTry(knowledgeId: string, question: string): Promise<string>
  onCopy(knowledgeId: string, toProjectId: string, replace?: boolean): Promise<void>
  /** A file of the project: a section of a guide. */
  onReadFile(path: string): Promise<ProjectFile>
}

const DAY = 24 * 3600 * 1000
const ago = (iso: string) => {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / DAY)
  return days < 1 ? 'today' : days === 1 ? '1 day' : `${days} days`
}
const minutesAgo = (iso: string) => {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000)
  return minutes < 1 ? 'just now' : minutes < 60 ? `${minutes} min ago` : minutes < 1440 ? `${Math.floor(minutes / 60)} h ago` : `${ago(iso)} ago`
}

// K-bilgi 8: this project's code - its only source (app/knowledge.py CODE), scanned with no model.
const CODE = 'code:'
const isCode = (known: Knowledge) => known.sources.length === 1 && known.sources[0] === CODE
// K-bilgi 6: the Project notes - notes KOLONİ writes from what you accept at a turn's end (app/project_notes.py); nothing to learn.
const isNotes = (known: Knowledge) => known.sources.length === 1 && known.sources[0] === 'notes:'
// KOLONİ's own guide, its docs/ (app/knowledge.py KOLONI_GUIDE): only the learner reads it, only on Learn.
const KOLONI_GUIDE = 'koloni-guide:'
// K-bilgi-repo: a repository, cloned on Learn outside the project (app/knowledge.py REPO) - its docs' pages, its code files and its free scan;
// a folder on this machine (LOCAL) is learned the same, read in place.
const isRepo = (known: Knowledge) => known.sources.some(one => one.startsWith('repo:') || one.startsWith('folder:'))
type LearnedCode = NonNullable<NonNullable<KnowledgeState['learned']>['code']>
// Its docs' pages: a repository's code files are counted on a line of their own (CodeLines).
const docsRead = (pages: NonNullable<KnowledgeState['learned']>['pages']) => pages.filter(one => one.read && !one.code).length
/**
 * Whether Learn more adds to its guide: what its pages hold beyond it (where the money limit was not too low for one request), or a
 * repository's code files left - not where its page cap stopped them (a Learn reads no more; the card says to raise it).
 */
const goesOn = (learned: KnowledgeState['learned']) =>
  ((learned?.left ?? 0) > 0 && !learned?.short) ||
  (!!learned?.code && learned.code.in_guide.length < learned.code.ranked && !learned.code.stopped?.startsWith('the page cap'))

/** What the next learning that adds to its guide costs at most, beside its button. (A repository's guide, from its docs and its code, costs model calls; its code map does not.) */
function costOf(known: Knowledge, state: KnowledgeState): string {
  const priced = state.estimate == null ? `unknown cost${state.requests ? ` · ≈${state.requests} requests` : ''}` : `${state.learned ? '≈' : 'at most'} ${state.estimate.toFixed(2)} USD`
  return isCode(known) ? 'free · only changed files' : isRepo(known) ? `${priced} · code map free` : priced
}

const removeAsked = (item: KnowledgeItem) =>
  `${item.project_id === null ? `${item.knowledge.topic} is in every project: remove it from all of them?` : `Remove ${item.knowledge.topic}?`} Its guide stays in the folder${isRepo(item.knowledge) ? '; the code it keeps is deleted' : ''}.`

/**
 * Decision 4: why its guide holds fewer pages than were read, and what Learn more adds - only from what the API says;
 * null when there is nothing to say. (One Learn's request count on a model with no known price is the backend's, not said.)
 */
function coverageLine(state: KnowledgeState): string | null {
  const learned = state.learned
  if (!learned) return null
  const read = docsRead(learned.pages)
  const said: string[] = []
  if (learned.short) said.push(`The money limit stopped it: raise it to at least ${learned.short.toFixed(2)} USD to read further.`)
  else if (learned.guide_from < read && state.estimate == null) said.push('On a model with no known price one Learn stops after a set number of requests.')
  if (learned.left > 0 && !learned.short) said.push(`Learn more adds the rest${state.requests ? ` (≈${state.requests} requests)` : state.estimate != null ? ` (≈ ${state.estimate.toFixed(2)} USD)` : ''}.`)
  return said.join(' ') || null
}

/** K-bilgi: the project's Knowledge page - a card for each knowledge, opened to its tabs (layout A). */
/** KOLONİ's own guide, offered until it is added. Added only: learning it costs model calls, so it waits for Learn on its card. */
function AddOwnGuide({ items, onAdd, onSaid }: { items: Props['items']; onAdd: Props['onAdd']; onSaid: (said: string | null) => void }) {
  if (items === null || items.some(one => one.knowledge.sources.includes(KOLONI_GUIDE))) return null
  const add = () => {
    onSaid(null)
    onAdd({ topic: 'KOLONİ guide', sources: [KOLONI_GUIDE], max_usd: 0.5, learn_with: null }).catch(err => onSaid(errorText(err)))
  }
  return (
    <p className="muted">
      <strong>KOLONİ’s own guide</strong> — how KOLONİ works, for agents to look up when you ask about it. Only its pages are read, not KOLONİ’s code. Learning it costs model calls: it
      learns when you press Learn on its card.{' '}
      <button type="button" className="btn btn-small" onClick={add}>
        Add KOLONİ’s own guide
      </button>
    </p>
  )
}

export function KnowledgePage(props: Props) {
  const { items, error, projectName, providers, onReload, onAdd, onLearn } = props
  const [open, setOpen] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [said, setSaid] = useState<string | null>(null)
  const learning = items?.some(one => one.state.learning) ?? false
  // While one learns: read again each second, until it is done (as the role's Knowledge tab).
  useEffect(() => {
    if (!learning) return
    const again = setTimeout(() => void onReload(), 1000)
    return () => clearTimeout(again)
  }, [learning, items, onReload])
  const learn = (id: string) => {
    setSaid(null)
    onLearn(id).catch(err => setSaid(errorText(err)))
  }
  const [scanning, setScanning] = useState(false)
  // Its card, once asked for: a knowledge of the project like any other, that roles turn on on their Knowledge tab.
  const scan = () => {
    setSaid(null)
    setScanning(true)
    // (A straight ' in the topic: agents name it to lookup as they type it.)
    onAdd({ topic: "This project's code", sources: [CODE], max_usd: 0.5, learn_with: null })
      .then(added => onLearn(added.id))
      .catch(err => setSaid(errorText(err)))
      .finally(() => setScanning(false))
  }
  return (
    <div className="triggers-page knowledge-page">
      <div className="conv-head">
        <h2>Knowledge</h2>
        <span className="muted trigger-lede">
          What agents can look things up in.{' '}
          <Hint doc={GUIDE.knowledge}>
            What the agents of {projectName} can look things up in. A role uses only what you give it, on its Knowledge tab. Knowledge marked “every project” is in all of your projects; “+ Add
            knowledge” adds to this one.
          </Hint>
        </span>
        <div className="memory-actions">
          <button type="button" className="btn btn-primary btn-small" onClick={() => setAdding(true)}>
            + Add knowledge
          </button>
        </div>
      </div>
      {(error || said) && (
        <div role="alert" className="alert">
          {error ?? said}
        </div>
      )}
      {items === null ? (
        !error && <p className="muted">Reading the project’s knowledge…</p>
      ) : items.length === 0 ? (
        <p className="muted hive-empty">No knowledge yet.</p>
      ) : (
        items.map(item => <Card key={item.id} item={item} open={open === item.id} page={props} onOpen={() => setOpen(open === item.id ? null : item.id)} onLearn={() => learn(item.id)} />)
      )}
      {items !== null && !items.some(one => isCode(one.knowledge)) && (
        <p className="muted">
          <strong>This project’s code</strong> — what each file defines, who calls it and its tests, for agents to look up. Free: KOLONİ reads the files here, no model.{' '}
          <button type="button" className="btn btn-small" disabled={scanning} onClick={scan}>
            Scan the code
          </button>
        </p>
      )}
      <AddOwnGuide items={items} onAdd={onAdd} onSaid={setSaid} />
      {adding && <AddKnowledge projectName={projectName} providers={providers} onAdd={onAdd} onLearn={onLearn} onClose={() => setAdding(false)} />}
    </div>
  )
}

const day = (iso: string) => new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

type Tab = 'guide' | 'pages' | 'unknown' | 'settings' | 'copy'

function Card({ item, open, page, onOpen, onLearn }: { item: KnowledgeItem; open: boolean; page: Props; onOpen: () => void; onLearn: () => void }) {
  const { knowledge: known, state } = item
  const learned = state.learned
  const read = learned ? docsRead(learned.pages) : 0
  // K-uzman-derin: every page under its sources is read; its guide is written from as many as its money limit pays for.
  const written = learned?.guide_from ?? 0
  const code = isCode(known)
  const notes = isNotes(known)
  const web = !code && !notes
  // K-bilgi 5: a learning after the first says what changed since the one before.
  const changed = learned?.changed
  const checked = changed == null ? null : changed ? `${changed} ${changed === 1 ? 'page' : 'pages'} changed` : 'up to date'
  const fresh = state.learning ? (code ? 'scanning…' : 'learning…') : !learned ? (code ? 'not scanned' : 'not learned') : state.stale ? 'old' : checked ? `checked ${minutesAgo(learned.learned_at)} · ${checked}` : ago(learned.learned_at)
  const more = goesOn(learned)
  const button = code ? (learned ? 'Rescan' : 'Scan the code') : !learned ? 'Learn' : more ? 'Learn more' : 'Learn again'
  // R168: it read as many pages as its cap and left some (its tries and time leave pages too, but never at the cap).
  const capped = web && !!learned && read >= known.max_pages && (learned.unread > 0 || learned.pages.some(one => one.why?.startsWith('the page limit')))
  const cost = costOf(known, state)
  const coverage = coverageLine(state)
  const labels = Object.entries(learned?.labels ?? {})
    .filter(([, count]) => count > 0)
    .map(([label, count]) => `${count} ${label}`)
    .join(', ')
  const confirm = useConfirm()
  const [deleteSaid, setDeleteSaid] = useState<string | null>(null)
  const remove = () =>
    confirm.ask(
      removeAsked(item),
      'Remove',
      () => void page.onDelete(item.id).catch(err => setDeleteSaid(errorText(err))),
      'Cancel',
    )
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<{ text: string; error: boolean } | null>(null)
  // What its form has typed and not saved: the top Learn would learn without it.
  const [dirty, setDirty] = useState(false)
  const [trying, setTrying] = useState(false)
  // What the form says, saved on the knowledge - its topic names its folder, and stays; `then`, once saved.
  const save = (sent: Sent, done: string, then?: () => Promise<void>) => {
    setBusy(true)
    setSaid(null)
    page
      .onSave(item.id, { ...sent, topic: known.topic })
      .then(then)
      .then(
        () => setSaid({ text: done, error: false }),
        err => setSaid({ text: errorText(err), error: true }),
      )
      .finally(() => setBusy(false))
  }
  const newSources = (sent: Sent) => sent.sources.join('\n') !== known.sources.join('\n')
  // B-365: what the form says (its model to learn with too) is saved first, then learned with.
  const learnButton = (sent: Sent | null, dirty: boolean) =>
    dirty && (
      <button type="button" className="btn btn-small" disabled={busy || state.learning || !sent} onClick={() => sent && save(sent, 'Saved, and learning.', () => page.onLearn(item.id))}>
        Save and learn
      </button>
    )
  const pages = (learned?.pages.length ?? 0) + (learned?.added.length ?? 0)
  const unknown = learned?.unknown
  const tabs: [Tab, string][] = [
    ...(state.guide ? [['guide', 'Guide'] as [Tab, string]] : []),
    ...(pages > 0 ? [['pages', `Pages · ${learned?.pages.length ?? 0}`] as [Tab, string]] : []),
    ...(web ? [['unknown', unknown ? `Not known yet · ${unknown.length}` : 'Not known yet'] as [Tab, string]] : []),
    ['settings', 'Settings'],
    ...(state.guide && web && page.otherProjects.length > 0 ? [['copy', 'Copy'] as [Tab, string]] : []),
  ]
  const [chosen, setTab] = useState<Tab>(state.guide ? 'guide' : 'settings')
  // A first learning done: its guide is what there is to see.
  const [hadGuide, setHadGuide] = useState(!!state.guide)
  if (!hadGuide && state.guide) {
    setHadGuide(true)
    setTab('guide')
  }
  const tab = tabs.some(([key]) => key === chosen) ? chosen : 'settings'
  const tabId = (key: Tab) => `${item.id}-tab-${key}`
  const onTabKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const at = tabs.findIndex(([key]) => key === tab)
    const to = ({ ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 } as Record<string, number>)[event.key]
    if (to === undefined) return
    event.preventDefault()
    const next = tabs[(to + tabs.length) % tabs.length][0]
    setTab(next)
    document.getElementById(tabId(next))?.focus()
  }
  const usedBy = (
    <span>
      Used by:{' '}
      {item.used_by.length === 0
        ? 'no role yet'
        : item.used_by.map(one => (
            <span key={one.role_id} className="chip">
              {one.name} · {one.mode}
            </span>
          ))}
    </span>
  )
  return (
    <article className="knowledge-card" aria-label={known.topic}>
      <div className="knowledge-card-head">
        <button type="button" className="link-btn knowledge-topic" aria-expanded={open} onClick={onOpen}>
          {open ? '▾' : '▸'} {known.topic}
        </button>
        <span className="muted knowledge-source">
          {code ? 'scanned from the project' : notes ? 'decisions the project kept' : known.sources[0]}
          {known.sources.length > 1 && ` +${known.sources.length - 1}`}
        </span>
        {item.project_id === null && <span className="tag">every project</span>}
        <span className="knowledge-spacer" />
        <button type="button" className="btn btn-small" aria-expanded={trying} onClick={() => setTrying(!trying)}>
          Try it
        </button>
        {notes ? (
          <span className="muted">written as you accept them</span>
        ) : (
          <>
            {/* What its next learning spends: in sight beside the button that spends it. */}
            <span className="muted knowledge-cost">{cost}</span>
            <button type="button" className="btn btn-primary btn-small" disabled={state.learning || dirty} title={dirty ? 'Save first: Save and learn uses what you changed' : undefined} onClick={onLearn}>
              {button}
            </button>
          </>
        )}
      </div>
      {web && learned && (
        <div className="knowledge-cover">
          {/* R162: all its pages are read; its guide is written from as many as its money limit pays for. */}
          <meter className="budget-meter" aria-label={`${known.topic}: pages in its guide`} min={0} max={read || 1} value={written} />
          <span>
            <strong>{written}</strong> of {read} pages in the guide
          </span>
        </div>
      )}
      {learned?.code && <CodeLines topic={known.topic} code={learned.code} />}
      {web && coverage && <p className="muted knowledge-why">{coverage}</p>}
      <div className="knowledge-facts">
        {code ? (
          <>
            <span>
              Scanned: <b>{learned && !state.learning ? minutesAgo(learned.learned_at) : fresh}</b>
            </span>
            {learned && (
              <span>
                <b>{written}</b> files · <b>{learned.symbols ?? 0}</b> symbols
              </span>
            )}
          </>
        ) : notes ? (
          <span>
            <b>{written}</b> notes
          </span>
        ) : (
          <>
            <span title={state.stale ?? undefined}>
              Fresh: <b>{fresh}</b>
              {known.weekly && ' · weekly'}
            </span>
            {learned && (
              <span>
                Spent:{' '}
                {learned.cost ? (
                  <b>
                    {learned.cost.amount.toFixed(2)} of {known.max_usd.toFixed(2)} {learned.cost.currency}
                  </b>
                ) : (
                  <>
                    <b>—</b> <Hint>A CLI’s or a plan’s use is not counted in USD.</Hint>
                  </>
                )}
              </span>
            )}
            <span>
              Learns with: <b>{known.learn_with ? known.learn_with.model_id : 'a role’s model'}</b>
            </span>
          </>
        )}
        {usedBy}
      </div>
      {capped && <p className="muted">Cap reached: raise the page cap to read more</p>}
      {state.version_warning && <p className="alert">Version: {state.version_warning}.</p>}
      {state.failed && !state.learning && (
        <p role="alert" className="alert">
          Not learned: {state.failed}
        </p>
      )}
      <span role="status" className="muted provider-note">
        {state.learning ? (code ? 'Scanning the code…' : 'Learning: reading its sources, then writing the guide…') : said && !said.error && said.text}
      </span>
      {said?.error && (
        <p role="alert" className="alert">
          {said.text}
        </p>
      )}
      {deleteSaid && (
        <p role="alert" className="alert">
          {deleteSaid}
        </p>
      )}
      {confirm.shown()}
      {trying && <TryIt state={state} onTry={question => page.onTry(item.id, question)} />}
      {open && (
        <>
          <div className="tabs knowledge-tabs" role="tablist" aria-label={known.topic} onKeyDown={onTabKey}>
            {tabs.map(([key, label]) => (
              <button key={key} id={tabId(key)} type="button" role="tab" className="tab" aria-selected={tab === key} aria-controls={`${tabId(key)}-panel`} tabIndex={tab === key ? 0 : -1} onClick={() => setTab(key)}>
                {label}
              </button>
            ))}
          </div>
          {/* Each is kept while another is shown: what is typed in Settings stays, and holds Learn until it is saved (B-365). */}
          {tabs.map(([key]) => (
            <div key={key} id={`${tabId(key)}-panel`} role="tabpanel" aria-labelledby={tabId(key)} className="knowledge-panel" hidden={tab !== key}>
              {key === 'guide' && (
                <>
                  {learned && (
                    <p className="muted">
                      learned {day(learned.learned_at)} on {learned.model}
                      {state.stale && <> · old: {state.stale}</>}
                      {labels && <> · Entries: {labels}</>}
                    </p>
                  )}
                  {/* (A section is kept by its pages, whatever model wrote it.) */}
                  {state.guide?.includes('\n## Sections\n') && <p className="muted">Learning again with another model rewrites only the map: its sections are kept.</p>}
                  <Guide state={state} onRead={page.onReadFile} />
                </>
              )}
              {/* A page a search found (or what was kept from one while answering), taken off: not read or kept from the next learning. */}
              {key === 'pages' && <Pages state={state} removed={known.removed ?? []} busy={busy} onRemove={source => save({ ...known, removed: [...(known.removed ?? []), source] }, 'Removed: Learn again to leave it out of the guide.')} />}
              {/* K-bilgi 7: what a clicked learning's questions of its guide found no page and line for (a scan is not asked). */}
              {key === 'unknown' && <NotKnown unknown={unknown ?? null} more={more} />}
              {key === 'settings' && (
                <>
                  <p className="muted">
                    {known.topic} · it names its folder, {state.folder}
                  </p>
                  {/* (Anew once saved: what is saved is what it shows.) */}
                  {notes ? (
                    <p className="muted">Notes KOLONİ writes from what you tick on a turn’s “Add to Project notes?” card: fixed findings and docs/ changes, one page each.</p>
                  ) : code ? (
                    <p className="muted">The Python and JS/TS files here, as the agents’ file tools see them: no secret, no node_modules or build output.</p>
                  ) : (
                    <Sources key={JSON.stringify(known)} knowledge={known} providers={page.providers} busy={busy} button="Save" onSave={sent => save(sent, newSources(sent) ? 'Saved: Learn again reads the new sources.' : 'Saved.')} learn={learnButton} onDirty={setDirty} />
                  )}
                  <button type="button" className="link-btn" onClick={remove}>
                    Remove
                  </button>
                </>
              )}
              {key === 'copy' && <CopyGuide topic={known.topic} projects={page.otherProjects} onCopy={(to, replace) => page.onCopy(item.id, to, replace)} />}
            </div>
          ))}
        </>
      )}
    </article>
  )
}

/** K-bilgi-repo: under its docs' line, a repository's code files in the guide its model writes, and its scan (no model). */
function CodeLines({ topic, code }: { topic: string; code: LearnedCode }) {
  return (
    <>
      <div className="knowledge-cover">
        <meter className="budget-meter" aria-label={`${topic}: code files in its guide`} min={0} max={code.ranked || 1} value={code.in_guide.length} />
        <span>
          <strong>{code.in_guide.length}</strong> of {code.ranked} code files in the guide
          {code.stopped && <span className="muted"> · stopped by {code.stopped}</span>}
        </span>
      </div>
      <p className="muted knowledge-why">Code map: {code.scanned} files scanned · free</p>
    </>
  )
}

function NotKnown({ unknown, more }: { unknown: string[] | null; more: boolean }) {
  if (unknown === null) return <p className="muted">Not measured yet.</p>
  if (unknown.length === 0) return <p className="muted">It answered every question KOLONİ asked it, from its pages.</p>
  return (
    <>
      <p className="muted">Asked as its learning ended, it found no page for:</p>
      <ul>
        {unknown.map(one => (
          <li key={one}>{one}</li>
        ))}
      </ul>
      {more && <p className="muted">Learn more may cover them.</p>}
    </>
  )
}

function TryIt({ state, onTry }: { state: KnowledgeState; onTry: (question: string) => Promise<string> }) {
  // B-372: the model that will answer, said before the user asks (a scan answers with none).
  const refused = state.answers_refused ?? null
  const id = useId()
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<{ text: string; error: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const ask = (event: FormEvent) => {
    event.preventDefault()
    if (!question.trim()) return
    setBusy(true)
    setAnswer(null)
    onTry(question.trim())
      .then(
        text => setAnswer({ text, error: false }),
        err => setAnswer({ text: errorText(err), error: true }),
      )
      .finally(() => setBusy(false))
  }
  return (
    <form className="knowledge-try" onSubmit={ask}>
      <label htmlFor={id}>
        <strong>Try it</strong> <span className="muted">— ask what an agent would</span>
      </label>
      {state.answers_on && (
        <p className="muted" title={state.per_token ? `${state.answers_on} (a pay-per-token provider)` : state.answers_on}>
          Answers on {state.answers_on}
        </p>
      )}
      {refused && <p className="muted">No model can answer it: {refused}</p>}
      <div className="knowledge-copy">
        <input id={id} className="input" value={question} maxLength={2000} disabled={refused !== null} autoFocus onChange={e => setQuestion(e.target.value)} />
        <button type="submit" className="btn btn-small" disabled={busy || !question.trim() || refused !== null}>
          Ask
        </button>
      </div>
      {busy && <p className="muted">Asking…</p>}
      {answer?.error && (
        <p role="alert" className="alert">
          {answer.text}
        </p>
      )}
      {/* R168: a model's answer, rendered as chat messages are (no raw HTML). */}
      {answer && !answer.error && (
        <div role="status" className="knowledge-answer">
          <Markdown written>{answer.text}</Markdown>
        </div>
      )}
    </form>
  )
}

/** "+ Add knowledge": one window, the Settings form in its new mode (decision 3). Which roles use it is said on each role's Knowledge tab, not here. */
function AddKnowledge({ projectName, providers, onAdd, onLearn, onClose }: { projectName: string; providers: Provider[]; onAdd: Props['onAdd']; onLearn: Props['onLearn']; onClose: () => void }) {
  const [topic, setTopic] = useState('')
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<string | null>(null)
  const add = (sent: Sent, learn: boolean) => {
    setBusy(true)
    setSaid(null)
    onAdd({ ...sent, topic: topic.trim() })
      .then(async added => {
        if (!learn) return onClose()
        try {
          await onLearn(added.id)
          onClose()
        } catch (err) {
          setSaid(`Added, not learned: ${errorText(err)}`)
        }
      }, err => setSaid(errorText(err)))
      .finally(() => setBusy(false))
  }
  const off = busy || !topic.trim()
  return (
    <div className="dialog-back" onKeyDown={e => e.key === 'Escape' && onClose()}>
      <div className="provider-dialog knowledge-add" role="dialog" aria-modal="true" aria-labelledby="knowledge-add-heading">
        <div className="provider-dialog-head">
          <h3 id="knowledge-add-heading">Add knowledge</h3>
          <span className="muted">Something the agents of {projectName} can look things up in.</span>
        </div>
        {said && (
          <p role="alert" className="alert">
            {said}
          </p>
        )}
        <Sources
          knowledge={null}
          kinds
          providers={providers}
          busy={off}
          button="Add and learn"
          onSave={sent => add(sent, true)}
          foot={sent => (
            <>
              <button type="button" className="link-btn" disabled={off || !sent} onClick={() => sent && add(sent, false)}>
                Add without learning
              </button>
              <span className="knowledge-spacer" />
              <button type="button" className="btn btn-small" onClick={onClose}>
                Cancel
              </button>
            </>
          )}
        >
          <div className="field">
            <label htmlFor="knowledge-topic">Topic</label>
            <input id="knowledge-topic" className="input" value={topic} maxLength={40} aria-describedby="knowledge-topic-note" onChange={e => setTopic(e.target.value)} />
            <span id="knowledge-topic-note" className="muted">
              How agents and the canvas name it.
            </span>
          </div>
        </Sources>
      </div>
    </div>
  )
}
