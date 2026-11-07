import { type FormEvent, type ReactNode, useEffect, useId, useState } from 'react'
import { ApiError, errorText } from '../api/client'
import type { Knowledge, KnowledgeState, Project, ProjectFile, Provider } from '../api/types'
import { useConfirm } from '../shell/Confirm'
import { modelChoices } from '../shell/modelName'

// K-bilgi: a knowledge's parts, on the project's Knowledge page (a row opened) and, for its sources, Agents -> New role -> Expert.

const lines = (text: string) =>
  text
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
const OWN = ''

export type Sent = Omit<Knowledge, 'topic'>

/** What "+ Add knowledge" adds from: the kind sets the sources field's name and example. */
const KINDS = [
  { key: 'site', name: 'A docs site', note: 'its pages under an address', label: 'Address', hint: 'https://mlflow.org/docs/latest/' },
  { key: 'files', name: 'Files here', note: 'a folder or file in this project', label: 'Folder or file', hint: 'docs/' },
  { key: 'repo', name: 'A repository', note: 'its code (a free scan) and a guide from its docs and code', label: 'Address', hint: 'https://github.com/owner/name' },
  { key: 'folder', name: 'A folder on this machine', note: 'outside this project, read in place as a repository is', label: 'Full path', hint: 'C:\\work\\mylib' },
  { key: 'research', name: 'Research a topic', note: 'it searches the web for it', label: 'What to research', hint: 'stripe webhooks' },
] as const
type Kind = (typeof KINDS)[number]['key']
const RESEARCH = /^research:/i
// K-bilgi-repo: a repository is sent as "repo: <its address>", a folder on this machine as "folder: <its path>" (app/knowledge.py REPO, LOCAL).
const KEPT_CODE = /^(repo|folder):/i

/** The sources as typed, a line each - in the add window (`kinds`), with the prefix its kind has put on: "research: <topic>", "repo: <address>". */
function typedSources(text: string, kinds: boolean | undefined, kind: Kind): string[] {
  const prefix = !kinds ? '' : kind === 'research' ? 'research: ' : kind === 'repo' ? 'repo: ' : kind === 'folder' ? 'folder: ' : ''
  return lines(text).map(one => (!prefix || RESEARCH.test(one) || KEPT_CODE.test(one) ? one : `${prefix}${one}`))
}

/** A repository's code-file cap as typed (0 to 1000) - as it was where no repository is among the sources; null: not valid. */
function codeCap(listed: string[], typed: string, knowledge: Knowledge | null): { max_code_files: number } | null {
  if (!listed.some(one => KEPT_CODE.test(one))) return { max_code_files: knowledge?.max_code_files ?? 100 }
  return /^\d{1,4}$/.test(typed.trim()) && Number(typed) <= 1000 ? { max_code_files: Number(typed) } : null
}

/** Beside the page cap, a repository's: how many of its code files new to its guide a learning reads. */
function CodeCap({ id, shown, value, onChange }: { id: string; shown: boolean; value: string; onChange: (value: string) => void }) {
  if (!shown) return null
  return (
    <>
      <label htmlFor={`${id}-code`}>At most this many code files a learning</label>
      <input id={`${id}-code`} className="input" inputMode="numeric" value={value} aria-describedby={`${id}-code-note`} onChange={e => onChange(e.target.value)} />
      <span id={`${id}-code-note`} className="muted">
        The most central first; Learn more goes on with the next ones. It holds where no price does (a CLI, a plan). 0: no guide to its code - its docs’ guide and the free scan only.
      </span>
    </>
  )
}

interface SourcesProps {
  knowledge: Knowledge | null
  providers: Provider[]
  busy: boolean
  button: string
  onSave: (sent: Sent) => void
  learn?: (sent: Sent | null, dirty: boolean) => ReactNode
  onDirty?: (dirty: boolean) => void
  /** "+ Add knowledge": the kind chosen on top, the page cap under More, and its web search left to the server until it is touched. */
  kinds?: boolean
  /** Under its sources field (the add window's topic). */
  children?: ReactNode
  /** Beside its button, given the form as typed. */
  foot?: (sent: Sent | null) => ReactNode
}

