import { useEffect, useState } from 'react'
import { api, errorText } from '../api/client'
import type { Project, ProjectMap as MapOf } from '../api/types'

/**
 * K-buyuk-proje: the project map - its parts, found by their files without any model, each
 * test command typed over in place and saved at once (Enter or Save), not by the project's Save.
 * Every button is type="button": this sits in the settings' form, whose submit would send the
 * project's settings.
 */
export function ProjectMap({ project }: { project: Project }) {
  const [map, setMap] = useState<MapOf | null>(null)
  // What is typed in a part's test box, by its path, until it is saved or taken back.
  const [typed, setTyped] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [said, setSaid] = useState('')

  async function act(work: () => Promise<MapOf>, done = '') {
    setBusy(true)
    setError(null)
    setSaid('')
    try {
      setMap(await work())
      setSaid(done)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    api.get<MapOf>(`/projects/${project.id}/map`).then(setMap, err => setError(errorText(err)))
  }, [project.id])
  const forget = (path: string) => setTyped(was => Object.fromEntries(Object.entries(was).filter(([key]) => key !== path)))

  const save = (path: string) =>
    act(async () => {
      const saved = await api.put<MapOf>(`/projects/${project.id}/map/test`, { path, command: typed[path] ?? '' })
      forget(path)
      return saved
    }, 'Saved')

  // KOLONİ's guess again: what the user set for the part is forgotten.
  const reset = (path: string) =>
    act(async () => {
      await api.delete(`/projects/${project.id}/map/test?path=${encodeURIComponent(path)}`)
      forget(path)
      return api.get<MapOf>(`/projects/${project.id}/map`)
    }, 'Saved')

  const parts = map?.parts ?? []
  return (
    <>
      <h2>Project map</h2>
      <span className="choice-note">
        The parts of this folder, found by their files (pyproject.toml, package.json, Cargo.toml…) without asking a model. A new
        chat’s Orchestrator is told of them when there is more than one. A test command runs in its part’s folder; saved empty, the part has no test. A
        command you write here runs in its part without a card, at every level; KOLONİ’s guess is asked as any command.
      </span>
      {map && (
        <p>
          {project.name} ({[map.git && 'git', `${parts.length} ${parts.length === 1 ? 'part' : 'parts'}`].filter(Boolean).join(', ')})
          {map.partial && <span className="muted"> · not every folder was looked in</span>}
        </p>
      )}
      {map && parts.length === 0 && <p className="muted">No part found: no folder has a project file.</p>}
      {parts.length > 0 && (
        <table className="usage-table project-map" aria-label="Parts of this folder">
          <thead>
            <tr>
              <th scope="col">Folder</th>
              <th scope="col">Language</th>
              <th scope="col">Files</th>
              <th scope="col">AGENTS.md</th>
              <th scope="col">Test command</th>
            </tr>
          </thead>
          <tbody>
            {parts.map(part => {
              const value = typed[part.path] ?? part.test ?? ''
              const changed = part.path in typed && typed[part.path].trim() !== (part.test ?? '')
              return (
                <tr key={part.path}>
                  <th scope="row" className="mono">
                    {part.path}
                  </th>
                  <td>{part.language}</td>
                  <td>{part.more ? `${part.files}+` : part.files}</td>
                  <td>{part.agents_md ? '✓' : <span className="muted">✗</span>}</td>
                  <td>
                    <span className="also-in-row">
                      <input
                        className="input mono"
                        aria-label={`Test command for ${part.path}`}
                        value={value}
                        maxLength={500}
                        placeholder="no test"
                        onChange={e => setTyped({ ...typed, [part.path]: e.target.value })}
                        onKeyDown={e => {
                          if (e.key === 'Enter') {
                            e.preventDefault() // (not the settings' form)
                            if (changed && !busy) void save(part.path)
                          } else if (e.key === 'Escape') {
                            forget(part.path)
                          }
                        }}
                      />
                      {changed ? (
                        <button type="button" className="btn btn-small" disabled={busy} onClick={() => void save(part.path)}>
                          Save
                        </button>
                      ) : part.edited ? (
                        <button type="button" className="btn btn-small" aria-label={`Use guess for ${part.path}`} disabled={busy} onClick={() => void reset(part.path)}>
                          Use guess
                        </button>
                      ) : (
                        part.test && <span className="muted">guess</span>
                      )}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {map?.not_copied.length ? <p className="choice-note">Not copied (git ignores, the project is big): {map.not_copied.join(', ')}</p> : null}
      {map?.big && !map.git && <p className="choice-note">Too big to copy: agents work in the folder itself.</p>}
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      <div className="role-actions">
        <button type="button" className="btn" disabled={busy} onClick={() => void act(() => api.post<MapOf>(`/projects/${project.id}/map/refresh`), 'Refreshed')}>
          Refresh
        </button>
        <span role="status" className="muted">
          {map || error ? said : 'Looking…'}
        </span>
      </div>
    </>
  )
}
