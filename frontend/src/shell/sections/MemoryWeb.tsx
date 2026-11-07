import { useState } from 'react'
import type { Project } from '../../api/types'
import { MEANING_COSTS } from '../../memory/Find'
import { ProviderOptions } from '../../models/ModelNameInput'
import { useApp } from '../../state/store'
import { GUIDE } from '../guide'
import { Hint } from '../Hint'
import { part, Row } from './part'

/** What noting by itself costs, holds up and does not do, in sight under its box; how it is made, behind ⓘ. */
const NOTES_SHOWN =
  'After each message’s work, a fast model writes at most three notes of what it found. That is one more model request after every message, on your plan or your bill; Usage shows it under that model. While it runs (at most 90 seconds) it holds a place like any model step, so the next message may wait for one. Nothing goes into the core by itself: that stays your decision.'
const NOTES_REST =
  'It is the first model you gave the fast tier in the team guide, with no tools. It is given your message, the Orchestrator’s answer, the agents’ reports and the names of the changed files. Its notes go into the journal, signed as that model’s; they never replace an agent’s note or a fact on the same subject. The Memory page shows how the last one went.'

/** This project › Memory and web: what is noted by itself, where recall also looks, and how agents search. */
export function useMemoryWeb(project: Project) {
  const [autoNotes, setAutoNotes] = useState(project.auto_notes)
  // 22c: the other projects whose memory recall also looks in. (A server older than the page has no such field yet.)
  const savedLinks = project.memory_links ?? []
  const [links, setLinks] = useState(savedLinks)
  const linksChanged = links.length !== savedLinks.length || links.some(id => !savedLinks.includes(id))
  // 22c: the search by meaning, as the Memory page sets it too.
  const [meaning, setMeaning] = useState(project.embedding_provider_id ?? null)
  const [model, setModel] = useState(project.embedding_model ?? 'text-embedding-3-small')
  const web = useWeb(project)
  const patch = {
    ...(autoNotes !== project.auto_notes && { auto_notes: autoNotes }),
    ...(linksChanged && { memory_links: links }),
    ...(meaning !== (project.embedding_provider_id ?? null) && { embedding_provider_id: meaning }),
    ...(model.trim() !== (project.embedding_model ?? 'text-embedding-3-small') && { embedding_model: model.trim() }),
    ...web.patch,
  }
  return part(
    patch,
    true,
    <>
      <h2>Memory</h2>
      <label className="choice">
        <input type="checkbox" aria-label={`Note what the work found, by itself ${NOTES_SHOWN} ${NOTES_REST}`} checked={autoNotes} onChange={e => setAutoNotes(e.target.checked)} />
        <span>
          Note what the work found, by itself
          <span className="choice-note">
            {NOTES_SHOWN} <Hint doc={GUIDE.memoryWho}>{NOTES_REST}</Hint>
          </span>
        </span>
      </label>
      <Meaning provider={meaning} setProvider={setMeaning} model={model} setModel={setModel} />
      <OtherMemories project={project} links={links} setLinks={setLinks} />
      {web.view}
    </>,
    { take: web.take },
  )
}

/** Which provider's server embeds for the search by meaning (off: by words alone), and its model. */
function Meaning({ provider, setProvider, model, setModel }: { provider: string | null; setProvider: (id: string | null) => void; model: string; setModel: (name: string) => void }) {
  const providers = useApp(s => s.providers).filter(p => p.base_url)
  return (
    <Row label="Search by meaning with" htmlFor="settings-meaning" warn={<span className="choice-note">{MEANING_COSTS}</span>}>
      <select id="settings-meaning" className="input" value={provider ?? ''} onChange={e => setProvider(e.target.value || null)}>
        <option value="">off: by words alone</option>
        <ProviderOptions providers={providers} />
      </select>
      <input className="input mono" aria-label="Embedding model" value={model} maxLength={200} disabled={provider === null} onChange={e => setModel(e.target.value)} />
    </Row>
  )
}

function OtherMemories({ project, links, setLinks }: { project: Project; links: string[]; setLinks: (ids: string[]) => void }) {
  const otherProjects = useApp(s => s.projects).filter(p => p.id !== project.id)
  return (
    <>
      <h2>Also look in the memory of</h2>
      <span className="choice-note">
        An agent’s recall also finds their notes, facts and earlier messages, each tagged with the project and not checked here: their files are not in
        this folder. Nothing of theirs is given to an agent at its start, and nothing is written there.
      </span>
      {otherProjects.length === 0 && <p className="muted">There is no other project yet.</p>}
      {otherProjects.map(other => (
        <label key={other.id} className="choice">
          <input
            type="checkbox"
            aria-label={`Also look in the memory of ${other.name}`}
            checked={links.includes(other.id)}
            onChange={e => setLinks(e.target.checked ? [...links, other.id] : links.filter(id => id !== other.id))}
          />
          <span>
            {other.name}
            <span className="choice-note mono">{other.root_path}</span>
          </span>
        </label>
      ))}
    </>
  )
}

/** Where an agent's web search goes. */
function useWeb(project: Project) {
  const [searchUrl, setSearchUrl] = useState(project.search_url ?? '')
  const [searchOrder, setSearchOrder] = useState(project.search_order)
  const [searchAgy, setSearchAgy] = useState(project.search_agy)
  const patch = {
    ...(searchUrl.trim() !== (project.search_url ?? '') && { search_url: searchUrl.trim() }),
    ...(searchOrder !== project.search_order && { search_order: searchOrder }),
    ...(searchAgy !== project.search_agy && { search_agy: searchAgy }),
  }
  return {
    patch,
    take: (now: Project) => setSearchOrder(now.search_order),
    view: (
      <>
        <h2>Web search</h2>
        <Row label="Search address (SearXNG)" htmlFor="search-url" doc={GUIDE.settingsMemoryWeb} why="Your own SearXNG. An agent’s web search asks it first (turn on its JSON format). Empty: none.">
          <input id="search-url" className="input mono" value={searchUrl} maxLength={500} placeholder="http://localhost:8888" onChange={e => setSearchUrl(e.target.value)} />
        </Row>
        <Row
          label="Otherwise search with"
          htmlFor="search-order"
          warn={
            <span className="choice-note">
              <span id="search-order-note">The built-in search sends the query to DuckDuckGo. It is not an official service and can stop working.</span>{' '}
              <span id="search-order-more">A CLI is your Codex or Claude Code provider (and agy, reading only, if you let it below); a search with it uses your plan.</span>
            </span>
          }
        >
          <select id="search-order" className="input" value={searchOrder} aria-describedby="search-order-note search-order-more" onChange={e => setSearchOrder(e.target.value as Project['search_order'])}>
            <option value="builtin">The built-in search first, then a CLI</option>
            <option value="cli">A CLI first, then the built-in search</option>
          </select>
        </Row>
        <label className="choice">
          <input type="checkbox" checked={searchAgy} onChange={e => setSearchAgy(e.target.checked)} />
          <span>
            Let agy search too
            <span className="choice-note">While it searches, agy is not held to its search tool: it may read files on this machine or open pages unasked. Codex and Claude Code are held to it.</span>
          </span>
        </label>
      </>
    ),
  }
}
