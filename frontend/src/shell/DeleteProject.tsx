import { type KeyboardEvent, useId, useState } from 'react'
import { api, download, errorText } from '../api/client'
import type { Project, ProjectDeletePreview } from '../api/types'
import { useApp } from '../state/store'

export const KEPT_ON_DISK = 'Its folder on disk is not touched: its files, its git and its .koloni/ stay.'

/** What a delete takes, counted: "12 chats, 34 memory records, 5 To-do tasks, 2 triggers, 0 knowledge topics". */
function goneWith(preview: ProjectDeletePreview): string {
  const parts: [number, string, string][] = [
    [preview.chats, 'chat', 'chats'],
    [preview.memory, 'memory record', 'memory records'],
    [preview.tasks, 'To-do task', 'To-do tasks'],
    [preview.triggers, 'trigger', 'triggers'],
    [preview.knowledge, 'knowledge topic', 'knowledge topics'],
  ]
  return parts.map(([n, one, many]) => `${n} ${n === 1 ? one : many}`).join(', ')
}

/**
 * Settings › This project › This folder, at the bottom: the project deleted from KOLONİ once its name is typed, with what goes counted and
 * an export offered first. Outside the settings' form: Enter in the name is not their Save.
 */
export function DeleteProject({ project }: { project: Project }) {
  const [preview, setPreview] = useState<ProjectDeletePreview | null>(null)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const id = useId()

  const open = async () => {
    setError(null)
    try {
      setPreview(await api.get<ProjectDeletePreview>(`/projects/${project.id}/delete-preview`))
    } catch (err) {
      setError(errorText(err))
    }
  }
  const close = () => {
    setPreview(null)
    setTyped('')
    setError(null)
  }
  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      await useApp.getState().deleteProject(project.id)
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }
  const exportFirst = async () => {
    setExporting(true)
    setError(null)
    try {
      await download('POST', '/backup/export?secrets=false')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setExporting(false)
    }
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== 'Escape') return
    event.stopPropagation()
    close()
  }

  return (
    <section className="delete-project" aria-label="Delete project">
      {!preview && (
        <p className="muted">
          <button type="button" className="btn btn-small btn-danger" onClick={() => void open()}>
            Delete project…
          </button>{' '}
          From KOLONİ only. {KEPT_ON_DISK}
        </p>
      )}
      {preview && (
        <div role="alertdialog" aria-labelledby={id} className="confirm-box delete-project-box" onKeyDown={onKeyDown}>
          <p id={id}>
            <strong>Delete {project.name} from KOLONİ?</strong>
          </p>
          <p>
            This deletes {goneWith(preview)}, with their messages, agents’ work, usage and history. {KEPT_ON_DISK} It cannot be undone.
          </p>
          <p>
            <button type="button" className="btn btn-small" disabled={exporting} onClick={() => void exportFirst()}>
              {exporting ? 'Exporting…' : 'Export first'}
            </button>{' '}
            <span className="muted">All of KOLONİ’s data in one .zip, without API keys.</span>
          </p>
          <label className="field">
            <span>Type the project’s name, {project.name}, to delete it</span>
            <input className="input" value={typed} autoFocus onChange={e => setTyped(e.target.value)} />
          </label>
          {error && (
            <div role="alert" className="alert">
              {error}
            </div>
          )}
          <div className="confirm-actions">
            <button type="button" className="btn btn-danger" disabled={busy || typed.normalize('NFC') !== project.name.normalize('NFC')} onClick={() => void remove()}>
              {busy ? 'Deleting…' : 'Delete project'}
            </button>
            <button type="button" className="btn" onClick={close}>
              Keep it
            </button>
          </div>
        </div>
      )}
      {!preview && error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
    </section>
  )
}