/**
 * Its sources, its limits and the model it learns with, as typed: a knowledge's Settings, the add window and an expert's
 * (decision 3: one form). `learn`: what stands beside "Learn with" - given the form as typed (null: not valid) and whether it
 * differs from what is saved; `onDirty` is told that too.
 */
export function Sources({ knowledge, providers, busy, button, onSave, learn, onDirty, kinds, children, foot }: SourcesProps) {
  // (A row of the Knowledge page and the add window may be open at once: ids of its own.)
  const id = useId()
  const [kind, setKind] = useState<Kind>('site')
  const chosenKind = KINDS.find(one => one.key === kind)!
  const [sources, setSources] = useState((knowledge?.sources ?? []).join('\n'))
  const [pages, setPages] = useState(String(knowledge?.max_pages ?? 500))
  const [usd, setUsd] = useState(String(knowledge?.max_usd ?? 0.5))
  const chosen = knowledge?.learn_with
  const [withModel, setWithModel] = useState(chosen ? `${chosen.provider_id} ${chosen.model_id}` : OWN)
  const [weekly, setWeekly] = useState(knowledge?.weekly ?? false)
  const [codeFiles, setCodeFiles] = useState(String(knowledge?.max_code_files ?? 100))
  // A topic to research is typed as it is; it is sent as "research: <topic>" - a repository's address as "repo: <address>".
  const listed = typedSources(sources, kinds, kind)
  const code = codeCap(listed, codeFiles, knowledge)
  const researches = listed.some(one => RESEARCH.test(one))
  // K-bilgi 5: a site is checked weekly too (app/knowledge.py stale); a project's files say when they change.
  const weeklyOffered = researches || listed.some(one => /^https?:\/\//i.test(one))
  // Not said yet: an expert of a topic to research may search while answering.
  const [searchSet, setSearches] = useState<boolean | null>(knowledge?.search_answering ?? null)
  const searches = searchSet ?? researches
  const maxPages = /^\d{1,4}$/.test(pages.trim()) && Number(pages) >= 1 && Number(pages) <= 1000 ? Number(pages) : null
  const maxUsd = Number(usd) > 0 && Number(usd) <= 100 ? Number(usd) : null
  const [provider_id, ...model] = withModel.split(' ')
  const sent: Sent | null =
    listed.length > 0 && maxPages !== null && maxUsd !== null && code !== null
      ? {
          sources: listed,
          max_pages: maxPages,
          max_usd: maxUsd,
          learn_with: withModel === OWN ? null : { provider_id, model_id: model.join(' ') },
          removed: knowledge?.removed ?? [],
          weekly: weeklyOffered && weekly,
          // Not touched in the add window: not sent - the server's default (a topic to research may search).
          ...(!kinds || searchSet !== null ? { search_answering: searches } : {}),
          ...code,
        }
      : null
  // B-365: what is typed against what was saved (the form starts anew on each save: its key).
  const typed = JSON.stringify([listed, pages, usd, withModel, weekly, searches, codeFiles])
  const [saved] = useState(typed)
  useEffect(() => {
    onDirty?.(typed !== saved)
    return () => onDirty?.(false)
  }, [typed, saved, onDirty])
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (sent) onSave(sent)
  }
  const pageCap = (
    <div className="field">
      <label htmlFor={`${id}-pages`}>At most this many pages (a safety cap)</label>
      <input id={`${id}-pages`} className="input" inputMode="numeric" value={pages} onChange={e => setPages(e.target.value)} />
      <CodeCap id={id} shown={listed.some(one => KEPT_CODE.test(one))} value={codeFiles} onChange={setCodeFiles} />
    </div>
  )
  return (
    <form className="role-editor" onSubmit={submit}>
      {kinds && (
        <div className="knowledge-kinds" role="radiogroup" aria-label="From">
          {KINDS.map((one, at) => (
            <button key={one.key} type="button" role="radio" autoFocus={at === 0} aria-checked={kind === one.key} className="knowledge-kind" onClick={() => setKind(one.key)}>
              <strong>{one.name}</strong>
              <span className="muted">{one.note}</span>
            </button>
          ))}
        </div>
      )}
      <div className="field">
        <label htmlFor={`${id}-sources`}>{kinds ? chosenKind.label : 'Sources'}</label>
        <textarea id={`${id}-sources`} className="input" rows={kinds ? 2 : 3} value={sources} placeholder={kinds ? chosenKind.hint : undefined} aria-describedby={`${id}-sources-note`} onChange={e => setSources(e.target.value)} />
        <span id={`${id}-sources-note`} className="muted">
          One a line: the documents’ address (https://…), a file or folder of the project, or <code>research: a topic</code> to search the web for. A site is read only under the path given; a
          repository (<code>repo: https://github.com/owner/name</code>) is cloned on Learn, outside the project, and a folder on this machine (<code>folder: C:\work\mylib</code>) is read
          where it is, never written to; each is its knowledge’s only source.
        </span>
      </div>
      {children}
      {weeklyOffered && (
        <label className="choice" htmlFor={`${id}-weekly`}>
          <input id={`${id}-weekly`} type="checkbox" checked={weekly} onChange={e => setWeekly(e.target.checked)} />
          <span>
            Learn again weekly
            {/* shortcut: checked only when an expert of it next works (app/knowledge.py brief); a Map-only one shows "old" - check it on a timer if that is missed. */}
            <span className="choice-note">Once its guide is a week old, it learns before its next answer or recipe step - only what changed is read and written again.</span>
          </span>
        </label>
      )}
      <label className="choice" htmlFor={`${id}-searches`}>
        <input id={`${id}-searches`} type="checkbox" checked={searches} onChange={e => setSearches(e.target.checked)} />
        <span>
          Agents may search the web when it has no answer
          <span className="choice-note">Each search costs, and is asked for unless the chat is at Full auto.</span>
        </span>
      </label>
      <div className="field">
        <label htmlFor={`${id}-usd`}>At most this much a learning (USD)</label>
        <input id={`${id}-usd`} className="input" inputMode="decimal" value={usd} aria-describedby={`${id}-usd-note`} onChange={e => setUsd(e.target.value)} />
        <span id={`${id}-usd-note`} className="muted">
          It reads everything under its sources; this is what writing its guide may spend, held where the model’s price is known. Learn again goes on from where it stopped.
        </span>
      </div>
      {!kinds && pageCap}
      <div className="field">
        <label htmlFor={`${id}-with`}>Learn with</label>
        <div className="knowledge-copy">
          <select id={`${id}-with`} className="input" value={withModel} onChange={e => setWithModel(e.target.value)}>
            <option value={OWN}>The model of a role that uses it</option>
            {modelChoices(providers).map(one => (
              <option key={one.value} value={one.value} disabled={one.off}>
                {one.label}
              </option>
            ))}
          </select>
          {learn?.(sent, typed !== saved)}
        </div>
      </div>
      {kinds && (
        <details className="more">
          <summary>More</summary>
          {pageCap}
        </details>
      )}
      <div className="knowledge-copy">
        <button type="submit" className={`btn btn-small${kinds ? ' btn-primary' : ''}`} disabled={busy || !sent}>
          {button}
        </button>
        {foot?.(sent)}
      </div>
    </form>
  )
}

/** What its learning read and skipped and why, and what was found while answering; a page a search found can be taken off. */
export function Pages({ state, removed, busy, onRemove }: { state: KnowledgeState; removed: string[]; busy: boolean; onRemove: (source: string) => void }) {
  const pages = state.learned?.pages ?? []
  const added = state.learned?.added ?? []
  const read = pages.filter(one => one.read).length
  const remove = (source: string, name: string) =>
    !removed.includes(source) && (
      <>
        {' '}
        <button type="button" className="link-btn" aria-label={`Remove ${name}`} disabled={busy} onClick={() => onRemove(source)}>
          Remove
        </button>
      </>
    )
  return (
    <>
      {pages.length > 0 && (
        <details open>
          <summary>
            Pages: {read} read, {pages.length - read} skipped
            {state.learned?.unread ? `, ${state.learned.unread} more not read (its limits)` : ''}
          </summary>
          <ul className="knowledge-pages">
            {pages.map((one, at) => (
              <li key={`${at}:${one.source}`}>
                {one.read ? 'read' : 'skipped'} {one.found && <span className="muted">found </span>}
                {one.source}
                {one.why && <span className="muted"> · {one.why}</span>}
                {one.found && one.read && remove(one.source, one.source)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {added.length > 0 && (
        <details>
          <summary>Found while answering: {added.length}, each a single source</summary>
          <ul className="knowledge-pages">
            {added.map(one => (
              <li key={one.source + one.text}>
                {one.text} <span className="muted">· {one.source}</span>
                {remove(one.source, one.text)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

// Under the map, in guide.md: each section and the pages it is from (app/knowledge.py LISTED).
const LISTED = '\n## Sections\n'
const SECTION = /^- (guide\/[0-9a-f]{12}\.md): (.*)$/

/** Its guide as it reads: the map, and each of its sections opened on its own. */
export function Guide({ state, onRead }: { state: KnowledgeState; onRead: (path: string) => Promise<ProjectFile> }) {
  const guide = state.guide ?? ''
  const at = guide.lastIndexOf(LISTED)
  const sections = at < 0 ? [] : guide.slice(at + LISTED.length).split('\n').flatMap(line => {
          const found = line.match(SECTION)
          return found ? [found] : []
        })
  return (
    <>
      <pre className="knowledge-guide">{at < 0 ? guide : guide.slice(0, at)}</pre>
      {sections.length > 0 && (
        <ul className="knowledge-pages">
          {sections.map(([, file, from]) => (
            <li key={file}>
              <Section path={`${state.folder}${file}`} name={file} from={from} onRead={onRead} />
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function Section({ path, name, from, onRead }: { path: string; name: string; from: string; onRead: (path: string) => Promise<ProjectFile> }) {
  const [text, setText] = useState<string | null>(null)
  const open = (opened: boolean) => {
    if (!opened || text !== null) return
    onRead(path).then(
      file => setText(file.text ?? (file.too_large ? 'It is too large to show here.' : 'It is not text.')),
      err => setText(`Could not be read: ${errorText(err)}`),
    )
  }
  return (
    <details onToggle={e => open(e.currentTarget.open)}>
      <summary>
        {name} <span className="muted">· {from}</span>
      </summary>
      <pre className="knowledge-guide">{text ?? 'Reading…'}</pre>
    </details>
  )
}

/** Its guide copied into another of the user's projects; a guide there already is replaced only on the user's yes. */
export function CopyGuide({ topic, projects, onCopy }: { topic: string; projects: Project[]; onCopy: (toProjectId: string, replace?: boolean) => Promise<void> }) {
  const id = useId()
  const [to, setTo] = useState('')
  // B-131: said beside its button.
  const [said, setSaid] = useState<string | null>(null)
  const confirm = useConfirm()
  const copy = () => {
    const target = projects.find(one => one.id === to)
    if (!target) return
    setSaid(null)
    const copied = () => setSaid(`Guide copied to ${target.name}.`)
    onCopy(target.id).then(copied, err => {
      // One there already: replaced, with the pages read there, only on the user's yes.
      if (err instanceof ApiError && err.status === 409 && err.detail.startsWith('there is a guide there already')) {
        const replace = () => onCopy(target.id, true).then(copied, again => setSaid(errorText(again)))
        confirm.ask(`${target.name} has a guide of ${topic} already. Replace it? The pages read there are deleted.`, 'Replace it', replace, 'Cancel')
        return
      }
      setSaid(errorText(err))
    })
  }
  return (
    <div className="field">
      <label htmlFor={id}>Copy the guide to</label>
      <div className="knowledge-copy">
        <select id={id} className="input" value={to} onChange={e => setTo(e.target.value)}>
          <option value="">Another project…</option>
          {projects.map(one => (
            <option key={one.id} value={one.id}>
              {one.name}
            </option>
          ))}
        </select>
        <button type="button" className="btn btn-small" disabled={!to} onClick={copy}>
          Copy guide
        </button>
        <span role="status" className="muted">
          {said}
        </span>
      </div>
      {confirm.shown()}
      <span className="muted">The guide and what was learned, not the pages read: learn again there to search them.</span>
    </div>
  )
}
